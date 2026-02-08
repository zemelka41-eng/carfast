"""Tests for /shacman/* SEO hubs: 200, canonical, robots, pagination, sitemap."""
import re
import sys

import pytest
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import resolve, reverse

from catalog.models import Category, City, ModelVariant, Offer, Series
from catalog.views import (
    SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY,
    SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2,
)
from tests.factories import CategoryFactory, ModelVariantFactory, ProductFactory, SeriesFactory


def _extract_canonical(content: str) -> str:
    match = re.search(r'rel="canonical" href="([^"]+)"', content)
    assert match, "canonical link not found"
    return match.group(1).replace("&amp;", "&")


@pytest.mark.django_db
def test_shacman_hub_returns_200(client):
    """GET /shacman/ must return 200 (even with empty list)."""
    response = client.get("/shacman/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    assert "text/html" in response.get("Content-Type", "")
    assert "SHACMAN" in content or "shacman" in content.lower()


@pytest.mark.django_db
def test_shacman_hub_canonical_clean(client):
    """GET /shacman/ (clean) has canonical without GET params."""
    SeriesFactory(slug="shacman", name="SHACMAN")
    response = client.get("/shacman/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical, f"Canonical must be clean: {canonical}"
    assert canonical.rstrip("/").endswith("/shacman")


@pytest.mark.django_db
def test_shacman_hub_page1_redirect(client):
    """GET /shacman/?page=1 redirects to clean /shacman/."""
    SeriesFactory(slug="shacman", name="SHACMAN")
    response = client.get("/shacman/?page=1")
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert location.endswith("/shacman/") and "page=" not in location


@pytest.mark.django_db
def test_shacman_hub_page2_noindex_self_canonical(client):
    """GET /shacman/?page=2 has noindex, follow and self-canonical (?page=2)."""
    SeriesFactory(slug="shacman", name="SHACMAN")
    response = client.get("/shacman/?page=2")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'name="robots" content="noindex, follow"' in content
    canonical = _extract_canonical(content)
    assert "page=2" in canonical, f"Expected self-canonical with ?page=2, got {canonical}"


def test_shacman_routes_registered():
    """resolve(/shacman/), /shacman/in-stock/, /shacman/line/x3000/ do not raise Resolver404."""
    resolve("/shacman/")
    resolve("/shacman/in-stock/")
    resolve("/shacman/line/x3000/")


@pytest.mark.django_db
def test_shacman_root_is_200(client):
    """GET /shacman/ returns 200 (even with empty stock)."""
    response = client.get("/shacman/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_shacman_root_200_via_request_factory():
    """resolve('/shacman/') and direct view call via RequestFactory return 200 (no test client)."""
    match = resolve("/shacman/")
    view_func = match.func
    request = RequestFactory().get("/shacman/")
    response = view_func(request)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"


@pytest.mark.django_db
@pytest.mark.skipif(sys.version_info >= (3, 14), reason="Django test client template context copy fails on Python 3.14")
def test_sitemap_view_returns_200(client):
    """sitemap view returns 200 and Content-Type xml (no 500)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content_type = response.get("Content-Type", "")
    assert "xml" in content_type.lower(), f"Expected xml Content-Type, got {content_type}"


@pytest.mark.django_db
def test_shacman_hub_sitemap_items_and_location_no_500():
    """ShacmanHubSitemap.items() and .location() do not raise (sitemap never 500 from shacman data)."""
    from catalog.sitemaps import ShacmanHubSitemap

    sitemap = ShacmanHubSitemap()
    items = sitemap.items()
    assert isinstance(items, list)
    for item in items[:5]:  # first 5 items
        url = sitemap.location(item)
        assert url and "/shacman" in url


@pytest.mark.django_db
def test_reverse_shacman_hub():
    """reverse('shacman_hub') resolves (no catalog namespace)."""
    url = reverse("shacman_hub")
    assert url == "/shacman/"


@pytest.mark.django_db
def test_sitemap_contains_shacman(client):
    """sitemap.xml includes /shacman/ (shacman_hubs section)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "/shacman/" in body, "Sitemap should include /shacman/"


@pytest.mark.django_db
def test_shacman_in_stock_returns_200(client):
    """GET /shacman/in-stock/ returns 200."""
    response = client.get("/shacman/in-stock/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_shacman_category_returns_200(client):
    """GET /shacman/<slug>/ returns 200 when category exists."""
    cat = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/shacman/{cat.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_shacman_category_404_unknown_slug(client):
    """GET /shacman/unknown-cat/ returns 404."""
    response = client.get("/shacman/unknown-cat/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_shacman_category_in_stock_returns_200(client):
    """GET /shacman/<slug>/in-stock/ returns 200 when category exists."""
    cat = CategoryFactory(slug="samosvaly", name="Самосвалы")
    response = client.get(f"/shacman/{cat.slug}/in-stock/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_shacman_hub_no_schema(client):
    """SHACMAN hubs must not output Product/BreadcrumbList/FAQPage schema (SEO invariant)."""
    SeriesFactory(slug="shacman", name="SHACMAN")
    for path in ["/shacman/", "/shacman/in-stock/"]:
        response = client.get(path)
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert '"@type":"Product"' not in content.replace(" ", "")
        assert '"@type":"BreadcrumbList"' not in content.replace(" ", "")
        assert '"@type":"FAQPage"' not in content.replace(" ", "")


@pytest.mark.django_db
def test_shacman_formula_hub_200_canonical_clean(client):
    """B3 hub /shacman/formula/<formula>/ returns 200 and canonical without query (when >=2 products)."""
    series = SeriesFactory(slug="shacman", name="SHACMAN")
    cat = CategoryFactory(slug="samosvaly", name="Самосвалы")
    ProductFactory(series=series, category=cat, wheel_formula="6x4", published=True, is_active=True)
    ProductFactory(series=series, category=cat, wheel_formula="6x4", published=True, is_active=True)

    response = client.get("/shacman/formula/6x4/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert canonical.rstrip("/").endswith("/shacman/formula/6x4")


@pytest.mark.django_db
def test_shacman_engine_hub_200_canonical_clean(client):
    """B3 hub /shacman/engine/wp13-550e501/ returns 200 and canonical clean (>=2 products)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )

    response = client.get("/shacman/engine/wp13-550e501/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert canonical.rstrip("/").endswith("/shacman/engine/wp13-550e501")


@pytest.mark.django_db
def test_shacman_line_hub_200_canonical_clean(client):
    """B3 hub /shacman/line/x3000/ returns 200 and canonical clean (>=2 products with line X3000)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv, published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv, published=True, is_active=True
    )

    response = client.get("/shacman/line/x3000/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert canonical.rstrip("/").endswith("/shacman/line/x3000")


@pytest.mark.django_db
def test_shacman_engine_hub_404_single_product(client):
    """B3 hub /shacman/engine/wp10-336e53/ returns 404 when only 1 product (threshold >=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP10.336E53", published=True, is_active=True
    )

    response = client.get("/shacman/engine/wp10-336e53/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_shacman_engine_line_hub_200_with_legacy_cache_format(client):
    """
    With legacy cache format (engine_slugs/line_slugs as list of tuples), engine and line hubs
    return 200; single-engine hub returns 404. Simulates prod cache before v2 migration.
    """
    # Clear v2 so we hit legacy path when we set legacy
    cache.delete(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2)
    legacy = {
        "engine_slugs": [("wp13-550e501", "WP13.550E501")],
        "line_slugs": [("x3000", "X3000")],
        "series_slugs": [("x3000", "X3000")],
        "formulas": ["6x4"],
    }
    cache.set(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY, legacy, 300)

    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(
        slug="samosvaly", defaults={"name": "Самосвалы"}
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv, published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv, published=True, is_active=True
    )

    r_engine = client.get("/shacman/engine/wp13-550e501/")
    assert r_engine.status_code == 200, f"Expected 200, got {r_engine.status_code}"

    r_line = client.get("/shacman/line/x3000/")
    assert r_line.status_code == 200, f"Expected 200, got {r_line.status_code}"

    r_single = client.get("/shacman/engine/wp10-336e53/")
    assert r_single.status_code == 404

    cache.delete(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY)
    cache.delete(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2)


# --- Combo hubs: /shacman/line/<line_slug>/<category_slug>/ and +/<formula>/ + in-stock ---


@pytest.mark.django_db
def test_shacman_combo_allowed_from_db_returns_named_structure():
    """_shacman_combo_allowed_from_db() returns named structure (ShacmanComboAllowed), not tuple — use .lc/.lcf."""
    from catalog.views import _shacman_combo_allowed_from_db, ShacmanComboAllowed

    allowed = _shacman_combo_allowed_from_db()
    assert not isinstance(allowed, tuple), "API must not be a raw tuple to avoid 'key in allowed' false False"
    assert hasattr(allowed, "lc"), "API must have .lc"
    assert hasattr(allowed, "lcf"), "API must have .lcf"
    assert isinstance(allowed, ShacmanComboAllowed)
    assert isinstance(allowed.lc, set)
    assert isinstance(allowed.lcf, set)


@pytest.mark.django_db
def test_combo_hub_200_when_two_products(client):
    """Combo /shacman/line/<line>/<category>/ returns 200 when >=2 products, canonical clean."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x3000/samosvaly/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert canonical.rstrip("/").endswith("/shacman/line/x3000/samosvaly")


@pytest.mark.django_db
def test_combo_hub_404_when_one_product(client):
    """Combo /shacman/line/<line>/<category>/ returns 404 when only 1 product (threshold >=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="tyagachi", defaults={"name": "Тягачи"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X6000 6x4",
        defaults={"slug": "x6000-6x4", "line": "X6000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x6000/tyagachi/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_combo_hub_page2_noindex_self_canonical(client):
    """Combo hub ?page=2 has noindex, follow and self-canonical (?page=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    for _ in range(3):
        ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x3000/samosvaly/?page=2")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'name="robots" content="noindex, follow"' in content
    canonical = _extract_canonical(content)
    assert "page=2" in canonical


@pytest.mark.django_db
def test_combo_hub_no_schema_with_get(client):
    """Combo hub URL with GET params must not output page-level schema (SEO invariant)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x3000/samosvaly/?utm_source=test")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert '"@type":"Product"' not in content.replace(" ", "")
    assert '"@type":"FAQPage"' not in content.replace(" ", "")


# --- Line+engine hubs: /shacman/line/<line_slug>/engine/<engine_slug>/ ---


@pytest.mark.django_db
def test_shacman_line_engine_allowed_from_db_returns_set():
    """_shacman_line_engine_allowed_from_db() returns set of (line_slug, engine_slug), cap 50."""
    from catalog.views import _shacman_line_engine_allowed_from_db

    allowed = _shacman_line_engine_allowed_from_db()
    assert isinstance(allowed, set)
    for item in allowed:
        assert isinstance(item, tuple), "Each item must be (line_slug, engine_slug)"
        assert len(item) == 2
        assert isinstance(item[0], str) and isinstance(item[1], str)


@pytest.mark.django_db
def test_line_engine_hub_200_when_two_products(client):
    """Line+engine /shacman/line/<line>/engine/<engine>/ returns 200 when >=2 products, canonical clean."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    for _ in range(2):
        ProductFactory(
            series=series, category=cat, model_variant=mv,
            engine_model="WP13.550E501", published=True, is_active=True,
        )

    response = client.get("/shacman/line/x3000/engine/wp13-550e501/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert "/shacman/line/x3000/engine/wp13-550e501" in canonical


@pytest.mark.django_db
def test_line_engine_hub_404_when_one_product(client):
    """Line+engine hub returns 404 when only 1 product (threshold >=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X6000 6x4",
        defaults={"slug": "x6000-6x4", "line": "X6000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv,
        engine_model="WP10.336E53", published=True, is_active=True,
    )

    response = client.get("/shacman/line/x6000/engine/wp10-336e53/")
    assert response.status_code == 404


# --- Category+formula hubs: /shacman/<category_slug>/<formula>/ ---


@pytest.mark.django_db
def test_shacman_category_formula_allowed_from_db_returns_set():
    """_shacman_category_formula_allowed_from_db() returns set of (category_slug, formula), cap 50."""
    from catalog.views import _shacman_category_formula_allowed_from_db

    allowed = _shacman_category_formula_allowed_from_db()
    assert isinstance(allowed, set)
    for item in allowed:
        assert isinstance(item, tuple), "Each item must be (category_slug, formula)"
        assert len(item) == 2
        assert isinstance(item[0], str) and isinstance(item[1], str)


@pytest.mark.django_db
def test_category_formula_hub_200_when_two_products(client):
    """Category+formula /shacman/<category>/<formula>/ returns 200 when >=2 products, canonical clean."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    for _ in range(2):
        ProductFactory(
            series=series, category=cat, model_variant=mv,
            wheel_formula="6x4", published=True, is_active=True,
        )

    response = client.get("/shacman/samosvaly/6x4/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert "/shacman/samosvaly/6x4" in canonical


@pytest.mark.django_db
def test_category_formula_hub_404_when_one_product(client):
    """Category+formula hub returns 404 when only 1 product (threshold >=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="tyagachi", defaults={"name": "Тягачи"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X6000 6x4",
        defaults={"slug": "x6000-6x4", "line": "X6000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(
        series=series, category=cat, model_variant=mv,
        wheel_formula="6x4", published=True, is_active=True,
    )

    response = client.get("/shacman/tyagachi/6x4/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_combo_hub_200_when_line_has_trailing_space(client):
    """Combo hub works when model_variant.line is stored with trailing space (e.g. 'X3000 ')."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        slug="x3000-6x4-space",
        defaults={"name": "X3000 6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    mv.line = "X3000 "
    mv.save(update_fields=["line"])
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x3000/samosvaly/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert canonical.rstrip("/").endswith("/shacman/line/x3000/samosvaly")


# --- Series 301 to line (no cannibalization) ---


@pytest.mark.django_db
def test_series_hub_301_redirects_to_line(client):
    """GET /shacman/series/<slug>/ returns 301 to /shacman/line/<slug>/ (canonical)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/series/x3000/")
    assert response.status_code == 301
    assert response["Location"].endswith("/shacman/line/x3000/")


@pytest.mark.django_db
def test_series_in_stock_hub_301_redirects_to_line(client):
    """GET /shacman/series/<slug>/in-stock/ returns 301 to /shacman/line/<slug>/in-stock/."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/series/x3000/in-stock/")
    assert response.status_code == 301
    assert response["Location"].endswith("/shacman/line/x3000/in-stock/")


@pytest.mark.django_db
def test_sitemap_no_series_urls(client):
    """Sitemap must not include /shacman/series/ (canonical is /shacman/line/)."""
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "/shacman/series/" not in body, "Sitemap must not include series URLs (301 to line)"


# --- Engine+category hubs: /shacman/engine/<engine_slug>/<category_slug>/ ---


@pytest.mark.django_db
def test_engine_category_hub_200_when_two_products(client):
    """Engine+category hub returns 200 when >=2 products, canonical clean."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )

    response = client.get("/shacman/engine/wp13-550e501/samosvaly/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    content = response.content.decode("utf-8")
    canonical = _extract_canonical(content)
    assert "?" not in canonical
    assert "/shacman/engine/wp13-550e501/samosvaly" in canonical


@pytest.mark.django_db
def test_engine_category_hub_404_when_one_product(client):
    """Engine+category hub returns 404 when only 1 product (threshold >=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP10.336E53", published=True, is_active=True
    )

    response = client.get("/shacman/engine/wp10-336e53/samosvaly/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_engine_category_hub_page2_noindex_self_canonical(client):
    """Engine+category hub ?page=2 has noindex, follow and self-canonical (?page=2)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    for _ in range(3):
        ProductFactory(
            series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
        )

    response = client.get("/shacman/engine/wp13-550e501/samosvaly/?page=2")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'name="robots" content="noindex, follow"' in content
    canonical = _extract_canonical(content)
    assert "page=2" in canonical


@pytest.mark.django_db
def test_engine_category_hub_no_schema_with_get(client):
    """Engine+category URL with GET params must not output page-level schema (SEO invariant)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )

    response = client.get("/shacman/engine/wp13-550e501/samosvaly/?utm_source=test")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert '"@type":"Product"' not in content.replace(" ", "")
    assert '"@type":"FAQPage"' not in content.replace(" ", "")


@pytest.mark.django_db
def test_sitemap_includes_engine_category_hubs(client):
    """Sitemap includes engine+category hub URLs when count>=2 (shacman_engine_category_hubs section)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )
    ProductFactory(
        series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True
    )

    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "/shacman/engine/wp13-550e501/samosvaly/" in body


@pytest.mark.django_db
def test_sitemap_engine_in_stock_urls_do_not_404(client):
    """All <loc> in sitemap matching /shacman/engine/.+/in-stock/ must return 200 or 3xx (no 404)."""
    try:
        reverse("shacman_hub")
    except Exception:
        pytest.skip("shacman URLs not in urlconf (root shacman_patterns required)")
    response = client.get("/sitemap.xml")
    assert response.status_code == 200, f"Sitemap returned {response.status_code}"
    body = response.content.decode("utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", body)
    engine_in_stock_pattern = re.compile(r"https?://[^/]+/shacman/engine/[^/]+/in-stock/?")
    for url in locs:
        if not engine_in_stock_pattern.search(url):
            continue
        rest = url.replace("https://", "").replace("http://", "").split("/", 1)[-1].rstrip("/")
        path = "/" + rest + "/"
        resp = client.get(path)
        assert resp.status_code in (200, 301, 302), (
            f"Sitemap URL {url} (path {path}) must not return 404, got {resp.status_code}"
        )


@pytest.mark.django_db
def test_engine_in_stock_200_when_has_stock(client):
    """GET /shacman/engine/<engine_slug>/in-stock/ returns 200 when at least one product in stock."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    city, _ = City.objects.get_or_create(slug="msk", defaults={"name": "Москва", "sort_order": 0})
    p1 = ProductFactory(series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True)
    ProductFactory(series=series, category=cat, engine_model="WP13.550E501", published=True, is_active=True)
    Offer.objects.get_or_create(product=p1, city=city, defaults={"qty": 1, "is_active": True, "price": 100})

    response = client.get("/shacman/engine/wp13-550e501/in-stock/")
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.skipif(sys.version_info >= (3, 14), reason="Django test client template context copy fails on Python 3.14")
def test_engine_in_stock_200_when_get_engine_in_stock_qs_exists(client):
    """When get_engine_in_stock_qs(engine_slug).exists() is True, /shacman/engine/<slug>/in-stock/ returns 200."""
    from catalog.views import get_engine_in_stock_qs

    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    city, _ = City.objects.get_or_create(slug="msk", defaults={"name": "Москва", "sort_order": 0})
    p1 = ProductFactory(series=series, category=cat, engine_model="WP10.336E53", published=True, is_active=True)
    ProductFactory(series=series, category=cat, engine_model="WP10.336E53", published=True, is_active=True)
    Offer.objects.get_or_create(product=p1, city=city, defaults={"qty": 1, "is_active": True, "price": 100})

    slug = "wp10-336e53"
    assert get_engine_in_stock_qs(slug).exists(), "Precondition: get_engine_in_stock_qs(slug).exists() must be True"
    response = client.get(f"/shacman/engine/{slug}/in-stock/")
    assert response.status_code == 200, f"Expected 200 when get_engine_in_stock_qs({slug!r}).exists(), got {response.status_code}"


@pytest.mark.django_db
def test_engine_in_stock_404_when_no_stock(client):
    """GET /shacman/engine/<engine_slug>/in-stock/ returns 404 when no products in stock for that engine."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    ProductFactory(series=series, category=cat, engine_model="WP12.430E50", published=True, is_active=True)
    ProductFactory(series=series, category=cat, engine_model="WP12.430E50", published=True, is_active=True)
    # No offers → total_qty = 0 → in-stock hub must 404

    response = client.get("/shacman/engine/wp12-430e50/in-stock/")
    assert response.status_code == 404


# --- Meta generator and H1 per hub type ---


@pytest.mark.django_db
def test_build_shacman_hub_meta_different_per_type():
    """build_shacman_hub_meta returns different title/description/h1 per hub type."""
    from catalog.views import build_shacman_hub_meta

    brand = build_shacman_hub_meta("brand_root")
    line = build_shacman_hub_meta("line", line_label="X3000")
    engine = build_shacman_hub_meta("engine", engine_label="WP13.550E501")
    line_cat = build_shacman_hub_meta("line_category", line_label="X3000", category_name="Самосвалы")
    line_engine = build_shacman_hub_meta("line_engine", line_label="X3000", engine_label="WP13.550E501")
    line_engine_in_stock = build_shacman_hub_meta("line_engine_in_stock", line_label="X3000", engine_label="WP13.550E501")
    cat_formula = build_shacman_hub_meta("category_formula", category_name="Самосвалы", formula="6x4")
    cat_formula_in_stock = build_shacman_hub_meta("category_formula_in_stock", category_name="Самосвалы", formula="6x4")

    assert "SHACMAN" in brand["title"] and "купить" in brand["title"]
    assert brand["title"] != line["title"]
    assert line["title"] != engine["title"]
    assert "X3000" in line["title"] and "X3000" in line["h1"]
    assert "WP13.550E501" in engine["title"] and engine["h1"]
    assert "X3000" in line_cat["h1"] and "Самосвалы" in line_cat["h1"]
    assert "лизинг" in brand["description"] or "доставка" in brand["description"]
    assert "X3000" in line_engine["h1"] and "WP13.550E501" in line_engine["h1"]
    assert "в наличии" in line_engine_in_stock["h1"]
    assert "Самосвалы" in cat_formula["h1"] and "6x4" in cat_formula["h1"]
    assert "в наличии" in cat_formula_in_stock["h1"]


@pytest.mark.django_db
def test_shacman_hub_h1_contains_commercial_keywords(client):
    """Brand root /shacman/ has H1 with SHACMAN/Шакман and commercial keywords."""
    Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    response = client.get("/shacman/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "SHACMAN" in content or "Шакман" in content
    assert "купить" in content
    assert "<h1" in content and "</h1>" in content


@pytest.mark.django_db
def test_combo_hub_h1_contains_cluster(client):
    """Combo hub H1 contains line and category (precise cluster)."""
    series, _ = Series.objects.get_or_create(
        slug="shacman", defaults={"name": "SHACMAN", "description_ru": "", "description_en": ""}
    )
    cat, _ = Category.objects.get_or_create(slug="samosvaly", defaults={"name": "Самосвалы"})
    mv, _ = ModelVariant.objects.get_or_create(
        brand=series,
        name="X3000 6x4",
        defaults={"slug": "x3000-6x4", "line": "X3000", "wheel_formula": "6x4", "sort_order": 0},
    )
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)
    ProductFactory(series=series, category=cat, model_variant=mv, published=True, is_active=True)

    response = client.get("/shacman/line/x3000/samosvaly/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "X3000" in content or "x3000" in content
    assert "Самосвалы" in content or "samosvaly" in content
    assert "купить" in content
