import pytest


@pytest.mark.django_db
def test_robots_safe_endpoint(client):
    response = client.get("/robots.txt", HTTP_HOST="bad.host")
    assert response.status_code == 200


@pytest.mark.django_db
def test_sitemap_safe_endpoint_https_links(client):
    response = client.get("/sitemap.xml", HTTP_HOST="bad.host")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "https://carfst.ru/" in content


@pytest.mark.django_db
def test_bad_host_catalog_not_ok(client):
    response = client.get("/catalog/", HTTP_HOST="bad.host")
    assert response.status_code in (400, 301, 302)
