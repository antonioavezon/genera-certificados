"""Configuración de la aplicación local de diplomas."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


DATA_DIR = _env_path("DATA_DIR", BASE_DIR / "data")
UPLOADS_DIR = _env_path("UPLOADS_DIR", BASE_DIR / "uploads")
TEMP_DIR = _env_path("TEMP_DIR", BASE_DIR / "temp")
LOGS_DIR = _env_path("LOGS_DIR", BASE_DIR / "logs")
FONTS_DIR = _env_path("FONTS_DIR", BASE_DIR / "fonts")
# La carpeta del paquete Python ya se llama diplomas/. Los PDF van aparte
# para no mezclar archivos generados con el código.
DIPLOMAS_OUTPUT_DIR = _env_path("DIPLOMAS_OUTPUT_DIR", BASE_DIR / "generated")

for _directory in (DATA_DIR, UPLOADS_DIR, TEMP_DIR, LOGS_DIR, FONTS_DIR, DIPLOMAS_OUTPUT_DIR):
    try:
        _directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # El arranque no debe ocultar el problema: la interfaz y el preflight lo informan.
        pass


def _secret_key() -> str:
    configured = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if configured:
        return configured
    path = DATA_DIR / "secret_key"
    try:
        if path.exists():
            stored = path.read_text(encoding="utf-8").strip()
            if stored:
                return stored
        generated = secrets.token_urlsafe(64)
        path.write_text(generated, encoding="utf-8")
        return generated
    except OSError:
        return "clave-local-de-desarrollo-cambie-esta-clave"


SECRET_KEY = _secret_key()
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "diplomas",
]

MIDDLEWARE = [
    "diplomas.middleware.FriendlyExceptionMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "diplomas.context_processors.shell",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 30},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = os.environ.get("TIME_ZONE", "America/Santiago")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 40 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
MAX_LIST_ROWS = _env_int("MAX_LIST_ROWS", 5000)
TEMP_FILE_MAX_AGE_HOURS = _env_int("TEMP_FILE_MAX_AGE_HOURS", 24)

EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "none").strip().lower() or "none"
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()
EMAIL_TIMEOUT = _env_int("EMAIL_TIMEOUT", 30)
EMAIL_MAX_ATTEMPTS = min(10, max(1, _env_int("EMAIL_MAX_ATTEMPTS", 3)))
EMAIL_RETRY_BACKOFF_SECONDS = max(0.0, _env_float("EMAIL_RETRY_BACKOFF_SECONDS", 1.0))

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "diplomas.views.errors.csrf_failure"

from django.contrib.messages import constants as message_constants

MESSAGE_TAGS = {
    message_constants.ERROR: "danger",
    message_constants.DEBUG: "secondary",
}


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": {"()": "diplomas.log_filters.LogContextFilter"},
    },
    "formatters": {
        "standard": {
            "format": (
                "%(asctime)s %(levelname)s %(name)s "
                "[batch=%(batch)s participant=%(participant)s] %(message)s"
            )
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["context"],
        },
        "application": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "application.log"),
            "maxBytes": 2_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "standard",
            "filters": ["context"],
        },
        "generation": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "generation.log"),
            "maxBytes": 2_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "standard",
            "filters": ["context"],
        },
        "email": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOGS_DIR / "email.log"),
            "maxBytes": 2_000_000,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "standard",
            "filters": ["context"],
        },
    },
    "loggers": {
        "diplomas": {"handlers": ["console", "application"], "level": "INFO", "propagate": False},
        "diplomas.generation": {
            "handlers": ["console", "generation"],
            "level": "INFO",
            "propagate": False,
        },
        "diplomas.email": {"handlers": ["console", "email"], "level": "INFO", "propagate": False},
    },
}
