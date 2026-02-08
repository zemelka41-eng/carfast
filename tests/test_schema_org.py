import json
import re

import pytest
from django.urls import reverse

from catalog.models import City, Offer


pytestmark = pytest.mark.django_db


def _extract_json_ld(content: str):
    pattern = re.compile(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    scripts = pattern.findall(content)
    assert scripts, "JSON-LD script tag not found"

    payload_items = []
    for script in scripts:
        data = json.loads(script)
        if isinstance(data, list):
            payload_items.extend(data)
        else:
            payload_items.append(data)
    return scripts, payload_items


def test_home_has_website_schema(client):
    response = client.get(reverse("catalog:home"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    scripts, payload_items = _extract_json_ld(content)
    assert len(scripts) <= 2

    types = {item.get("@type") for item in payload_items if isinstance(item, dict)}
    assert "Organization" in types
    assert "WebSite" in types

    website = next(
        item for item in payload_items if item.get("@type") == "WebSite"
    )
    potential_action = website.get("potentialAction", {})
    assert potential_action.get("@type") == "SearchAction"


def test_product_schema_and_breadcrumbs(product_factory, client):
    product = product_factory(price=1250000)
    city = City.objects.create(name="Moscow", slug="moskva")
    Offer.objects.create(product=product, city=city, qty=2, price=1250000)

    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    scripts, payload_items = _extract_json_ld(content)
    assert len(scripts) <= 2

    types = {item.get("@type") for item in payload_items if isinstance(item, dict)}
    assert "Product" in types
    assert "BreadcrumbList" in types
    assert "FAQPage" in types

    product_schema = next(
        item for item in payload_items if item.get("@type") == "Product"
    )
    offer = product_schema.get("offers", {})
    assert offer.get("priceCurrency") == "RUB"
    assert offer.get("availability") == "https://schema.org/InStock"


def test_product_clean_url_has_product_schema(product_factory, client):
    """Clean product URL must have Product schema (SEO invariant)."""
    product = product_factory(published=True, is_active=True)
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    _, payload_items = _extract_json_ld(content)
    types = {item.get("@type") for item in payload_items if isinstance(item, dict)}
    assert "Product" in types


def test_product_url_with_get_has_no_schema(product_factory, client):
    """Product URL with GET params must not output Product/FAQPage/BreadcrumbList schema (SEO invariant)."""
    product = product_factory(published=True, is_active=True)
    response = client.get(product.get_absolute_url() + "?utm_source=test")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    # schema_allowed is False when request has GET, so no JSON-LD or empty
    if '"@type"' in content:
        assert '"@type":"Product"' not in content.replace(" ", "")
        assert '"@type":"FAQPage"' not in content.replace(" ", "")
        assert '"@type":"BreadcrumbList"' not in content.replace(" ", "")
