from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from accounts.admin import backoffice_site
from accounts.forms import BackofficePasswordResetForm
from config.health import health

urlpatterns = [
    path("health/", health, name="health"),
    path(
        "backoffice/password_reset/",
        auth_views.PasswordResetView.as_view(
            form_class=BackofficePasswordResetForm,
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="admin_password_reset",
    ),
    path(
        "backoffice/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "backoffice/password_reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            success_url=reverse_lazy("password_reset_complete")
        ),
        name="password_reset_confirm",
    ),
    path(
        "backoffice/password_reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("backoffice/", backoffice_site.urls),
]
