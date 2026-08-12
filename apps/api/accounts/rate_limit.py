import hashlib

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest


def auth_rate_limited(request: HttpRequest, bucket: str) -> bool:
    address = request.META.get("REMOTE_ADDR", "unknown")
    key = f"vendor-auth:{bucket}:{hashlib.sha256(address.encode()).hexdigest()}"
    count = int(cache.get(key, 0))
    if count >= settings.VENDOR_AUTH_RATE_LIMIT:
        return True
    cache.set(key, count + 1, settings.VENDOR_AUTH_RATE_WINDOW_SECONDS)
    return False
