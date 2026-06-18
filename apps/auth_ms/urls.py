from django.urls import path
from .views import LoginView, AuthCallbackView, LogoutView, MeView

urlpatterns = [
    path("/", LoginView.as_view(), name="ms-login"),
    path("login/", LoginView.as_view(), name="ms-login"),
    path("auth/callback/", AuthCallbackView.as_view(), name="ms-callback"),
    path("api/auth/logout/", LogoutView.as_view(), name="ms-logout"),
    path("api/auth/me/", MeView.as_view(), name="ms-me"),
]
