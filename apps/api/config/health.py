from typing import Any

from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from redis import Redis


@require_GET
def health(request: Any) -> JsonResponse:
    checks: dict[str, str] = {}
    try:
        connections["default"].ensure_connection()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    finally:
        client.close()

    healthy = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status=200 if healthy else 503,
    )
