import secrets
import threading

import pytest
from django.core.cache import cache
from django.db import connections
from django.test import Client

from accounts.models import User
from learner.models import AccessPass, Device, Enrollment, LearnerSession, hash_access_token
from learner.tests.helpers import activate, make_device, request_exchange
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
def test_concurrent_transfers_leave_exactly_one_active_session(iteration: int) -> None:
    cache.clear()
    token = _make_access(f"learner-{iteration}@example.com")
    first = Client()
    activate(first, token, device=make_device())

    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            response = request_exchange(
                Client(), token, device=make_device(), confirm_transfer=True
            )
        finally:
            connections.close_all()
        with lock:
            results.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [200, 200], f"unexpected exchange results: {results}"
    active_devices = list(Device.objects.filter(revoked_at__isnull=True))
    active_sessions = list(LearnerSession.objects.filter(revoked_at__isnull=True))
    assert len(active_devices) == 1
    assert len(active_sessions) == 1
    active_device = active_devices[0]
    active_session = active_sessions[0]
    assert active_session.device_id == active_device.id
    assert active_session.pass_generation == AccessPass.objects.get().generation
