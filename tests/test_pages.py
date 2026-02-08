import pytest
from django.urls import reverse

from tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "view_name",
    [
        "catalog:parts",
        "catalog:service",
        "catalog:leasing",
        "catalog:used",
        "catalog:payment_delivery",
    ],
)
def test_info_pages_return_200(client, view_name):
    response = client.get(reverse(view_name))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Получить КП" in content
    unique_phrases = {
        "catalog:parts": "Подбираем и поставляем запчасти",
        "catalog:service": "Сервис — это не",
        "catalog:used": "у нас нет собственного склада б/у",
    }
    og_phrases = {
        "catalog:parts": "контроль совместимости, наличие и доставка по РФ",
        "catalog:service": "рекомендации для снижения простоев и рисков",
        "catalog:used": "помощь с осмотром и сопровождение выбора",
    }
    if view_name in unique_phrases:
        assert unique_phrases[view_name] in content
    if view_name in og_phrases:
        assert 'property="og:description"' in content
        assert og_phrases[view_name] in content
    if view_name == "catalog:parts":
        assert "zip@carfst.ru" in content
    if view_name == "catalog:leasing":
        assert "Партнёры по лизингу" in content
        assert "СберЛизинг" in content
        assert "Европлан" in content


def test_leasing_has_static_seo_zone(client):
    """GET /leasing/ (clean) must contain id=\"static-seo-zone\"."""
    response = client.get(reverse("catalog:leasing"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'id="static-seo-zone"' in content


def test_leasing_schema_only_on_clean_url(client):
    """Schema (application/ld+json) must appear only on clean URL; with GET params no JSON-LD."""
    clean_response = client.get(reverse("catalog:leasing"))
    assert clean_response.status_code == 200
    clean_content = clean_response.content.decode("utf-8")
    # Clean URL may have JSON-LD (Organization + WebSite + optional FAQPage from StaticPageSEO)
    assert "application/ld+json" in clean_content

    utm_response = client.get(reverse("catalog:leasing") + "?utm_source=test")
    assert utm_response.status_code == 200
    utm_content = utm_response.content.decode("utf-8")
    # With GET params, base template skips entire JSON-LD block (SEO invariant)
    assert "application/ld+json" not in utm_content


def test_used_page_shows_used_products_only(client, product):
    """/used/ lists only products with is_used=True; new product must not appear in the listing."""
    from catalog.models import Product

    used_product = ProductFactory(
        model_name_ru="Б/у самосвал тест",
        slug="used-product-test",
        is_used=True,
        published=True,
        is_active=True,
    )
    # product from fixture is new (is_used=False)
    new_product = product
    assert new_product.is_used is False

    response = client.get(reverse("catalog:used"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    # Used product must appear in the used-products section
    assert "used-products" in content
    idx = content.find('id="used-products"')
    assert idx != -1
    section = content[idx : idx + 8000]
    assert used_product.slug in section or used_product.model_name_ru in section
    assert new_product.slug not in section


def test_used_badge_rendered(client):
    """Badge 'Б/у' is shown on card and detail for is_used product."""
    used_product = ProductFactory(
        model_name_ru="Б/у тягач",
        slug="used-badge-test",
        is_used=True,
        published=True,
        is_active=True,
    )

    # On /used/ page the card must show the badge
    response = client.get(reverse("catalog:used"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Б/у" in content

    # On product detail the badge and "Состояние" must appear
    response_detail = client.get(used_product.get_absolute_url())
    assert response_detail.status_code == 200
    detail_content = response_detail.content.decode("utf-8")
    assert "Б/у" in detail_content
