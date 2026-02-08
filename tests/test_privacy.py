import pytest


pytestmark = pytest.mark.django_db


def test_privacy_page_content_and_meta(client):
    response = client.get("/privacy/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Политика конфиденциальности" in content
    assert "ИНН 2536339021" in content
    assert "КПП 253601001" in content
    assert "Beget" in content
    assert "Яндекс.Метрика" in content
    assert "106366435" in content
    assert "152-ФЗ" in content
    assert "Персональные данные / carfst.ru" in content
    assert "Трансграничная передача" in content
    assert "Локализация данных граждан РФ" in content
    assert "Cookies и аналитика" in content
    assert 'name="robots" content="index, follow"' in content
    assert 'rel="canonical" href="https://carfst.ru/privacy/"' in content


@pytest.mark.parametrize(
    "path",
    [
        "/lead/",
        "/contacts/",
    ],
)
def test_forms_have_privacy_link(client, path):
    response = client.get(path)
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Политикой конфиденциальности" in content
    assert 'href="/privacy/"' in content
