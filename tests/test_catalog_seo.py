import html
import re

import pytest

from catalog.models import Category, Series
from tests.factories import CategoryFactory, ProductFactory, SeriesFactory


def _extract_canonical(content: str) -> str:
    match = re.search(r'rel="canonical" href="([^"]+)"', content)
    assert match, "canonical link not found"
    return html.unescape(match.group(1))


@pytest.mark.django_db
def test_catalog_canonical_for_series_only(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    response = client.get(f"/catalog/?series={series.slug}")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/")


@pytest.mark.django_db
def test_catalog_series_landing_indexable(client):
    series = SeriesFactory(slug="series-test-1", name="SHACMAN")
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert _extract_canonical(content) == f"https://carfst.ru/catalog/series/{series.slug}/"
    assert 'name="robots" content="index, follow"' in content
    assert "<h1" in content and "SHACMAN" in content


@pytest.mark.django_db
def test_catalog_canonical_for_category_only(client):
    category = CategoryFactory(slug="category-test-1", name="Самосвалы")
    response = client.get(f"/catalog/?category={category.slug}")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/category/{category.slug}/")


@pytest.mark.django_db
def test_catalog_series_redirect_keeps_tracking(client):
    series = SeriesFactory(slug="series-test-tracking", name="SHACMAN")
    response = client.get(f"/catalog/?series={series.slug}&utm_source=x")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith(f"/catalog/series/{series.slug}/")
    assert "utm_source=x" in location


@pytest.mark.django_db
def test_catalog_category_redirect_keeps_tracking(client):
    category = CategoryFactory(slug="category-test-tracking", name="Самосвалы")
    response = client.get(f"/catalog/?category={category.slug}&utm_medium=x")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith(f"/catalog/category/{category.slug}/")
    assert "utm_medium=x" in location


@pytest.mark.django_db
def test_catalog_list_invalid_category_404(client):
    """?category=несуществующий slug → 404 (анти-мусор для параметрических URL)."""
    from django.http import Http404
    from django.test import RequestFactory
    from catalog.views import catalog_list

    factory = RequestFactory()
    request = factory.get("/catalog/", {"category": "nonexistent-category-slug-xyz"})
    request.session = {}
    request.META["SERVER_NAME"] = "testserver"
    with pytest.raises(Http404):
        catalog_list(request)


@pytest.mark.django_db
def test_catalog_nav_and_footer_link_to_in_stock_not_catalog_list(client):
    """Пункт «Каталог» в меню и футере ведёт на /catalog/in-stock/, а не на /catalog/."""
    from django.urls import reverse

    response = client.get(reverse("catalog:home"))
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    in_stock_path = reverse("catalog:catalog_in_stock")
    assert in_stock_path in content, "Ожидается ссылка на каталог в наличии"
    # Не должно быть ссылки с href="/catalog/" (без in-stock) у пункта Каталог
    assert 'href="/catalog/">' not in content, (
        "Пункт «Каталог» не должен вести на /catalog/; должен вести на /catalog/in-stock/"
    )


@pytest.mark.django_db
def test_catalog_list_invalid_series_404(client):
    """?series=несуществующий slug → 404 (анти-мусор для параметрических URL)."""
    from django.http import Http404
    from django.test import RequestFactory
    from catalog.views import catalog_list

    factory = RequestFactory()
    request = factory.get("/catalog/", {"series": "nonexistent-series-slug-xyz"})
    request.session = {}
    request.META["SERVER_NAME"] = "testserver"
    with pytest.raises(Http404):
        catalog_list(request)


@pytest.mark.django_db
def test_catalog_tracking_only_noindex(client):
    response = client.get("/catalog/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/"


@pytest.mark.django_db
def test_catalog_category_landing_indexable(client):
    category = CategoryFactory(slug="category-test-1", name="Самосвалы")
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert _extract_canonical(content) == f"https://carfst.ru/catalog/category/{category.slug}/"
    assert 'name="robots" content="index, follow"' in content
    assert "<h1" in content and "Самосвалы" in content


@pytest.mark.django_db
def test_catalog_noindex_for_combined_filters(client):
    """?series=X&category=Y redirects 301 to /catalog/series/X/Y/ (no longer noindex on /catalog/)."""
    series = SeriesFactory(slug="series-test-2", name="SHACMAN")
    category = CategoryFactory(slug="category-test-1", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}")
    assert response.status_code == 301
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")


@pytest.mark.django_db
def test_catalog_redirect_series_category_clean(client):
    """GET /catalog/?series=X&category=Y -> 301 Location: /catalog/series/X/Y/."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    category = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}")
    assert response.status_code == 301
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")
    assert "?" not in location or location.split("?")[0].endswith(f"/catalog/series/{series.slug}/{category.slug}/")


@pytest.mark.django_db
def test_catalog_redirect_series_category_with_utm(client):
    """GET /catalog/?series=X&category=Y&utm_source=test -> 301 to clean URL (utm dropped)."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    category = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}&utm_source=test")
    assert response.status_code == 301
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")
    assert "utm_source" not in location


@pytest.mark.django_db
def test_catalog_redirect_series_category_with_page2(client):
    """GET /catalog/?series=X&category=Y&page=2 -> 301 Location: .../series/X/Y/?page=2."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    category = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}&page=2")
    assert response.status_code == 301
    location = response.headers.get("Location", "")
    base_path = f"/catalog/series/{series.slug}/{category.slug}/"
    assert base_path in location
    assert "page=2" in location


@pytest.mark.django_db
def test_catalog_redirect_series_category_page1_dropped(client):
    """GET /catalog/?series=X&category=Y&page=1 -> 301 to .../series/X/Y/ (no ?page=1)."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    category = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}&page=1")
    assert response.status_code == 301
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")
    assert "page=1" not in location and "page=" not in location


@pytest.mark.django_db
def test_catalog_series_category_invalid_page_no_redirect(client):
    """GET /catalog/?series=X&category=Y&page=abc -> no redirect (invalid page), no 500."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    category = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/catalog/?series={series.slug}&category={category.slug}&page=abc")
    assert response.status_code == 200


@pytest.mark.django_db
def test_catalog_series_category_landing_indexable(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    category, _ = Category.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert (
        _extract_canonical(content)
        == f"https://carfst.ru/catalog/series/{series.slug}/{category.slug}/"
    )
    assert 'name="robots" content="index, follow"' in content
    assert "Каталог техники" in content
    assert "SHACMAN" in content
    assert "Самосвалы" in content


@pytest.mark.django_db
def test_catalog_series_category_page2_noindex(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    category, _ = Category.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert (
        _extract_canonical(content)
        == f"https://carfst.ru/catalog/series/{series.slug}/{category.slug}/?page=2"
    )


@pytest.mark.django_db
def test_catalog_series_page1_redirects(client):
    series = SeriesFactory(slug="series-page1", name="SHACMAN")
    response = client.get(f"/catalog/series/{series.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/")


@pytest.mark.django_db
def test_catalog_category_page1_redirects(client):
    category = CategoryFactory(slug="category-page1", name="Самосвалы")
    response = client.get(f"/catalog/category/{category.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/category/{category.slug}/")


@pytest.mark.django_db
def test_catalog_series_category_page1_redirects(client):
    series = SeriesFactory(slug="series-page1-2", name="SHACMAN")
    category = CategoryFactory(slug="category-page1-2", name="Самосвалы")
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")


@pytest.mark.django_db
def test_catalog_page1_with_utm_no_redirect(client):
    series = SeriesFactory(slug="series-page1-utm", name="SHACMAN")
    response = client.get(f"/catalog/series/{series.slug}/?page=1&utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content


@pytest.mark.django_db
def test_catalog_series_category_utm_noindex(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    category, _ = Category.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert (
        _extract_canonical(content)
        == f"https://carfst.ru/catalog/series/{series.slug}/{category.slug}/"
    )


@pytest.mark.django_db
def test_brand_detail_category_links_use_series_category_urls(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    categories = [
        Category.objects.get_or_create(
            slug="avtobetonosmesiteli",
            defaults={"name": "Автобетоносмесители"},
        )[0],
        Category.objects.get_or_create(
            slug="samosvaly",
            defaults={"name": "Самосвалы"},
        )[0],
        Category.objects.get_or_create(
            slug="sedelnye-tyagachi",
            defaults={"name": "Седельные тягачи"},
        )[0],
    ]
    response = client.get(f"/brands/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    for category in categories:
        assert (
            f'href="/catalog/series/{series.slug}/{category.slug}/"' in content
        )
    assert f'href="/catalog/series/{series.slug}/"' in content
    assert "/catalog/?category=" not in content
    assert "/catalog/?series=" not in content


@pytest.mark.django_db
def test_brand_detail_links_are_seo_urls_no_get_params(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    categories = [
        Category.objects.get_or_create(
            slug="samosvaly",
            defaults={"name": "Самосвалы"},
        )[0],
        Category.objects.get_or_create(
            slug="tyagachi",
            defaults={"name": "Тягачи"},
        )[0],
    ]
    response = client.get(f"/brands/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "/catalog/?category=" not in content
    for category in categories:
        assert f'href="/catalog/series/{series.slug}/{category.slug}/"' in content


@pytest.mark.django_db
def test_catalog_category_fast_filter_keeps_category(client):
    shacman, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    dayun, _ = Series.objects.get_or_create(
        slug="dayun",
        defaults={
            "name": "DAYUN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "DAYUN",
        },
    )
    category, _ = Category.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    ProductFactory(series=shacman, category=category)
    ProductFactory(series=dayun, category=category)
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert f'href="/catalog/series/{shacman.slug}/{category.slug}/"' in content
    assert f'href="/catalog/series/{dayun.slug}/{category.slug}/"' in content
    match = re.search(
        r'<a[^>]+href="([^"]+)"[^>]*>\s*Все бренды\s*</a>',
        content,
    )
    assert match, "Все бренды link not found"
    assert match.group(1) == f"/catalog/category/{category.slug}/"


@pytest.mark.django_db
def test_catalog_category_fast_filter_links_keep_category(client):
    series, _ = Series.objects.get_or_create(
        slug="shacman",
        defaults={
            "name": "SHACMAN",
            "description_ru": "",
            "description_en": "",
            "history": "",
            "logo": "",
            "logo_alt_ru": "SHACMAN",
        },
    )
    category, _ = Category.objects.get_or_create(
        slug="samosvaly",
        defaults={"name": "Самосвалы"},
    )
    ProductFactory(series=series, category=category)
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert f'href="/catalog/series/{series.slug}/{category.slug}/"' in content
    assert f'href="/catalog/category/{category.slug}/"' in content


@pytest.mark.django_db
def test_catalog_series_category_404(client):
    response = client.get("/catalog/series/unknown/samosvaly/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_catalog_index_no_robots(client):
    response = client.get("/catalog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/"
    assert "официаль" not in content.lower()


@pytest.mark.django_db
def test_catalog_noindex_for_search(client):
    response = client.get("/catalog/?q=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/"


@pytest.mark.django_db
def test_catalog_series_page_indexable(client):
    series = SeriesFactory(slug="series-test-3", name="SHACMAN")
    response = client.get(f"/catalog/?series={series.slug}&page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/"
    assert "страница 2" in content


@pytest.mark.django_db
def test_catalog_noindex_for_utm_params(client):
    series = SeriesFactory(slug="series-test-4", name="SHACMAN")
    response = client.get(f"/catalog/?series={series.slug}&utm_source=test")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith(f"/catalog/series/{series.slug}/")
    assert "utm_source=test" in location


@pytest.mark.django_db
def test_blog_noindex(client):
    response = client.get("/blog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content


@pytest.mark.django_db
def test_home_noindex_for_series_param(client):
    response = client.get("/?series=shacman")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert _extract_canonical(content) == "http://testserver/"
    assert 'name="robots" content="noindex, follow"' in content


@pytest.mark.django_db
def test_contacts_noindex_for_series_param(client):
    response = client.get("/contacts/?series=shacman")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert _extract_canonical(content) == "http://testserver/contacts/"
    assert 'name="robots" content="noindex, follow"' in content


@pytest.mark.django_db
def test_contacts_returns_200(client):
    response = client.get("/contacts/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_catalog_availability_redirects_to_in_stock(client):
    response = client.get("/catalog/?availability=in_stock")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith("/catalog/in-stock/")


@pytest.mark.django_db
def test_catalog_availability_redirects_with_utm(client):
    response = client.get("/catalog/?availability=in_stock&utm_source=test")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith("/catalog/in-stock/")
    assert "utm_source=test" in location


@pytest.mark.django_db
def test_catalog_availability_redirects_with_page(client):
    response = client.get("/catalog/?availability=in_stock&page=2&utm_campaign=x")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith("/catalog/in-stock/")
    assert "page=2" in location
    assert "utm_campaign=x" in location


@pytest.mark.django_db
def test_catalog_availability_redirects_with_page_and_gclid(client):
    response = client.get("/catalog/?availability=in_stock&page=2&gclid=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith("/catalog/in-stock/")
    assert "page=2" in location
    assert "gclid=1" in location


@pytest.mark.django_db
def test_catalog_availability_redirects_with_gclid(client):
    response = client.get("/catalog/?availability=in_stock&gclid=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.startswith("/catalog/in-stock/")
    assert "gclid=1" in location


@pytest.mark.django_db
def test_product_faq_questions_not_duplicated(client):
    product = ProductFactory(model_name_ru="Test Model")
    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    content = re.sub(
        r'<script[^>]+application/ld\+json[^>]*>.*?</script>',
        "",
        content,
        flags=re.DOTALL,
    )
    assert response.status_code == 200
    assert content.count("Какие сроки поставки?") == 1
    assert content.count("Какие варианты оплаты") == 1


@pytest.mark.django_db
def test_product_faq_not_duplicated_visible_html(client):
    product = ProductFactory(model_name_ru="Test Model")
    response = client.get(product.get_absolute_url())
    content = response.content.decode("utf-8")
    content = re.sub(
        r'<script[^>]+application/ld\+json[^>]*>.*?</script>',
        "",
        content,
        flags=re.DOTALL,
    )
    assert response.status_code == 200
    assert content.count("Какие сроки поставки?") == 1


@pytest.mark.django_db
def test_catalog_footer_addresses_have_labels(client):
    for path in ("/catalog/", "/contacts/"):
        response = client.get(path)
        content = response.content.decode("utf-8")
        assert response.status_code == 200
        assert "Офис (МО)" in content
        assert "Саратов" in content


@pytest.mark.django_db
def test_footer_address_labels_present(client):
    response = client.get("/catalog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "Офис (МО)" in content
    assert "Саратов" in content


@pytest.mark.django_db
def test_header_max_label_not_duplicated(client):
    response = client.get("/catalog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "MAX MAX" not in content


@pytest.mark.django_db
def test_max_not_duplicated(client):
    response = client.get("/catalog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "MAX MAX" not in content


@pytest.mark.django_db
def test_catalog_listing_removes_space_before_comma(client):
    product = ProductFactory(model_name_ru="SX32488L344C , 6×4")
    list_response = client.get("/catalog/")
    list_content = list_response.content.decode("utf-8")
    assert list_response.status_code == 200
    assert "SX32488L344C , 6×4" not in list_content
    assert "SX32488L344C, 6×4" in list_content

    detail_response = client.get(product.get_absolute_url())
    detail_content = detail_response.content.decode("utf-8")
    detail_content = re.sub(
        r'<script[^>]+application/ld\+json[^>]*>.*?</script>',
        "",
        detail_content,
        flags=re.DOTALL,
    )
    assert detail_response.status_code == 200
    assert "SX32488L344C , 6×4" not in detail_content
    assert "SX32488L344C, 6×4" in detail_content


@pytest.mark.django_db
def test_no_space_before_comma_in_listing(client):
    ProductFactory(model_name_ru="SX32488L344C , 6×4")
    response = client.get("/catalog/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "SX32488L344C , 6×4" not in content


@pytest.mark.django_db
def test_in_stock_page_indexable_and_canonical(client):
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/in-stock/"


@pytest.mark.django_db
def test_in_stock_page2_indexable(client):
    response = client.get("/catalog/in-stock/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/in-stock/?page=2"


@pytest.mark.django_db
def test_in_stock_page_utm_noindex(client):
    response = client.get("/catalog/in-stock/?utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    assert _extract_canonical(content) == "https://carfst.ru/catalog/in-stock/"


@pytest.mark.django_db
def test_catalog_series_category_seo_content(client):
    """Test that SeriesCategorySEO description and FAQ are displayed on series+category landing page."""
    from catalog.models import SeriesCategorySEO
    
    series = SeriesFactory(slug="test-series-seo", name="Test Series")
    category = CategoryFactory(slug="test-category-seo", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    # Create SEO content
    seo_obj = SeriesCategorySEO.objects.create(
        series=series,
        category=category,
        seo_description="Test description for series+category landing page.",
        seo_faq="What is this?|This is a test FAQ answer.\nHow does it work?|It works perfectly.",
    )
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    # Check that description is present
    assert "Test description for series+category landing page." in content
    
    # Check that FAQ items are present
    assert "What is this?" in content
    assert "This is a test FAQ answer." in content
    assert "How does it work?" in content
    assert "It works perfectly." in content


def _extract_json_ld(content: str):
    """Extract JSON-LD schemas from HTML content."""
    import html
    import json
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
def test_catalog_series_faq_schema_indexable(client):
    """Test that FAQPage schema is present on indexable catalog_series page."""
    series = SeriesFactory(slug="series-faq-test", name="Test Series")
    series.seo_faq = "Question 1?|Answer 1.\nQuestion 2?|Answer 2."
    series.save()
    
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1
    assert len(faq_schemas[0]["mainEntity"]) == 2


@pytest.mark.django_db
def test_catalog_series_faq_schema_page2_absent(client):
    """Test that FAQPage schema is absent on page=2."""
    series = SeriesFactory(slug="series-faq-test-2", name="Test Series")
    series.seo_faq = "Question?|Answer."
    series.save()
    
    response = client.get(f"/catalog/series/{series.slug}/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0


@pytest.mark.django_db
def test_catalog_series_faq_schema_utm_absent(client):
    """Test that FAQPage schema is absent with utm params."""
    series = SeriesFactory(slug="series-faq-test-3", name="Test Series")
    series.seo_faq = "Question?|Answer."
    series.save()
    
    response = client.get(f"/catalog/series/{series.slug}/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0


@pytest.mark.django_db
def test_catalog_category_faq_schema_indexable(client):
    """Test that FAQPage schema is present on indexable catalog_category page."""
    category = CategoryFactory(slug="category-faq-test", name="Test Category")
    category.seo_faq = "Question 1?|Answer 1."
    category.save()
    
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1


@pytest.mark.django_db
def test_catalog_category_faq_schema_page2_absent(client):
    """Test that FAQPage schema is absent on page=2."""
    category = CategoryFactory(slug="category-faq-test-2", name="Test Category")
    category.seo_faq = "Question?|Answer."
    category.save()
    
    response = client.get(f"/catalog/category/{category.slug}/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0


@pytest.mark.django_db
def test_catalog_series_category_faq_schema_indexable(client):
    """Test that FAQPage schema is present on indexable catalog_series_category page."""
    from catalog.models import SeriesCategorySEO
    
    series = SeriesFactory(slug="series-faq-sc-test", name="Test Series")
    category = CategoryFactory(slug="category-faq-sc-test", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    seo_obj = SeriesCategorySEO.objects.create(
        series=series,
        category=category,
        seo_faq="Question?|Answer.",
    )
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1


@pytest.mark.django_db
def test_catalog_in_stock_faq_schema_indexable(client):
    """Test that FAQPage schema is present on indexable catalog_in_stock page."""
    from catalog.models import SiteSettings
    
    site_settings = SiteSettings.get_solo()
    site_settings.in_stock_seo_faq = "Question 1?|Answer 1.\nQuestion 2?|Answer 2."
    site_settings.save()
    
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1
    assert len(faq_schemas[0]["mainEntity"]) == 2


@pytest.mark.django_db
def test_catalog_in_stock_faq_schema_page2_absent(client):
    """Test that FAQPage schema is absent on page=2."""
    from catalog.models import SiteSettings
    
    site_settings = SiteSettings.get_solo()
    site_settings.in_stock_seo_faq = "Question?|Answer."
    site_settings.save()
    
    response = client.get("/catalog/in-stock/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0


@pytest.mark.django_db
def test_catalog_in_stock_faq_schema_utm_absent(client):
    """Test that FAQPage schema is absent with utm params."""
    from catalog.models import SiteSettings
    
    site_settings = SiteSettings.get_solo()
    site_settings.in_stock_seo_faq = "Question?|Answer."
    site_settings.save()
    
    response = client.get("/catalog/in-stock/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0


@pytest.mark.django_db
def test_catalog_series_itemlist_schema_indexable(client):
    """Test that ItemList schema is present on indexable catalog_series page."""
    series = SeriesFactory(slug="series-itemlist-test", name="Test Series")
    products = [ProductFactory(series=series, published=True, is_active=True) for _ in range(5)]
    
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1
    assert len(itemlist_schemas[0]["itemListElement"]) >= 1


@pytest.mark.django_db
def test_catalog_series_itemlist_schema_page2_absent(client):
    """Test that ItemList schema is absent on page=2."""
    series = SeriesFactory(slug="series-itemlist-test-2", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 0


@pytest.mark.django_db
def test_catalog_series_itemlist_schema_utm_absent(client):
    """Test that ItemList schema is absent with utm params."""
    series = SeriesFactory(slug="series-itemlist-test-3", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 0


@pytest.mark.django_db
def test_catalog_category_itemlist_schema_indexable(client):
    """Test that ItemList schema is present on indexable catalog_category page."""
    category = CategoryFactory(slug="category-itemlist-test", name="Test Category")
    products = [ProductFactory(category=category, published=True, is_active=True) for _ in range(5)]
    
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1


@pytest.mark.django_db
def test_catalog_series_category_itemlist_schema_indexable(client):
    """Test that ItemList schema is present on indexable catalog_series_category page."""
    series = SeriesFactory(slug="series-itemlist-sc-test", name="Test Series")
    category = CategoryFactory(slug="category-itemlist-sc-test", name="Test Category")
    products = [ProductFactory(series=series, category=category, published=True, is_active=True) for _ in range(5)]
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1


@pytest.mark.django_db
def test_catalog_in_stock_itemlist_schema_indexable(client):
    """Test that ItemList schema is present on indexable catalog_in_stock page."""
    products = [ProductFactory(published=True, is_active=True) for _ in range(5)]
    
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1


@pytest.mark.django_db
def test_catalog_in_stock_itemlist_schema_utm_absent(client):
    """Test that ItemList schema is absent with utm params."""
    ProductFactory(published=True, is_active=True)
    
    response = client.get("/catalog/in-stock/?utm_source=x")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 0


@pytest.mark.django_db
def test_catalog_in_stock_has_both_schemas_when_faq_present(client):
    """Test that both FAQPage and ItemList schemas are present on indexable /catalog/in-stock/ when FAQ is set."""
    from catalog.models import City, Offer, SiteSettings
    
    # Create products with offers so they appear in /catalog/in-stock/ (total_qty > 0)
    products = [ProductFactory(published=True, is_active=True) for _ in range(3)]
    city, _ = City.objects.get_or_create(slug="msk", defaults={"name": "Москва", "sort_order": 0})
    for product in products:
        Offer.objects.get_or_create(
            product=product,
            city=city,
            defaults={"qty": 1, "is_active": True},
        )
    
    # Set FAQ in SiteSettings
    site_settings = SiteSettings.get_solo()
    site_settings.in_stock_seo_faq = "Question 1?|Answer 1.\nQuestion 2?|Answer 2."
    site_settings.save()
    
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    
    # Check FAQPage
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1, "FAQPage schema should be present"
    
    # Check ItemList
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1, "ItemList schema should be present"
    assert len(itemlist_schemas[0]["itemListElement"]) > 0, "ItemList should contain products"


@pytest.mark.django_db
def test_catalog_in_stock_itemlist_without_faq(client):
    """Test that ItemList schema is present even without FAQ on indexable /catalog/in-stock/."""
    from catalog.models import City, Offer

    # Create products with offers so they appear in /catalog/in-stock/ (total_qty > 0)
    products = [ProductFactory(published=True, is_active=True) for _ in range(3)]
    city, _ = City.objects.get_or_create(slug="msk", defaults={"name": "Москва", "sort_order": 0})
    for product in products:
        Offer.objects.get_or_create(
            product=product,
            city=city,
            defaults={"qty": 1, "is_active": True},
        )

    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    
    schemas = _extract_json_ld(content)
    
    # Check ItemList (should be present)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 1, "ItemList schema should be present even without FAQ"
    
    # Check FAQPage (should be absent if no FAQ)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 0, "FAQPage should be absent when no FAQ is set"


@pytest.mark.django_db
def test_catalog_in_stock_json_ld_valid(client):
    """Test that JSON-LD in base.html is valid when page_schema_payload is present."""
    import json
    from catalog.models import SiteSettings
    
    # Create products
    products = [ProductFactory(published=True, is_active=True) for _ in range(3)]
    
    # Set FAQ in SiteSettings
    site_settings = SiteSettings.get_solo()
    site_settings.in_stock_seo_faq = "Question 1?|Answer 1.\nQuestion 2?|Answer 2."
    site_settings.save()
    
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    
    # Extract JSON-LD script
    import re
    scripts = re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        content,
        flags=re.DOTALL,
    )
    assert len(scripts) > 0, "JSON-LD script should be present"
    
    # Parse JSON-LD (should be valid JSON array)
    for script in scripts:
        try:
            data = json.loads(html.unescape(script.strip()))
            assert isinstance(data, list), "JSON-LD should be an array"
            assert len(data) >= 2, "JSON-LD should contain at least Organization and WebSite"
            # Check that all items are valid schema objects
            for item in data:
                assert isinstance(item, dict), "Each schema item should be a dict"
                assert "@type" in item, "Each schema item should have @type"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON-LD: {e}\nScript content: {script[:500]}")


@pytest.mark.django_db
def test_catalog_in_stock_faq_format_examples(client):
    """Test that _parse_seo_faq correctly parses FAQ format examples."""
    from catalog.models import SiteSettings
    from catalog.views import _parse_seo_faq
    
    site_settings = SiteSettings.get_solo()
    
    # Example 1: Simple Q|A pairs
    site_settings.in_stock_seo_faq = "Какие сроки поставки?|Сроки зависят от наличия техники.\nКакие варианты оплаты?|Работаем с различными вариантами оплаты."
    site_settings.save()
    
    faq_items = _parse_seo_faq(site_settings.in_stock_seo_faq)
    assert len(faq_items) == 2
    assert faq_items[0]["question"] == "Какие сроки поставки?"
    assert faq_items[0]["answer"] == "Сроки зависят от наличия техники."
    
    # Example 2: With empty lines and extra spaces
    site_settings.in_stock_seo_faq = "Вопрос 1?|Ответ 1.\n\nВопрос 2?|Ответ 2."
    site_settings.save()
    
    faq_items = _parse_seo_faq(site_settings.in_stock_seo_faq)
    assert len(faq_items) == 2
    
    # Example 3: Single Q|A
    site_settings.in_stock_seo_faq = "Как оформить заказ?|Заполните форму на сайте или свяжитесь с нами."
    site_settings.save()
    
    faq_items = _parse_seo_faq(site_settings.in_stock_seo_faq)
    assert len(faq_items) == 1
    assert faq_items[0]["question"] == "Как оформить заказ?"
    
    # Verify FAQ appears on page
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    schemas = _extract_json_ld(content)
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    assert len(faq_schemas) == 1


@pytest.mark.django_db
def test_catalog_in_stock_page1_redirects(client):
    """Test that /catalog/in-stock/?page=1 redirects to /catalog/in-stock/."""
    response = client.get("/catalog/in-stock/?page=1")
    assert response.status_code in (301, 302), f"Expected redirect, got {response.status_code}"
    location = response.headers.get("Location", "")
    assert location.endswith("/catalog/in-stock/"), f"Expected redirect to /catalog/in-stock/, got {location}"


@pytest.mark.django_db
def test_catalog_in_stock_page_invalid_no_schema(client):
    """Test that /catalog/in-stock/?page=abc has noindex and NO schema."""
    products = [ProductFactory(published=True, is_active=True) for _ in range(3)]
    
    response = client.get("/catalog/in-stock/?page=abc")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    # Should NOT have ItemList, FAQPage, or BreadcrumbList
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    faq_schemas = [s for s in schemas if s.get("@type") == "FAQPage"]
    breadcrumb_schemas = [s for s in schemas if s.get("@type") == "BreadcrumbList"]
    
    assert len(itemlist_schemas) == 0, "ItemList should be absent for invalid page param"
    assert len(faq_schemas) == 0, "FAQPage should be absent for invalid page param"
    assert len(breadcrumb_schemas) == 0, "BreadcrumbList should be absent for invalid page param"


@pytest.mark.django_db
def test_catalog_series_page1_redirects(client):
    """Test that /catalog/series/<slug>/?page=1 redirects to clean URL."""
    series = SeriesFactory(slug="series-page1-test", name="Test Series")
    response = client.get(f"/catalog/series/{series.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/")


@pytest.mark.django_db
def test_catalog_series_page_invalid_no_schema(client):
    """Test that /catalog/series/<slug>/?page=abc has noindex and NO schema."""
    series = SeriesFactory(slug="series-invalid-test", name="Test Series")
    ProductFactory(series=series, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/?page=abc")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    breadcrumb_schemas = [s for s in schemas if s.get("@type") == "BreadcrumbList"]
    
    assert len(itemlist_schemas) == 0, "ItemList should be absent for invalid page param"
    assert len(breadcrumb_schemas) == 0, "BreadcrumbList should be absent for invalid page param"


@pytest.mark.django_db
def test_catalog_category_page1_redirects(client):
    """Test that /catalog/category/<slug>/?page=1 redirects to clean URL."""
    category = CategoryFactory(slug="category-page1-test", name="Test Category")
    response = client.get(f"/catalog/category/{category.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/category/{category.slug}/")


@pytest.mark.django_db
def test_catalog_category_page_invalid_no_schema(client):
    """Test that /catalog/category/<slug>/?page=abc has noindex and NO schema."""
    category = CategoryFactory(slug="category-invalid-test", name="Test Category")
    ProductFactory(category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/category/{category.slug}/?page=abc")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    breadcrumb_schemas = [s for s in schemas if s.get("@type") == "BreadcrumbList"]
    
    assert len(itemlist_schemas) == 0, "ItemList should be absent for invalid page param"
    assert len(breadcrumb_schemas) == 0, "BreadcrumbList should be absent for invalid page param"


@pytest.mark.django_db
def test_catalog_series_category_page1_redirects(client):
    """Test that /catalog/series/<series>/<category>/?page=1 redirects to clean URL."""
    series = SeriesFactory(slug="series-sc-page1", name="Test Series")
    category = CategoryFactory(slug="category-sc-page1", name="Test Category")
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith(f"/catalog/series/{series.slug}/{category.slug}/")


@pytest.mark.django_db
def test_catalog_series_category_page_invalid_no_schema(client):
    """Test that /catalog/series/<series>/<category>/?page=abc has noindex and NO schema."""
    series = SeriesFactory(slug="series-sc-invalid", name="Test Series")
    category = CategoryFactory(slug="category-sc-invalid", name="Test Category")
    ProductFactory(series=series, category=category, published=True, is_active=True)
    
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/?page=abc")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in content
    
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    breadcrumb_schemas = [s for s in schemas if s.get("@type") == "BreadcrumbList"]
    
    assert len(itemlist_schemas) == 0, "ItemList should be absent for invalid page param"
    assert len(breadcrumb_schemas) == 0, "BreadcrumbList should be absent for invalid page param"


@pytest.mark.django_db
def test_catalog_in_stock_page1_no_schema(client):
    """Test that /catalog/in-stock/?page=1 does NOT have schema (should redirect, but if not - no schema)."""
    products = [ProductFactory(published=True, is_active=True) for _ in range(3)]
    
    # First check redirect
    response = client.get("/catalog/in-stock/?page=1", follow=False)
    if response.status_code in (301, 302):
        # Redirect works - good
        return
    
    # If no redirect (shouldn't happen, but test anyway)
    content = response.content.decode("utf-8")
    schemas = _extract_json_ld(content)
    itemlist_schemas = [s for s in schemas if s.get("@type") == "ItemList"]
    assert len(itemlist_schemas) == 0, "ItemList should be absent for ?page=1"


@pytest.mark.django_db
def test_all_landing_pages_indexable_have_schema(client):
    """Test that all indexable landing pages have ItemList and BreadcrumbList schemas."""
    series = SeriesFactory(slug="test-series-schema", name="Test Series")
    category = CategoryFactory(slug="test-category-schema", name="Test Category")
    products = [ProductFactory(series=series, category=category, published=True, is_active=True) for _ in range(3)]
    
    # Test catalog_series
    response = client.get(f"/catalog/series/{series.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    schemas = _extract_json_ld(content)
    assert any(s.get("@type") == "ItemList" for s in schemas), "catalog_series should have ItemList"
    assert any(s.get("@type") == "BreadcrumbList" for s in schemas), "catalog_series should have BreadcrumbList"
    
    # Test catalog_category
    response = client.get(f"/catalog/category/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    schemas = _extract_json_ld(content)
    assert any(s.get("@type") == "ItemList" for s in schemas), "catalog_category should have ItemList"
    assert any(s.get("@type") == "BreadcrumbList" for s in schemas), "catalog_category should have BreadcrumbList"
    
    # Test catalog_series_category
    response = client.get(f"/catalog/series/{series.slug}/{category.slug}/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    schemas = _extract_json_ld(content)
    assert any(s.get("@type") == "ItemList" for s in schemas), "catalog_series_category should have ItemList"
    assert any(s.get("@type") == "BreadcrumbList" for s in schemas), "catalog_series_category should have BreadcrumbList"
    
    # Test catalog_in_stock
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert 'name="robots" content="index, follow"' in content
    schemas = _extract_json_ld(content)
    assert any(s.get("@type") == "ItemList" for s in schemas), "catalog_in_stock should have ItemList"
    assert any(s.get("@type") == "BreadcrumbList" for s in schemas), "catalog_in_stock should have BreadcrumbList"


@pytest.mark.django_db
def test_product_detail_no_schema_with_get_params(client):
    """Test that product detail page does not include Product/BreadcrumbList/FAQPage schema when GET params are present."""
    product = ProductFactory(published=True, is_active=True)
    response = client.get(f"{product.get_absolute_url()}?utm_source=test")
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
        assert '"@type": "Product"' not in block
        assert '"@type": "BreadcrumbList"' not in block
        assert '"@type": "FAQPage"' not in block


@pytest.mark.django_db
def test_news_page_no_schema_with_get_params(client):
    """Test that news page does not include ItemList schema when GET params are present."""
    response = client.get("/news/?utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
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
        assert '"@type": "ItemList"' not in block


@pytest.mark.django_db
def test_canonical_always_clean_from_context_processor(client):
    """Test that canonical URL from context processor is always clean (no querystring).
    
    Policy: context processor always provides clean canonical without querystring.
    Views can override canonical for self-canonical (e.g., catalog_in_stock with ?page=N).
    """
    # Test 1: utm/gclid should be excluded
    response = client.get("/contacts/?utm_source=test&gclid=123")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    # Canonical should not contain utm/gclid
    assert "utm_source" not in canonical
    assert "gclid" not in canonical
    # Should be clean URL (no query)
    assert canonical == "https://carfst.ru/contacts/"
    
    # Test 2: page>1 should be clean canonical (context processor policy)
    # Note: views can override canonical for self-canonical if needed
    response = client.get("/contacts/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    # Context processor provides clean canonical (no query)
    assert canonical == "https://carfst.ru/contacts/"
    
    # Test 3: page=1 should be clean (no query)
    response = client.get("/contacts/?page=1")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    # Should be clean canonical
    assert canonical == "https://carfst.ru/contacts/"
    
    # Test 4: mixed params (page + utm) -> clean canonical
    response = client.get("/contacts/?page=2&utm_source=test")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    # Mixed params should result in clean canonical (no query)
    assert "utm_source" not in canonical
    assert "page" not in canonical
    assert canonical == "https://carfst.ru/contacts/"


@pytest.mark.django_db
def test_catalog_in_stock_self_canonical_preserved(client):
    """Test that catalog_in_stock view preserves self-canonical with ?page=N (view overrides context processor)."""
    # Create products for pagination
    products = [ProductFactory(published=True, is_active=True) for _ in range(15)]
    
    # Test: page=2 should have self-canonical
    response = client.get("/catalog/in-stock/?page=2")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    # View should override context processor and provide self-canonical
    assert canonical == "https://carfst.ru/catalog/in-stock/?page=2"
    
    # Test: clean URL should have clean canonical
    response = client.get("/catalog/in-stock/")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    canonical = _extract_canonical(content)
    assert canonical == "https://carfst.ru/catalog/in-stock/"


@pytest.mark.django_db
def test_catalog_in_stock_has_seo_zone(client):
    """GET /catalog/in-stock/ (clean) must contain id='catalog-in-stock-seo-zone'."""
    response = client.get("/catalog/in-stock/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'id="catalog-in-stock-seo-zone"' in content


@pytest.mark.django_db
def test_catalog_in_stock_uses_catalog_landing_seo(client):
    """Test that CatalogLandingSEO overrides meta and provides intro/body."""
    from catalog.models import CatalogLandingSEO

    seo = CatalogLandingSEO.objects.create(
        landing_key=CatalogLandingSEO.LandingKey.CATALOG_IN_STOCK,
        meta_title="Custom Title — CARFAST",
        meta_description="Custom meta description.",
        seo_intro_html="<p>Custom intro text.</p>",
        seo_body_html="<p>Custom body text.</p>",
        faq_items="Custom Q?|Custom A.",
    )

    response = client.get("/catalog/in-stock/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Custom Title — CARFAST" in content
    assert "Custom meta description" in content
    assert "Custom intro text" in content
    assert "Custom body text" in content
    assert "Custom Q?" in content
    assert "Custom A." in content


@pytest.mark.django_db
def test_catalog_in_stock_no_json_ld_with_utm(client):
    """Test that /catalog/in-stock/?utm_source=test has no application/ld+json (schema only on clean)."""
    response = client.get("/catalog/in-stock/?utm_source=test")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "application/ld+json" not in content


@pytest.mark.django_db
def test_catalog_in_stock_has_quick_nav_links(client):
    """Test that /catalog/in-stock/ contains quick nav links to clean URLs."""
    from catalog.models import Category, Series

    Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": "", "history": ""}
    )
    Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    Category.objects.get_or_create(slug="sedelnye-tyagachi", defaults={"name": "Седельные тягачи"})

    response = client.get("/catalog/in-stock/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "/catalog/series/shacman/" in content
    assert "/catalog/category/samosvaly/" in content
    assert "/catalog/series/shacman/samosvaly/" in content
