import html
import json
import re

import pytest

from django.test import override_settings

from catalog.utils.text_cleaner import clean_text
from tests.factories import CategoryFactory, ProductFactory, SeriesFactory


def _extract_json_ld(content: str):
    scripts = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        content,
        flags=re.DOTALL,
    )
    schemas = []
    for raw in scripts:
        data = json.loads(html.unescape(raw.strip()))
        if isinstance(data, list):
            schemas.extend(data)
        else:
            schemas.append(data)
    return schemas


@pytest.mark.django_db
@override_settings(CONTACT_MAX_URL="https://max.example.com")
def test_max_not_duplicated_anywhere(client):
    series, _ = SeriesFactory._meta.model.objects.get_or_create(
        slug="shacman",
        defaults={"name": "SHACMAN"},
    )
    category, _ = CategoryFactory._meta.model.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    ProductFactory(series=series, category=category)

    for path in ("/", "/contacts/", "/brands/shacman/", "/catalog/", "/catalog/category/samosvaly/"):
        response = client.get(path)
        content = response.content.decode("utf-8")
        assert response.status_code == 200
        assert "MAX MAX" not in content


def test_clean_text_adds_space_after_comma_safely():
    cases = {
        "8×4,WP13.550E501,козырьком": "8×4, WP13.550E501, козырьком",
        "Model,Test": "Model, Test",
        "1,5 тонны": "1,5 тонны",
        "WP10.336E53": "WP10.336E53",
        "A, B": "A, B",
    }
    for raw, expected in cases.items():
        assert clean_text(raw) == expected


@pytest.mark.django_db
def test_catalog_category_listing_normalizes_commas(client):
    series, _ = SeriesFactory._meta.model.objects.get_or_create(
        slug="shacman",
        defaults={"name": "SHACMAN"},
    )
    category, _ = CategoryFactory._meta.model.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    ProductFactory(
        series=series,
        category=category,
        model_name_ru="8×4,WP13.550E501,козырьком PRO",
    )

    response = client.get("/catalog/category/samosvaly/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "8×4,WP13.550E501,козырьком PRO" not in content
    assert "8×4, WP13.550E501, козырьком PRO" in content


@pytest.mark.django_db
def test_product_breadcrumbs_use_seo_urls(client):
    series, _ = SeriesFactory._meta.model.objects.get_or_create(
        slug="shacman",
        defaults={"name": "SHACMAN"},
    )
    category, _ = CategoryFactory._meta.model.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    product = ProductFactory(series=series, category=category)

    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200

    schemas = _extract_json_ld(content)
    breadcrumb = next(schema for schema in schemas if schema.get("@type") == "BreadcrumbList")
    urls = [item.get("item", "") for item in breadcrumb.get("itemListElement", [])]

    assert all("/catalog/?" not in url for url in urls)
    assert any(f"/catalog/series/{series.slug}/" in url for url in urls)
    assert any(f"/catalog/series/{series.slug}/{category.slug}/" in url for url in urls)


def test_robots_txt_multiline_and_has_sitemap(client):
    response = client.get("/robots.txt")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "\n" in content
    assert content.count("\n") >= 3
    assert "Sitemap: https://carfst.ru/sitemap.xml" in content


@pytest.mark.django_db
def test_sitemap_xml_ok_and_no_get_catalog_links(client):
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/catalog/?" not in content


@pytest.mark.django_db
def test_sitemap_xml_no_page_params(client):
    """Sitemap should not contain ?page= parameters."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "?page=" not in content
    assert "&page=" not in content


@pytest.mark.django_db
def test_sitemap_xml_contains_series_landing(client):
    """Sitemap should contain indexable series landing pages."""
    series, _ = SeriesFactory._meta.model.objects.get_or_create(
        slug="shacman",
        defaults={"name": "SHACMAN"},
    )
    category, _ = CategoryFactory._meta.model.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert f"/catalog/series/{series.slug}/" in content


@pytest.mark.django_db
def test_catalog_series_has_breadcrumb_schema(client):
    """Catalog series landing page should have BreadcrumbList JSON-LD."""
    series = SeriesFactory(slug="test-series", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    assert len(breadcrumb.get("itemListElement", [])) == 2
    assert breadcrumb["itemListElement"][0]["name"] == "Главная"
    assert breadcrumb["itemListElement"][1]["name"] == series.name


@pytest.mark.django_db
def test_catalog_category_has_breadcrumb_schema(client):
    """Catalog category landing page should have BreadcrumbList JSON-LD."""
    category = CategoryFactory(slug="test-category", name="Test Category")
    ProductFactory(category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    assert len(breadcrumb.get("itemListElement", [])) == 2
    assert breadcrumb["itemListElement"][0]["name"] == "Главная"
    assert breadcrumb["itemListElement"][1]["name"] == category.name


@pytest.mark.django_db
def test_catalog_series_category_has_breadcrumb_schema(client):
    """Catalog series+category landing page should have BreadcrumbList JSON-LD."""
    series = SeriesFactory(slug="test-series", name="Test Series")
    category = CategoryFactory(slug="test-category", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    assert len(breadcrumb.get("itemListElement", [])) == 3
    assert breadcrumb["itemListElement"][0]["name"] == "Главная"
    assert breadcrumb["itemListElement"][1]["name"] == series.name
    assert breadcrumb["itemListElement"][2]["name"] == category.name


@pytest.mark.django_db
def test_blog_post_has_blogposting_schema(client):
    """Blog post should have BlogPosting JSON-LD."""
    from blog.models import BlogPost
    from django.utils import timezone
    
    post = BlogPost.objects.create(
        title="Test Post",
        slug="test-post",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
        published_at=timezone.now(),
    )
    
    response = client.get(post.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    blogposting = next((s for s in schemas if s.get("@type") == "BlogPosting"), None)
    assert blogposting is not None
    assert blogposting["headline"] == post.title
    assert blogposting["description"] == post.excerpt
    assert "datePublished" in blogposting
    assert "dateModified" in blogposting
    assert blogposting["author"]["@type"] == "Organization"
    assert blogposting["publisher"]["@type"] == "Organization"


@pytest.mark.django_db
def test_pages_have_default_og_image(client):
    """Pages should have default og:image if not specified."""
    response = client.get("/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'property="og:image"' in content
    assert 'name="twitter:image"' in content


@pytest.mark.django_db
def test_key_pages_have_unique_titles(client):
    """Key pages should have unique meta titles."""
    pages = {
        "/": "CARFAST",
        "/parts/": "Запчасти",
        "/service/": "Сервис",
        "/used/": "Б/У техника",
        "/contacts/": "Контакты",
    }
    
    titles = {}
    for path, expected_in_title in pages.items():
        response = client.get(path)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Extract title from <title> tag
        title_match = re.search(r'<title>(.*?)</title>', content, re.DOTALL)
        assert title_match, f"Title not found for {path}"
        title = title_match.group(1)
        assert expected_in_title in title, f"Expected '{expected_in_title}' in title for {path}"
        titles[path] = title
    
    # Check uniqueness
    unique_titles = set(titles.values())
    assert len(unique_titles) == len(titles), "Some pages have duplicate titles"


@pytest.mark.django_db
def test_key_pages_have_unique_descriptions(client):
    """Key pages should have unique meta descriptions."""
    pages = {
        "/": "SHACMAN",
        "/parts/": "Запчасти",
        "/service/": "Сервис",
        "/used/": "Б/У",
        "/contacts/": "Контакты",
    }
    
    descriptions = {}
    for path, expected_in_desc in pages.items():
        response = client.get(path)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Extract description from meta tag
        desc_match = re.search(r'<meta name="description" content="([^"]+)"', content)
        assert desc_match, f"Description not found for {path}"
        description = desc_match.group(1)
        assert expected_in_desc in description, f"Expected '{expected_in_desc}' in description for {path}"
        descriptions[path] = description
    
    # Check uniqueness
    unique_descriptions = set(descriptions.values())
    assert len(unique_descriptions) == len(descriptions), "Some pages have duplicate descriptions"


@pytest.mark.django_db
def test_sitemap_excludes_catalog_root(client):
    """Sitemap should not contain /catalog/ root URL."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    # Should not contain /catalog/ as standalone URL (without series/category)
    assert '<loc>https://carfst.ru/catalog/</loc>' not in content
    assert '<loc>http://testserver/catalog/</loc>' not in content


@pytest.mark.django_db
def test_sitemap_excludes_querystring_urls(client):
    """Sitemap should not contain URLs with querystring parameters."""
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    # Should not contain any URLs with ? or &
    loc_tags = re.findall(r'<loc>([^<]+)</loc>', content)
    for url in loc_tags:
        assert "?" not in url, f"Sitemap contains URL with querystring: {url}"
        assert "&" not in url, f"Sitemap contains URL with querystring: {url}"


@pytest.mark.django_db
def test_breadcrumb_urls_are_absolute(client):
    """BreadcrumbList URLs should be absolute."""
    series = SeriesFactory(slug="test-series", name="Test Series")
    category = CategoryFactory(slug="test-category", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    
    for item in breadcrumb.get("itemListElement", []):
        url = item.get("item", "")
        assert url.startswith("http://") or url.startswith("https://"), \
            f"Breadcrumb URL should be absolute: {url}"


@pytest.mark.django_db
def test_blogposting_has_required_fields(client):
    """BlogPosting should have all required fields including mainEntityOfPage."""
    from blog.models import BlogPost
    from django.utils import timezone
    
    post = BlogPost.objects.create(
        title="Test Post",
        slug="test-post",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
        published_at=timezone.now(),
    )
    
    response = client.get(post.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    blogposting = next((s for s in schemas if s.get("@type") == "BlogPosting"), None)
    assert blogposting is not None
    
    # Required fields
    assert "headline" in blogposting
    assert "description" in blogposting
    assert "url" in blogposting
    assert "datePublished" in blogposting
    assert "dateModified" in blogposting
    assert "author" in blogposting
    assert "publisher" in blogposting
    assert "mainEntityOfPage" in blogposting
    
    # Check mainEntityOfPage structure
    main_entity = blogposting["mainEntityOfPage"]
    assert main_entity["@type"] == "WebPage"
    assert "@id" in main_entity
    assert main_entity["@id"].startswith("http://") or main_entity["@id"].startswith("https://")


@pytest.mark.django_db
def test_og_image_on_different_page_types(client):
    """Different page types should have og:image."""
    # Home page
    response = client.get("/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'property="og:image"' in content
    
    # Static page
    response = client.get("/parts/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'property="og:image"' in content
    
    # Catalog landing page
    series = SeriesFactory(slug="test-series", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'property="og:image"' in content
    
    # Product page
    product = ProductFactory()
    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'property="og:image"' in content


@pytest.mark.django_db
def test_twitter_card_present(client):
    """Pages should have twitter:card meta tag."""
    response = client.get("/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="twitter:card"' in content


@pytest.mark.django_db
def test_build_id_header_on_redirects(client):
    """X-Build-ID header should be present on redirects."""
    series = SeriesFactory(slug="test-series", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    
    # Test redirect from /catalog/?series=test-series to /catalog/series/test-series/
    response = client.get(f"/catalog/?series={series.slug}")
    assert response.status_code in (301, 302)
    assert "X-Build-ID" in response.headers
    
    # Test redirect from page=1
    response = client.get(f"/catalog/series/{series.slug}/?page=1")
    assert response.status_code in (301, 302)
    assert "X-Build-ID" in response.headers


@pytest.mark.django_db
def test_build_id_matches_version_endpoint(client):
    """X-Build-ID header should match /__version__/ endpoint."""
    from carfst_site.build_id import get_build_id
    
    # Get build ID from header
    response = client.get("/")
    assert response.status_code == 200
    header_build_id = response.headers.get("X-Build-ID")
    assert header_build_id is not None
    
    # Get build ID from version endpoint
    response = client.get("/__version__/")
    assert response.status_code == 200
    import json
    version_data = json.loads(response.content.decode("utf-8"))
    endpoint_build_id = version_data.get("build_id")
    
    # Get build ID from function
    function_build_id = get_build_id()
    
    # All should match
    assert header_build_id == endpoint_build_id == function_build_id, \
        f"Build IDs don't match: header={header_build_id}, endpoint={endpoint_build_id}, function={function_build_id}"


@pytest.mark.django_db
def test_catalog_series_has_faqpage_schema(client):
    """Catalog series landing page should have FAQPage JSON-LD when FAQ is present."""
    series = SeriesFactory(slug="test-series-faq", name="Test Series")
    series.seo_faq = "What is this?|This is a test answer."
    series.save()
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schema = next((s for s in schemas if s.get("@type") == "FAQPage"), None)
    assert faq_schema is not None
    assert len(faq_schema.get("mainEntity", [])) == 1
    assert faq_schema["mainEntity"][0]["name"] == "What is this?"
    assert faq_schema["mainEntity"][0]["acceptedAnswer"]["text"] == "This is a test answer."


@pytest.mark.django_db
def test_catalog_series_faqpage_not_on_page2(client):
    """FAQPage schema should not be present on page>1."""
    series = SeriesFactory(slug="test-series-faq-page2", name="Test Series")
    series.seo_faq = "What is this?|This is a test answer."
    series.save()
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schema = next((s for s in schemas if s.get("@type") == "FAQPage"), None)
    assert faq_schema is None


@pytest.mark.django_db
def test_catalog_category_has_faqpage_schema(client):
    """Catalog category landing page should have FAQPage JSON-LD when FAQ is present."""
    category = CategoryFactory(slug="test-category-faq", name="Test Category")
    category.seo_faq = "How does it work?|It works perfectly."
    category.save()
    ProductFactory(category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schema = next((s for s in schemas if s.get("@type") == "FAQPage"), None)
    assert faq_schema is not None
    assert len(faq_schema.get("mainEntity", [])) == 1
    assert faq_schema["mainEntity"][0]["name"] == "How does it work?"
    assert faq_schema["mainEntity"][0]["acceptedAnswer"]["text"] == "It works perfectly."


@pytest.mark.django_db
def test_catalog_series_category_has_faqpage_schema(client):
    """Catalog series+category landing page should have FAQPage JSON-LD when FAQ is present."""
    from catalog.models import SeriesCategorySEO
    
    series = SeriesFactory(slug="test-series-cat-faq", name="Test Series")
    category = CategoryFactory(slug="test-category-cat-faq", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    SeriesCategorySEO.objects.create(
        series=series,
        category=category,
        seo_faq="What is this combination?|This is a series+category FAQ.",
    )
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schema = next((s for s in schemas if s.get("@type") == "FAQPage"), None)
    assert faq_schema is not None
    assert len(faq_schema.get("mainEntity", [])) == 1
    assert faq_schema["mainEntity"][0]["name"] == "What is this combination?"
    assert faq_schema["mainEntity"][0]["acceptedAnswer"]["text"] == "This is a series+category FAQ."


@pytest.mark.django_db
def test_blog_list_has_breadcrumb_schema(client):
    """Blog list page should have BreadcrumbList JSON-LD."""
    from blog.models import BlogPost
    from django.utils import timezone
    
    BlogPost.objects.create(
        title="Test Post",
        slug="test-post",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
        published_at=timezone.now(),
    )
    
    response = client.get("/blog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    assert len(breadcrumb.get("itemListElement", [])) == 2
    assert breadcrumb["itemListElement"][0]["name"] == "Главная"
    assert breadcrumb["itemListElement"][1]["name"] == "Блог"
    # Check that URLs are absolute
    assert breadcrumb["itemListElement"][0]["item"].startswith("http://") or breadcrumb["itemListElement"][0]["item"].startswith("https://")
    assert breadcrumb["itemListElement"][1]["item"].startswith("http://") or breadcrumb["itemListElement"][1]["item"].startswith("https://")


@pytest.mark.django_db
def test_blog_detail_has_breadcrumb_schema(client):
    """Blog detail page should have BreadcrumbList JSON-LD."""
    from blog.models import BlogPost
    from django.utils import timezone
    
    post = BlogPost.objects.create(
        title="Test Post Detail",
        slug="test-post-detail",
        excerpt="Test excerpt",
        content_html="<p>Test content</p>",
        is_published=True,
        published_at=timezone.now(),
    )
    
    response = client.get(post.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    breadcrumb = next((s for s in schemas if s.get("@type") == "BreadcrumbList"), None)
    assert breadcrumb is not None
    assert len(breadcrumb.get("itemListElement", [])) == 3
    assert breadcrumb["itemListElement"][0]["name"] == "Главная"
    assert breadcrumb["itemListElement"][1]["name"] == "Блог"
    assert breadcrumb["itemListElement"][2]["name"] == post.title
    # Check that URLs are absolute
    for item in breadcrumb["itemListElement"]:
        assert item["item"].startswith("http://") or item["item"].startswith("https://")
    
    # Check that BlogPosting schema is still present
    blogposting = next((s for s in schemas if s.get("@type") == "BlogPosting"), None)
    assert blogposting is not None
    assert blogposting["headline"] == post.title
