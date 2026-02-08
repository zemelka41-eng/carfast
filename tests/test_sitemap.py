import pytest


@pytest.mark.django_db
def test_sitemap_xml_returns_ok(client):
    """GET /sitemap.xml must return 200 and application/xml (no 500 under gunicorn)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content_type = response.headers.get("Content-Type", "")
    assert "xml" in content_type.lower(), f"Expected xml in Content-Type, got {content_type}"
    body = response.content.decode("utf-8", errors="replace")
    assert body.lstrip().startswith("<?xml"), "Sitemap body must start with <?xml"
