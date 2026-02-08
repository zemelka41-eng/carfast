from pathlib import Path
import shutil

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from pytest_factoryboy import register
from rest_framework.test import APIClient

from tests import factories

pytest_plugins = ["pytest_factoryboy"]

register(factories.SeriesFactory)
register(factories.CategoryFactory)
register(factories.ModelVariantFactory)
register(factories.ProductFactory)
register(factories.ProductImageFactory)
register(factories.LeadFactory)

TESTS_ROOT = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _configure_test_settings(settings, tmp_path_factory):
    base_dir = tmp_path_factory.mktemp("test-artifacts")
    media_root = base_dir / "media"
    static_root = base_dir / "staticfiles"
    log_dir = base_dir / "logs"

    media_root.mkdir(parents=True, exist_ok=True)
    static_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    settings.MEDIA_ROOT = media_root
    settings.STATIC_ROOT = static_root
    settings.LOG_DIR = log_dir
    settings.ALLOWED_HOSTS = ["testserver", "localhost", "carfst.ru", "www.carfst.ru"]
    return settings


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_request(rf):
    request = rf.get("/admin/")
    request.user = AnonymousUser()
    request.session = {}
    setattr(request, "_messages", FallbackStorage(request))
    return request


@pytest.fixture
def sample_workbook_path(tmp_path):
    source = TESTS_ROOT / "fixtures" / "sample_products.xlsx"
    target = tmp_path / "sample_products.xlsx"
    shutil.copyfile(source, target)
    return target


@pytest.fixture
def sample_media_dir(tmp_path):
    media_dir = tmp_path / "import_media"
    media_dir.mkdir()
    source_image = TESTS_ROOT / "fixtures" / "media" / "product.jpg"
    shutil.copyfile(source_image, media_dir / "product.jpg")
    return media_dir
