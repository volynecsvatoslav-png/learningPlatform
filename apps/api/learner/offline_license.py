import base64
import time
import uuid
from datetime import timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from django.conf import settings
from django.utils import timezone

from accounts.models import User
from learner.models import AccessPass, Device, OfflineLicense
from learning.models import Course, CourseRevision


def _private_key_pem() -> bytes:
    return base64.b64decode(settings.OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64, validate=True)


def verification_jwk() -> dict[str, Any]:
    private_key = serialization.load_pem_private_key(_private_key_pem(), password=None)
    public_key = private_key.public_key()
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise ValueError("Offline license key must be an EC private key")
    return jwt.algorithms.ECAlgorithm.to_jwk(public_key, as_dict=True)


def issue_offline_license(
    *,
    learner: User,
    access_pass: AccessPass,
    device: Device,
    course: Course,
    revision: CourseRevision,
) -> dict[str, Any]:
    issued_at = int(time.time())
    expires_at = issued_at + settings.OFFLINE_LICENSE_TTL_HOURS * 60 * 60
    claims: dict[str, Any] = {
        "license_id": str(uuid.uuid4()),
        "learner_id": str(learner.id),
        "course_id": str(course.id),
        "revision_id": str(revision.id),
        "revision": revision.revision_number,
        "access_pass_id": str(access_pass.id),
        "pass_generation": access_pass.generation,
        "device_id": str(device.id),
        "session_id": None,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(claims, _private_key_pem(), algorithm="ES256", headers={"typ": "JWT"})
    OfflineLicense.objects.create(
        device=device,
        access_pass=access_pass,
        course=course,
        course_revision=revision,
        pass_generation=access_pass.generation,
        expires_at=timezone.now() + timedelta(hours=settings.OFFLINE_LICENSE_TTL_HOURS),
    )
    return {"token": token, "claims": claims}
