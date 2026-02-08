import os
import sys
from pathlib import Path
from typing import Iterable

import django
import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent
DJANGO_VERSION = django.VERSION
DJANGO_VERSION_STR = django.get_version()
DJANGO_IS_51_PLUS = DJANGO_VERSION >= (5, 1)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _ensure_trailing_slash(url: str, default: str) -> str:
    if not url:
        return default
    return url if url.endswith("/") else f"{url}/"


env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    LOG_LEVEL=(str, "INFO"),
    LOG_TO_FILE=(bool, True),
    ALLOWED_HOSTS=(list, ["carfst.ru", "www.carfst.ru"]),
    CSRF_TRUSTED_ORIGINS=(list, ["https://carfst.ru", "https://www.carfst.ru"]),
    USE_X_FORWARDED_HOST=(bool, False),
    # CSP configuration
    CSP_REPORT_ONLY=(bool, False),
    CSP_REPORT_URI=(str, None),
    ENV_FILE=(str, None),  # Explicit path to .env file (optional)
)

# Read .env file only if:
# 1. ENV_FILE is explicitly set, OR
# 2. DEBUG=True (development mode), OR
# 3. .env file exists in project root (backward compatibility)
env_file_path = env("ENV_FILE", default=None)
if env_file_path:
    # Use explicit path if provided
    env_file = Path(env_file_path)
elif os.environ.get("DJANGO_DEBUG", "").lower() in ("true", "1"):
    # Development mode: try project root .env
    env_file = BASE_DIR / ".env"
else:
    # Production: only read .env if explicitly allowed via ENV_FILE
    # Default: rely on environment variables (systemd EnvironmentFile, etc.)
    env_file = None

if env_file and env_file.exists():
    environ.Env.read_env(str(env_file))

# DEBUG must be defined FIRST, before any checks that use it
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# SECRET_KEY: try DJANGO_SECRET_KEY first, fallback to SECRET_KEY for backward compatibility (dev only)
SECRET_KEY = env("DJANGO_SECRET_KEY", default=None)
if SECRET_KEY is None:
    # Fallback for backward compatibility (dev only)
    SECRET_KEY = env("SECRET_KEY", default="dev-secret-key")

# Strict validation for SECRET_KEY in production (DEBUG=False)
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    
    errors = []
    if not SECRET_KEY:
        errors.append("SECRET_KEY is required in production")
    elif SECRET_KEY.startswith("django-insecure-"):
        errors.append("SECRET_KEY must not start with 'django-insecure-'")
    elif SECRET_KEY == "dev-secret-key":
        errors.append("SECRET_KEY must not be the default 'dev-secret-key'")
    elif len(SECRET_KEY) < 50:
        errors.append(f"SECRET_KEY must be at least 50 characters long (got {len(SECRET_KEY)})")
    else:
        # Check unique characters
        unique_chars = len(set(SECRET_KEY))
        if unique_chars < 5:
            errors.append(f"SECRET_KEY must contain at least 5 unique characters (got {unique_chars})")
    
    if errors:
        error_msg = "SECRET_KEY validation failed in production:\n" + "\n".join(f"  - {e}" for e in errors)
        error_msg += "\n\nGenerate a secure key with:"
        error_msg += "\n  python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'"
        error_msg += "\n\nThen set it in .env or EnvironmentFile:"
        error_msg += "\n  DJANGO_SECRET_KEY=your-generated-key"
        raise ImproperlyConfigured(error_msg)
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_TO_FILE = env.bool("LOG_TO_FILE", default=True)
TESTING = (
    os.environ.get("PYTEST_CURRENT_TEST") is not None
    or "pytest" in sys.modules
    or any("pytest" in str(arg) for arg in sys.argv)
)

DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "carfst.local",
    "carfst.ru",
    "www.carfst.ru",
    "109.69.16.149",
    "testserver",
]
ALLOWED_HOSTS = _unique(env.list("ALLOWED_HOSTS", default=DEFAULT_ALLOWED_HOSTS))

DEFAULT_CSRF_TRUSTED_ORIGINS = [
    "https://carfst.ru",
    "https://www.carfst.ru",
    "https://127.0.0.1",
    "https://localhost",
    "https://carfst.local",
    "http://127.0.0.1",
    "http://localhost",
    "http://carfst.local",
]
CSRF_TRUSTED_ORIGINS = _unique(
    env.list("CSRF_TRUSTED_ORIGINS", default=DEFAULT_CSRF_TRUSTED_ORIGINS)
)
SITE_DOMAIN = env("SITE_DOMAIN", default="www.carfst.ru")
CANONICAL_HOST = env("CANONICAL_HOST", default="carfst.ru")
# Optional: set SITEMAP_CACHE_VERSION (e.g. to build_id) on deploy to invalidate sitemap cache
SITEMAP_CACHE_VERSION = env("SITEMAP_CACHE_VERSION", default=None)
ADMIN_URL = env("ADMIN_URL", default="admin/").rstrip("/") + "/"
WHATSAPP_NUMBER = env("WHATSAPP_NUMBER", default="")
CONTACT_MAX_URL = env("CONTACT_MAX_URL", default="")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django_extensions",
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "catalog",
    "blog",
]

MIDDLEWARE = [
    "carfst_site.middleware_canonical_host.CanonicalHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "carfst_site.middleware.SecurityHeadersMiddleware",
    # Serve static files (incl. Django admin) in production without relying on nginx config.
    # Must be right after SecurityMiddleware: https://whitenoise.readthedocs.io/
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "carfst_site.middleware.ErrorLoggingMiddleware",
    "carfst_site.middleware.BuildIdHeaderMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "carfst_site.middleware.UploadValidationMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "carfst_site.middleware.RobotsNoIndexMiddleware",
    "carfst_site.middleware.AdminCacheControlMiddleware",
    "carfst_site.middleware.TemplateArtifactCleanupMiddleware",
]

ROOT_URLCONF = "carfst_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "catalog.context_processors.site_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "carfst_site.wsgi.application"
ASGI_APPLICATION = "carfst_site.asgi.application"


DATABASE_URL = env("DATABASE_URL", default=None)
if DATABASE_URL:
    DATABASES = {"default": env.db()}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = env("LANGUAGE_CODE", default="ru")
TIME_ZONE = env("TIME_ZONE", default="Europe/Moscow")
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("ru", _("Русский")),
    ("en", _("English")),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = _ensure_trailing_slash(env("STATIC_URL", default="/static/"), "/static/")
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = Path(env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles")))

# Django 5.x: configure storages via STORAGES (STATICFILES_STORAGE is deprecated).
# WhiteNoise provides gzip/brotli + hashed filenames via Manifest storage.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = _ensure_trailing_slash(env("MEDIA_URL", default="/media/"), "/media/")
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
if LOG_TO_FILE:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
DJANGO_LOG_FILE = LOG_DIR / "django.log"
ERROR_LOG_FILE = LOG_DIR / "errors.log"

# Note: .jfif is a JPEG container/extension used by some phones/messengers.
DEFAULT_ALLOWED_IMAGE_EXTENSIONS = ["jpg", "jpeg", "jfif", "png", "webp"]
DEFAULT_ALLOWED_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"]
MEDIA_ALLOWED_IMAGE_EXTENSIONS = [
    ext.lower().lstrip(".")
    for ext in env.list(
        "MEDIA_ALLOWED_IMAGE_EXTENSIONS",
        default=DEFAULT_ALLOWED_IMAGE_EXTENSIONS,
    )
    if ext
]
MEDIA_ALLOWED_IMAGE_MIME_TYPES = [
    mime.lower()
    for mime in env.list(
        "MEDIA_ALLOWED_IMAGE_MIME_TYPES",
        default=DEFAULT_ALLOWED_IMAGE_MIME_TYPES,
    )
    if mime
]
if not MEDIA_ALLOWED_IMAGE_EXTENSIONS:
    MEDIA_ALLOWED_IMAGE_EXTENSIONS = DEFAULT_ALLOWED_IMAGE_EXTENSIONS
if not MEDIA_ALLOWED_IMAGE_MIME_TYPES:
    MEDIA_ALLOWED_IMAGE_MIME_TYPES = DEFAULT_ALLOWED_IMAGE_MIME_TYPES
MAX_IMAGE_SIZE = env.int("MAX_IMAGE_SIZE", default=10 * 1024 * 1024)  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "FILE_UPLOAD_MAX_MEMORY_SIZE",
    default=min(5 * 1024 * 1024, MAX_IMAGE_SIZE),
)
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE",
    default=MAX_IMAGE_SIZE,
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@carfst.ru")

# Email notifications for leads
LEAD_NOTIFY_EMAILS = env.list(
    "LEAD_NOTIFY_EMAILS",
    default=[],
)
LEADS_NOTIFY_EMAIL_TO = env.list(
    "LEADS_NOTIFY_EMAIL_TO",
    default=[],
)
LEADS_NOTIFY_ENABLE = env.bool("LEADS_NOTIFY_ENABLE", default=True)
LEADS_NOTIFY_TIMEOUT = env.int("LEADS_NOTIFY_TIMEOUT", default=3)
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID", default="")

LOGGING_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOGGING_HANDLERS = {
    "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
}
if LOG_TO_FILE:
    LOGGING_HANDLERS.update(
        {
            "django_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "verbose",
                "filename": str(DJANGO_LOG_FILE),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "delay": True,
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "verbose",
                "filename": str(ERROR_LOG_FILE),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "delay": True,
            },
        }
    )

LOGGING_FILE_HANDLERS = ["django_file"] if LOG_TO_FILE else []
LOGGING_ERROR_HANDLERS = ["error_file"] if LOG_TO_FILE else ["console"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": LOGGING_FORMAT},
    },
    "handlers": LOGGING_HANDLERS,
    "root": {"handlers": ["console", *LOGGING_FILE_HANDLERS], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console", *LOGGING_FILE_HANDLERS], "level": LOG_LEVEL},
        "django.request": {
            "handlers": [*LOGGING_ERROR_HANDLERS, *LOGGING_FILE_HANDLERS],
            "level": "INFO",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", *LOGGING_FILE_HANDLERS],
            "level": "INFO",
            "propagate": False,
        },
        "request_errors": {
            "handlers": LOGGING_ERROR_HANDLERS,
            "level": "ERROR",
            "propagate": False,
        },
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST", default=False)
SESSION_COOKIE_SAMESITE = env("SESSION_COOKIE_SAMESITE", default="Lax")
CSRF_COOKIE_SAMESITE = env("CSRF_COOKIE_SAMESITE", default="Lax")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True  # Always enabled for security
CSRF_COOKIE_HTTPONLY = False  # Must be False for CSRF token to work in JavaScript
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG and not TESTING)
if os.environ.get("SSL_REDIRECT") is not None:
    SECURE_SSL_REDIRECT = env.bool("SSL_REDIRECT", default=SECURE_SSL_REDIRECT)
SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS",
    default=0 if (DEBUG or TESTING) else 31536000,
)
SECURE_REDIRECT_EXEMPT = env.list(
    "SECURE_REDIRECT_EXEMPT",
    default=["^api/.*", "^health/?$", "^sitemap\\.xml$", "^sitemap-[^/]+\\.xml$"],
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "carfst-cache",
    }
}

REDIS_URL = env("REDIS_URL", default=None)
if REDIS_URL and not TESTING:
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Content-Security-Policy (Report-Only mode by default)
# Set CSP_REPORT_ONLY=1 in environment to enable CSP reporting
# Set CSP_REPORT_URI to send reports to a specific endpoint
CSP_REPORT_ONLY = env.bool("CSP_REPORT_ONLY", default=False)
CSP_REPORT_URI = env("CSP_REPORT_URI", default=None)

# Default CSP policy (restrictive, allows common Django admin needs)
# Can be overridden via CSP_POLICY environment variable
DEFAULT_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "  # unsafe-inline/eval needed for Django admin
    "style-src 'self' 'unsafe-inline'; "  # unsafe-inline needed for Django admin
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)
CSP_POLICY = env("CSP_POLICY", default=DEFAULT_CSP_POLICY)

SPECTACULAR_SETTINGS = {
    "TITLE": "CARFAST API",
    "DESCRIPTION": "Документация API каталога.",
    "VERSION": "1.0.0",
}

