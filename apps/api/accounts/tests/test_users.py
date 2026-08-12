import pytest
from django.db import IntegrityError, transaction

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_email_is_trimmed_and_casefolded() -> None:
    user = User.objects.create_user("  Owner@EXAMPLE.COM  ")

    assert user.email == "owner@example.com"
    assert user.password is None
    assert not user.has_usable_password()
    assert not user.check_password("anything")


def test_email_is_globally_case_insensitive_unique() -> None:
    User.objects.create_user("owner@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("OWNER@example.com")
