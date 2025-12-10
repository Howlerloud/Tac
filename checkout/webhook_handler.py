from django.http import HttpResponse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from .models import Order, OrderLineItem
from products.models import Product
from profiles.models import UserProfile

import json
import time


class StripeWH_Handler:
    """Handle Stripe webhooks"""

    def __init__(self, request):
        self.request = request

    def _send_confirmation_email(self, order):
        """Send the user a confirmation email"""
        cust_email = order.email
        subject = render_to_string(
            'checkout/confirmation_emails/confirmation_email_subject.txt',
            {'order': order})
        body = render_to_string(
            'checkout/confirmation_emails/confirmation_email_body.txt',
            {'order': order, 'contact_email': settings.DEFAULT_FROM_EMAIL})
        
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [cust_email]
        )

    def handle_event(self, event):
        """Handle any webhook that isn't specifically handled"""
        return HttpResponse(
            content=f"Unhandled webhook received: {event['type']}",
            status=200,
        )

    def handle_payment_intent_succeeded(self, event):
        """
        Handle the payment_intent.succeeded webhook from Stripe
        FIXED FOR 2025 API FORMAT
        """
        intent = event.data.object
        pid = intent.id

        # -------------------------------
        # FIX: Bag may be dict or JSON string
        # -------------------------------
        bag = intent.metadata.get("bag", "{}")
        if isinstance(bag, str):
            try:
                bag_data = json.loads(bag)
            except json.JSONDecodeError:
                bag_data = {}
        else:
            bag_data = bag

        save_info = intent.metadata.get("save_info")

        # -------------------------------
        # FIX: Billing email sometimes missing in new API versions
        # -------------------------------
        charge = intent.charges.data[0]
        billing_details = charge.billing_details
        shipping_details = intent.shipping

        email = (
            billing_details.email
            or (shipping_details.email if hasattr(shipping_details, "email") else None)
            or "noemail@example.com"
        )

        grand_total = round(charge.amount / 100, 2)

        # Clean blank shipping fields
        for field, value in shipping_details.address.items():
            if value == "":
                shipping_details.address[field] = None

        # Handle user profile saving
        profile = None
        username = intent.metadata.get("username")
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

        # -------------------------------
        # Try to find existing order (as CI walkthrough does)
        # -------------------------------
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

        if order_exists:
            self._send_confirmation_email(order)
            return HttpResponse(
                content=(
                    f"Webhook received: {event['type']} | "
                    f"SUCCESS: Verified order already in database"
                ),
                status=200,
            )

        # -------------------------------
        # Create new order
        # -------------------------------
        order = None
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

            # Add order line items
            for item_id, item_data in bag_data.items():
                product = Product.objects.get(id=item_id)

                if isinstance(item_data, int):
                    # No sizes
                    OrderLineItem.objects.create(
                        order=order, product=product, quantity=item_data
                    )
                else:
                    # Has sizes
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
                content=f"Webhook received: {event['type']} | ERROR: {e}",
                status=500,
            )

        self._send_confirmation_email(order)

        return HttpResponse(
            content=(
                f"Webhook received: {event['type']} | "
                f"SUCCESS: Created order in webhook"
            ),
            status=200,
        )

    def handle_payment_intent_payment_failed(self, event):
        """Handle payment failure webhooks"""
        return HttpResponse(
            content=f"Webhook received: {event['type']}",
            status=200,
        )