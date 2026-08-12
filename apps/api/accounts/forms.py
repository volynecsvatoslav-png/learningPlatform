from collections.abc import Iterator
from typing import Any

from django.contrib.auth.forms import (
    PasswordResetForm,
    ReadOnlyPasswordHashField,
    UserChangeForm,
    UserCreationForm,
)
from django.contrib.auth.tokens import default_token_generator
from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.models import User


class BackofficeUserCreationForm(UserCreationForm):  # type: ignore[type-arg]
    class Meta:
        model = User
        fields = ("email",)


class BackofficeUserChangeForm(UserChangeForm):  # type: ignore[type-arg]
    password = ReadOnlyPasswordHashField()

    class Meta:
        model = User
        fields = "__all__"


class BackofficePasswordResetForm(PasswordResetForm):
    def get_users(self, email: str) -> Iterator[User]:
        users: QuerySet[User] = User.objects.filter(email__iexact=email, is_active=True)
        for user in users:
            if user.has_usable_password() and (
                user.is_superuser
                or (
                    user.email_verified_at is not None
                    and user.vendor_memberships.filter(vendor__status="active").exists()
                )
            ):
                yield user

    def save(
        self,
        domain_override: str | None = None,
        subject_template_name: str = "registration/password_reset_subject.txt",
        email_template_name: str = "registration/password_reset_email.txt",
        use_https: bool = False,
        token_generator: Any = default_token_generator,
        from_email: str | None = None,
        request: HttpRequest | None = None,
        html_email_template_name: str | None = None,
        extra_email_context: dict[str, Any] | None = None,
    ) -> None:
        # Django's implementation is existence-neutral and its token becomes invalid
        # after a successful password change due to the password hash in the token state.
        super().save(
            domain_override,
            subject_template_name,
            email_template_name,
            use_https,
            token_generator,
            from_email,
            request,
            html_email_template_name,
            extra_email_context,
        )
