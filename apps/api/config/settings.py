import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def postgres_database() -> dict[str, object]:
    raw_url = os.getenv("DATABASE_URL", "postgresql://learning:learning@localhost:5432/learning")
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": parsed.port or 5432,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if host
]
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "vendors",
    "media_assets",
    "learning",
    "learner",
    "vendor_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": postgres_database()}
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

MEDIA_S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
MEDIA_S3_PUBLIC_ENDPOINT_URL = os.getenv("S3_PUBLIC_ENDPOINT_URL", MEDIA_S3_ENDPOINT_URL)
MEDIA_S3_REGION = os.getenv("S3_REGION", "us-east-1")
MEDIA_S3_BUCKET = os.getenv("S3_BUCKET", "learning-platform")
MEDIA_S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "minio-local")
MEDIA_S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "minio-local-secret")
MEDIA_S3_USE_SSL = env_bool("S3_USE_SSL", False)
MEDIA_S3_CHECKSUM_POLICY_SUPPORTED = env_bool("S3_CHECKSUM_POLICY_SUPPORTED", False)
MEDIA_UPLOAD_URL_TTL_SECONDS = min(int(os.getenv("MEDIA_UPLOAD_URL_TTL_SECONDS", "600")), 600)
MEDIA_GET_URL_TTL_SECONDS = min(int(os.getenv("MEDIA_GET_URL_TTL_SECONDS", "60")), 60)
MEDIA_MAX_BYTES = {
    "image": int(os.getenv("MEDIA_IMAGE_MAX_BYTES", str(20 * 1024 * 1024))),
    "audio": int(os.getenv("MEDIA_AUDIO_MAX_BYTES", str(250 * 1024 * 1024))),
    "video": int(os.getenv("MEDIA_VIDEO_MAX_BYTES", str(5 * 1024 * 1024 * 1024))),
}
MEDIA_MAX_DURATION_SECONDS = int(os.getenv("MEDIA_MAX_DURATION_SECONDS", str(4 * 60 * 60)))
MEDIA_FFPROBE_PATH = os.getenv("MEDIA_FFPROBE_PATH", "ffprobe")
MEDIA_FFPROBE_TIMEOUT_SECONDS = int(os.getenv("MEDIA_FFPROBE_TIMEOUT_SECONDS", "30"))
MEDIA_TRANSFER_MODE = os.getenv("MEDIA_TRANSFER_MODE", "proxy" if DEBUG else "presigned")
if MEDIA_TRANSFER_MODE not in {"proxy", "presigned"}:
    raise ValueError("MEDIA_TRANSFER_MODE must be proxy or presigned")
FILE_UPLOAD_MAX_MEMORY_SIZE = 0

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.auth.BackofficeAuthenticationBackend"]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 15},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_RESET_TIMEOUT = 30 * 60
LOGIN_REDIRECT_URL = "/backoffice/"
LOGIN_URL = "/backoffice/login/"
LOGOUT_REDIRECT_URL = "/backoffice/login/"

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
SESSION_COOKIE_NAME = "__Host-backoffice_session" if SESSION_COOKIE_SECURE else "sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", str(60 * 60 * 8)))
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("SMTP_HOST", "localhost")
EMAIL_PORT = int(os.getenv("SMTP_PORT", "1025"))
EMAIL_HOST_USER = os.getenv("SMTP_USERNAME", "")
EMAIL_HOST_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_USE_TLS = env_bool("SMTP_USE_TLS")
DEFAULT_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "no-reply@localhost")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

VENDOR_AUTH_RATE_LIMIT = int(os.getenv("VENDOR_AUTH_RATE_LIMIT", "8"))
VENDOR_AUTH_RATE_WINDOW_SECONDS = int(os.getenv("VENDOR_AUTH_RATE_WINDOW_SECONDS", "300"))
OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64 = os.getenv(
    "OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64",
    "LS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tCk1JR0hBZ0VBTUJNR0J5cUdTTTQ5QWdFR0NDcUdTTTQ5QXdFSEJHMHdhd0lCQVFRZ3RpRURSd2ZQMEtqN2dCVUkKYmRUSTMybS9XckVrWGEraXFERDhrbWQ5bm55aFJBTkNBQVNYYmpZWTB4QUJCSnI0WkpXMVIrVTU1THFiV1RNUQo2TDJoRUR6eHhUSG0vMGNQNGtoamt2QTQzK1hadWMxU2FBY0NMSkREb3BBS1IvS1R6cWVyNGRIcQotLS0tLUVORCBQUklWQVRFIEtFWS0tLS0tCg==",
)
OFFLINE_LICENSE_TTL_HOURS = int(os.getenv("OFFLINE_LICENSE_TTL_HOURS", "168"))
