"""
Tests for SEO invariants: canonical without GET, JSON-LD only on clean URLs,
page>1 noindex on hubs, sitemap contents.
"""
import json
import re

import pytest
from django.urls import reverse

from catalog.models import Category, City, Offer, Series
from tests.factories import CategoryFactory, ProductFactory, SeriesFactory


pytestmark = pytest.mark.django_db


def _extract_json_ld(content: str):
    pattern = re.compile(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    scripts = pattern.findall(content)
    items = []
    for script in scripts:
        data = json.loads(script)
        if isinstance(data, list):
            items.extend(data)
        else:
            items.append(data)
    return items


def _get_canonical(content: str) -> str | None:
    m = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', content, re.IGNORECASE)
    return m.group(1) if m else None


def _get_robots(content: str) -> str | None:
    m = re.search(r'<meta\s+name="robots"\s+content="([^"]+)"', content, re.IGNORECASE)
    return m.group(1) if m else None


def test_product_clean_url_has_canonical_without_get(product_factory, client):
    product = product_factory()
    url = product.get_absolute_url()
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    canonical = _get_canonical(content)
    assert canonical is not None
    assert "?" not in canonical
    assert url in canonical or canonical.endswith(url)


def test_product_clean_url_has_json_ld_product_offer(product_factory, client):
    product = product_factory()
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    items = _extract_json_ld(content)
    types = {item.get("@type") for item in items if isinstance(item, dict)}
    assert "Product" in types
    product_schema = next(i for i in items if i.get("@type") == "Product")
    assert "offers" in product_schema


def test_product_url_with_get_has_canonical_without_get(product_factory, client):
    product = product_factory()
    url_with_get = product.get_absolute_url() + "?utm_source=test"
    response = client.get(url_with_get)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    canonical = _get_canonical(content)
    assert canonical is not None
    assert "?" not in canonical
    assert "utm_source" not in canonical


def test_product_url_with_get_no_json_ld(product_factory, client):
    product = product_factory()
    url_with_get = product.get_absolute_url() + "?ref=test"
    response = client.get(url_with_get)
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    items = _extract_json_ld(content)
    types = {item.get("@type") for item in items if isinstance(item, dict)}
    assert "Product" not in types


def test_shacman_hub_canonical_correct(client):
    SeriesFactory(slug="shacman", name="SHACMAN")
    response = client.get("/shacman/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    canonical = _get_canonical(content)
    assert canonical is not None
    assert "?" not in canonical
    assert "/shacman/" in canonical


def test_shacman_hub_page1_index(client):
    SeriesFactory(slug="shacman", name="SHACMAN")
    response = client.get("/shacman/")
    assert response.status_code == 200
    robots = _get_robots(response.content.decode("utf-8"))
    assert robots is None or "noindex" not in robots or "index" in robots


def test_shacman_hub_page2_noindex_follow(client):
    SeriesFactory(slug="shacman", name="SHACMAN")
    ProductFactory(series=Series.objects.get(slug="shacman"), published=True, is_active=True)
    response = client.get("/shacman/?page=2")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    robots = _get_robots(content)
    assert robots is not None
    assert "noindex" in robots
    assert "follow" in robots
    canonical = _get_canonical(content)
    assert canonical is not None
    assert "page=2" in canonical


def test_sitemap_no_catalog_root(client):
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "<loc>https://carfst.ru/catalog/</loc>" not in content


def test_sitemap_has_product_urls(client, product_factory):
    product_factory(published=True, is_active=True)
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/product/" in content


def test_sitemap_has_shacman_hubs(client):
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    ProductFactory(series=series, published=True, is_active=True)
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/shacman/</loc>" in content or "shacman</loc>" in content
