from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from budget import views as budget_views
from budget.forms import StyledPasswordChangeForm, StyledSetPasswordForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", budget_views.register, name="register"),
    # Password change (logged in) & reset (via email link)
    path(
        "accounts/password_change/",
        auth_views.PasswordChangeView.as_view(form_class=StyledPasswordChangeForm),
        name="password_change",
    ),
    path("accounts/password_change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("accounts/password_reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("accounts/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(form_class=StyledSetPasswordForm),
        name="password_reset_confirm",
    ),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("", include("budget.urls")),
]
