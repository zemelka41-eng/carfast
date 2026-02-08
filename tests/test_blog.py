import re

import pytest
from django.utils import timezone

from blog.models import BlogPost


pytestmark = pytest.mark.django_db


def _ensure_post():
    return BlogPost.objects.get_or_create(
        slug="lizing-kredit-ili-pokupka-za-svoi-2026",
        defaults={
            "title": (
                "Лизинг, кредит или покупка за свои в 2026: что выгоднее для "
                "грузовой техники и спецтехники"
            ),
            "excerpt": (
                "Лизинг, кредит или покупка за свои в 2026: полная стоимость, "
                "денежный поток, ОСНО/УСН, ошибки выбора и чек-лист."
            ),
            "content_html": "<p>Тестовый контент.</p>",
            "is_published": True,
            "published_at": timezone.now(),
        },
    )[0]


def test_blog_list_returns_200(client):
    post = _ensure_post()
    response = client.get("/blog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert post.title in content
    assert post.get_absolute_url() in content
    assert 'name="robots" content="index, follow"' in content
    assert 'rel="canonical" href="https://carfst.ru/blog/"' in content


def test_blog_detail_indexable(client):
    post = _ensure_post()
    response = client.get(post.get_absolute_url())
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    assert f'rel="canonical" href="https://carfst.ru{post.get_absolute_url()}"' in content


def test_blog_detail_utm_noindex(client):
    post = _ensure_post()
    response = client.get(f"{post.get_absolute_url()}?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert f'rel="canonical" href="https://carfst.ru{post.get_absolute_url()}"' in content


def test_blog_list_no_schema_with_page(client):
    """Test that blog list page does not include BreadcrumbList/BlogPosting schema when page param is present."""
    _ensure_post()
    response = client.get("/blog/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    # Extract JSON-LD schema blocks
    schema_blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        content,
        re.DOTALL,
    )
    assert len(schema_blocks) > 0, "Should have Organization/WebSite schema"
    # Check that page-level schemas (BreadcrumbList, BlogPosting) are not present
    for block in schema_blocks:
        # Organization and WebSite are allowed (always present)
        if '"@type": "Organization"' in block or '"@type": "WebSite"' in block:
            continue
        # Page-level schemas should not be present
        assert '"@type": "BreadcrumbList"' not in block, f"Found BreadcrumbList in schema block: {block[:200]}"
        assert '"@type": "BlogPosting"' not in block, f"Found BlogPosting in schema block: {block[:200]}"


def test_blog_detail_no_schema_with_utm(client):
    """Test that blog detail page does not include BlogPosting/BreadcrumbList schema when GET params are present."""
    post = _ensure_post()
    response = client.get(f"{post.get_absolute_url()}?utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    # Extract JSON-LD schema blocks
    schema_blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        content,
        re.DOTALL,
    )
    assert len(schema_blocks) > 0, "Should have Organization/WebSite schema"
    # Check that page-level schemas are not present
    for block in schema_blocks:
        # Organization and WebSite are allowed (always present)
        if '"@type": "Organization"' in block or '"@type": "WebSite"' in block:
            continue
        # Page-level schemas should not be present
        assert '"@type": "BlogPosting"' not in block
        assert '"@type": "BreadcrumbList"' not in block


def test_blog_in_sitemap(client):
    post = _ensure_post()
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert re.search(r"<loc>https?://[^<]+/blog/</loc>", content)
    assert re.search(
        rf"<loc>https?://[^<]+{re.escape(post.get_absolute_url())}</loc>",
        content,
    )


def test_blog_seed_post_exists():
    assert BlogPost.objects.filter(slug="lizing-kredit-ili-pokupka-za-svoi-2026").exists()


def test_sitemap_no_duplicate_locations(client):
    response = client.get("/sitemap.xml")
    content = response.content.decode("utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", content)
    assert len(locs) == len(set(locs))
