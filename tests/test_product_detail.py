import pytest
from django.db.utils import OperationalError

from catalog.models import Product
from tests.factories import ProductFactory


pytestmark = pytest.mark.django_db


def test_product_detail_ignores_views_count_errors(client, product, monkeypatch):
    original_filter = Product.objects.filter

    def fake_filter(*args, **kwargs):
        if kwargs.get("pk") == product.pk:
            class DummyQuerySet:
                def update(self, **kwargs):
                    raise OperationalError("attempt to write a readonly database")

            return DummyQuerySet()
        return original_filter(*args, **kwargs)

    monkeypatch.setattr(Product.objects, "filter", fake_filter)

    response = client.get(product.get_absolute_url())
    assert response.status_code == 200


def test_product_detail_increments_views_count(client, product):
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200

    product.refresh_from_db()
    assert product.views_count == 1


def test_product_detail_no_pair_text_in_html(client):
    """Test that 'pair' text does not appear in product detail HTML."""
    # Create product with options that previously caused "pair" to appear
    product = ProductFactory(
        options={
            "Двигатель": ["pair", "Двигатель", "Cummins ISD245 50"],
            "Модель": "X3000",
        }
    )
    
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    
    content = response.content.decode("utf-8")
    
    # Check that "pair" does not appear as standalone text
    # Use regex to avoid false positives (e.g., "repair", "pairing")
    import re
    # Look for "pair" as a word boundary (not part of another word)
    pair_matches = re.findall(r'\bpair\b', content, re.IGNORECASE)
    assert len(pair_matches) == 0, f"Found 'pair' text in HTML: {pair_matches[:5]}"
    
    # Verify that the actual values are present
    assert "Двигатель" in content
    assert "Cummins ISD245 50" in content
    assert "Модель" in content
    assert "X3000" in content


def test_product_detail_options_rendered_correctly(client):
    """Test that product options are rendered correctly in both desktop and mobile views."""
    product = ProductFactory(
        options={
            "Двигатель": ["pair", "Двигатель", "Cummins ISD245 50"],
            "Мощность": "336 л.с.",
            "Комплектация": ["Опция 1", "Опция 2"],
        }
    )
    
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    
    content = response.content.decode("utf-8")
    
    # Check that values are present
    assert "Двигатель" in content
    assert "Cummins ISD245 50" in content
    assert "Мощность" in content
    assert "336 л.с." in content
    assert "Опция 1" in content
    assert "Опция 2" in content
    
    # Check that "pair" does not appear
    import re
    pair_matches = re.findall(r'\bpair\b', content, re.IGNORECASE)
    assert len(pair_matches) == 0, f"Found 'pair' text in HTML"


def test_product_detail_flat_pair_tokens_format(client):
    """Test product with flat tokenized format: ["pair", key, value, "pair", key, value, ...]."""
    product = ProductFactory(
        options=["pair", "Двигатель", "Cummins", "pair", "КПП", "FAST"]
    )
    
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    
    content = response.content.decode("utf-8")
    
    # Critical: check that <li>pair</li> does not appear
    assert "<li>pair</li>" not in content
    assert '>pair<' not in content
    
    # Verify that actual characteristics are present
    assert "Двигатель" in content
    assert "Cummins" in content
    assert "КПП" in content
    assert "FAST" in content
    
    # Additional check: no "pair" as standalone word
    import re
    pair_matches = re.findall(r'\bpair\b', content, re.IGNORECASE)
    assert len(pair_matches) == 0, f"Found 'pair' text in HTML: {pair_matches[:5]}"


def test_product_detail_dict_with_pair_tokens_in_value(client):
    """Test product with dict format where value contains pair tokens."""
    product = ProductFactory(
        options={"Характеристики": ["pair", "Двигатель", "Cummins", "pair", "КПП", "FAST"]}
    )
    
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    
    content = response.content.decode("utf-8")
    
    # Critical: check that <li>pair</li> does not appear
    assert "<li>pair</li>" not in content
    assert '>pair<' not in content
    
    # Verify that actual characteristics are present
    assert "Двигатель" in content
    assert "Cummins" in content
    assert "КПП" in content
    assert "FAST" in content
    
    # Additional check: no "pair" as standalone word
    import re
    pair_matches = re.findall(r'\bpair\b', content, re.IGNORECASE)
    assert len(pair_matches) == 0, f"Found 'pair' text in HTML: {pair_matches[:5]}"


def test_product_detail_no_li_pair_in_html_regression(client):
    """Regression test: ensure <li>pair</li> never appears in HTML."""
    # Test with clean dict data (as reported in production)
    product = ProductFactory(
        options={
            "Модель": "Автобетоносмеситель SHACMAN X3000",
            "Двигатель": "Cummins ISD245 50",
            "КПП": "FAST",
        }
    )
    
    response = client.get(product.get_absolute_url())
    assert response.status_code == 200
    
    content = response.content.decode("utf-8")
    
    # Critical assertion: <li>pair</li> must not appear anywhere
    assert "<li>pair</li>" not in content, "Found <li>pair</li> in HTML output"
    
    # Verify characteristics are present
    assert "Модель" in content
    assert "Автобетоносмеситель" in content or "SHACMAN" in content
    assert "Двигатель" in content
    assert "Cummins" in content
    
    # Check that characteristics appear in both desktop and mobile sections
    # Desktop section (should have table)
    assert "product-specs-table" in content
    # Mobile accordion (should have accordion)
    assert "accordion" in content or "productTabs" in content


def test_product_detail_nonexistent_slug_returns_404(client):
    """Non-existent product slug must return 404, not 500."""
    response = client.get("/product/nonexistent-slug-xyz/")
    assert response.status_code == 404


def test_product_detail_weird_slug_returns_404(client):
    """Valid slug format but non-existent product (e.g. typo) must return 404."""
    response = client.get("/product/avtobetonosmesitel-x5000-8x4-1/")
    assert response.status_code == 404


def test_product_detail_alias_301_to_canonical(client):
    """Product with canonical_product set returns 301 to canonical product URL (дубли → канон)."""
    canonical = ProductFactory(published=True, slug="canonical-samovar")
    alias = ProductFactory(published=True, slug="alias-samovar", canonical_product=canonical)

    response = client.get(alias.get_absolute_url())
    assert response.status_code == 301
    location = response.get("Location", "")
    assert location.endswith(canonical.get_absolute_url()) or canonical.get_absolute_url() in location


def test_product_detail_redirect_to_url_301(client):
    """Product with redirect_to_url set returns 301 to that URL (редирект на хаб)."""
    hub_url = "https://carfst.ru/shicman/"
    product = ProductFactory(
        published=True, slug="redirect-hub-product", redirect_to_url=hub_url
    )

    response = client.get(product.get_absolute_url())
    assert response.status_code == 301
    assert response.get("Location", "").strip() == hub_url
