import pytest


@pytest.mark.django_db
def test_favicon_links_present(client):
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "favicons/favicon.ico" in content
    assert "favicons/apple-touch-icon.png" in content
    assert "favicons/site.webmanifest" in content
