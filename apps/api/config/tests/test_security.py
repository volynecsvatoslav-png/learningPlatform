import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
class TestSecurityHeaders:
    def test_api_responses_carry_strict_csp(self, client: Client) -> None:
        response = client.get("/api/v1/learner/csrf")

        assert response["Content-Security-Policy"] == (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )

    def test_api_csp_is_present_even_on_errors(self, client: Client) -> None:
        response = client.get("/api/v1/learner/courses")

        assert response.status_code == 401
        assert "default-src 'none'" in response["Content-Security-Policy"]

    def test_backoffice_csp_blocks_clickjacking(self, client: Client) -> None:
        response = client.get("/backoffice/login/")

        assert response.status_code == 200
        assert response["Content-Security-Policy"] == "frame-ancestors 'none'"

    def test_nosniff_and_frame_options_are_set(self, client: Client) -> None:
        response = client.get("/api/v1/learner/csrf")

        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["X-Frame-Options"] == "DENY"

    def test_secure_cookies_use_host_prefix(self, client: Client) -> None:
        with override_settings(
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SESSION_COOKIE_NAME="__Host-backoffice_session",
            CSRF_COOKIE_NAME="__Host-csrftoken",
        ):
            response = client.get("/api/v1/learner/csrf")

        assert response.cookies["__Host-csrftoken"]["secure"] is True
        assert response.cookies["__Host-csrftoken"]["httponly"] is True
        assert response.cookies["__Host-csrftoken"]["samesite"] == "Lax"


@pytest.mark.django_db
class TestCorsAllowlist:
    def test_no_cors_headers_by_default(self, client: Client) -> None:
        response = client.get("/api/v1/learner/csrf", HTTP_ORIGIN="http://evil.example")

        assert "Access-Control-Allow-Origin" not in response

    def test_allowed_origin_gets_headers(self, client: Client) -> None:
        with override_settings(CORS_ALLOWED_ORIGINS=("http://app.example",)):
            response = client.get("/api/v1/learner/csrf", HTTP_ORIGIN="http://app.example")

        assert response["Access-Control-Allow-Origin"] == "http://app.example"
        assert response["Access-Control-Allow-Credentials"] == "true"
        assert "Origin" in response.get("Vary", "")

    def test_disallowed_origin_gets_no_headers(self, client: Client) -> None:
        with override_settings(CORS_ALLOWED_ORIGINS=("http://app.example",)):
            response = client.get("/api/v1/learner/csrf", HTTP_ORIGIN="http://evil.example")

        assert "Access-Control-Allow-Origin" not in response

    def test_preflight_allowed_origin(self, client: Client) -> None:
        with override_settings(CORS_ALLOWED_ORIGINS=("http://app.example",)):
            response = client.options(
                "/api/v1/vendor/auth/login",
                HTTP_ORIGIN="http://app.example",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            )

        assert response.status_code == 200
        assert response["Access-Control-Allow-Origin"] == "http://app.example"
        assert "POST" in response["Access-Control-Allow-Methods"]
        assert "x-csrftoken" in response["Access-Control-Allow-Headers"]

    def test_preflight_disallowed_origin_is_rejected(self, client: Client) -> None:
        with override_settings(CORS_ALLOWED_ORIGINS=("http://app.example",)):
            response = client.options(
                "/api/v1/vendor/auth/login",
                HTTP_ORIGIN="http://evil.example",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            )

        assert response.status_code == 403
