import pytest

from django.test import override_settings
from django.urls import reverse


def test_robots_txt_content(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    expected_lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /adminlogin/",
        "Disallow: /staff/",
        "Disallow: /lead/",
        "User-agent: Yandex",
        "Clean-param: utm_source&utm_medium&utm_campaign&utm_content&utm_term&utm_id&utm_referrer&gclid&fbclid&yclid&ysclid",
        "Sitemap: https://carfst.ru/sitemap.xml",
    ]
    for line in expected_lines:
        assert line in content
    content_type = response.headers.get("Content-Type", "")
    assert "text/plain" in content_type
    assert "charset" in content_type


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
def test_admin_login_has_meta_robots(client):
    login_url = reverse("admin:login")
    response = client.get(login_url)
    assert response.status_code == 200
    content = response.content.decode("utf-8").lower()
    assert content.count('meta name="robots"') == 1
    assert 'meta name="robots" content="noindex, nofollow, noarchive"' in content


@pytest.mark.django_db
def test_sitemap_has_no_x_robots_tag(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    x_robots = response.headers.get("X-Robots-Tag", "")
    assert "noindex" not in x_robots.lower()
