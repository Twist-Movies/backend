from django.urls import path
from .views import CookieTokenRefreshView, LoginView, LogoutView, RegisterView, PasswordResetRequestView, PasswordResetConfirmView

urlpatterns = [
    path("register/", RegisterView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("password-reset/", PasswordResetRequestView.as_view()),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view()),
    path("token/refresh/", CookieTokenRefreshView.as_view()),
]