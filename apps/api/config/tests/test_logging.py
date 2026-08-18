import logging

from config.logging import RedactSecretsFilter, redact


class TestRedact:
    def test_presigned_url_parameters_are_redacted(self) -> None:
        url = (
            "https://s3.example/bucket/key?X-Amz-Signature=abcdef0123456789abcdef0123456789"
            "abcdef0123456789abcdef0123456789&X-Amz-Credential=AKIAEXAMPLE%2F20260818"
            "&X-Amz-Security-Token=tokenvalue123456789"
        )
        result = redact(url)

        assert "abcdef0123456789abcdef0123456789" not in result
        assert "AKIAEXAMPLE%2F20260818" not in result
        assert "tokenvalue123456789" not in result
        assert "[REDACTED]" in result

    def test_legacy_signing_credentials_are_redacted(self) -> None:
        result = redact(
            "AWSAccessKeyId=AKIAIOSFODNN7EXAMPLE&"
            "Signature=abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
        )

        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "abcdef0123456789" not in result

    def test_bearer_authorization_is_redacted(self) -> None:
        result = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.value")

        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_password_and_tokens_in_json_are_redacted(self) -> None:
        result = redact(
            '{"email": "a@b.c", "password": "s3cr3t-p@ss", "access_token": "tok_12345678"}'
        )

        assert "s3cr3t-p@ss" not in result
        assert "tok_12345678" not in result
        assert "a@b.c" in result

    def test_access_key_pattern_is_redacted(self) -> None:
        result = redact("key=AKIAIOSFODNN7EXAMPLE-inline")

        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_plain_legit_message_survives(self) -> None:
        message = "course published revision=3 total=12"
        assert redact(message) == message


class TestRedactSecretsFilter:
    def test_filter_mutates_message_and_args(self) -> None:
        filter_ = RedactSecretsFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="token=%s password=%s",
            args=("tok_12345678", "s3cr3t-pass"),
            exc_info=None,
        )

        assert filter_.filter(record) is True
        assert "s3cr3t-pass" not in record.getMessage()
