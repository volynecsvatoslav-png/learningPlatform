import logging
import re
from typing import Any

_SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)(X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|"
            r"AWSAccessKeyId|Signature)(=|\"|%3D)([A-Za-z0-9%+/_.~-]{16,})"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(access_token|recovery_token|reset_token|csrfmiddlewaretoken|"
            r"x-csrftoken|password|old_password|new_password)([\"']?\\?[\"']?\s*[:=]\s*)"
            r"([\"']?[A-Za-z0-9._%+/@#!$_-]{8,})"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)authorization\s*[:=]\s*Bearer\s+[A-Za-z0-9._~+/=-]+"), "[REDACTED]"),
    (re.compile(r"(?i)AKIA[0-9A-Z]{16}"), "[REDACTED]"),
)


def redact(value: Any) -> str:
    text = str(value)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactSecretsFilter(logging.Filter):
    """Scrub tokens, passwords and S3 signing parameters from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def build_logging_config() -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"redact_secrets": {"()": "config.logging.RedactSecretsFilter"}},
        "formatters": {
            "console": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "filters": ["redact_secrets"],
            }
        },
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {
            "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
            "django.security": {"handlers": ["console"], "level": "ERROR", "propagate": False},
            "gunicorn": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "gunicorn.error": {"handlers": ["console"], "level": "ERROR", "propagate": False},
            "gunicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        },
    }
