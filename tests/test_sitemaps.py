import re

import pytest
from django.urls import reverse

from blog.sitemaps import BlogIndexSitemap
from catalog.sitemaps import (
    CategorySitemap,
    ProductSitemap,
    SeriesCategorySitemap,
    SeriesSitemap,
    StaticViewSitemap,
)

pytestmark = pytest.mark.django_db


def test_product_sitemap_returns_only_published(product_factory):
    published = product_factory(published=True)
    product_factory(published=False)

    sitemap = ProductSitemap()
    items = list(sitemap.items())
    assert items == [published]
    assert sitemap.location(published) == published.get_absolute_url()
    assert sitemap.lastmod(published) == published.updated_at


def test_product_sitemap_excludes_aliases_and_redirects(product_factory):
    """Sitemap includes only canonical products (no canonical_product, no redirect_to_url)."""
    canonical = product_factory(published=True, slug="canonical-product")
    alias = product_factory(published=True, slug="alias-product", canonical_product=canonical)
    redirect_product = product_factory(
        published=True, slug="redirect-product", redirect_to_url="https://carfst.ru/shicman/"
    )

    sitemap = ProductSitemap()
    items = list(sitemap.items())
    urls = [sitemap.location(p) for p in items]

    assert canonical in items
    assert alias not in items
    assert redirect_product not in items
    assert canonical.get_absolute_url() in urls
    assert alias.get_absolute_url() not in urls
    assert redirect_product.get_absolute_url() not in urls


def test_series_and_category_locations(series, category):
    series_sitemap = SeriesSitemap()
    category_sitemap = CategorySitemap()

    series_url = reverse("catalog:catalog_series", kwargs={"slug": series.slug})
    category_url = reverse("catalog:catalog_category", kwargs={"slug": category.slug})
    assert series_sitemap.location(series) == series_url
    assert category_sitemap.location(category) == category_url


def test_series_and_category_items_are_ordered():
    series_items = SeriesSitemap().items()
    category_items = CategorySitemap().items()

    assert series_items.ordered is True
    assert category_items.ordered is True


def test_static_view_sitemap_contains_known_paths():
    sitemap = StaticViewSitemap()
    locations = [sitemap.location(item) for item in sitemap.items()]
    assert reverse("catalog:home") in locations
    assert reverse("catalog:catalog_in_stock") in locations


def test_blog_index_sitemap_location():
    sitemap = BlogIndexSitemap()
    locations = [sitemap.location(item) for item in sitemap.items()]
    assert reverse("blog:blog_list") in locations


def test_series_category_sitemap_locations(series, category, product_factory):
    product_factory(series=series, category=category, published=True, is_active=True)
    sitemap = SeriesCategorySitemap()
    locations = [sitemap.location(item) for item in sitemap.items()]
    expected = reverse(
        "catalog:catalog_series_category",
        kwargs={"series_slug": series.slug, "category_slug": category.slug},
    )
    assert expected in locations


def test_series_category_sitemap_deduplicates_pairs(series, category, product_factory):
    product_factory(series=series, category=category, published=True, is_active=True)
    product_factory(series=series, category=category, published=True, is_active=True)
    pairs = list(SeriesCategorySitemap().items())
    # Items are now tuples: (series_slug, category_slug, latest_product)
    matching_pairs = [p for p in pairs if p[0] == series.slug and p[1] == category.slug]
    assert len(matching_pairs) == 1


def test_sitemap_response_content_type(client):
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    content_type = response.headers.get("Content-Type", "")
    assert "application/xml" in content_type


def test_sitemap_does_not_include_catalog_root(client):
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert "<loc>https://carfst.ru/catalog/</loc>" not in content


def test_sitemap_has_no_duplicate_locations(client):
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", content)
    assert len(locs) == len(set(locs))


def test_sitemap_all_urls_use_canonical_domain(client):
    """Test that all URLs in sitemap use https://carfst.ru/ domain."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    # Extract all <loc> URLs
    locs = re.findall(r"<loc>([^<]+)</loc>", content)
    assert len(locs) > 0, "Sitemap should contain at least one URL"
    
    # Check all URLs start with https://carfst.ru/
    for url in locs:
        assert url.startswith("https://carfst.ru/"), f"URL does not start with https://carfst.ru/: {url}"
        # Check for common typos
        assert "carfst.r/" not in url, f"URL contains typo 'carfst.r': {url}"
        assert "carfst.r " not in url, f"URL contains typo 'carfst.r ': {url}"
        # Check no querystring
        assert "?" not in url, f"URL contains querystring: {url}"
        assert "&" not in url, f"URL contains querystring separator: {url}"


def test_sitemap_no_typo_domain(client):
    """Test that sitemap does not contain common domain typos like 'carfst.r'."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    # Check for common typos
    assert "carfst.r/" not in content, "Sitemap contains typo 'carfst.r/'"
    assert "carfst.r " not in content, "Sitemap contains typo 'carfst.r '"
    assert "http://carfst.ru" not in content, "Sitemap contains HTTP instead of HTTPS"
    
    # All URLs should be HTTPS
    locs = re.findall(r"<loc>([^<]+)</loc>", content)
    for url in locs:
        assert url.startswith("https://"), f"URL is not HTTPS: {url}"


def test_sitemap_no_querystring(client):
    """Test that sitemap URLs do not contain querystring parameters."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    locs = re.findall(r"<loc>([^<]+)</loc>", content)
    for url in locs:
        assert "?" not in url, f"URL contains querystring: {url}"
        assert "&" not in url, f"URL contains querystring separator: {url}"


def test_series_category_sitemap_has_lastmod(series, category, product_factory):
    """Test that SeriesCategorySitemap returns lastmod for series+category pairs."""
    from datetime import datetime
    
    product = product_factory(series=series, category=category, published=True, is_active=True)
    sitemap = SeriesCategorySitemap()
    items = list(sitemap.items())
    
    assert len(items) > 0
    # Check that items are tuples with 3 elements (series_slug, category_slug, latest_product)
    for item in items:
        assert len(item) >= 3
        lastmod = sitemap.lastmod(item)
        assert lastmod is not None
        assert isinstance(lastmod, datetime)
    
    # Verify that lastmod matches product's updated_at
    matching_item = next((item for item in items if item[0] == series.slug and item[1] == category.slug), None)
    if matching_item:
        lastmod = sitemap.lastmod(matching_item)
        assert lastmod is not None


def test_series_category_sitemap_xml_contains_lastmod(client, series, category, product_factory):
    """Test that sitemap XML contains <lastmod> for series_category URLs."""
    product_factory(series=series, category=category, published=True, is_active=True)
    
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    # Find series_category URL in sitemap
    series_category_url = reverse(
        "catalog:catalog_series_category",
        kwargs={"series_slug": series.slug, "category_slug": category.slug},
    )
    
    # Extract the <url> block for this location (sitemap may use canonical full URL)
    url_pattern = rf'<url>.*?<loc>(?:https?://[^/]+)?{re.escape(series_category_url)}</loc>.*?</url>'
    match = re.search(url_pattern, content, re.DOTALL)
    assert match, f"Series+category URL not found in sitemap: {series_category_url}"
    
    url_block = match.group(0)
    # Check that <lastmod> is present
    assert "<lastmod>" in url_block
    assert "</lastmod>" in url_block
