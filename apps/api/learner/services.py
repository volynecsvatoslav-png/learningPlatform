import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jwt as pyjwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.conf import settings
from django.contrib.auth import login
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from accounts.models import User
from accounts.rate_limit import trusted_client_ip
from audit.models import AuditEvent
from learner.models import (
    AccessPass,
    Device,
    DeviceChallenge,
    Enrollment,
    LearnerSession,
    RecoveryChallenge,
    hash_access_token,
    hash_recovery_token,
    hash_session_token,
)
from learning.models import Course


class InvalidAccessLink(Exception):
    pass


class DeviceProofError(Exception):
    pass


class TransferConfirmationRequired(Exception):
    pass


class InvalidRecoveryToken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LearnerAuthContext:
    learner: User
    session: LearnerSession
    access_pass: AccessPass
    device: Device


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    access_pass: AccessPass
    device: Device
    session: LearnerSession
    transfer_performed: bool


def new_access_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_access_token(raw_token)


def normalize_public_jwk(public_key_jwk: object) -> dict[str, str]:
    if not isinstance(public_key_jwk, dict):
        raise DeviceProofError("Public key must be a JSON object.")
    try:
        return {field: str(public_key_jwk[field]) for field in ("kty", "crv", "x", "y")}
    except KeyError as error:
        raise DeviceProofError("Public key JWK is incomplete.") from error


def require_p256_jwk(public_key_jwk: dict[str, str]) -> dict[str, str]:
    if public_key_jwk["kty"] != "EC" or public_key_jwk["crv"] != "P-256":
        raise DeviceProofError("Only ECDSA P-256 keys are accepted.")
    return public_key_jwk


def jwk_fingerprint(public_key_jwk: dict[str, str]) -> str:
    canonical = json.dumps(
        {key: public_key_jwk[key] for key in ("kty", "crv", "x", "y")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_device_signature(
    *, public_key_jwk: dict[str, str], message: bytes, signature: str
) -> bool:
    try:
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if len(raw) != 64:
            return False
        public_key = pyjwt.algorithms.ECAlgorithm.from_jwk(
            {
                "kty": "EC",
                "crv": "P-256",
                "x": public_key_jwk["x"],
                "y": public_key_jwk["y"],
            }
        )
        if not isinstance(public_key, EllipticCurvePublicKey):
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        public_key.verify(der, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, TypeError, ValueError, pyjwt.exceptions.InvalidKeyError):
        return False


def user_agent_summary(user_agent: str) -> str:
    browser = "Браузер"
    for marker, name in (
        ("Edg/", "Edge"),
        ("OPR/", "Opera"),
        ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"),
        ("Safari/", "Safari"),
    ):
        if marker in user_agent:
            browser = name
            break
    if "iPhone" in user_agent or "iPad" in user_agent or "iPod" in user_agent:
        platform = "iOS"
    elif "Android" in user_agent:
        platform = "Android"
    elif "Windows" in user_agent:
        platform = "Windows"
    elif "Mac OS X" in user_agent or "Macintosh" in user_agent:
        platform = "macOS"
    elif "Linux" in user_agent:
        platform = "Linux"
    else:
        platform = ""
    return " · ".join(part for part in (browser, platform) if part) or "Браузер"


def write_audit(
    *,
    event_type: str,
    vendor: Any = None,
    actor: User | None = None,
    target_type: str = "",
    target_id: uuid.UUID | None = None,
    request: HttpRequest | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    ip_hash: str | None = None
    agent_summary = ""
    if request is not None:
        ip_hash = hashlib.sha256(trusted_client_ip(request).encode("utf-8")).hexdigest()
        agent_summary = user_agent_summary(str(request.META.get("HTTP_USER_AGENT", "")))
    AuditEvent.objects.create(
        vendor=vendor,
        actor_user=actor,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        ip_hash=ip_hash,
        user_agent_summary=agent_summary,
        metadata=metadata or {},
    )


def _pass_for_token(token: str) -> AccessPass | None:
    return (
        AccessPass.objects.filter(
            token_hash=hash_access_token(token),
            status=AccessPass.Status.ACTIVE,
            user__is_active=True,
        )
        .select_related("user", "vendor")
        .first()
    )


def _access_link(raw_token: str) -> str:
    return f"{settings.PUBLIC_APP_URL}/app/#access={raw_token}"


def _revoke_active_sessions(access_pass: AccessPass, reason: str) -> None:
    LearnerSession.objects.filter(access_pass=access_pass, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason
    )


def grant_course_access(
    *,
    vendor: Any,
    learner_email: str,
    course_ids: list[uuid.UUID],
    granted_by: User,
    request: HttpRequest,
) -> dict[str, Any]:
    courses = list(
        Course.objects.filter(pk__in=course_ids, vendor=vendor, status=Course.Status.PUBLISHED)
    )
    if len(courses) != len(set(course_ids)):
        raise InvalidAccessLink("Course does not belong to the vendor.")
    learner, _ = User.objects.get_or_create(
        email=User.objects.normalize_email_address(learner_email)
    )
    with transaction.atomic():
        enrollments: list[Enrollment] = []
        for course in courses:
            enrollment, _ = Enrollment.objects.update_or_create(
                user=learner,
                course=course,
                defaults={
                    "vendor": vendor,
                    "status": Enrollment.Status.ACTIVE,
                    "source": Enrollment.Source.MANUAL,
                    "revoked_at": None,
                    "granted_by": granted_by,
                },
            )
            enrollments.append(enrollment)
            write_audit(
                event_type="grant_enrollment",
                vendor=vendor,
                actor=granted_by,
                target_type="Enrollment",
                target_id=enrollment.id,
                request=request,
                metadata={"course_id": str(course.id)},
            )
        access_pass = (
            AccessPass.objects.filter(vendor=vendor, user=learner, status=AccessPass.Status.ACTIVE)
            .select_for_update()
            .first()
        )
        raw_token: str | None = None
        link: str | None = None
        if access_pass is None:
            raw_token, token_hash = new_access_token()
            access_pass = AccessPass.objects.create(
                vendor=vendor,
                user=learner,
                token_hash=token_hash,
                token_prefix=raw_token[:8],
                generation=1,
            )
            link = _access_link(raw_token)
            write_audit(
                event_type="access_pass_creation",
                vendor=vendor,
                actor=granted_by,
                target_type="AccessPass",
                target_id=access_pass.id,
                request=request,
            )
        if link is not None:
            send_mail(
                subject=f"Доступ к курсам: {vendor.name}",
                message=f"Откройте ссылку для входа: {link}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[learner.email],
            )
    return {
        "enrollments": enrollments,
        "access_pass": access_pass,
        "link": link,
        "token": raw_token,
    }


def rotate_access_pass(
    *, access_pass: AccessPass, actor: User, request: HttpRequest
) -> tuple[AccessPass, str]:
    with transaction.atomic():
        locked = AccessPass.objects.select_for_update().get(pk=access_pass.pk)
        if locked.status != AccessPass.Status.ACTIVE:
            raise InvalidAccessLink("Access pass is revoked.")
        raw_token, token_hash = new_access_token()
        locked.token_hash = token_hash
        locked.token_prefix = raw_token[:8]
        locked.rotated_at = timezone.now()
        locked.save(update_fields=("token_hash", "token_prefix", "rotated_at"))
        write_audit(
            event_type="access_pass_rotation",
            vendor=locked.vendor,
            actor=actor,
            target_type="AccessPass",
            target_id=locked.id,
            request=request,
        )
    link = _access_link(raw_token)
    send_mail(
        subject=f"Доступ к курсам: {locked.vendor.name}",
        message=f"Откройте ссылку для входа: {link}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[locked.user.email],
    )
    return locked, link


def revoke_access_pass(*, access_pass: AccessPass, actor: User, request: HttpRequest) -> None:
    now = timezone.now()
    with transaction.atomic():
        locked = AccessPass.objects.select_for_update().get(pk=access_pass.pk)
        if locked.status == AccessPass.Status.REVOKED:
            return
        locked.status = AccessPass.Status.REVOKED
        locked.rotated_at = now
        locked.save(update_fields=("status", "rotated_at"))
        Device.objects.filter(access_pass=locked, revoked_at__isnull=True).update(revoked_at=now)
        _revoke_active_sessions(locked, LearnerSession.RevokeReason.MANUAL)
        write_audit(
            event_type="access_pass_revoke",
            vendor=locked.vendor,
            actor=actor,
            target_type="AccessPass",
            target_id=locked.id,
            request=request,
        )


def inspect_access(
    *,
    token: str,
    installation_id: uuid.UUID,
    public_key_jwk: dict[str, str],
) -> tuple[AccessPass, DeviceChallenge, bool, bool]:
    access_pass = _pass_for_token(token)
    if access_pass is None:
        raise InvalidAccessLink("Access pass not found.")
    challenge = DeviceChallenge.objects.create(
        access_pass=access_pass,
        challenge=secrets.token_urlsafe(32),
        installation_id=installation_id,
        public_key_jwk=public_key_jwk,
        public_key_fingerprint=jwk_fingerprint(public_key_jwk),
        expires_at=timezone.now() + timedelta(seconds=settings.DEVICE_CHALLENGE_TTL_SECONDS),
    )
    DeviceChallenge.objects.filter(
        access_pass=access_pass,
        installation_id=installation_id,
        used_at__isnull=True,
    ).exclude(pk=challenge.pk).update(used_at=timezone.now())
    existing = (
        Device.objects.filter(access_pass=access_pass, revoked_at__isnull=True)
        .order_by("-last_seen_at")
        .first()
    )
    fingerprint = jwk_fingerprint(public_key_jwk)
    device_match = (
        existing is not None
        and existing.installation_id == installation_id
        and existing.public_key_fingerprint == fingerprint
    )
    transfer_required = existing is not None and not device_match
    return access_pass, challenge, device_match, transfer_required


def _create_learner_session(
    request: HttpRequest, access_pass: AccessPass, device: Device
) -> LearnerSession:
    login(request, access_pass.user)
    request.session.set_expiry(settings.LEARNER_SESSION_AGE)
    session_key = request.session.session_key
    if session_key is None:
        raise RuntimeError("Django did not create a learner session")
    if LearnerSession.objects.filter(session_key=session_key).exists():
        request.session.cycle_key()
        request.session.set_expiry(settings.LEARNER_SESSION_AGE)
        session_key = request.session.session_key
        if session_key is None:
            raise RuntimeError("Django did not create a learner session")
    return LearnerSession.objects.create(
        learner=access_pass.user,
        access_pass=access_pass,
        device=device,
        session_key=session_key,
        session_token_hash=hash_session_token(session_key),
        device_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        pass_generation=access_pass.generation,
        expires_at=timezone.now() + timedelta(seconds=settings.LEARNER_SESSION_AGE),
    )


@transaction.atomic
def exchange_access(
    *,
    request: HttpRequest,
    token: str,
    installation_id: uuid.UUID,
    public_key_jwk: dict[str, str],
    challenge_value: str,
    signature: str,
    confirm_transfer: bool,
) -> ExchangeResult:
    access_pass = _pass_for_token(token)
    if access_pass is None:
        raise InvalidAccessLink("Access pass not found.")
    normalized_jwk = require_p256_jwk(normalize_public_jwk(public_key_jwk))
    challenge = (
        DeviceChallenge.objects.select_for_update()
        .filter(access_pass=access_pass, challenge=challenge_value)
        .first()
    )
    now = timezone.now()
    if (
        challenge is None
        or challenge.used_at is not None
        or challenge.expires_at <= now
        or challenge.installation_id != installation_id
        or challenge.public_key_fingerprint != jwk_fingerprint(normalized_jwk)
    ):
        raise DeviceProofError("Challenge is invalid or expired.")
    message = challenge.challenge.encode("utf-8")
    if not verify_device_signature(
        public_key_jwk=normalized_jwk, message=message, signature=signature
    ):
        raise DeviceProofError("Device signature is invalid.")
    challenge.used_at = now
    challenge.save(update_fields=("used_at",))

    with transaction.atomic():
        locked_pass = AccessPass.objects.select_for_update().get(pk=access_pass.pk)
        if locked_pass.status != AccessPass.Status.ACTIVE:
            raise InvalidAccessLink("Access pass is revoked.")
        existing = (
            Device.objects.filter(access_pass=locked_pass, revoked_at__isnull=True)
            .select_for_update()
            .order_by("-last_seen_at")
            .first()
        )
        fingerprint = jwk_fingerprint(normalized_jwk)
        device_match = (
            existing is not None
            and existing.installation_id == installation_id
            and existing.public_key_fingerprint == fingerprint
        )
        transfer_performed = False
        if not device_match and existing is not None:
            if not confirm_transfer:
                raise TransferConfirmationRequired()
            transfer_performed = True
            locked_pass.generation += 1
            locked_pass.save(update_fields=("generation",))
            existing.revoked_at = now
            existing.save(update_fields=("revoked_at",))
            _revoke_active_sessions(locked_pass, LearnerSession.RevokeReason.REPLACED)
            write_audit(
                event_type="device_transfer",
                vendor=locked_pass.vendor,
                actor=locked_pass.user,
                target_type="Device",
                target_id=existing.id,
                request=request,
                metadata={"new_installation_id": str(installation_id)},
            )
            write_audit(
                event_type="session_replacement",
                vendor=locked_pass.vendor,
                actor=locked_pass.user,
                target_type="AccessPass",
                target_id=locked_pass.id,
                request=request,
            )
        if device_match:
            device = existing
            assert device is not None
            _revoke_active_sessions(locked_pass, LearnerSession.RevokeReason.REPLACED)
        else:
            device = Device.objects.create(
                access_pass=locked_pass,
                installation_id=installation_id,
                public_key_jwk=normalized_jwk,
                public_key_fingerprint=jwk_fingerprint(normalized_jwk),
                display_name=user_agent_summary(str(request.META.get("HTTP_USER_AGENT", ""))),
            )
            write_audit(
                event_type="device_activation",
                vendor=locked_pass.vendor,
                actor=locked_pass.user,
                target_type="Device",
                target_id=device.id,
                request=request,
            )
        locked_pass.last_used_at = now
        locked_pass.save(update_fields=("last_used_at",))
        session = _create_learner_session(request, locked_pass, device)
        write_audit(
            event_type="access_exchange",
            vendor=locked_pass.vendor,
            actor=locked_pass.user,
            target_type="LearnerSession",
            target_id=session.id,
            request=request,
            metadata={"generation": locked_pass.generation},
        )
    return ExchangeResult(
        access_pass=locked_pass,
        device=device,
        session=session,
        transfer_performed=transfer_performed,
    )


def request_recovery(*, email: str, request: HttpRequest) -> list[RecoveryChallenge]:
    normalized = User.objects.normalize_email_address(email)
    user = (
        User.objects.filter(
            email=normalized,
            is_active=True,
            access_passes__status=AccessPass.Status.ACTIVE,
        )
        .distinct()
        .first()
    )
    if user is None:
        return []
    ip_hash = hashlib.sha256(trusted_client_ip(request).encode("utf-8")).hexdigest()
    created: list[RecoveryChallenge] = []
    passes = AccessPass.objects.filter(user=user, status=AccessPass.Status.ACTIVE)
    for access_pass in passes.select_related("vendor"):
        raw_token = secrets.token_urlsafe(32)
        challenge = RecoveryChallenge.objects.create(
            user=user,
            vendor=access_pass.vendor,
            token_hash=hash_recovery_token(raw_token),
            expires_at=timezone.now() + timedelta(seconds=settings.RECOVERY_TOKEN_TTL_SECONDS),
            requested_ip_hash=ip_hash,
        )
        link = f"{settings.PUBLIC_APP_URL}/app/#recovery={raw_token}"
        send_mail(
            subject="Восстановление доступа к обучению",
            message=f"Откройте ссылку для восстановления доступа: {link}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
        created.append(challenge)
    return created


@transaction.atomic
def recover_access(
    *,
    request: HttpRequest,
    recovery_token: str,
    installation_id: uuid.UUID,
    public_key_jwk: dict[str, str],
    signature: str,
) -> tuple[AccessPass, str]:
    normalized_jwk = require_p256_jwk(normalize_public_jwk(public_key_jwk))
    now = timezone.now()
    challenge = (
        RecoveryChallenge.objects.select_for_update()
        .filter(token_hash=hash_recovery_token(recovery_token))
        .select_related("user", "vendor")
        .first()
    )
    if (
        challenge is None
        or challenge.used_at is not None
        or challenge.expires_at <= now
        or not challenge.user.is_active
    ):
        raise InvalidRecoveryToken("Recovery token is invalid.")
    message = (
        f"lms-recovery:{installation_id}:{hashlib.sha256(recovery_token.encode()).hexdigest()}"
    ).encode()
    if not verify_device_signature(
        public_key_jwk=normalized_jwk, message=message, signature=signature
    ):
        raise DeviceProofError("Device signature is invalid.")
    challenge.used_at = now
    challenge.save(update_fields=("used_at",))

    with transaction.atomic():
        learner = User.objects.select_for_update().get(pk=challenge.user_id)
        previous = (
            AccessPass.objects.select_for_update()
            .filter(vendor=challenge.vendor, user=learner, status=AccessPass.Status.ACTIVE)
            .first()
        )
        if previous is not None:
            previous.status = AccessPass.Status.REVOKED
            previous.rotated_at = now
            previous.save(update_fields=("status", "rotated_at"))
            Device.objects.filter(access_pass=previous, revoked_at__isnull=True).update(
                revoked_at=now
            )
            _revoke_active_sessions(previous, LearnerSession.RevokeReason.REPLACED)
            write_audit(
                event_type="access_pass_revoke",
                vendor=challenge.vendor,
                actor=learner,
                target_type="AccessPass",
                target_id=previous.id,
                request=request,
            )
        raw_token, token_hash = new_access_token()
        access_pass = AccessPass.objects.create(
            vendor=challenge.vendor,
            user=learner,
            token_hash=token_hash,
            token_prefix=raw_token[:8],
            generation=1,
        )
        device = Device.objects.create(
            access_pass=access_pass,
            installation_id=installation_id,
            public_key_jwk=normalized_jwk,
            public_key_fingerprint=jwk_fingerprint(normalized_jwk),
            display_name=user_agent_summary(str(request.META.get("HTTP_USER_AGENT", ""))),
        )
        _create_learner_session(request, access_pass, device)
        write_audit(
            event_type="learner_recovery",
            vendor=challenge.vendor,
            actor=learner,
            target_type="AccessPass",
            target_id=access_pass.id,
            request=request,
            metadata={"recovery_challenge_id": str(challenge.id)},
        )
        write_audit(
            event_type="device_activation",
            vendor=challenge.vendor,
            actor=learner,
            target_type="Device",
            target_id=device.id,
            request=request,
        )
    return access_pass, raw_token
