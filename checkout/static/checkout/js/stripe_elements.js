var stripePublicKey = JSON.parse(document.getElementById('id_stripe_public_key').textContent);
var clientSecret = JSON.parse(document.getElementById('id_client_secret').textContent);

var stripe = Stripe(stripePublicKey);
var elements = stripe.elements();

var style = {
    base: {
        color: '#000',
        fontFamily: 'Arial, sans-serif',
        fontSmoothing: 'antialiased',
        fontSize: '16px',
        '::placeholder': { color: '#aab7c4' }
    },
    invalid: {
        color: '#dc3545',
        iconColor: '#dc3545'
    }
};

var card = elements.create('card', { style: style });
card.mount('#card-element');

card.on('change', function (event) {
    var errorDiv = document.getElementById('card-errors');
    if (event.error) {
        errorDiv.innerHTML = `
            <span class="icon" role="alert"><i class="fas fa-times"></i></span>
            <span>${event.error.message}</span>
        `;
    } else {
        errorDiv.textContent = '';
    }
});

var form = document.getElementById('payment-form');
var cacheUrl = form.getAttribute('data-cache-url') || '/checkout/cache_checkout_data/';

form.addEventListener('submit', function (ev) {
    ev.preventDefault();

    // Disable UI
    card.update({ disabled: true });
    $('#submit-button').prop('disabled', true);
    $('#button-text').text('Processing payment…');

    var saveInfo = ($('#id-save-info').length)
        ? $('#id-save-info').prop('checked')
        : false;

    var csrfToken = $('input[name="csrfmiddlewaretoken"]').val();

    var postData = {
        'csrfmiddlewaretoken': csrfToken,
        'client_secret': clientSecret,
        'save_info': saveInfo,
    };

    $.post(cacheUrl, postData)
        .done(function () {
            stripe.confirmCardPayment(clientSecret, {
                payment_method: {
                    card: card,
                    billing_details: {
                        name: $.trim($('#id_full_name').val()),
                        phone: $.trim($('#id_phone_number').val()),
                        email: $.trim($('#id_email').val()),
                        address: {
                            line1: $.trim($('#id_street_address1').val()),
                            line2: $.trim($('#id_street_address2').val()),
                            city: $.trim($('#id_town_or_city').val()),
                            country: $.trim($('#id_country').val()),
                            state: $.trim($('#id_county').val()),
                        }
                    }
                },
                shipping: {
                    name: $.trim($('#id_full_name').val()),
                    phone: $.trim($('#id_phone_number').val()),
                    address: {
                        line1: $.trim($('#id_street_address1').val()),
                        line2: $.trim($('#id_street_address2').val()),
                        city: $.trim($('#id_town_or_city').val()),
                        postal_code: $.trim($('#id_postcode').val()),
                        country: $.trim($('#id_country').val()),
                        state: $.trim($('#id_county').val()),
                    }
                }
            }).then(function (result) {

                if (result.error) {
                    // Stripe error
                    $('#card-errors').html(`
                        <span class="icon"><i class="fas fa-times"></i></span>
                        <span>${result.error.message}</span>
                    `);

                    card.update({ disabled: false });
                    $('#submit-button').prop('disabled', false);
                    $('#button-text').text('Complete Order');

                } else if (result.paymentIntent.status === 'succeeded') {

                    // IMPORTANT: re-enable before submit
                    $('#submit-button').prop('disabled', false);

                    // Submit form to Django
                    form.submit();
                }
            });
        })
        .fail(function () {
            location.reload();
        });
});