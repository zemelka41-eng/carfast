import pytest


pytestmark = pytest.mark.django_db


def test_metrika_script_and_noscript_present(client):
    response = client.get("/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "mc.yandex.ru/metrika/tag.js?id=106366435" in content
    assert "ym(106366435" in content
    assert "mc.yandex.ru/watch/106366435" in content
