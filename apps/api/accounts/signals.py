from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import User


@receiver(user_logged_in)
def record_last_login_at(sender: object, user: User, **kwargs: object) -> None:
    User.objects.filter(pk=user.pk).update(last_login_at=timezone.now())
