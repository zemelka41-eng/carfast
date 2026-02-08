import pytest
from django.urls import reverse

from catalog.models import City, Offer

pytestmark = pytest.mark.django_db


def test_home_returns_200(client, settings):
    settings.CONTACT_MAX_URL = "https://example.com/max"
    response = client.get(reverse("catalog:home"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "nikita.metelev@yandex.ru" not in content
    assert "info@carfst.ru" in content
    assert "Бренды" not in content
    assert "Направления" in content
    assert "Как мы работаем" in content
    assert "FAQ" in content
    assert "Рассчитаем под задачу" in content
    assert (
        "Техника в наличии" in content
        or "Подобрать комплектацию" in content
        or "Рассчитать лизинг" in content
    )
    assert "MAX" in content
    assert "availability=in_stock" not in content


def test_home_renders_without_in_stock(client, product_factory):
    product_factory()
    response = client.get(reverse("catalog:home"))
    assert response.status_code == 200
    assert "В наличии сейчас" not in response.content.decode("utf-8")


def test_home_renders_with_in_stock(client, product_factory):
    product = product_factory()
    city = City.objects.create(name="Test City", slug="test-city")
    Offer.objects.create(product=product, city=city, qty=1, price=1000000)

    response = client.get(reverse("catalog:home"))
    assert response.status_code == 200
    assert "В наличии сейчас" in response.content.decode("utf-8")


@pytest.mark.parametrize(
    "view_name",
    [
        "catalog:home",
        "catalog:parts",
        "catalog:service",
        "catalog:used",
        "blog:blog_list",
    ],
)
def test_cookie_banner_present(client, view_name):
    response = client.get(reverse(view_name))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'id="cookie-consent"' in content
    assert reverse("catalog:privacy") in content
    assert "cookie-consent.js" in content
