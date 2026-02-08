import os
import secrets

# Packaging must never fail on SECRET_KEY validation.
os.environ.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(48))

"""
Settings for packaging (ZIP build) on Windows.

Uses SimpleAdminConfig instead of default AdminConfig to avoid admin.autodiscover
during makemigrations --check, which can fail in some Windows environments
(ImportError when loading admin modules). Does not change SEO, routes, or templates.
"""

import os

# Ensure valid SECRET_KEY for migration check (base settings validate length when DEBUG=False)
_secret = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY")
if not _secret or _secret == "dev-secret-key" or len(_secret) < 50:
    _secret = "packaging-check-secret-key-min-50-chars-xxxxxxxxxxxxxxxx"
os.environ.setdefault("DJANGO_SECRET_KEY", _secret)
os.environ.setdefault("DJANGO_DEBUG", "0")

from .settings import *  # noqa: F401, F403

# Override INSTALLED_APPS: use SimpleAdminConfig (no autodiscover) instead of django.contrib.admin
INSTALLED_APPS = list(INSTALLED_APPS)
for i, app in enumerate(INSTALLED_APPS):
    if app == "django.contrib.admin":
        INSTALLED_APPS[i] = "django.contrib.admin.apps.SimpleAdminConfig"
        break
    if app == "django.contrib.admin.apps.AdminConfig":
        INSTALLED_APPS[i] = "django.contrib.admin.apps.SimpleAdminConfig"
        break

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _secret)
