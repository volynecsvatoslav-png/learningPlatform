from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.utils.cache import patch_vary_headers

_ALLOWED_METHODS = ("GET", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS")
_ALLOWED_HEADERS = ("accept", "content-type", "x-csrftoken")
_MAX_AGE = 600


class CorsAllowlistMiddleware:
    """Strict CORS allowlist.

    No CORS headers are emitted unless the request Origin is on the explicit
    allowlist, so same-origin clients keep working and cross-origin browsers
    get blocked by default. Preflight requests are short-circuited.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        origin = request.headers.get("Origin") or ""
        allowed = origin in settings.CORS_ALLOWED_ORIGINS
        if request.method == "OPTIONS" and "Access-Control-Request-Method" in request.headers:
            if not allowed:
                return HttpResponse(status=403)
            response = HttpResponse()
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = ", ".join(_ALLOWED_METHODS)
            response["Access-Control-Allow-Headers"] = ", ".join(_ALLOWED_HEADERS)
            response["Access-Control-Max-Age"] = str(_MAX_AGE)
            return response
        result = self.get_response(request)
        if allowed:
            result["Access-Control-Allow-Origin"] = origin
            result["Access-Control-Allow-Credentials"] = "true"
            patch_vary_headers(result, ["Origin"])
        return result
