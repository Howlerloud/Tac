from django.http import HttpResponse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from .models import Order, OrderLineItem
from products.models import Product
from profiles.models import UserProfile

import stripe
import json
import time


class StripeWH_Handler:
    """Processes incoming Stripe webhook events and updates the store accordingly."""

    def __init__(self, request):
        self.request = request

    def _send_confirmation_email(self, order):
        """Sends a confirmation email to the customer after a successful order."""
        cust_email = order.email
        subject = render_to_string(
            'checkout/confirmation_emails/confirmation_email_subject.txt',
            {'order': order}
        )
        body = render_to_string(
            'checkout/confirmation_emails/confirmation_email_body.txt',
            {'order': order, 'contact_email': settings.DEFAULT_FROM_EMAIL}
        )

        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [cust_email]
        )

    def handle_event(self, event):
        """Handles any webhook event that does not have a dedicated method."""
        return HttpResponse(
            content=f"Unhandled webhook received: {event['type']}",
            status=200
        )

    def handle_payment_intent_payment_failed(self, event):
        """Handles payment failures (mainly for logging)."""
        return HttpResponse(
            content=f"Payment failed webhook received: {event['type']}",
            status=200
        )

    def handle_payment_intent_succeeded(self, event):
        """
        Handles successful Stripe payments.

        Stripe's 2025 API no longer includes `charges` on the payment intent,
        so we must fetch the charge using latest_charge.
        """
        intent = event.data.object
        pid = intent.id

        # Fetch the real charge (required in new API versions)
        latest_charge_id = intent.latest_charge
        charge = stripe.Charge.retrieve(latest_charge_id)

        # Read bag data (may be a dict or JSON string)
        bag_raw = intent.metadata.get("bag", "{}")
        try:
            bag_data = json.loads(bag_raw)
        except Exception:
            bag_data = {}

        save_info = intent.metadata.get("save_info")
        username = intent.metadata.get("username")

        # Extract contact information
        billing_details = charge.billing_details
        shipping_details = intent.shipping

        # Use the first non-empty email we can find
        email = (
            billing_details.email
            or getattr(shipping_details, "email", None)
            or "noemail@example.com"
        )

        grand_total = round(charge.amount / 100, 2)

        # Replace blank address fields with None so Django validation works
        for field, value in shipping_details.address.items():
            if value == "":
                shipping_details.address[field] = None

        # Handle logged-in user profiles
        profile = None
        if username and username != "AnonymousUser":
            profile = UserProfile.objects.get(user__username=username)

            if save_info:
                profile.default_phone_number = shipping_details.phone
                profile.default_country = shipping_details.address.country
                profile.default_postcode = shipping_details.address.postal_code
                profile.default_town_or_city = shipping_details.address.city
                profile.default_street_address1 = shipping_details.address.line1
                profile.default_street_address2 = shipping_details.address.line2
                profile.default_county = shipping_details.address.state
                profile.save()

        # Try several times to find an order already created during checkout
        order = None
        order_exists = False
        attempt = 1

        while attempt <= 5:
            try:
                order = Order.objects.get(
                    full_name__iexact=shipping_details.name,
                    email__iexact=email,
                    phone_number__iexact=shipping_details.phone,
                    country__iexact=shipping_details.address.country,
                    postcode__iexact=shipping_details.address.postal_code,
                    town_or_city__iexact=shipping_details.address.city,
                    street_address1__iexact=shipping_details.address.line1,
                    street_address2__iexact=shipping_details.address.line2,
                    county__iexact=shipping_details.address.state,
                    grand_total=grand_total,
                    original_bag=json.dumps(bag_data),
                    stripe_pid=pid,
                )
                order_exists = True
                break
            except Order.DoesNotExist:
                attempt += 1
                time.sleep(1)

        # If we found an order, email confirmation and finish
        if order_exists:
            self._send_confirmation_email(order)
            return HttpResponse(
                content=(
                    f"Webhook received: {event['type']} | "
                    f"Order already existed — confirmation email sent."
                ),
                status=200,
            )

        # If no order found, create a new one
        try:
            order = Order.objects.create(
                full_name=shipping_details.name,
                user_profile=profile,
                email=email,
                phone_number=shipping_details.phone,
                country=shipping_details.address.country,
                postcode=shipping_details.address.postal_code,
                town_or_city=shipping_details.address.city,
                street_address1=shipping_details.address.line1,
                street_address2=shipping_details.address.line2,
                county=shipping_details.address.state,
                grand_total=grand_total,
                original_bag=json.dumps(bag_data),
                stripe_pid=pid,
            )

            # Build the order line items
            for item_id, item_data in bag_data.items():
                product = Product.objects.get(id=item_id)

                # Single item (no size variants)
                if isinstance(item_data, int):
                    OrderLineItem.objects.create(
                        order=order,
                        product=product,
                        quantity=item_data
                    )
                else:
                    # Multiple sizes (e.g., clothing)
                    for size, quantity in item_data["items_by_size"].items():
                        OrderLineItem.objects.create(
                            order=order,
                            product=product,
                            quantity=quantity,
                            product_size=size,
                        )

        except Exception as e:
            if order:
                order.delete()
            return HttpResponse(
                content=f"Webhook error: Could not create order — {e}",
                status=500
            )

        # Send confirmation email on success
        self._send_confirmation_email(order)

        return HttpResponse(
            content=(
                f"Webhook received: {event['type']} | "
                f"New order created successfully."
            ),
            status=200
        )