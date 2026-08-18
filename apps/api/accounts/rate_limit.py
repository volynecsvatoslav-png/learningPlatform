import hashlib
import ipaddress
import uuid

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest


def _rate_limited(
    *, prefix: str, bucket: str, identity: str, limit: int, window_seconds: int
) -> bool:
    key = f"{prefix}:{bucket}:{hashlib.sha256(identity.encode()).hexdigest()}"
    if cache.add(key, 1, window_seconds):
        return False
    try:
        return int(cache.incr(key)) > limit
    except ValueError:
        cache.set(key, 1, window_seconds)
        return False


def _ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted_proxy(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for value in settings.TRUSTED_PROXY_CIDRS:
        try:
            if address in ipaddress.ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def trusted_client_ip(request: HttpRequest) -> str:
    remote = _ip_address(str(request.META.get("REMOTE_ADDR", "")))
    if remote is None:
        return "unknown"
    if not _trusted_proxy(remote):
        return str(remote)

    forwarded = str(
        request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("HTTP_X_REAL_IP") or ""
    )
    chain = [address for value in forwarded.split(",") if (address := _ip_address(value))]
    for address in reversed(chain):
        if not _trusted_proxy(address):
            return str(address)
    return str(chain[0] if chain else remote)


def auth_rate_limited(request: HttpRequest, bucket: str, email: str) -> bool:
    return _rate_limited(
        prefix="vendor-auth",
        bucket=bucket,
        identity=f"{email.strip().casefold()}:{trusted_client_ip(request)}",
        limit=settings.VENDOR_AUTH_RATE_LIMIT,
        window_seconds=settings.VENDOR_AUTH_RATE_WINDOW_SECONDS,
    )


def pwa_transfer_rate_limited(request: HttpRequest, transfer_id: uuid.UUID | None) -> bool:
    identity = (
        f"transfer:{transfer_id}"
        if transfer_id is not None
        else f"invalid:{trusted_client_ip(request)}"
    )
    return _rate_limited(
        prefix="pwa-transfer",
        bucket="consume",
        identity=identity,
        limit=settings.PWA_TRANSFER_RATE_LIMIT,
        window_seconds=settings.PWA_TRANSFER_RATE_WINDOW_SECONDS,
    )


def learner_auth_rate_limited(request: HttpRequest, bucket: str) -> bool:
    return _rate_limited(
        prefix="learner-auth",
        bucket=bucket,
        identity=trusted_client_ip(request),
        limit=settings.ACCESS_AUTH_RATE_LIMIT,
        window_seconds=settings.ACCESS_AUTH_RATE_WINDOW_SECONDS,
    )


def recovery_request_rate_limited(request: HttpRequest, email: str) -> tuple[bool, bool]:
    ip_limited = _rate_limited(
        prefix="learner-recovery",
        bucket="request-ip",
        identity=trusted_client_ip(request),
        limit=settings.RECOVERY_REQUEST_IP_LIMIT,
        window_seconds=settings.RECOVERY_REQUEST_RATE_WINDOW_SECONDS,
    )
    email_limited = _rate_limited(
        prefix="learner-recovery",
        bucket="request-email",
        identity=hashlib.sha256(email.strip().casefold().encode()).hexdigest(),
        limit=settings.RECOVERY_REQUEST_EMAIL_LIMIT,
        window_seconds=settings.RECOVERY_REQUEST_RATE_WINDOW_SECONDS,
    )
    return ip_limited, email_limited


def heartbeat_rate_limited(request: HttpRequest, session_key: str) -> bool:
    return _rate_limited(
        prefix="learner-heartbeat",
        bucket="session",
        identity=f"session:{hashlib.sha256(session_key.encode()).hexdigest()}",
        limit=settings.HEARTBEAT_RATE_LIMIT,
        window_seconds=settings.HEARTBEAT_RATE_WINDOW_SECONDS,
    )
