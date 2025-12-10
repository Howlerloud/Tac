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
    """
    Handles incoming Stripe webhook events and processes successful payments
    by creating or verifying orders in the database.
    """

    def __init__(self, request):
        self.request = request

    def _send_confirmation_email(self, order):
        """
        Sends a confirmation email to the customer once the order is processed.
        """
        subject = render_to_string(
            'checkout/confirmation_emails/confirmation_email_subject.txt',
            {'order': order},
        )
        body = render_to_string(
            'checkout/confirmation_emails/confirmation_email_body.txt',
            {'order': order, 'contact_email': settings.DEFAULT_FROM_EMAIL},
        )

        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [order.email],
        )

    def handle_event(self, event):
        """
        Handles any webhook event that does not have a dedicated handler.
        This prevents Stripe from retrying endlessly on unimportant events.
        """
        return HttpResponse(
            content=f"Unhandled webhook received: {event['type']}",
            status=200,
        )

    def handle_payment_intent_succeeded(self, event):
        """
        Processes a successful Stripe payment:
        - Retrieves charge information (new Stripe API requirements)
        - Loads shopping bag data from metadata
        - Updates the user's saved delivery info if requested
        - Attempts to locate an existing matching order (avoid duplicates)
        - Creates a new order and line items if none exists
        - Sends a confirmation email to the customer
        """

        intent = event.data.object
        pid = intent.id

        # Retrieve the charge using the updated Stripe API
        charge = stripe.Charge.retrieve(intent.latest_charge)
        billing_details = charge.billing_details
        amount_received = charge.amount

        shipping = intent.shipping
        email = (
            billing_details.email
            or getattr(shipping, "email", None)
            or "noemail@example.com"
        )

        grand_total = round(amount_received / 100, 2)

        # Bag metadata arrives as a JSON string
        raw_bag = intent.metadata.get("bag", "{}")
        try:
            bag = json.loads(raw_bag)
        except json.JSONDecodeError:
            bag = {}

        save_info = intent.metadata.get("save_info")

        # Clean empty shipping fields so the DB accepts them
        for field, value in shipping.address.items():
            if value == "":
                shipping.address[field] = None

        # Update user profile if logged in and "save info" was selected
        profile = None
        username = intent.metadata.get("username")

        if username and username != "AnonymousUser":
            profile = UserProfile.objects.get(user__username=username)

            if save_info:
                profile.default_phone_number = shipping.phone
                profile.default_country = shipping.address.country
                profile.default_postcode = shipping.address.postal_code
                profile.default_town_or_city = shipping.address.city
                profile.default_street_address1 = shipping.address.line1
                profile.default_street_address2 = shipping.address.line2
                profile.default_county = shipping.address.state
                profile.save()

        # Look for an existing order (helps prevent duplicates during retries)
        order_exists = False
        attempt = 1
        while attempt <= 5:
            try:
                order = Order.objects.get(
                    full_name__iexact=shipping.name,
                    email__iexact=email,
                    phone_number__iexact=shipping.phone,
                    country__iexact=shipping.address.country,
                    postcode__iexact=shipping.address.postal_code,
                    town_or_city__iexact=shipping.address.city,
                    street_address1__iexact=shipping.address.line1,
                    street_address2__iexact=shipping.address.line2,
                    county__iexact=shipping.address.state,
                    grand_total=grand_total,
                    original_bag=json.dumps(bag),
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
                content=f"Webhook received: {event['type']} | Order verified",
                status=200,
            )

        # Create a new order if none was found
        try:
            order = Order.objects.create(
                full_name=shipping.name,
                user_profile=profile,
                email=email,
                phone_number=shipping.phone,
                country=shipping.address.country,
                postcode=shipping.address.postal_code,
                town_or_city=shipping.address.city,
                street_address1=shipping.address.line1,
                street_address2=shipping.address.line2,
                county=shipping.address.state,
                grand_total=grand_total,
                original_bag=json.dumps(bag),
                stripe_pid=pid,
            )

            # Add the items from the shopping bag
            for item_id, item_data in bag.items():
                product = Product.objects.get(id=item_id)

                if isinstance(item_data, int):
                    OrderLineItem.objects.create(
                        order=order, product=product, quantity=item_data
                    )
                else:
                    for size, qty in item_data["items_by_size"].items():
                        OrderLineItem.objects.create(
                            order=order,
                            product=product,
                            quantity=qty,
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
            content=f"Webhook received: {event['type']} | Order created",
            status=200,
        )

    def handle_payment_intent_payment_failed(self, event):
        """
        Handles failed payments. Nothing needs to be created or updated,
        but responding with 200 stops Stripe from retrying the event.
        """
        return HttpResponse(
            content=f"Webhook received: {event['type']}",
            status=200,
        )