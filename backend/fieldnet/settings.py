"""Django settings for FieldNet Monitor.

All environment-dependent values come from env vars so the same image runs in
docker compose, locally and in tests.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# When on, /test/* endpoints exist and background work only runs inside
# /test/clock and /test/drain (see the brief's "Test endpoints").
TEST_MODE = env_bool("TEST_MODE")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "core",
    "gateways",
    "sensors",
    "batches",
    "testing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.server_now",
]

ROOT_URLCONF = "fieldnet.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

WSGI_APPLICATION = "fieldnet.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "fieldnet"),
        "USER": os.environ.get("POSTGRES_USER", os.environ.get("USER", "postgres")),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.errors.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "FieldNet Monitor API",
    "DESCRIPTION": (
        "All bodies are JSON and all times ISO 8601 UTC. Errors are "
        '`{"error": "<code>", "detail": "<text>"}`: invalid bodies 422, conflicts and illegal actions 409, '
        "unknown ids 404. Devices call /gw/v1 with `Authorization: Bearer <token>`. "
        "Every response carries `X-Server-Now`: the server clock (in TEST_MODE, the test clock)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "gatewayToken": {"type": "http", "scheme": "bearer", "description": "The token returned at registration."}
        }
    },
    "SECURITY": [],
}
