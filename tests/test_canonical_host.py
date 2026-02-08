import pytest
from django.http import HttpResponse

from carfst_site.middleware_canonical_host import CanonicalHostMiddleware


@pytest.fixture
def middleware():
    return CanonicalHostMiddleware(lambda request: HttpResponse("ok"))


def test_invalid_host_returns_bad_request(settings, rf, middleware):
    settings.ALLOWED_HOSTS = ["carfst.ru", "www.carfst.ru"]
    request = rf.get("/", HTTP_HOST="109.69.16.149")

    response = middleware(request)

    assert response.status_code == 400


def test_canonical_host_allows_request(settings, rf, middleware):
    settings.ALLOWED_HOSTS = ["carfst.ru", "www.carfst.ru"]
    settings.CANONICAL_HOST = "carfst.ru"
    request = rf.get("/", HTTP_HOST="carfst.ru")

    response = middleware(request)

    assert response.status_code == 200
