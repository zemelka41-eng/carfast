"""
Part D: Tests for SEO invariants (product clean URL, product with GET, /shacman/*, sitemap).
"""
import re

import pytest
from django.urls import reverse

from catalog.models import Category, Series
from tests.factories import CategoryFactory, ProductFactory, SeriesFactory

pytestmark = pytest.mark.django_db


def _extract_canonical(content: str) -> str:
    match = re.search(r'rel="canonical" href="([^"]+)"', content)
    assert match, "canonical link not found"
    return match.group(1)


def _extract_json_ld(content: str):
    import json
    scripts = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        content,
        flags=re.DOTALL,
    )
    schemas = []
    for raw in scripts:
        data = json.loads(raw.strip())
        if isinstance(data, list):
            schemas.extend(data)
        else:
            schemas.append(data)
    return schemas


def test_product_clean_url_has_canonical_without_get(client):
    """Product clean URL: canonical without GET params."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert product.get_absolute_url() in canonical or canonical.endswith(product.slug + "/")


def test_product_clean_url_has_json_ld_product_offer(client):
    """Product clean URL: JSON-LD Product + Offer present."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    schemas = _extract_json_ld(content)
    product_schemas = [s for s in schemas if s.get("@type") == "Product"]
    assert len(product_schemas) >= 1
    offer = product_schemas[0].get("offers", {})
    assert offer.get("priceCurrency") == "RUB"


def test_product_url_with_get_canonical_without_get(client):
    """Product URL with GET: canonical without GET params."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get(f"{product.get_absolute_url()}?utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    assert "utm_source" not in canonical
    assert "?" not in canonical


def test_product_url_with_get_no_json_ld_product(client):
    """Product URL with GET: JSON-LD Product/FAQPage/BreadcrumbList absent."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get(f"{product.get_absolute_url()}?utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    schemas = _extract_json_ld(content)
    product_schemas = [s for s in schemas if s.get("@type") == "Product"]
    breadcrumb_schemas = [s for s in schemas if s.get("@type") == "BreadcrumbList"]
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(product_schemas) == 0
    assert len(breadcrumb_schemas) == 0
    assert len(faq_schemas) == 0


def test_shacman_hub_canonical_correct(client):
    """SHACMAN hub: canonical correct (request.path)."""
    Series.objects.get_or_create(slug="shacman", defaults={"name": "SHACMAN"})
    response = client.get("/shacman/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    assert "/shacman/" in canonical
    assert "?" not in canonical


def test_shacman_hub_page1_index(client):
    """SHACMAN hub: page=1 (clean URL) index, follow."""
    Series.objects.get_or_create(slug="shacman", defaults={"name": "SHACMAN"})
    response = client.get("/shacman/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content


def test_shacman_hub_page2_noindex_follow(client):
    """SHACMAN hub: page>1 noindex, follow + self-canonical."""
    Series.objects.get_or_create(slug="shacman", defaults={"name": "SHACMAN"})
    ProductFactory(series=Series.objects.get(slug="shacman"), published=True, is_active=True)
    response = client.get("/shacman/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    canonical = _extract_canonical(content)
    assert "page=2" in canonical


def test_shacman_hub_page1_redirects(client):
    """SHACMAN hub: ?page=1 redirects to clean URL."""
    Series.objects.get_or_create(slug="shacman", defaults={"name": "SHACMAN"})
    response = client.get("/shacman/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith("/shacman/")


def test_sitemap_catalog_root_absent(client):
    """Sitemap: /catalog/ (root) absent."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "<loc>https://carfst.ru/catalog/</loc>" not in content


def test_sitemap_product_present(client):
    """Sitemap: product URLs present."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/product/" in content
    assert product.slug in content


def test_sitemap_shacman_present(client):
    """Sitemap: /shacman/* present when SHACMAN exists."""
    Series.objects.get_or_create(slug="shacman", defaults={"name": "SHACMAN"})
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/shacman/" in content
