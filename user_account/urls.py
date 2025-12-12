from django.urls import path
from .views import account_view

urlpatterns = [
    path("", account_view, name="user_account"),
]