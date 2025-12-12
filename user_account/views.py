from django.shortcuts import render
from allauth.account.forms import LoginForm, SignupForm


def account_view(request):
    """
    Renders a single page containing both login and register forms
    """
    context = {
        "login_form": LoginForm(),
        "signup_form": SignupForm(),
    }
    return render(request, "user_account/account.html", context)