from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from accounts.models import User


class BackofficeAuthenticationBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        email = kwargs.get(User.USERNAME_FIELD, username)
        if not email or password is None:
            return None
        normalized = User.objects.normalize_email_address(email)
        try:
            user = User.objects.get(email__iexact=normalized)
        except User.DoesNotExist:
            User().set_password(password)
            return None
        if not user.check_password(password) or not self.user_can_authenticate(user):
            return None
        if user.is_superuser:
            return user
        if not user.is_email_verified:
            return None
        if user.vendor_memberships.filter(vendor__status="active").exists():
            return user
        return None

    def user_can_authenticate(self, user: Any) -> bool:
        return bool(getattr(user, "is_active", False))
