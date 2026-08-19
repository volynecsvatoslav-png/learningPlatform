import secrets
import threading

import pytest
from django.core.cache import cache
from django.db import connections
from django.test import Client

from accounts.models import User
from learner.models import AccessPass, Device, Enrollment, LearnerSession, hash_access_token
from learner.tests.helpers import activate, make_device
from learning.models import ContentUnit, Course, Lesson, Module
from learning.services import publish_course
from vendors.models import Vendor


def _make_access(email: str) -> str:
    learner = User.objects.create_user(email)
    vendor = Vendor.objects.create(name="Alpha", slug="alpha")
    course = Course.objects.create(vendor=vendor, title="Published", slug="published")
    module = Module.objects.create(course=course, title="Module", position=1)
    lesson = Lesson.objects.create(module=module, title="Lesson", position=1, is_published=True)
    ContentUnit.objects.create(
        lesson=lesson,
        type=ContentUnit.Type.TEXT,
        position=1,
        text_markdown="# Hello",
    )
    course.status = Course.Status.PUBLISHED
    publish_course(course)
    token = secrets.token_urlsafe(32)
    Enrollment.objects.create(user=learner, vendor=vendor, course=course)
    AccessPass.objects.create(
        user=learner,
        vendor=vendor,
        token_hash=hash_access_token(token),
        token_prefix=token[:12],
    )
    return token


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("iteration", range(10))
def test_deterministic_concurrent_transfers_leave_exactly_one_active_session(
    iteration: int,
) -> None:
    cache.clear()
    token = _make_access(f"learner-{iteration}@example.com")
    activate(Client(), token, device=make_device())

    devices = [make_device() for _ in range(2)]
    challenges: list[str] = []
    for device in devices:
        inspect = Client().post(
            "/api/v1/auth/access/inspect",
            data={
                "token": token,
                "installation_id": str(device[0]),
                "public_key_jwk": device[1],
            },
            content_type="application/json",
        )
        assert inspect.status_code == 200, inspect.content
        challenges.append(inspect.json()["challenge"])
    assert challenges[0] != challenges[1]

    barrier = threading.Barrier(2)
    results: list[dict[str, object]] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        barrier.wait()
        try:
            response = Client().post(
                "/api/v1/auth/access/exchange",
                data={
                    "token": token,
                    "installation_id": str(devices[index][0]),
                    "public_key_jwk": devices[index][1],
                    "challenge": challenges[index],
                    "signature": devices[index][2](challenges[index].encode("ascii")),
                    "confirm_transfer": True,
                },
                content_type="application/json",
            )
            if response.status_code == 200:
                outcome: dict[str, object] = {"status": response.status_code}
            else:
                outcome = {"status": response.status_code, "code": response.json().get("code")}
        except Exception as error:
            outcome = {"raised": type(error).__name__}
        finally:
            connections.close_all()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    errors = [result for result in results if result != {"status": 200}]
    assert errors == [], f"unexpected exchange results: {results}"
    active_devices = list(Device.objects.filter(revoked_at__isnull=True))
    active_sessions = list(LearnerSession.objects.filter(revoked_at__isnull=True))
    assert len(active_devices) == 1
    assert len(active_sessions) == 1
    active_device = active_devices[0]
    active_session = active_sessions[0]
    assert active_session.device_id == active_device.id
    assert active_session.pass_generation == AccessPass.objects.get().generation
