import os

# Ensure test settings do not trigger production validation.
os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault(
    "DJANGO_SECRET_KEY",
    "test-secret-key-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
)

from .settings import *  # noqa: F403,F401

DEBUG = True
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",  # noqa: F405
    }
}

ALLOWED_HOSTS = ["testserver", "localhost", "carfst.ru", "www.carfst.ru"]

# Use non-manifest static storage in tests to avoid missing build artifacts.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
