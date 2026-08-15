import base64
import hashlib
import json
import secrets
import time
import uuid
from typing import Any

from django.conf import settings

from accounts.models import User
from learner.models import LearnerSession
from learning.models import Course, CourseRevision

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
Point = tuple[int, int] | None


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _point_add(left: Point, right: Point) -> Point:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if left == right:
        slope = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    return x3, (slope * (x1 - x3) - y1) % P


def _scalar_multiply(value: int, point: Point = (GX, GY)) -> Point:
    result: Point = None
    addend = point
    while value:
        if value & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        value >>= 1
    return result


def _private_scalar() -> int:
    configured = str(settings.OFFLINE_LICENSE_SIGNING_PRIVATE_KEY).encode()
    return int.from_bytes(hashlib.sha256(configured).digest(), "big") % (N - 1) + 1


def verification_jwk() -> dict[str, Any]:
    point = _scalar_multiply(_private_scalar())
    if point is None:
        raise RuntimeError("Unable to derive offline license public key")
    x, y = point
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _base64url(x.to_bytes(32, "big")),
        "y": _base64url(y.to_bytes(32, "big")),
        "ext": True,
        "key_ops": ["verify"],
    }


def _sign(value: bytes) -> bytes:
    digest = int.from_bytes(hashlib.sha256(value).digest(), "big")
    private = _private_scalar()
    while True:
        nonce = secrets.randbelow(N - 1) + 1
        point = _scalar_multiply(nonce)
        if point is None:
            continue
        r = point[0] % N
        if r == 0:
            continue
        s = pow(nonce, -1, N) * (digest + r * private) % N
        if s:
            s = min(s, N - s)
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def issue_offline_license(
    *, learner: User, course: Course, revision: CourseRevision, session: LearnerSession
) -> dict[str, Any]:
    issued_at = int(time.time())
    expires_at = issued_at + settings.OFFLINE_LICENSE_TTL_HOURS * 60 * 60
    claims: dict[str, Any] = {
        "license_id": str(uuid.uuid4()),
        "learner_id": str(learner.id),
        "course_id": str(course.id),
        "revision_id": str(revision.id),
        "revision": revision.revision_number,
        "device_id": session.device_hash,
        "session_id": str(session.id),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "iat": issued_at,
        "exp": expires_at,
    }
    header = _base64url(json.dumps({"alg": "ES256", "typ": "JWT"}).encode())
    payload = _base64url(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    token = f"{header}.{payload}.{_base64url(_sign(signing_input))}"
    return {"token": token, "claims": claims, "verification_key": verification_jwk()}
