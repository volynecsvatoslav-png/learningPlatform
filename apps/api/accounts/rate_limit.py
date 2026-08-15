import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest


def _rate_limited(
    request: HttpRequest, *, prefix: str, bucket: str, limit: int, window_seconds: int
) -> bool:
    address = request.META.get("REMOTE_ADDR", "unknown")
    key = f"{prefix}:{bucket}:{hashlib.sha256(address.encode()).hexdigest()}"
    if cache.add(key, 1, window_seconds):
        return False
    try:
        return int(cache.incr(key)) > limit
    except ValueError:
        cache.set(key, 1, window_seconds)
        return False


def auth_rate_limited(request: HttpRequest, bucket: str) -> bool:
    return _rate_limited(
        request,
        prefix="vendor-auth",
        bucket=bucket,
        limit=settings.VENDOR_AUTH_RATE_LIMIT,
        window_seconds=settings.VENDOR_AUTH_RATE_WINDOW_SECONDS,
    )


def pwa_transfer_rate_limited(request: HttpRequest) -> bool:
    return _rate_limited(
        request,
        prefix="pwa-transfer",
        bucket="consume",
        limit=settings.PWA_TRANSFER_RATE_LIMIT,
        window_seconds=settings.PWA_TRANSFER_RATE_WINDOW_SECONDS,
    )
