from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap as django_sitemap
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from carfst_site.health import health_view
from carfst_site import views as site_views
from carfst_site.views import robots_txt_view

from blog.sitemaps import BlogIndexSitemap, BlogPostSitemap
from catalog.api import LeadCreateAPI, ProductDetailAPI, ProductListAPI
from catalog.sitemaps import (
    CategorySitemap,
    ProductSitemap,
    SeriesCategorySitemap,
    SeriesSitemap,
    ShacmanCategoryEngineSitemap,
    ShacmanCategoryFormulaSitemap,
    ShacmanCategoryLineFormulaSitemap,
    ShacmanCategoryLineSitemap,
    ShacmanHubSitemap,
    ShacmanLineFormulaSitemap,
    ShacmanModelCodeSitemap,
    StaticViewSitemap,
)
from catalog import views as catalog_views
from catalog.views import version_view

# Admin: use trailing slash so reverse() yields /admin/catalog/... (not /admincatalog/...)
ADMIN_PATH = (settings.ADMIN_URL or "admin/").rstrip("/") + "/"  # e.g. "admin/"

# /catalog/ root is not in sitemap; /catalog/series/*, /catalog/category/* landings are (StaticView has no catalog_list)
# Section keys must be URL-friendly (hyphens) for sitemap-<section>.xml routes.
sitemaps = {
    "products": ProductSitemap,
    "blog": BlogPostSitemap,
    "blog_index": BlogIndexSitemap,
    "series": SeriesSitemap,
    "categories": CategorySitemap,
    "series_categories": SeriesCategorySitemap,
    "shacman-hubs": ShacmanHubSitemap,
    "shacman-category-engine": ShacmanCategoryEngineSitemap,
    "shacman-category-line": ShacmanCategoryLineSitemap,
    "shacman-line-formula": ShacmanLineFormulaSitemap,
    "shacman-category-formula": ShacmanCategoryFormulaSitemap,
    "shacman-category-line-formula": ShacmanCategoryLineFormulaSitemap,
    "shacman-model-code": ShacmanModelCodeSitemap,
    "static": StaticViewSitemap,
}

# Django sitemap index uses reverse(sitemap_url_name, kwargs={"section": section}) -> /sitemap-<section>.xml
SITEMAP_SECTION_URL_NAME = "sitemap_section"


def _empty_sitemap_response():
    """Return 200 application/xml with empty urlset (for section errors so section URL is always 200)."""
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    return HttpResponse(body, content_type="application/xml", status=200)


def _sitemap_response(request, response, cache_key, cache_seconds):
    """Apply canonical host fix to <loc> and optional cache."""
    import re
    from urllib.parse import urlparse, urlunparse

    from django.core.cache import cache

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    if hasattr(response, "render") and callable(response.render):
        response.render()
    content_type = getattr(response, "get", lambda k, d="": d)("Content-Type", "") or "application/xml"
    if response.status_code != 200 or "xml" not in content_type.lower():
        return response
    content = response.content.decode("utf-8")
    loc_pattern = r"<loc>(https?://[^<]+)</loc>"

    def fix_url(match):
        url = match.group(1)
        parsed = urlparse(url)
        fixed = urlunparse(("https", canonical_host, parsed.path, "", "", ""))
        return f"<loc>{fixed}</loc>"

    content = re.sub(loc_pattern, fix_url, content)
    body = content.encode("utf-8")
    if cache_seconds and not getattr(settings, "DEBUG", False):
        cache.set(cache_key, {"body": body, "content_type": content_type}, cache_seconds)
    return HttpResponse(body, content_type=content_type, status=200)


def sitemap_view(request, section=None, *args, **kwargs):
    """
    Custom sitemap: canonical domain URLs, optional cache.
    GET /sitemap.xml -> index (lists /sitemap-<section>.xml).
    GET /sitemap-<section>.xml -> section sitemap (section from path).
    """
    from django.contrib.sitemaps.views import index as sitemap_index_view
    from django.core.cache import cache

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    # Use sitemaps from path() kwargs so section keys (e.g. shacman-category-engine) match exactly
    sitemaps = kwargs.get("sitemaps") or {}
    cache_seconds = getattr(settings, "SITEMAP_CACHE_SECONDS", 1800)
    # SITEMAP_CACHE_VERSION: set in env on deploy to bust cache; v3 ensures index lists shacman-category-engine
    cache_version = getattr(settings, "SITEMAP_CACHE_VERSION", None) or "v3"
    cache_key = f"sitemap:{section or 'index'}:{cache_version}"

    if cache_seconds and not getattr(settings, "DEBUG", False):
        cached = cache.get(cache_key)
        if cached is not None:
            return HttpResponse(cached["body"], content_type=cached["content_type"], status=200)

    original_meta = request.META.copy()
    host_without_port = canonical_host.split(":")[0]
    request.META["HTTP_HOST"] = canonical_host
    request.META["SERVER_NAME"] = host_without_port

    try:
        if section is not None:
            from django.http import Http404
            if section not in sitemaps:
                raise Http404("No sitemap available for section: %r" % section)
            from django.contrib.sitemaps.views import sitemap as sitemap_section_view
            try:
                response = sitemap_section_view(request, sitemaps, section=section)
            except Http404:
                # EmptyPage/PageNotAnInteger or internal 404: return 200 with empty urlset so section URL is always 200
                response = _empty_sitemap_response()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Sitemap section %r failed", section)
                response = _empty_sitemap_response()
            if response.status_code != 200:
                response = _empty_sitemap_response()
            return _sitemap_response(request, response, cache_key, cache_seconds)
        else:
            # Index: Django builds from sitemaps.items(); all section keys get a <loc>.../sitemap-<section>.xml</loc>
            response = sitemap_index_view(
                request,
                sitemaps,
                sitemap_url_name=SITEMAP_SECTION_URL_NAME,
            )
            return _sitemap_response(request, response, cache_key, cache_seconds)
    finally:
        request.META = original_meta

api_urlpatterns = [
    path("api/products/", ProductListAPI.as_view(), name="api-products"),
    path("api/products/<slug:slug>/", ProductDetailAPI.as_view(), name="api-product-detail"),
    path("api/leads/", LeadCreateAPI.as_view(), name="api-leads"),
]

# DRF Spectacular docs: only available in DEBUG mode or for staff users
if settings.DEBUG:
    api_urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
else:
    # In production, restrict schema/docs to staff users only
    from functools import wraps
    from django.contrib.auth.decorators import login_required
    from django.http import HttpResponseForbidden
    
    def staff_required(view_func):
        """Decorator that requires user to be authenticated and staff."""
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not request.user.is_staff:
                return HttpResponseForbidden("Access denied. Staff only.")
            return view_func(request, *args, **kwargs)
        return wrapper
    
    api_urlpatterns += [
        path("api/schema/", staff_required(SpectacularAPIView.as_view()), name="schema"),
        path("api/docs/", staff_required(SpectacularSwaggerView.as_view(url_name="schema")), name="swagger-ui"),
    ]

# SHACMAN hub routes: single source so reverse("shacman_hub") etc. resolve without namespace
shacman_urlpatterns = [
    path("", catalog_views.shacman_hub, name="shacman_hub"),
    path("in-stock/", catalog_views.shacman_in_stock, name="shacman_in_stock"),
    # line: more specific first
    path("line/<slug:line_slug>/", catalog_views.shacman_line_hub, name="shacman_line_hub"),
    path("line/<slug:line_slug>/in-stock/", catalog_views.shacman_line_in_stock_hub, name="shacman_line_in_stock_hub"),
    path(
        "line/<slug:line_slug>/engine/<slug:engine_slug>/",
        catalog_views.shacman_line_engine_hub,
        name="shacman_line_engine_hub",
    ),
    path(
        "line/<slug:line_slug>/engine/<slug:engine_slug>/in-stock/",
        catalog_views.shacman_line_engine_in_stock_hub,
        name="shacman_line_engine_in_stock_hub",
    ),
    path(
        "line/<slug:line_slug>/formula/<slug:formula_slug>/",
        catalog_views.shacman_line_formula_hub,
        name="shacman_line_formula_hub",
    ),
    path(
        "line/<slug:line_slug>/formula/<slug:formula_slug>/in-stock/",
        catalog_views.shacman_line_formula_in_stock_hub,
        name="shacman_line_formula_in_stock_hub",
    ),
    path(
        "line/<slug:line_slug>/<slug:category_slug>/",
        catalog_views.shacman_line_category_hub,
        name="shacman_line_category_hub",
    ),
    path(
        "line/<slug:line_slug>/<slug:category_slug>/in-stock/",
        catalog_views.shacman_line_category_in_stock_hub,
        name="shacman_line_category_in_stock_hub",
    ),
    path(
        "line/<slug:line_slug>/<slug:category_slug>/<path:formula>/",
        catalog_views.shacman_line_category_formula_hub,
        name="shacman_line_category_formula_hub",
    ),
    path(
        "line/<slug:line_slug>/<slug:category_slug>/<path:formula>/in-stock/",
        catalog_views.shacman_line_category_formula_in_stock_hub,
        name="shacman_line_category_formula_in_stock_hub",
    ),
    # engine
    path("engine/<slug:engine_slug>/", catalog_views.shacman_engine_hub, name="shacman_engine_hub"),
    path(
        "engine/<slug:engine_slug>/in-stock/",
        catalog_views.shacman_engine_in_stock_hub,
        name="shacman_engine_in_stock_hub",
    ),
    path(
        "engine/<slug:engine_slug>/<slug:category_slug>/",
        catalog_views.shacman_engine_category_hub,
        name="shacman_engine_category_hub",
    ),
    path(
        "engine/<slug:engine_slug>/<slug:category_slug>/in-stock/",
        catalog_views.shacman_engine_category_in_stock_hub,
        name="shacman_engine_category_in_stock_hub",
    ),
    # formula, series (redirects)
    path("formula/<path:formula>/", catalog_views.shacman_formula_hub, name="shacman_formula_hub"),
    path(
        "formula/<path:formula>/in-stock/",
        catalog_views.shacman_formula_in_stock_hub,
        name="shacman_formula_in_stock_hub",
    ),
    path("series/<slug:series_slug>/", catalog_views.shacman_series_hub, name="shacman_series_hub"),
    path(
        "series/<slug:series_slug>/in-stock/",
        catalog_views.shacman_series_in_stock_hub,
        name="shacman_series_in_stock_hub",
    ),
    # model code (SX…)
    path(
        "model/<slug:model_code_slug>/",
        catalog_views.shacman_model_code_hub,
        name="shacman_model_code_hub",
    ),
    path(
        "model/<slug:model_code_slug>/in-stock/",
        catalog_views.shacman_model_code_in_stock_hub,
        name="shacman_model_code_in_stock_hub",
    ),
    # category-first engine combo: /shacman/category/<cat>/engine/<val>/ (+ in-stock)
    path(
        "category/<slug:category_slug>/engine/<slug:engine_slug>/",
        catalog_views.shacman_category_engine_hub,
        name="shacman_category_engine_hub",
    ),
    path(
        "category/<slug:category_slug>/engine/<slug:engine_slug>/in-stock/",
        catalog_views.shacman_category_engine_in_stock_hub,
        name="shacman_category_engine_in_stock_hub",
    ),
    path(
        "category/<slug:category_slug>/line/<slug:line_slug>/",
        catalog_views.shacman_category_line_hub,
        name="shacman_category_line_hub",
    ),
    path(
        "category/<slug:category_slug>/line/<slug:line_slug>/in-stock/",
        catalog_views.shacman_category_line_in_stock_hub,
        name="shacman_category_line_in_stock_hub",
    ),
    path(
        "category/<slug:category_slug>/line/<slug:line_slug>/formula/<slug:formula_slug>/",
        catalog_views.shacman_category_line_formula_hub,
        name="shacman_category_line_formula_hub",
    ),
    path(
        "category/<slug:category_slug>/line/<slug:line_slug>/formula/<slug:formula_slug>/in-stock/",
        catalog_views.shacman_category_line_formula_in_stock_hub,
        name="shacman_category_line_formula_in_stock_hub",
    ),
    path(
        "category/<slug:category_slug>/formula/<slug:formula_slug>/",
        catalog_views.shacman_category_formula_explicit_hub,
        name="shacman_category_formula_explicit_hub",
    ),
    path(
        "category/<slug:category_slug>/formula/<slug:formula_slug>/in-stock/",
        catalog_views.shacman_category_formula_explicit_in_stock_hub,
        name="shacman_category_formula_explicit_in_stock_hub",
    ),
    # category (catch-all slug; after literals so in-stock/line/engine/formula/series/category not captured)
    path("<slug:category_slug>/", catalog_views.shacman_category, name="shacman_category"),
    path(
        "<slug:category_slug>/in-stock/",
        catalog_views.shacman_category_in_stock,
        name="shacman_category_in_stock",
    ),
    path(
        "<slug:category_slug>/<path:formula>/",
        catalog_views.shacman_category_formula_hub,
        name="shacman_category_formula_hub",
    ),
    path(
        "<slug:category_slug>/<path:formula>/in-stock/",
        catalog_views.shacman_category_formula_in_stock_hub,
        name="shacman_category_formula_in_stock_hub",
    ),
]

public_patterns = [
    path("health/", health_view, name="health"),
    path(
        "yandex_70c3a80a6008addf.html",
        site_views.yandex_verification,
        name="yandex-verification",
    ),
    # Deployment marker (required): GET /__version__/ -> {"build_id": "<string>"}
    path("__version__/", version_view, name="version"),
    # Backward-compatible alias (some monitors use /version/)
    path("version/", version_view, name="version-compat"),
    path("sitemap.xml", sitemap_view, {"sitemaps": sitemaps}, name="sitemap"),
    path("sitemap-<str:section>.xml", sitemap_view, {"sitemaps": sitemaps}, name=SITEMAP_SECTION_URL_NAME),
    path("robots.txt", robots_txt_view, name="robots"),
]

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    # 301 /admin → /admin/ (exact path only; does not match /admin/...)
    re_path(r"^admin$", RedirectView.as_view(url="/admin/", permanent=True)),
    path(ADMIN_PATH, admin.site.urls),
    *public_patterns,
    *api_urlpatterns,
]

urlpatterns += i18n_patterns(
    path("", include(("catalog.urls", "catalog"), namespace="catalog")),
    path("shacman/", include(shacman_urlpatterns)),
    path("blog/", include(("blog.urls", "blog"), namespace="blog")),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom 404: no JSON-LD on 404 (carfst_site.views.custom_404 sets schema_allowed=False, page_schema_payload=None)
handler404 = "carfst_site.views.custom_404"

