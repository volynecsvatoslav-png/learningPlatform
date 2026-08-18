from collections.abc import Callable

from django.http import HttpRequest, HttpResponseBase

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
ADMIN_CSP = "frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    """Add CSP headers that Django's SecurityMiddleware does not configure.

    JSON API responses carry a strict policy that executes nothing. The Django
    admin keeps its scripts working while still blocking clickjacking.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        path = request.path
        if path.startswith("/api/"):
            response["Content-Security-Policy"] = API_CSP
        elif path.startswith("/backoffice/"):
            response["Content-Security-Policy"] = ADMIN_CSP
        return response
