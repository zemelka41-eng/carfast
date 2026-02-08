import json
import logging
import re
import time
from typing import NamedTuple
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Prefetch, When
from django.db.utils import DatabaseError, OperationalError
from django.http import Http404, HttpResponse, HttpResponseNotFound, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from .filters import ProductFilter
from .forms import ContactsLeadForm, LeadForm
from .models import Category, CatalogLandingSEO, Lead, ModelVariant, Offer, Product, Series, SeriesCategorySEO, ShacmanHubSEO, StaticPageSEO
from .notifications import send_lead_notification
from .seo_product import (
    build_product_first_block,
    build_product_h1,
    build_product_image_alt,
    build_product_seo_description,
    build_product_seo_title,
)
from .blog_crosslink import get_related_blog_posts_for_shacman
from .seo_html import deduplicate_additional_info_heading
from .utils import generate_whatsapp_link
from .utils.text_cleaner import clean_text
from .utils.site_settings import get_site_settings_safe

logger = logging.getLogger(__name__)

_CACHE_ERROR_LOGGED = False
_CACHE_DISABLED = False


def _redirect_page_one(request, target_url: str):
    if len(request.GET.keys()) != 1:
        return None
    page_raw = (request.GET.get("page") or "").strip()
    if not page_raw:
        return None
    try:
        if int(page_raw) == 1:
            return redirect(target_url, permanent=True)
    except ValueError:
        return None
    return None


def _cache_get_safe(key: str, default=None):
    """
    Cache get that never raises (critical for prod when Redis is misconfigured/unavailable).
    """
    global _CACHE_ERROR_LOGGED, _CACHE_DISABLED
    if _CACHE_DISABLED:
        return default
    try:
        from django.core.cache import cache

        return cache.get(key, default)
    except Exception as exc:  # pragma: no cover - environment dependent
        _CACHE_DISABLED = True
        if not _CACHE_ERROR_LOGGED:
            logger.warning("Cache unavailable (get): %s", exc, exc_info=True)
            _CACHE_ERROR_LOGGED = True
        return default


def _cache_set_safe(key: str, value, timeout: int | None = None) -> bool:
    """Cache set that never raises; returns True if set succeeded."""
    global _CACHE_ERROR_LOGGED, _CACHE_DISABLED
    if _CACHE_DISABLED:
        return False
    try:
        from django.core.cache import cache

        cache.set(key, value, timeout=timeout)
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        _CACHE_DISABLED = True
        if not _CACHE_ERROR_LOGGED:
            logger.warning("Cache unavailable (set): %s", exc, exc_info=True)
            _CACHE_ERROR_LOGGED = True
        return False

BRAND_LOGO_STATIC: dict[str, str] = {
    "shacman": "img/brands/shacman-logo.png",
    "dayun": "img/brands/dayun-logo.png",
}

SHACMAN_CATEGORY_ORDER = (
    "Самосвалы",
    "Седельные тягачи",
    "Автобетоносмесители",
    "КМУ",
    "КДМ",
    "Сортиментовозы",
    "Мусоровозы",
    "Бортовые грузовики",
    "Мультилифты",
    "АТЗ",
    "МКДУ",
    "Ломовозы",
)

SHACMAN_MODEL_ORDER = (
    "X6000 4x2",
    "X6000 6x4",
    "X5000 6x4",
    "X5000 6x6",
    "X5000 8x4",
    "X3000 8x4",
    "X3000 4x2",
    "X3000 6x4",
)


def _seo_context(
    title,
    description,
    request,
    obj=None,
    og_image=None,
    allowed_query_keys: set[str] | None = None,
):
    """
    Build SEO context with title, description, canonical, and OpenGraph/Twitter meta tags.
    
    Args:
        title: Page title
        description: Meta description (auto-truncated to 155 chars for meta tag)
        request: Django request object
        obj: Optional object (Product, Series, etc.) for generating OG tags
        og_image: Optional image URL for OpenGraph
        allowed_query_keys: Set of allowed query parameter keys (others trigger noindex)
    """
    from .templatetags.catalog_format import truncate_meta_description
    
    canonical = request.build_absolute_uri(request.path)
    
    # Auto-truncate description for meta tag (ideal: 155-160 chars)
    meta_description = truncate_meta_description(description, 155) if description else ""
    
    context = {
        "meta_title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "hreflang_ru": canonical.replace("/en/", "/ru/"),
        "hreflang_en": canonical.replace("/ru/", "/en/"),
        "object": obj,
        "og_title": title,
        "og_description": meta_description,  # Same truncated description for OG
        "og_url": canonical,
        "og_type": "website",
    }
    
    # Generate OpenGraph image
    if og_image:
        context["og_image"] = og_image
    elif obj:
        # For Product: use main image
        if hasattr(obj, "main_image") and obj.main_image:
            context["og_image"] = request.build_absolute_uri(obj.main_image.image.url)
        # For Series: use logo
        elif hasattr(obj, "logo") and obj.logo:
            context["og_image"] = request.build_absolute_uri(obj.logo.url)
    
    # Default og:image if none set (brand asset)
    if not context.get("og_image"):
        from django.contrib.staticfiles.storage import staticfiles_storage
        default_og_image = request.build_absolute_uri(staticfiles_storage.url("img/logo-h128.webp"))
        context["og_image"] = default_og_image
    
    # Twitter Card
    context["twitter_card"] = "summary_large_image" if context.get("og_image") else "summary"

    if allowed_query_keys is None:
        allowed_query_keys = set()
    if request.GET and not context.get("meta_robots"):
        extra_keys = [key for key in request.GET.keys() if key not in allowed_query_keys]
        if extra_keys:
            context["meta_robots"] = "noindex, follow"

    return context


def home(request):
    series = Series.objects.public()[:6]
    
    # Популярные позиции: приоритет по total_qty > 0, наличию main_image, display_price
    # Сортировка: сначала по total_qty (DESC), затем по updated_at/created_at (DESC)
    from .models import ProductImage
    
    # Проверяем наличие изображений через подзапрос (order=0 - главное фото)
    has_image = Exists(
        ProductImage.objects.filter(product=OuterRef("pk"), order=0)
    )
    
    products_qs = (
        Product.objects.public()
        .with_stock_stats()
        .select_related("series", "category")
        .annotate(
            has_main_image=has_image,
            priority_score=Case(
                When(total_qty__gt=0, then=100),
                default=0,
                output_field=IntegerField(),
            ) + Case(
                When(has_main_image=True, then=10),
                default=0,
                output_field=IntegerField(),
            ) + Case(
                When(display_price__isnull=False, then=1),
                default=0,
                output_field=IntegerField(),
            )
        )
        .order_by("-priority_score", "-updated_at", "-created_at")
    )
    
    # Пытаемся взять 12 товаров
    products = list(products_qs[:12])
    
    # Если товаров меньше 6, показываем "последние добавленные" (без приоритетов)
    if len(products) < 6:
        products = list(
            Product.objects.public()
            .with_stock_stats()
            .select_related("series", "category")
            .order_by("-created_at", "-updated_at")[:12]
        )
    
    # Prefetch images для всех товаров
    from django.db.models import Prefetch
    product_ids = [p.id for p in products]
    products_with_images = (
        Product.objects.filter(id__in=product_ids)
        .prefetch_related("images")
        .select_related("series", "category")
    )
    products_dict = {p.id: p for p in products_with_images}
    products = [products_dict.get(p.id, p) for p in products]
    
    in_stock_products = list(
        Product.objects.public()
        .with_stock_stats()
        .select_related("series", "category")
        .prefetch_related("images")
        .filter(total_qty__gt=0)
        .order_by("-total_qty", "-updated_at", "-created_at")[:6]
    )
    
    context = {
        "series_list": series,
        "products": products,
        "in_stock_products": in_stock_products,
    }
    context.update(_seo_context("CARFAST — Каталог спецтехники", "Официальный дилер SHACMAN. Каталог спецтехники в наличии и под заказ.", request))
    resp = render(request, "catalog/home.html", context)
    # Diagnostic: confirms / is served by this view; remove after verifying on prod
    resp["X-Home-Template"] = "templates/catalog/home.html"
    return resp


def _is_in_stock_value(value: str) -> bool:
    normalized = (value or "").strip().lower().replace("-", "_")
    return normalized in {"in_stock", "instock", "1", "true", "yes", "y", "да"}


def _build_catalog_base_context(request, query_params):
    selected_brand_slug = (query_params.get("series") or "").strip()
    selected_brand_slug_lower = selected_brand_slug.lower()

    series_list = Series.objects.public()
    selected_series = (
        series_list.filter(slug__iexact=selected_brand_slug).first()
        if selected_brand_slug
        else None
    )

    selected_category_slug = (query_params.get("category") or "").strip()
    selected_category = (
        Category.objects.filter(slug__iexact=selected_category_slug).first()
        if selected_category_slug
        else None
    )

    selected_model_slug = (query_params.get("model") or "").strip()
    selected_model = (
        ModelVariant.objects.select_related("brand")
        .filter(slug__iexact=selected_model_slug)
        .first()
        if selected_model_slug
        else None
    )

    category_list = Category.objects.all()
    if selected_brand_slug_lower == "shacman":
        category_order = Case(
            *[
                When(name=category_name, then=pos)
                for pos, category_name in enumerate(SHACMAN_CATEGORY_ORDER)
            ],
            output_field=IntegerField(),
        )
        category_list = Category.objects.filter(
            name__in=SHACMAN_CATEGORY_ORDER
        ).order_by(category_order)

    model_qs = ModelVariant.objects.select_related("brand")
    if selected_brand_slug:
        if selected_brand_slug_lower == "shacman":
            model_order = Case(
                *[
                    When(name=model_name, then=pos)
                    for pos, model_name in enumerate(SHACMAN_MODEL_ORDER)
                ],
                output_field=IntegerField(),
            )
            model_list = ModelVariant.objects.select_related("brand").filter(
                brand__slug__iexact="shacman",
                name__in=SHACMAN_MODEL_ORDER,
            ).order_by(model_order)
        else:
            model_list = model_qs.filter(brand__slug__iexact=selected_brand_slug)
    else:
        model_list = model_qs.filter(brand__slug__iexact="shacman")

    qs = (
        Product.objects.public()
        .select_related("series", "category", "model_variant")
        .with_stock_stats()
    )
    product_filter = ProductFilter(query_params, queryset=qs)
    products = product_filter.qs.prefetch_related("images")

    has_filters = any(
        query_params.get(key)
        for key in ["series", "category", "model", "availability", "price_min", "price_max", "q", "page"]
    )

    return {
        "filter": product_filter,
        "products": products,
        "series_list": series_list,
        "category_list": category_list,
        "model_list": model_list,
        "selected_series": selected_series,
        "selected_category": selected_category,
        "selected_model": selected_model,
        "has_filters": has_filters,
        "selected_brand_slug": selected_brand_slug,
        "selected_category_slug": selected_category_slug,
        "selected_model_slug": selected_model_slug,
    }


def catalog_list(request):
    redirect_response = _redirect_page_one(request, reverse("catalog:catalog_list"))
    if redirect_response:
        return redirect_response

    tracking_keys = {
        "gclid",
        "ysclid",
        "yclid",
        "ymclid",
        "fbclid",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "_openstat",
        "roistat",
        "from",
        "ref",
    }
    tracking_like = {
        key
        for key in request.GET.keys()
        if key.startswith("utm_") or key in tracking_keys
    }
    filter_keys = set(request.GET.keys()) - tracking_like

    series_only = request.GET.get("series")
    category_only = request.GET.get("category")
    if series_only and filter_keys == {"series"}:
        series = Series.objects.public().filter(slug__iexact=series_only).first()
        if not series:
            raise Http404("Серия не найдена")
        redirect_url = reverse(
            "catalog:catalog_series", kwargs={"slug": series.slug}
        )
        if tracking_like:
            tracking_params = {
                key: request.GET.get(key)
                for key in request.GET.keys()
                if key in tracking_like
            }
            redirect_url = f"{redirect_url}?{urlencode(tracking_params)}"
        return redirect(redirect_url, permanent=True)
    if category_only and filter_keys == {"category"}:
        category = Category.objects.filter(slug__iexact=category_only).first()
        if not category:
            raise Http404("Категория не найдена")
        redirect_url = reverse(
            "catalog:catalog_category", kwargs={"slug": category.slug}
        )
        if tracking_like:
            tracking_params = {
                key: request.GET.get(key)
                for key in request.GET.keys()
                if key in tracking_like
            }
            redirect_url = f"{redirect_url}?{urlencode(tracking_params)}"
        return redirect(redirect_url, permanent=True)

    # series + category -> 301 to /catalog/series/<series>/<category>/ (tracking params dropped)
    if series_only and category_only and filter_keys in (
        {"series", "category"},
        {"series", "category", "page"},
    ):
        page_param = None
        do_redirect = True
        if "page" in filter_keys:
            page_raw = (request.GET.get("page") or "").strip()
            if page_raw:
                try:
                    n = int(page_raw)
                    if n > 1:
                        page_param = n
                except ValueError:
                    do_redirect = False
        if do_redirect:
            series = Series.objects.public().filter(slug__iexact=series_only).first()
            category = Category.objects.filter(slug__iexact=category_only).first()
            if series and category:
                redirect_url = reverse(
                    "catalog:catalog_series_category",
                    kwargs={"series_slug": series.slug, "category_slug": category.slug},
                )
                if page_param is not None:
                    redirect_url = f"{redirect_url}?page={page_param}"
                return redirect(redirect_url, permanent=True)
            if not series or not category:
                raise Http404("Серия или категория не найдена")

    availability_raw = (request.GET.get("availability") or "").strip()
    if availability_raw and _is_in_stock_value(availability_raw):
        query_keys = set(request.GET.keys())
        allowed_keys = {"availability", "page"}
        tracking_like = {
            key for key in query_keys if key.startswith("utm_") or key in tracking_keys
        }
        disallowed_keys = query_keys - allowed_keys - tracking_like
        if not disallowed_keys:
            page_raw = (request.GET.get("page") or "").strip()
            page_num = None
            if page_raw:
                try:
                    page_num = int(page_raw)
                    if page_num <= 1:
                        page_num = None
                except ValueError:
                    page_num = None
            redirect_url = reverse("catalog:catalog_in_stock")
            if page_num:
                redirect_url = f"{redirect_url}?page={page_num}"
            if tracking_like:
                tracking_params = {
                    key: request.GET.get(key)
                    for key in request.GET.keys()
                    if key in tracking_like
                }
                joiner = "&" if "?" in redirect_url else "?"
                redirect_url = f"{redirect_url}{joiner}{urlencode(tracking_params)}"
            return redirect(redirect_url, permanent=True)

    base_context = _build_catalog_base_context(request, request.GET)
    selected_series = base_context["selected_series"]
    selected_category = base_context["selected_category"]
    selected_model = base_context["selected_model"]
    selected_brand_slug = base_context["selected_brand_slug"]
    selected_category_slug = base_context["selected_category_slug"]

    # Build SEO title and description based on filters
    title_parts = ["Каталог техники"]
    desc_parts = ["Каталог спецтехники CARFAST"]

    if selected_series:
        title_parts.append(f"{selected_series.name}")
        desc_parts.append(f"Техника {selected_series.name}")
    if selected_category:
        title_parts.append(f"{selected_category.name}")
        desc_parts.append(f"{selected_category.name}")
    if selected_model:
        title_parts.append(f"{selected_model.name}")
        desc_parts.append(f"Модель {selected_model.name}")

    page_raw = (request.GET.get("page") or "").strip()
    page_num = None
    page_invalid = False
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_invalid = True
                page_num = None
        except ValueError:
            page_invalid = True

    if page_num:
        title_parts.append(f"страница {page_num}")

    seo_title = " — ".join(title_parts) if len(title_parts) > 1 else title_parts[0]
    seo_description = ". ".join(desc_parts) + ". В наличии и под заказ."

    meta_robots = None
    if request.GET:
        meta_robots = "noindex, follow"
    elif request.path.rstrip("/") == "/catalog":
        meta_robots = "noindex, follow"

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = f"https://{canonical_host}{reverse('catalog:catalog_list')}"
    selected_series_valid = bool(selected_series)
    selected_category_valid = bool(selected_category)
    canonical_url = canonical_base
    if selected_series_valid and not selected_category_valid and filter_keys == {"series"}:
        canonical_url = (
            f"https://{canonical_host}"
            f"{reverse('catalog:catalog_series', kwargs={'slug': selected_series.slug})}"
        )
    elif selected_category_valid and not selected_series_valid and filter_keys == {"category"}:
        canonical_url = (
            f"https://{canonical_host}"
            f"{reverse('catalog:catalog_category', kwargs={'slug': selected_category.slug})}"
        )
    
    context = {
        **base_context,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            allowed_query_keys={"series", "category", "page"},
        )
    )
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    context["catalog_h1"] = seo_title
    context["catalog_seo_intro_html"] = ""
    context["catalog_seo_body_html"] = ""
    return render(request, "catalog/catalog_list.html", context)


def _parse_seo_faq(raw_text: str) -> list[dict]:
    items: list[dict] = []
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        question, answer = line.split("|", 1)
        question = question.strip()
        answer = answer.strip()
        if question and answer:
            items.append({"question": question, "answer": answer})
    return items


def _build_breadcrumb_schema(request, items: list[dict]) -> dict:
    """
    Build BreadcrumbList JSON-LD schema.
    
    Args:
        request: Django request object
        items: List of dicts with 'name' and 'url' keys
    
    Returns:
        BreadcrumbList schema dict
    """
    breadcrumb_items = []
    for position, item in enumerate(items, start=1):
        breadcrumb_items.append({
            "@type": "ListItem",
            "position": position,
            "name": item["name"],
            "item": request.build_absolute_uri(item["url"]),
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumb_items,
    }


def _build_faq_schema(faq_items: list[dict]) -> dict:
    """
    Build FAQPage JSON-LD schema.
    
    Args:
        faq_items: List of dicts with 'question' and 'answer' keys
    
    Returns:
        FAQPage schema dict
    """
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"],
                },
            }
            for item in faq_items
        ],
    }


def _build_itemlist_schema(request, products_queryset, max_items: int = 20) -> dict:
    """
    Build ItemList JSON-LD schema for product catalog pages.
    
    Args:
        request: Django request object
        products_queryset: QuerySet of Product objects (should be from page=1)
        max_items: Maximum number of items to include (default: 20)
    
    Returns:
        ItemList schema dict
    """
    # Get first N products from the queryset
    products = list(products_queryset[:max_items])
    
    item_list_elements = []
    for position, product in enumerate(products, start=1):
        raw_name = product.model_name_ru or product.sku
        item_list_elements.append({
            "@type": "ListItem",
            "position": position,
            "url": request.build_absolute_uri(product.get_absolute_url()),
            "name": clean_text(raw_name) if raw_name else raw_name,
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": item_list_elements,
    }


def catalog_series(request, slug):
    series = get_object_or_404(Series.objects.public(), slug__iexact=slug)
    from django.http import QueryDict

    redirect_response = _redirect_page_one(
        request, reverse("catalog:catalog_series", kwargs={"slug": series.slug})
    )
    if redirect_response:
        return redirect_response

    query_params = QueryDict(mutable=True)
    query_params["series"] = series.slug
    page_raw = (request.GET.get("page") or "").strip()
    if page_raw:
        query_params["page"] = page_raw

    base_context = _build_catalog_base_context(request, query_params)

    page_num = None
    page_invalid = False
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_invalid = True
                page_num = None
        except ValueError:
            page_invalid = True

    title_parts = ["Каталог техники", series.name]
    if page_num:
        title_parts.append(f"страница {page_num}")
    seo_title = " — ".join(title_parts)
    seo_description = f"Каталог техники {series.name} от CARFAST. В наличии и под заказ."

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = f"https://{canonical_host}{reverse('catalog:catalog_series', kwargs={'slug': series.slug})}"
    canonical_url = f"{canonical_base}?page={page_num}" if page_num else canonical_base

    meta_robots = "index, follow"
    if page_invalid or page_num:
        meta_robots = "noindex, follow"
    extra_keys = [key for key in request.GET.keys() if key != "page"]
    if extra_keys:
        meta_robots = "noindex, follow"

    # Build breadcrumb schema for indexable pages (only clean URL without page param)
    breadcrumb_schema = None
    faq_schema = None
    itemlist_schema = None
    # is_indexable: TRUE only when page param is absent AND no extra GET params
    # This ensures schema is NOT added for ?page=abc, ?page=1, or any invalid page values
    is_indexable = (not page_raw or page_raw == "") and not extra_keys
    
    if is_indexable:
        breadcrumb_items = [
            {"name": "Главная", "url": reverse("catalog:home")},
            {"name": series.name, "url": reverse("catalog:catalog_series", kwargs={"slug": series.slug})},
        ]
        breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
        # Build ItemList schema for first page products
        itemlist_schema = _build_itemlist_schema(request, base_context["products"])
    
    catalog_faq_items = _parse_seo_faq(series.seo_faq)
    if is_indexable and catalog_faq_items:
        faq_schema = _build_faq_schema(catalog_faq_items)
    
    context = {
        **base_context,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            allowed_query_keys={"page"},
        )
    )
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    context["catalog_h1"] = seo_title
    context["catalog_description"] = (series.seo_description or "").strip()
    context["catalog_faq_items"] = catalog_faq_items
    context["catalog_seo_intro_html"] = (getattr(series, "seo_intro_html", None) or "").strip()
    context["catalog_seo_body_html"] = deduplicate_additional_info_heading(
        (getattr(series, "seo_body_html", None) or "").strip()
    )
    
    schema_items = []
    if breadcrumb_schema:
        schema_items.append(breadcrumb_schema)
    if faq_schema:
        schema_items.append(faq_schema)
    if itemlist_schema:
        schema_items.append(itemlist_schema)
    if schema_items:
        context["page_schema_payload"] = json.dumps(schema_items, ensure_ascii=False)[1:-1]
    
    return render(request, "catalog/catalog_list.html", context)


def catalog_category(request, slug):
    category = get_object_or_404(Category.objects, slug__iexact=slug)
    from django.http import QueryDict

    redirect_response = _redirect_page_one(
        request, reverse("catalog:catalog_category", kwargs={"slug": category.slug})
    )
    if redirect_response:
        return redirect_response

    query_params = QueryDict(mutable=True)
    query_params["category"] = category.slug
    page_raw = (request.GET.get("page") or "").strip()
    if page_raw:
        query_params["page"] = page_raw

    base_context = _build_catalog_base_context(request, query_params)

    page_num = None
    page_invalid = False
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_invalid = True
                page_num = None
        except ValueError:
            page_invalid = True

    title_parts = ["Каталог техники", category.name]
    if page_num:
        title_parts.append(f"страница {page_num}")
    seo_title = " — ".join(title_parts)
    seo_description = f"Каталог техники {category.name} от CARFAST. В наличии и под заказ."

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = f"https://{canonical_host}{reverse('catalog:catalog_category', kwargs={'slug': category.slug})}"
    canonical_url = f"{canonical_base}?page={page_num}" if page_num else canonical_base

    meta_robots = "index, follow"
    if page_invalid or page_num:
        meta_robots = "noindex, follow"
    extra_keys = [key for key in request.GET.keys() if key != "page"]
    if extra_keys:
        meta_robots = "noindex, follow"

    # Build breadcrumb schema for indexable pages (only clean URL without page param)
    breadcrumb_schema = None
    faq_schema = None
    itemlist_schema = None
    # is_indexable: TRUE only when page param is absent AND no extra GET params
    # This ensures schema is NOT added for ?page=abc, ?page=1, or any invalid page values
    is_indexable = (not page_raw or page_raw == "") and not extra_keys
    
    if is_indexable:
        breadcrumb_items = [
            {"name": "Главная", "url": reverse("catalog:home")},
            {"name": category.name, "url": reverse("catalog:catalog_category", kwargs={"slug": category.slug})},
        ]
        breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
        # Build ItemList schema for first page products
        itemlist_schema = _build_itemlist_schema(request, base_context["products"])
    
    catalog_faq_items = _parse_seo_faq(category.seo_faq)
    if is_indexable and catalog_faq_items:
        faq_schema = _build_faq_schema(catalog_faq_items)
    
    context = {
        **base_context,
        "current_category_slug": category.slug,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            allowed_query_keys={"page"},
        )
    )
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    context["catalog_h1"] = seo_title
    context["catalog_description"] = (category.seo_description or "").strip()
    context["catalog_faq_items"] = catalog_faq_items
    context["catalog_seo_intro_html"] = (getattr(category, "seo_intro_html", None) or "").strip()
    context["catalog_seo_body_html"] = deduplicate_additional_info_heading(
        (getattr(category, "seo_body_html", None) or "").strip()
    )
    
    schema_items = []
    if breadcrumb_schema:
        schema_items.append(breadcrumb_schema)
    if faq_schema:
        schema_items.append(faq_schema)
    if itemlist_schema:
        schema_items.append(itemlist_schema)
    if schema_items:
        context["page_schema_payload"] = json.dumps(schema_items, ensure_ascii=False)[1:-1]
    
    return render(request, "catalog/catalog_list.html", context)


def catalog_series_category(request, series_slug, category_slug):
    series = get_object_or_404(Series.objects.public(), slug__iexact=series_slug)
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    from django.http import QueryDict

    redirect_response = _redirect_page_one(
        request,
        reverse(
            "catalog:catalog_series_category",
            kwargs={"series_slug": series.slug, "category_slug": category.slug},
        ),
    )
    if redirect_response:
        return redirect_response

    query_params = QueryDict(mutable=True)
    query_params["series"] = series.slug
    query_params["category"] = category.slug
    page_raw = (request.GET.get("page") or "").strip()
    if page_raw:
        query_params["page"] = page_raw

    base_context = _build_catalog_base_context(request, query_params)

    page_num = None
    page_invalid = False
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_invalid = True
                page_num = None
        except ValueError:
            page_invalid = True

    title_parts = ["Каталог техники", series.name, category.name]
    if page_num:
        title_parts.append(f"страница {page_num}")
    seo_title = " — ".join(title_parts)
    seo_description = (
        f"Каталог техники {series.name} — {category.name}. "
        "В наличии и под заказ."
    )

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = (
        f"https://{canonical_host}"
        f"{reverse('catalog:catalog_series_category', kwargs={'series_slug': series.slug, 'category_slug': category.slug})}"
    )
    canonical_url = f"{canonical_base}?page={page_num}" if page_num else canonical_base

    meta_robots = "index, follow"
    if page_invalid or page_num:
        meta_robots = "noindex, follow"
    extra_keys = [key for key in request.GET.keys() if key != "page"]
    if extra_keys:
        meta_robots = "noindex, follow"
        canonical_url = canonical_base

    # Build breadcrumb schema for indexable pages (only clean URL without page param)
    breadcrumb_schema = None
    faq_schema = None
    itemlist_schema = None
    # is_indexable: TRUE only when page param is absent AND no extra GET params
    # This ensures schema is NOT added for ?page=abc, ?page=1, or any invalid page values
    is_indexable = (not page_raw or page_raw == "") and not extra_keys
    
    if is_indexable:
        breadcrumb_items = [
            {"name": "Главная", "url": reverse("catalog:home")},
            {"name": series.name, "url": reverse("catalog:catalog_series", kwargs={"slug": series.slug})},
            {"name": category.name, "url": reverse("catalog:catalog_series_category", kwargs={"series_slug": series.slug, "category_slug": category.slug})},
        ]
        breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
        # Build ItemList schema for first page products
        itemlist_schema = _build_itemlist_schema(request, base_context["products"])
    
    # Get SEO content for series+category
    seo_obj = SeriesCategorySEO.objects.filter(series=series, category=category).first()
    catalog_description = ""
    catalog_faq_items = []
    if seo_obj:
        catalog_description = (seo_obj.seo_description or "").strip()
        catalog_faq_items = _parse_seo_faq(seo_obj.seo_faq)
    
    if is_indexable and catalog_faq_items:
        faq_schema = _build_faq_schema(catalog_faq_items)
    
    context = {
        **base_context,
        "current_category_slug": category.slug,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            allowed_query_keys={"page"},
        )
    )
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    context["catalog_h1"] = f"Каталог техники — {series.name} — {category.name}"
    context["catalog_description"] = catalog_description
    context["catalog_faq_items"] = catalog_faq_items
    context["catalog_seo_intro_html"] = (getattr(seo_obj, "seo_intro_html", None) or "").strip() if seo_obj else ""
    context["catalog_seo_body_html"] = deduplicate_additional_info_heading(
        (getattr(seo_obj, "seo_body_html", None) or "").strip()
    ) if seo_obj else ""
    
    schema_items = []
    if breadcrumb_schema:
        schema_items.append(breadcrumb_schema)
    if faq_schema:
        schema_items.append(faq_schema)
    if itemlist_schema:
        schema_items.append(itemlist_schema)
    if schema_items:
        context["page_schema_payload"] = json.dumps(schema_items, ensure_ascii=False)[1:-1]
    
    return render(request, "catalog/catalog_list.html", context)


def catalog_in_stock(request):
    from django.http import QueryDict

    tracking_keys = {
        "gclid", "ysclid", "yclid", "ymclid", "fbclid",
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "_openstat", "roistat", "from", "ref",
    }
    tracking_like = {
        key for key in request.GET.keys()
        if key.startswith("utm_") or key in tracking_keys
    }
    non_tracking_keys = set(request.GET.keys()) - tracking_like

    # Redirect ?page=1 to clean URL when page is the only non-tracking param
    if non_tracking_keys == {"page"} and request.GET.get("page") == "1":
        return redirect(reverse("catalog:catalog_in_stock"), permanent=True)

    query_params = QueryDict(mutable=True)
    page_raw = (request.GET.get("page") or "").strip()
    if page_raw:
        query_params["page"] = page_raw
    query_params["availability"] = "in_stock"

    base_context = _build_catalog_base_context(request, query_params)

    page_num = None
    page_invalid = False
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_invalid = True
                page_num = None
        except ValueError:
            page_invalid = True

    title_parts = ["Каталог техники", "В наличии"]
    if page_num:
        title_parts.append(f"страница {page_num}")
    seo_title = " — ".join(title_parts)
    seo_description = "Каталог техники CARFAST в наличии. Актуальные модели на складе."

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = f"https://{canonical_host}{reverse('catalog:catalog_in_stock')}"
    canonical_url = (
        f"{canonical_base}?page={page_num}" if page_num else canonical_base
    )

    # No page with GET params is indexable; schema only on clean URL (no GET at all)
    schema_allowed = len(request.GET) == 0
    meta_robots = "index, follow" if schema_allowed else "noindex, follow"

    # Get SEO content from CatalogLandingSEO (primary) with SiteSettings fallback
    landing_seo = CatalogLandingSEO.objects.filter(
        landing_key=CatalogLandingSEO.LandingKey.CATALOG_IN_STOCK
    ).first()
    site_settings = get_site_settings_safe()

    # Meta overrides from CatalogLandingSEO
    if landing_seo and (landing_seo.meta_title or "").strip():
        seo_title = (landing_seo.meta_title or "").strip()
    if landing_seo and (landing_seo.meta_description or "").strip():
        seo_description = (landing_seo.meta_description or "").strip()

    # SEO content: intro, body, description, FAQ
    catalog_seo_intro_html = ""
    catalog_seo_body_html = ""
    catalog_description = ""
    catalog_faq_items = []

    if landing_seo:
        catalog_seo_intro_html = (landing_seo.seo_intro_html or "").strip()
        catalog_seo_body_html = deduplicate_additional_info_heading(
            (landing_seo.seo_body_html or "").strip()
        )
        catalog_faq_items = _parse_seo_faq(landing_seo.faq_items or "")
    # Fallback to SiteSettings for description and FAQ if CatalogLandingSEO is empty
    if not catalog_faq_items and site_settings:
        catalog_description = (getattr(site_settings, "in_stock_seo_description", "") or "").strip()
        catalog_faq_items = _parse_seo_faq(getattr(site_settings, "in_stock_seo_faq", "") or "")

    breadcrumb_schema = None
    faq_schema = None
    itemlist_schema = None
    if schema_allowed:
        breadcrumb_items = [
            {"name": "Главная", "url": reverse("catalog:home")},
            {"name": "В наличии", "url": reverse("catalog:catalog_in_stock")},
        ]
        breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
        # Build ItemList schema for first page products
        itemlist_schema = _build_itemlist_schema(request, base_context["products"])
        if catalog_faq_items:
            faq_schema = _build_faq_schema(catalog_faq_items)

    # Quick navigator links for internal linking (clean URLs only)
    quick_nav_links = []
    shacman_series = Series.objects.filter(slug__iexact="shacman").first()
    if shacman_series:
        quick_nav_links.append({
            "url": reverse("catalog:catalog_series", kwargs={"slug": shacman_series.slug}),
            "label": shacman_series.name,
        })
    main_categories = Category.objects.filter(
        slug__in=["samosvaly", "sedelnye-tyagachi", "avtobetonosmesiteli"]
    ).order_by("name")
    for cat in main_categories:
        quick_nav_links.append({
            "url": reverse("catalog:catalog_category", kwargs={"slug": cat.slug}),
            "label": cat.name,
        })
        if shacman_series:
            quick_nav_links.append({
                "url": reverse(
                    "catalog:catalog_series_category",
                    kwargs={"series_slug": shacman_series.slug, "category_slug": cat.slug},
                ),
                "label": f"{shacman_series.name} {cat.name}",
            })

    context = {
        **base_context,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            allowed_query_keys={"page"},
        )
    )
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    context["catalog_h1"] = seo_title
    context["catalog_description"] = catalog_description
    context["catalog_faq_items"] = catalog_faq_items
    context["catalog_seo_intro_html"] = catalog_seo_intro_html
    context["catalog_seo_body_html"] = catalog_seo_body_html
    context["quick_nav_links"] = quick_nav_links
    context["is_catalog_in_stock"] = True
    context["schema_allowed"] = schema_allowed

    # Explicitly remove any schema from base_context if schema not allowed
    if not schema_allowed:
        context.pop("page_schema_payload", None)
        schema_items = []
    else:
        schema_items = []
        if breadcrumb_schema:
            schema_items.append(breadcrumb_schema)
        if faq_schema:
            schema_items.append(faq_schema)
        if itemlist_schema:
            schema_items.append(itemlist_schema)
        if schema_items:
            context["page_schema_payload"] = json.dumps(schema_items, ensure_ascii=False)[1:-1]

    return render(request, "catalog/catalog_list.html", context)


def _shacman_series():
    """Return SHACMAN Series or None (by slug only; does not filter by public)."""
    return Series.objects.filter(slug__iexact="shacman").first()


def _shacman_series_is_public(series):
    """True if series exists and is in public queryset (for indexability / products)."""
    if not series:
        return False
    return Series.objects.public().filter(pk=series.pk).exists()


# Default intro (1 para) for SHACMAN hubs when no ShacmanHubSEO.seo_intro_html. Шакман (Shacman) 1–2 раза.
DEFAULT_SHACMAN_HUB_INTRO_HTML = """
<p>Купить технику <strong>Шакман (Shacman)</strong> в CARFAST — самосвалы, седельные тягачи, автобетоносмесители. Официальный дилер в РФ. Цена, наличие и комплектации по запросу. Лизинг, доставка по регионам, гарантия и сервис.</p>
""".strip()

# Default SEO body for SHACMAN hubs when no ShacmanHubSEO record or seo_text/seo_body_html empty.
# Единая структура без повторов: интро уже в seo_intro_html; здесь: выгоды → цена/наличие → доставка/лизинг/гарантия → КП. Один блок also_search_line в конце (в шаблоне).
# Включает: купить, цена, в наличии, лизинг, доставка, гарантия. Заголовки уникальные, без дубля «Дополнительная информация».
DEFAULT_SHACMAN_HUB_SEO_TEXT = """
<p>Преимущества покупки: официальный дилер, заводская гарантия, сервисная сеть по России, оригинальные запчасти на складе. Подбор комплектации под задачи, лизинг от 10% первоначального взноса, доставка в регионы.</p>

<h3>Цена и наличие</h3>
<p>В наличии и под заказ. Актуальные цены и наличие уточняйте у менеджера. Часть моделей на складе — возможна предзапись и резерв. Остальная техника поставляется под заказ с указанием сроков.</p>

<h3>Доставка и лизинг</h3>
<p>Доставка по РФ — автовозом или своим ходом. Стоимость и сроки зависят от направления. Условия на странице <a href="/payment-delivery/">Оплата и доставка</a>. Лизинг для юрлиц и ИП — программы на технику Shacman, подробности на <a href="/leasing/">Лизинг</a>.</p>

<h3>Гарантия и сервис</h3>
<p>Техника Shacman поставляется с официальной гарантией. Сервисное сопровождение и запчасти — партнёрская сеть по России. Подберём сервис в вашем регионе по запросу.</p>

<h3>Как получить КП</h3>
<p>Оставьте заявку на сайте или по телефону. Укажите модель, регион и условия (покупка/лизинг). Менеджер подготовит коммерческое предложение с ценой и сроками. Контакты — <a href="/contacts/">Контакты</a>.</p>
"""

# Default FAQ for SHACMAN hubs when no ShacmanHubSEO FAQ. Шакман (Shacman) в 1–2 ответах.
DEFAULT_SHACMAN_HUB_FAQ = [
    {"question": "Какая цена на технику Шакман (Shacman)?", "answer": "Цена зависит от модели, комплектации и условий поставки. Актуальные цены и наличие уточняйте у менеджера по телефону или через форму на сайте."},
    {"question": "Какие сроки поставки SHACMAN?", "answer": "Сроки зависят от наличия на складе и завода. Часть моделей поставляется со склада, остальные — под заказ с указанием сроков."},
    {"question": "Есть ли лизинг на Shacman?", "answer": "Да, для юридических лиц и ИП доступны программы лизинга. Условия и первоначальный взнос подбираются индивидуально. Подробности на странице Лизинг или по контактам."},
    {"question": "Какая гарантия на SHACMAN?", "answer": "Техника Шакман (Shacman) поставляется с официальной гарантией завода. Срок и условия уточняйте при заказе."},
    {"question": "Как доставить технику SHACMAN в регион?", "answer": "Организуем доставку по РФ. Стоимость и сроки зависят от направления и способа перевозки. Условия — в разделе Оплата и доставка."},
    {"question": "Как выбрать колёсную формулу 6x4 или 8x4?", "answer": "6x4 — три оси, подходит для большинства дорог. 8x4 — четыре оси, выше грузоподъёмность и проходимость. Выбор зависит от задач и условий эксплуатации; менеджер поможет подобрать вариант."},
    {"question": "Где сервис и запчасти SHACMAN?", "answer": "Сервисное сопровождение и запчасти обеспечиваются партнёрской сетью. Подберём сервис в вашем регионе по запросу."},
]


def build_shacman_hub_meta(
    hub_type: str,
    *,
    category=None,
    line_label=None,
    engine_label=None,
    formula=None,
    category_name=None,
    in_stock=None,
    model_code_label=None,
):
    """
    Единый генератор метаданных (title, description, h1) для каждого типа хаба SHACMAN.
    Тексты различаются по типам; включают «купить», «цена», «в наличии» по контексту;
    бренд SHACMAN и RU «Шакман» — аккуратно; description — лизинг, доставка по РФ, официальный дилер, гарантия/сервис.
    Returns dict: title, description, h1.
    """
    cat_name = (category.name if category else None) or category_name or ""
    line = line_label or ""
    engine = engine_label or ""
    model_code = model_code_label or ""
    formula_part = f" {formula}" if formula else ""
    in_stock_suffix = " в наличии" if in_stock else ""
    in_stock_only = in_stock is True

    # Разные шаблоны по типам, без дублей
    meta = {
        "brand_root": {
            "title": "SHACMAN (Шакман) — купить, цена, в наличии | CARFAST",
            "description": "Каталог SHACMAN (Шакман): самосвалы, тягачи, АБС. Цена, наличие, лизинг, доставка по РФ. Официальный дилер, гарантия и сервис. CARFAST.",
            "h1": "SHACMAN (Шакман) — купить, цена, в наличии",
        },
        "brand_in_stock": {
            "title": "SHACMAN в наличии — цена, доставка | CARFAST",
            "description": "Техника SHACMAN в наличии на складе. Актуальные цены, лизинг, доставка по РФ. Официальный дилер CARFAST.",
            "h1": "SHACMAN в наличии — цена, доставка",
        },
        "category": {
            "title": f"SHACMAN {cat_name} — купить, цена, в наличии | CARFAST" if cat_name else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN (Шакман) {cat_name}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер, сервис. CARFAST." if cat_name else "",
            "h1": f"SHACMAN {cat_name} — купить, цена, в наличии" if cat_name else "SHACMAN",
        },
        "category_in_stock": {
            "title": f"SHACMAN {cat_name} в наличии — цена | CARFAST" if cat_name else "SHACMAN в наличии | CARFAST",
            "description": f"{cat_name} SHACMAN в наличии. Цена, доставка по РФ, лизинг. CARFAST." if cat_name else "",
            "h1": f"SHACMAN {cat_name} в наличии — цена" if cat_name else "SHACMAN в наличии",
        },
        "line": {
            "title": f"SHACMAN {line} — купить, цена, в наличии | CARFAST" if line else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN (Шакман) {line}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if line else "",
            "h1": f"SHACMAN {line} — купить, цена, в наличии" if line else "SHACMAN",
        },
        "line_in_stock": {
            "title": f"SHACMAN {line} в наличии — цена | CARFAST" if line else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN в наличии. Цена, доставка по РФ, лизинг. CARFAST." if line else "",
            "h1": f"SHACMAN {line} в наличии — цена" if line else "SHACMAN в наличии",
        },
        "formula": {
            "title": f"SHACMAN {formula}{in_stock_suffix} — купить, цена | CARFAST" if formula else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN колёсная формула {formula}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if formula else "",
            "h1": f"SHACMAN {formula}{in_stock_suffix} — купить, цена" if formula else "SHACMAN",
        },
        "formula_in_stock": {
            "title": f"SHACMAN {formula} в наличии — цена | CARFAST" if formula else "SHACMAN в наличии | CARFAST",
            "description": f"SHACMAN {formula} в наличии. Цена, доставка по РФ, лизинг. CARFAST." if formula else "",
            "h1": f"SHACMAN {formula} в наличии — цена" if formula else "SHACMAN в наличии",
        },
        "engine": {
            "title": f"SHACMAN {engine} — купить, цена | CARFAST" if engine else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN двигатель {engine}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер, гарантия. CARFAST." if engine else "",
            "h1": f"SHACMAN {engine} — купить, цена" if engine else "SHACMAN",
        },
        "engine_in_stock": {
            "title": f"SHACMAN {engine} в наличии — цена | CARFAST" if engine else "SHACMAN в наличии | CARFAST",
            "description": f"SHACMAN {engine} в наличии. Цена, доставка по РФ. CARFAST." if engine else "",
            "h1": f"SHACMAN {engine} в наличии — цена" if engine else "SHACMAN в наличии",
        },
        "engine_category": {
            "title": f"SHACMAN {engine} {cat_name}{in_stock_suffix} — купить, цена | CARFAST" if (engine and cat_name) else "SHACMAN | CARFAST",
            "description": f"SHACMAN {engine} {cat_name}. Цена, наличие, лизинг, доставка по РФ. CARFAST." if (engine and cat_name) else "",
            "h1": f"SHACMAN {engine} {cat_name}{in_stock_suffix} — купить, цена" if (engine and cat_name) else "SHACMAN",
        },
        "engine_category_in_stock": {
            "title": f"SHACMAN {engine} {cat_name} в наличии — цена | CARFAST" if (engine and cat_name) else "SHACMAN в наличии | CARFAST",
            "description": f"SHACMAN {engine} {cat_name} в наличии. Цена, доставка по РФ. CARFAST." if (engine and cat_name) else "",
            "h1": f"SHACMAN {engine} {cat_name} в наличии — цена" if (engine and cat_name) else "SHACMAN в наличии",
        },
        "line_category": {
            "title": f"SHACMAN {line} {cat_name}{formula_part}{in_stock_suffix} — купить, цена | CARFAST" if (line and cat_name) else "SHACMAN | CARFAST",
            "description": f"{line} SHACMAN {cat_name}{formula_part}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if (line and cat_name) else "",
            "h1": f"SHACMAN {line} {cat_name}{formula_part}{in_stock_suffix} — купить, цена" if (line and cat_name) else "SHACMAN",
        },
        "line_category_in_stock": {
            "title": f"SHACMAN {line} {cat_name}{formula_part} в наличии — цена | CARFAST" if (line and cat_name) else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN {cat_name}{formula_part} в наличии. Цена, доставка по РФ. CARFAST." if (line and cat_name) else "",
            "h1": f"SHACMAN {line} {cat_name}{formula_part} в наличии — цена" if (line and cat_name) else "SHACMAN в наличии",
        },
        "line_engine": {
            "title": f"SHACMAN {line} {engine} — купить, цена | CARFAST" if (line and engine) else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN (Шакман) {line}, двигатель {engine}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер, гарантия и сервис. CARFAST." if (line and engine) else "",
            "h1": f"SHACMAN {line} {engine} — купить, цена" if (line and engine) else "SHACMAN",
        },
        "line_engine_in_stock": {
            "title": f"SHACMAN {line} {engine} в наличии — цена | CARFAST" if (line and engine) else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN {engine} в наличии. Цена, доставка по РФ, лизинг. Официальный дилер CARFAST." if (line and engine) else "",
            "h1": f"SHACMAN {line} {engine} в наличии — цена" if (line and engine) else "SHACMAN в наличии",
        },
        "category_formula": {
            "title": f"SHACMAN {cat_name} {formula} — купить, цена | CARFAST" if (cat_name and formula) else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN (Шакман) {cat_name}, колёсная формула {formula}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер, гарантия и сервис. CARFAST." if (cat_name and formula) else "",
            "h1": f"SHACMAN {cat_name} {formula} — купить, цена" if (cat_name and formula) else "SHACMAN",
        },
        "category_formula_in_stock": {
            "title": f"SHACMAN {cat_name} {formula} в наличии — цена | CARFAST" if (cat_name and formula) else "SHACMAN в наличии | CARFAST",
            "description": f"{cat_name} SHACMAN {formula} в наличии. Цена, доставка по РФ, лизинг. Официальный дилер CARFAST." if (cat_name and formula) else "",
            "h1": f"SHACMAN {cat_name} {formula} в наличии — цена" if (cat_name and formula) else "SHACMAN в наличии",
        },
        "category_line": {
            "title": f"SHACMAN {line} {cat_name}{in_stock_suffix} — купить, цена | CARFAST" if (line and cat_name) else "SHACMAN | CARFAST",
            "description": f"{line} SHACMAN {cat_name}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if (line and cat_name) else "",
            "h1": f"SHACMAN {line} {cat_name}{in_stock_suffix} — купить, цена" if (line and cat_name) else "SHACMAN",
        },
        "category_line_in_stock": {
            "title": f"SHACMAN {line} {cat_name} в наличии — цена | CARFAST" if (line and cat_name) else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN {cat_name} в наличии. Цена, доставка по РФ, лизинг. CARFAST." if (line and cat_name) else "",
            "h1": f"SHACMAN {line} {cat_name} в наличии — цена" if (line and cat_name) else "SHACMAN в наличии",
        },
        "line_formula": {
            "title": f"SHACMAN {line} {formula}{in_stock_suffix} — купить, цена | CARFAST" if (line and formula) else "SHACMAN | CARFAST",
            "description": f"{line} SHACMAN колёсная формула {formula}. Цена, наличие, лизинг, доставка по РФ. CARFAST." if (line and formula) else "",
            "h1": f"SHACMAN {line} {formula}{in_stock_suffix} — купить, цена" if (line and formula) else "SHACMAN",
        },
        "line_formula_in_stock": {
            "title": f"SHACMAN {line} {formula} в наличии — цена | CARFAST" if (line and formula) else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN {formula} в наличии. Цена, доставка по РФ, лизинг. CARFAST." if (line and formula) else "",
            "h1": f"SHACMAN {line} {formula} в наличии — цена" if (line and formula) else "SHACMAN в наличии",
        },
        "category_line_formula": {
            "title": f"SHACMAN {line} {cat_name} {formula}{in_stock_suffix} — купить, цена | CARFAST" if (line and cat_name and formula) else "SHACMAN | CARFAST",
            "description": f"{line} SHACMAN {cat_name} {formula}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if (line and cat_name and formula) else "",
            "h1": f"SHACMAN {line} {cat_name} {formula}{in_stock_suffix} — купить, цена" if (line and cat_name and formula) else "SHACMAN",
        },
        "category_line_formula_in_stock": {
            "title": f"SHACMAN {line} {cat_name} {formula} в наличии — цена | CARFAST" if (line and cat_name and formula) else "SHACMAN в наличии | CARFAST",
            "description": f"{line} SHACMAN {cat_name} {formula} в наличии. Цена, доставка по РФ, лизинг. CARFAST." if (line and cat_name and formula) else "",
            "h1": f"SHACMAN {line} {cat_name} {formula} в наличии — цена" if (line and cat_name and formula) else "SHACMAN в наличии",
        },
        "model_code": {
            "title": f"SHACMAN {model_code}{in_stock_suffix} — купить, цена | CARFAST" if model_code else "SHACMAN | CARFAST",
            "description": f"Техника SHACMAN (Шакман) код {model_code}. Цена, наличие, лизинг, доставка по РФ. Официальный дилер CARFAST." if model_code else "",
            "h1": f"SHACMAN {model_code}{in_stock_suffix} — купить, цена" if model_code else "SHACMAN",
        },
        "model_code_in_stock": {
            "title": f"SHACMAN {model_code} в наличии — цена | CARFAST" if model_code else "SHACMAN в наличии | CARFAST",
            "description": f"SHACMAN {model_code} в наличии. Цена, доставка по РФ, лизинг. CARFAST." if model_code else "",
            "h1": f"SHACMAN {model_code} в наличии — цена" if model_code else "SHACMAN в наличии",
        },
    }
    out = meta.get(hub_type, meta["brand_root"])
    return {"title": out["title"], "description": out["description"], "h1": out["h1"]}


def _get_shacman_facet_seo_content(hub_type: str, facet_key: str):
    """
    Load SEO content for facet hubs (formula/engine/line) from ShacmanHubSEO by hub_type + facet_key.
    Returns dict: seo_intro_html, seo_body_html, faq_items (and meta_title, meta_description if set).
    When intro/body empty, uses default with Шакман (Shacman) for key hubs.
    """
    from .models import ShacmanHubSEO

    rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, facet_key__iexact=facet_key).first()
    if not rec:
        return {
            "seo_intro_html": DEFAULT_SHACMAN_HUB_INTRO_HTML,
            "seo_body_html": "",
            "faq_items": [],
            "meta_title": None,
            "meta_description": None,
        }
    faq_items = _parse_seo_faq(rec.faq or "")
    intro = (rec.seo_intro_html or "").strip()
    if not intro:
        intro = DEFAULT_SHACMAN_HUB_INTRO_HTML
    return {
        "seo_intro_html": intro,
        "seo_body_html": deduplicate_additional_info_heading((rec.seo_body_html or "").strip()),
        "faq_items": faq_items,
        "meta_title": (rec.meta_title or "").strip() or None,
        "meta_description": (rec.meta_description or "").strip() or None,
    }


def _get_shacman_hub_seo_content(hub_type: str, category=None):
    """
    Load SEO content for /shacman/* from ShacmanHubSEO (editable in admin).
    Returns dict: meta_title, meta_description, meta_h1, seo_text, faq_items, also_search_line.
    Uses build_shacman_hub_meta() for fallbacks and h1.
    """
    from .models import ShacmanHubSEO

    # Fallbacks and h1 from unified generator
    _type_key = {"main": "brand_root", "in_stock": "brand_in_stock"}.get(hub_type, hub_type)
    gen = build_shacman_hub_meta(
        _type_key,
        category=category,
        category_name=category.name if category else None,
    )
    fallback_titles = {"main": gen["title"], "in_stock": gen["title"], "category": gen["title"], "category_in_stock": gen["title"]}
    fallback_descriptions = {"main": gen["description"], "in_stock": gen["description"], "category": gen["description"], "category_in_stock": gen["description"]}
    default_also_search = "Также ищут: Шакман / Shacman / Shaanxi / Шахман"

    rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category=category).first()
    seo_text_raw = (rec.seo_text or "").strip() if rec else ""
    seo_text = seo_text_raw if seo_text_raw else DEFAULT_SHACMAN_HUB_SEO_TEXT.strip()
    if rec:
        faq_items = _parse_seo_faq(rec.faq or "")
        if not faq_items:
            faq_items = DEFAULT_SHACMAN_HUB_FAQ
        body_html = deduplicate_additional_info_heading((getattr(rec, "seo_body_html", None) or "").strip())
        seo_text_dedup = deduplicate_additional_info_heading(seo_text)
        return {
            "meta_title": (rec.meta_title or "").strip() or fallback_titles.get(hub_type, ""),
            "meta_description": (rec.meta_description or "").strip() or fallback_descriptions.get(hub_type, ""),
            "meta_h1": gen["h1"],
            "seo_text": seo_text_dedup,
            "seo_intro_html": (getattr(rec, "seo_intro_html", None) or "").strip(),
            "seo_body_html": body_html,
            "faq_items": faq_items,
            "also_search_line": (rec.also_search_line or "").strip() or default_also_search,
        }
    return {
        "meta_title": fallback_titles.get(hub_type, ""),
        "meta_description": fallback_descriptions.get(hub_type, ""),
        "meta_h1": gen["h1"],
        "seo_text": deduplicate_additional_info_heading(seo_text),
        "seo_intro_html": DEFAULT_SHACMAN_HUB_INTRO_HTML,
        "seo_body_html": "",
        "faq_items": DEFAULT_SHACMAN_HUB_FAQ,
        "also_search_line": default_also_search,
    }


def _shacman_hub_categories():
    """Categories that have SHACMAN products (for link block on hubs)."""
    return (
        Category.objects.filter(
            products__series__slug__iexact="shacman",
            products__published=True,
            products__is_active=True,
        )
        .distinct()
        .order_by("name")
    )


def _shacman_top_products(limit=12, series=None, category=None):
    """Top SHACMAN products for link block on hub (by stock, then updated)."""
    qs = (
        Product.objects.public()
        .filter(series__slug__iexact="shacman")
        .with_stock_stats()
        .select_related("series", "category")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    if series:
        qs = qs.filter(series=series)
    if category:
        qs = qs.filter(category=category)
    return list(qs[:limit])


def _shacman_hub_context(request, base_path: str, title: str, description: str, products_queryset, faq_items: list, h1=None, noindex_for_thin=False):
    """
    Build SEO context for /shacman/* hubs: canonical, meta_robots, pagination, schema.
    base_path: e.g. "/shacman/" or "/shacman/samosvaly/"
    h1: optional H1 (if None, uses title).
    noindex_for_thin: if True, set meta_robots to noindex, follow (e.g. single-product hub).
    """
    from django.core.paginator import Paginator

    page_raw = (request.GET.get("page") or "").strip()
    if len(request.GET.keys()) == 1 and page_raw == "1":
        return redirect(request.build_absolute_uri(base_path.rstrip("/") + "/"), permanent=True), None

    page_num = None
    if page_raw:
        try:
            page_num = int(page_raw)
            if page_num <= 1:
                page_num = None
        except ValueError:
            page_num = None

    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    canonical_base = f"https://{canonical_host}{base_path.rstrip('/')}/"
    canonical_url = f"{canonical_base}?page={page_num}" if page_num else canonical_base
    meta_robots = "noindex, follow" if (page_num or request.GET or noindex_for_thin) else "index, follow"

    paginator = Paginator(products_queryset, 24)
    page_obj = paginator.get_page(page_num or 1)
    products = list(page_obj.object_list)

    # Schema.org on hubs NOT output (per project invariants)
    page_schema_payload = ""

    related_blog_posts = get_related_blog_posts_for_shacman(5)
    context = {
        "products": products,
        "page_obj": page_obj,
        "canonical": canonical_url,
        "meta_robots": meta_robots,
        "meta_title": title,
        "meta_description": description,
        "catalog_h1": h1 if h1 is not None else title,
        "catalog_description": "",
        "catalog_faq_items": faq_items,
        "page_schema_payload": page_schema_payload,
        "series_list": Series.objects.public(),
        "category_list": Category.objects.all(),
        "model_list": [],
        "selected_series": _shacman_series(),
        "selected_category": None,
        "selected_model": None,
        "has_filters": False,
        "related_blog_posts": related_blog_posts,
    }
    context.update(_seo_context(title, description, request, allowed_query_keys={"page"}))
    context["canonical"] = canonical_url
    context["meta_robots"] = meta_robots
    return None, context


def _shacman_hub_fallback_context(request, path="/shacman/", title="SHACMAN", description=""):
    """Minimal context for /shacman/ or /shacman/in-stock/ when normal build fails — 200 with empty list, noindex."""
    from django.core.paginator import Paginator

    qs = Product.objects.none()
    paginator = Paginator(qs, 24)
    page_obj = paginator.get_page(1)
    try:
        canonical_url = request.build_absolute_uri(path)
    except Exception:
        canonical_url = path
    hub_seo = {"seo_text": "", "faq_items": [], "also_search_line": "", "meta_title": title, "meta_description": description, "meta_h1": title, "seo_intro_html": "", "seo_body_html": ""}
    context = {
        "products": [],
        "page_obj": page_obj,
        "canonical": canonical_url,
        "meta_robots": "noindex, follow",
        "catalog_h1": title,
        "hub_seo": hub_seo,
        "shacman_hub_categories": [],
        "shacman_top_products": [],
        "shacman_combo_links": [],
        "related_blog_posts": get_related_blog_posts_for_shacman(5),
    }
    context.update(_seo_context(title, description, request, allowed_query_keys={"page"}))
    context["canonical"] = canonical_url
    return context


def shacman_hub(request):
    """SHACMAN brand hub: /shacman/. Never 404: if series missing/not public or error -> 200, empty list, noindex."""
    try:
        series = _shacman_series()
        use_series = _shacman_series_is_public(series)
        redirect_response = _redirect_page_one(request, reverse("shacman_hub"))
        if redirect_response:
            return redirect_response

        hub_seo = _get_shacman_hub_seo_content("main", category=None)
        if not use_series:
            qs = Product.objects.none()
            faq_items = hub_seo.get("faq_items") or []
        else:
            qs = (
                Product.objects.public()
                .filter(series=series)
                .with_stock_stats()
                .select_related("series", "category", "model_variant")
                .prefetch_related("images")
                .order_by("-total_qty", "-updated_at", "-id")
            )
            faq_items = hub_seo.get("faq_items") or _parse_seo_faq(series.seo_faq or "")
        title = hub_seo.get("meta_title") or "SHACMAN"
        description = hub_seo.get("meta_description") or ""
        redirect_out, context = _shacman_hub_context(request, "/shacman/", title, description, qs, faq_items)
        if redirect_out:
            return redirect_out
        context["catalog_h1"] = hub_seo.get("meta_h1") or title
        context["hub_seo"] = hub_seo
        context["shacman_hub_categories"] = _shacman_hub_categories()
        context["shacman_top_products"] = _shacman_top_products(limit=12, series=series if use_series else None)
        if not use_series:
            context["meta_robots"] = "noindex, follow"
        return render(request, "catalog/shacman_hub.html", context)
    except Exception:
        logger.exception("shacman_hub: fallback to 200 with noindex")
        context = _shacman_hub_fallback_context(request, "/shacman/", title="SHACMAN", description="")
        return render(request, "catalog/shacman_hub.html", context)


def shacman_in_stock(request):
    """SHACMAN in stock: /shacman/in-stock/. Never 404: if series missing/not public or error -> 200, empty list, noindex."""
    try:
        series = _shacman_series()
        use_series = _shacman_series_is_public(series)
        redirect_response = _redirect_page_one(request, reverse("shacman_in_stock"))
        if redirect_response:
            return redirect_response

        hub_seo = _get_shacman_hub_seo_content("in_stock", category=None)
        if not use_series:
            qs = Product.objects.none()
            faq_items = hub_seo.get("faq_items") or []
        else:
            qs = (
                Product.objects.public()
                .filter(series=series)
                .with_stock_stats()
                .filter(total_qty__gt=0)
                .select_related("series", "category", "model_variant")
                .prefetch_related("images")
                .order_by("-total_qty", "-updated_at", "-id")
            )
            if not hub_seo.get("faq_items"):
                site_settings = get_site_settings_safe()
                faq_raw = getattr(site_settings, "in_stock_seo_faq", "") or "" if site_settings else ""
                hub_seo = {**hub_seo, "faq_items": _parse_seo_faq(faq_raw)}
            faq_items = hub_seo.get("faq_items") or []
        title = hub_seo.get("meta_title") or "SHACMAN в наличии"
        description = hub_seo.get("meta_description") or ""
        redirect_out, context = _shacman_hub_context(request, "/shacman/in-stock/", title, description, qs, faq_items)
        if redirect_out:
            return redirect_out
        context["catalog_h1"] = hub_seo.get("meta_h1") or title
        context["hub_seo"] = hub_seo
        context["shacman_hub_categories"] = _shacman_hub_categories()
        context["shacman_top_products"] = _shacman_top_products(limit=12, series=series if use_series else None)
        context["shacman_combo_links"] = _shacman_combo_links_for_display(line_slug=None, category_slug=None)
        if not use_series:
            context["meta_robots"] = "noindex, follow"
        return render(request, "catalog/shacman_hub.html", context)
    except Exception:
        logger.exception("shacman_in_stock: fallback to 200 with noindex")
        context = _shacman_hub_fallback_context(request, "/shacman/in-stock/", title="SHACMAN в наличии", description="")
        return render(request, "catalog/shacman_hub.html", context)


def shacman_category(request, category_slug):
    """SHACMAN by category: /shacman/<category_slug>/. 404 only if category_slug missing; else 200 (noindex if no products)."""
    series = _shacman_series()
    use_series = _shacman_series_is_public(series)
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request, reverse("shacman_category", kwargs={"category_slug": category.slug})
    )
    if redirect_response:
        return redirect_response

    hub_seo = _get_shacman_hub_seo_content("category", category=category)
    if not use_series:
        qs = Product.objects.none()
        faq_items = hub_seo["faq_items"]
        seo_obj = None
    else:
        qs = (
            Product.objects.public()
            .filter(series=series, category=category)
            .with_stock_stats()
            .select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("-total_qty", "-updated_at", "-id")
        )
        seo_obj = SeriesCategorySEO.objects.filter(series=series, category=category).first()
        if not hub_seo["faq_items"] and seo_obj and seo_obj.seo_faq:
            hub_seo = {**hub_seo, "faq_items": _parse_seo_faq(seo_obj.seo_faq)}
        faq_items = hub_seo["faq_items"]
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/{category.slug}/", title, description, qs, faq_items
    )
    if redirect_out:
        return redirect_out
    context["catalog_h1"] = hub_seo.get("meta_h1") or title
    context["hub_seo"] = hub_seo
    context["current_category_slug"] = category.slug
    context["category"] = category
    context["catalog_description"] = (seo_obj.seo_description or "").strip() if seo_obj else ""
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(
        limit=12, series=series if use_series else None, category=category
    )
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(category_slug=category.slug)
        + _shacman_category_formula_links_for_display(category_slug=category.slug)
    )[:SHACMAN_COMBO_LINKS_CAP]
    page_obj = context.get("page_obj")
    if not use_series or (page_obj and page_obj.paginator.count == 0):
        context["meta_robots"] = "noindex, follow"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_in_stock(request, category_slug):
    """SHACMAN category in stock: /shacman/<category_slug>/in-stock/. 404 only if category_slug missing; else 200 (noindex if no products)."""
    series = _shacman_series()
    use_series = _shacman_series_is_public(series)
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request,
        reverse("shacman_category_in_stock", kwargs={"category_slug": category.slug}),
    )
    if redirect_response:
        return redirect_response

    hub_seo = _get_shacman_hub_seo_content("category_in_stock", category=category)
    if not use_series:
        qs = Product.objects.none()
        faq_items = hub_seo["faq_items"]
        seo_obj = None
    else:
        qs = (
            Product.objects.public()
            .filter(series=series, category=category)
            .with_stock_stats()
            .filter(total_qty__gt=0)
            .select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("-total_qty", "-updated_at", "-id")
        )
        seo_obj = SeriesCategorySEO.objects.filter(series=series, category=category).first()
        if not hub_seo["faq_items"] and seo_obj and seo_obj.seo_faq:
            hub_seo = {**hub_seo, "faq_items": _parse_seo_faq(seo_obj.seo_faq)}
        faq_items = hub_seo["faq_items"]
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/{category.slug}/in-stock/", title, description, qs, faq_items
    )
    if redirect_out:
        return redirect_out
    context["catalog_h1"] = hub_seo.get("meta_h1") or title
    context["hub_seo"] = hub_seo
    context["current_category_slug"] = category.slug
    context["category"] = category
    context["catalog_description"] = (seo_obj.seo_description or "").strip() if seo_obj else ""
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(
        limit=12, series=series if use_series else None, category=category
    )
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(category_slug=category.slug)
        + _shacman_category_formula_links_for_display(category_slug=category.slug)
    )[:SHACMAN_COMBO_LINKS_CAP]
    page_obj = context.get("page_obj")
    if not use_series or (page_obj and page_obj.paginator.count == 0):
        context["meta_robots"] = "noindex, follow"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_formula_hub(request, category_slug, formula):
    """Category+formula: /shacman/<category_slug>/<formula>/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    norm = _shacman_normalize_formula(formula)
    if not norm:
        raise Http404
    allowed = _shacman_category_formula_allowed_from_db(min_count=1)
    key = (category_slug, norm)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_formula_hub"
            resp["X-Diag-Allowed-CF"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_formula_hub",
            kwargs={"category_slug": category.slug, "formula": norm},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_formula_hub_queryset(category.slug, norm, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_formula_explicit", category=category, facet_key=norm
    )
    meta = build_shacman_hub_meta("category_formula", category_name=category.name, formula=norm)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/{category.slug}/{norm}/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_formula_hub",
        kwargs={"category_slug": category.slug, "formula": norm},
    )
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(category_slug=category.slug)
        + [l for l in _shacman_category_formula_links_for_display(category_slug=category.slug, exclude_url=current_path)]
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["hub_label"] = f"{category.name} {norm}"
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_category_formula_hub"
        response["X-Diag-Allowed-CF"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_category_formula_in_stock_hub(request, category_slug, formula):
    """Category+formula: /shacman/<category_slug>/<formula>/in-stock/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    diag = _shacman_hub_diag(request)
    norm = _shacman_normalize_formula(formula)
    if not norm:
        raise Http404
    allowed = _shacman_category_formula_allowed_from_db(min_count=1)
    key = (category_slug, norm)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_formula_in_stock_hub"
            resp["X-Diag-Allowed-CF"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_formula_in_stock_hub",
            kwargs={"category_slug": category.slug, "formula": norm},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_formula_hub_queryset(category.slug, norm, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_formula_explicit_in_stock", category=category, facet_key=norm
    )
    meta = build_shacman_hub_meta("category_formula_in_stock", category_name=category.name, formula=norm)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/{category.slug}/{norm}/in-stock/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_formula_in_stock_hub",
        kwargs={"category_slug": category.slug, "formula": norm},
    )
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(category_slug=category.slug)
        + [l for l in _shacman_category_formula_links_for_display(category_slug=category.slug, exclude_url=current_path)]
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["hub_label"] = f"{category.name} {norm}"
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_category_formula_in_stock_hub"
        response["X-Diag-Allowed-CF"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


# --- B3: series/formula/engine hubs (max 60 pages, min 2 products per cluster) ---

def _shacman_normalize_formula(value):
    """Normalize wheel formula to 4x2, 6x4, 8x4."""
    if not value:
        return ""
    raw = str(value).strip().lower().replace("\u00d7", "x").replace("\u0445", "x").replace(" ", "")
    return "".join(c for c in raw if c in "0123456789x") or ""


def _shacman_engine_slug(engine_model):
    """Normalize engine_model to URL slug: dot -> hyphen then slugify (WP13.550E501 -> wp13-550e501)."""
    from django.utils.text import slugify as django_slugify

    if not engine_model:
        return ""
    raw = (engine_model or "").strip().replace(".", "-")
    return django_slugify(raw) or ""


def _shacman_engine_allowed_from_db():
    """
    Return dict slug -> engine_model for SHACMAN engines with >=2 products (DB only, no cache).
    Slug = slugify(engine_model.replace(".", "-")) e.g. WP13.550E501 -> wp13-550e501.
    Base: is_active=True (match prod "в БД N раз"). Cap 20.
    """
    from django.db.models import Count

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True)
    qs = (
        base.exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        .values("engine_model")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2)
        .order_by("-cnt")[:20]
    )
    out = {}
    for row in qs:
        em = (row.get("engine_model") or "").strip()
        if em:
            slug = _shacman_engine_slug(em)
            if slug:
                out[slug] = em
    return out


SHACMAN_ENGINE_CATEGORY_CAP = 50

# Minimum products for indexable hub (sitemap + index,follow). Below this: 200 + noindex,follow, not in sitemap.
HUB_INDEX_MIN_PRODUCTS = 2

# force_index override: minimum content to allow index,follow for thin hubs (1 product)
FORCE_INDEX_MIN_BODY_CHARS = 1500
FORCE_INDEX_MIN_FAQ = 3

# Cap for new combo sitemap sections
SHACMAN_CATEGORY_LINE_CAP = 50
SHACMAN_LINE_FORMULA_CAP = 50
SHACMAN_CATEGORY_LINE_FORMULA_CAP = 50
SHACMAN_MODEL_CODE_CAP = 50


def _shacman_hub_seo_content_sufficient(rec) -> bool:
    """
    True if ShacmanHubSEO record has enough content for force_index (body/text >= FORCE_INDEX_MIN_BODY_CHARS or FAQ >= FORCE_INDEX_MIN_FAQ).
    """
    from .seo_text import visible_len

    if not rec:
        return False
    body_len = max(
        visible_len(rec.seo_body_html or ""),
        visible_len(rec.seo_text or ""),
    )
    if body_len >= FORCE_INDEX_MIN_BODY_CHARS:
        return True
    faq_count = len([line for line in (rec.faq or "").strip().split("\n") if "|" in line.strip()])
    return faq_count >= FORCE_INDEX_MIN_FAQ


def _shacman_hub_force_index_override(hub_type: str, category=None, facet_key: str = "") -> bool:
    """
    True if ShacmanHubSEO exists for this hub with force_index=True and content sufficient.
    Used to allow index,follow for thin hubs (products_count < HUB_INDEX_MIN_PRODUCTS) when white-listed.
    """
    from .models import ShacmanHubSEO

    qs = ShacmanHubSEO.objects.filter(hub_type=hub_type)
    if category is not None:
        qs = qs.filter(category=category)
    else:
        qs = qs.filter(category__isnull=True)
    key = (facet_key or "").strip()
    if key:
        qs = qs.filter(facet_key__iexact=key)
    else:
        qs = qs.filter(facet_key="")
    rec = qs.first()
    return bool(rec and getattr(rec, "force_index", False) and _shacman_hub_seo_content_sufficient(rec))


def _shacman_engine_category_allowed_from_db():
    """
    Allowed engine+category hubs: (engine_slug, category_slug) with >=1 product, where engine is in
    engine allow-list (>=2 products per engine). DB only, no cache. Synced with shacman_category_engine_hub
    and _shacman_engine_category_hub_queryset (hub returns 200 only when engine_slug in engine_mapping).
    No 404 URLs in ShacmanCategoryEngineSitemap.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    engine_allowed = _shacman_engine_allowed_from_db()  # engines with >=2 products (same as hub queryset)
    if not engine_allowed:
        return set()

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(engine_model__isnull=True).exclude(engine_model="").exclude(category__isnull=True)
    qs = (
        base.values("engine_model", "category__slug")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=1)
        .exclude(category__slug__isnull=True)
        .order_by("-cnt")[:SHACMAN_ENGINE_CATEGORY_CAP]
    )
    out = set()
    for row in qs:
        em = (row.get("engine_model") or "").strip()
        cat = (row.get("category__slug") or "").strip()
        if em and cat:
            eng_slug = _shacman_engine_slug(em)
            cat_slug = django_slugify(cat)
            if eng_slug and cat_slug and eng_slug in engine_allowed:
                out.add((eng_slug, cat_slug))
    return out


def _shacman_line_allowed_from_db():
    """
    Return dict slug -> line_label for SHACMAN model_variant.line with >=2 products (DB only, no cache).
    Slug = slugify(line). Base: is_active=True. Cap 20.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True)
    qs = (
        base.exclude(model_variant__isnull=True)
        .values("model_variant__line")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .order_by("-cnt")[:20]
    )
    out = {}
    for row in qs:
        line = (row.get("model_variant__line") or "").strip()
        if line:
            slug = django_slugify(line)
            if slug:
                out[slug] = line
    return out


def _shacman_hub_diag(request):
    """True if request has X-Carfast-Diag: 1 (enable diagnostic 404 response and step logging)."""
    return (request.headers.get("X-Carfast-Diag") or request.META.get("HTTP_X_CARFAST_DIAG")) == "1"


def _shacman_404_response(request, view_name, reason, **extra_headers):
    """Return HttpResponseNotFound with X-Diag-Resolver-View and X-Diag-Reason when X-Carfast-Diag: 1."""
    resp = HttpResponseNotFound(b"404")
    if _shacman_hub_diag(request):
        resp["X-Diag-Resolver-View"] = view_name
        resp["X-Diag-Reason"] = reason
        for k, v in extra_headers.items():
            if k and v is not None:
                resp[k] = str(v)
    return resp


def _log_shacman_hub_404_diagnostic(engine_slug=None, line_slug=None, mapping_engine=None, mapping_line=None, hub_type="engine"):
    """Log diagnostic context before raising Http404 on engine/line hub (for journalctl)."""
    cache_backend = ""
    db_name = ""
    try:
        cache_backend = str(settings.CACHES.get("default", {}).get("BACKEND", ""))
        db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
    except Exception:
        pass
    try:
        shacman_count = Product.objects.filter(
            series__slug__iexact="shacman", is_active=True
        ).count()
    except Exception as e:
        shacman_count = "error: %s" % e
    slug = engine_slug if hub_type == "engine" else line_slug
    mapping = mapping_engine if hub_type == "engine" else mapping_line
    mapping_len = len(mapping) if mapping is not None else 0
    sample = list(mapping.keys())[:3] if mapping else []
    logger.warning(
        "shacman_%s_hub 404 slug=%r cache_backend=%r db_name=%r shacman_count=%s mapping_len=%s sample=%s",
        hub_type, slug, cache_backend, db_name, shacman_count, mapping_len, sample,
    )


# Cache keys for SHACMAN allowed clusters (versioned to survive old list-of-tuples format)
SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2 = "shacman_allowed_clusters_v2"
SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY = "shacman_allowed_clusters"
SHACMAN_ALLOWED_CLUSTERS_CACHE_TIMEOUT = 300  # 5 min


def _normalize_shacman_allowed_clusters(data):
    """
    Ensure engine_slugs/line_slugs are set[str] and engine_labels/line_labels are dict.
    Accepts legacy format: engine_slugs/line_slugs as list of (slug, label) tuples.
    Returns normalized dict; does not mutate input.
    """
    if not data or not isinstance(data, dict):
        return data
    out = dict(data)
    # engine_slugs: ensure set of str; engine_labels: dict slug -> label
    es = data.get("engine_slugs")
    if isinstance(es, list):
        slugs = set()
        labels = dict(data.get("engine_labels") or {})
        for item in es:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                s = str(item[0]).strip()
                if s:
                    slugs.add(s)
                    labels[s] = item[1]
            elif isinstance(item, str) and item.strip():
                slugs.add(item.strip())
        out["engine_slugs"] = slugs
        out["engine_labels"] = labels
    elif isinstance(es, set):
        out["engine_slugs"] = set(es)
        out["engine_labels"] = dict(data.get("engine_labels") or {})
    else:
        out["engine_slugs"] = set()
        out["engine_labels"] = dict(data.get("engine_labels") or {})

    # line_slugs: ensure set of str; line_labels: dict slug -> label
    ls = data.get("line_slugs")
    if isinstance(ls, list):
        slugs = set()
        labels = dict(data.get("line_labels") or {})
        for item in ls:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                s = str(item[0]).strip()
                if s:
                    slugs.add(s)
                    labels[s] = item[1]
            elif isinstance(item, str) and item.strip():
                slugs.add(item.strip())
        out["line_slugs"] = slugs
        out["line_labels"] = labels
    elif isinstance(ls, set):
        out["line_slugs"] = set(ls)
        out["line_labels"] = dict(data.get("line_labels") or {})
    else:
        out["line_slugs"] = set()
        out["line_labels"] = dict(data.get("line_labels") or {})

    return out


def _shacman_allowed_clusters_fresh():
    """
    Compute allowed clusters from DB without reading/writing cache.
    Same structure as _shacman_allowed_clusters() return value.
    Use for fallback when slug not in cached allowed (e.g. LocMemCache per-worker stale).
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = (
        Product.objects.public()
        .filter(series__slug__iexact="shacman")
        .exclude(series__isnull=True)
    )
    out = {"series_slugs": [], "formulas": [], "engine_slugs": set(), "engine_labels": {}, "line_slugs": set(), "line_labels": {}}
    cap = 20

    series_qs = (
        base.exclude(model_variant__isnull=True)
        .values("model_variant__line")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .order_by("-cnt")[:cap]
    )
    for row in series_qs:
        line = (row.get("model_variant__line") or "").strip()
        if line:
            slug = django_slugify(line)
            if slug:
                out["series_slugs"].append((slug, line))

    formula_qs = (
        base.values("wheel_formula")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2)
        .order_by("-cnt")[:cap]
    )
    seen_formulas = set()
    for row in formula_qs:
        wf = _shacman_normalize_formula(row.get("wheel_formula"))
        if wf and wf not in seen_formulas:
            seen_formulas.add(wf)
            out["formulas"].append(wf)

    engine_qs = (
        base.exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        .values("engine_model")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2)
        .order_by("-cnt")[:cap]
    )
    for row in engine_qs:
        em = (row.get("engine_model") or "").strip()
        if em:
            slug = _shacman_engine_slug(em)
            if slug:
                out["engine_slugs"].add(slug)
                out["engine_labels"][slug] = em

    for slug, label in out["series_slugs"]:
        out["line_slugs"].add(slug)
        out["line_labels"][slug] = label

    return out


def _shacman_allowed_clusters():
    """
    Return allowed clusters for B3 hubs (count >= 2, cap 20).
    - series_slugs: list of (slug, label) — unchanged.
    - formulas: list of str — unchanged.
    - engine_slugs: set of slug str; engine_labels: dict slug -> label.
    - line_slugs: set of slug str; line_labels: dict slug -> label.
    Cached under SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2; legacy key normalized and migrated.
    """
    # Try v2 cache first
    data = _cache_get_safe(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2)
    if data is not None:
        return _normalize_shacman_allowed_clusters(data)

    # Try legacy key (list-of-tuples format), normalize and migrate to v2
    data = _cache_get_safe(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY)
    if data is not None:
        normalized = _normalize_shacman_allowed_clusters(data)
        _cache_set_safe(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2, normalized, SHACMAN_ALLOWED_CLUSTERS_CACHE_TIMEOUT)
        try:
            from django.core.cache import cache
            cache.delete(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_LEGACY)
        except Exception:
            pass
        return normalized

    # Compute fresh and cache
    out = _shacman_allowed_clusters_fresh()
    _cache_set_safe(SHACMAN_ALLOWED_CLUSTERS_CACHE_KEY_V2, out, SHACMAN_ALLOWED_CLUSTERS_CACHE_TIMEOUT)
    return out


def _shacman_series_hub_queryset(series_slug, in_stock_only=False):
    """Products for /shacman/series/<series_slug>/ (match by model_variant line slug)."""
    from django.utils.text import slugify as django_slugify

    series = _shacman_series()
    if not series:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, model_variant__isnull=False)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    # Match model_variant.line slugified == series_slug
    from django.db.models import Q
    from django.db.models.functions import Lower
    # Filter by model_variant whose line slugifies to series_slug
    model_variant_ids = [
        mv.id for mv in ModelVariant.objects.filter(brand=series)
        if django_slugify((mv.line or "").strip()) == series_slug
    ]
    qs = qs.filter(model_variant_id__in=model_variant_ids) if model_variant_ids else Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _shacman_line_hub_queryset(line_slug, in_stock_only=False):
    """Products for /shacman/line/<line_slug>/ (match by model_variant.line slug, same as series)."""
    from django.utils.text import slugify as django_slugify

    series = _shacman_series()
    if not series:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, model_variant__isnull=False)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    model_variant_ids = [
        mv.id for mv in ModelVariant.objects.filter(brand=series)
        if django_slugify((mv.line or "").strip()) == line_slug
    ]
    qs = qs.filter(model_variant_id__in=model_variant_ids) if model_variant_ids else Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


SHACMAN_CATEGORY_FORMULA_CAP = 50


def _shacman_category_formula_allowed_from_db(min_count=None):
    """
    Allowed category+formula hubs: (category_slug, formula) with count >= min_count. DB only, no cache.
    For sitemap use min_count=HUB_INDEX_MIN_PRODUCTS; for view use min_count=1 (then noindex when count < HUB_INDEX_MIN_PRODUCTS).
    Cap SHACMAN_CATEGORY_FORMULA_CAP. formula normalized via _shacman_normalize_formula.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    if min_count is None:
        min_count = HUB_INDEX_MIN_PRODUCTS
    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(category__isnull=True).exclude(category__slug__isnull=True)
    qs = (
        base.values("category__slug", "wheel_formula")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=min_count)
        .order_by("-cnt")[:SHACMAN_CATEGORY_FORMULA_CAP]
    )
    norm = _shacman_normalize_formula
    out = set()
    for row in qs:
        cat = (row.get("category__slug") or "").strip()
        formula_raw = (row.get("wheel_formula") or "").strip()
        formula = norm(formula_raw)
        if cat and formula:
            cat_slug = django_slugify(cat)
            if cat_slug:
                out.add((cat_slug, formula))
    return out


def _shacman_category_formula_hub_queryset(category_slug, formula, in_stock_only=False):
    """Products for /shacman/<category_slug>/<formula>/ (and in-stock). Formula normalized."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    norm = _shacman_normalize_formula(formula)
    if not norm:
        return Product.objects.none()
    category = Category.objects.filter(slug__iexact=category_slug).first()
    if not category:
        return Product.objects.none()
    from django.db.models import Q
    qs = (
        Product.objects.public()
        .filter(series=series, category=category)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    qs = qs.filter(
        Q(wheel_formula__iexact=norm) | Q(wheel_formula__iexact=norm.replace("x", "\u00d7"))
    )
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


SHACMAN_COMBO_HUB_CAP = 50


class ShacmanComboAllowed(NamedTuple):
    """Named result of _shacman_combo_allowed_from_db(); use .lc and .lcf to avoid tuple unpacking errors."""
    lc: set  # set of (line_slug, category_slug)
    lcf: set  # set of (line_slug, category_slug, formula)


def _shacman_combo_allowed_from_db() -> ShacmanComboAllowed:
    """
    Allowed combo hubs: (line_slug, category_slug) and (line_slug, category_slug, formula) with >=2 products.
    Keys are strictly slug form: line_slug=slugify(line.strip()), category_slug=slugify(cat.strip()),
    formula=normalized lower (4x2/6x4/8x4). No cache/global state.
    Returns ShacmanComboAllowed(lc=..., lcf=...) — use allowed.lc and allowed.lcf.
    Cap SHACMAN_COMBO_HUB_CAP each, ordered by count desc.
    """
    from collections import Counter
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_variant__isnull=True).exclude(category__isnull=True)
    # (line_slug, category_slug) — keys strictly slug form to match URL
    line_cat_qs = (
        base.values("model_variant__line", "category__slug")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .exclude(category__slug__isnull=True)
        .order_by("-cnt")[:SHACMAN_COMBO_HUB_CAP]
    )
    allowed_line_category = set()
    for row in line_cat_qs:
        line = (row.get("model_variant__line") or "").strip()
        cat = (row.get("category__slug") or "").strip()
        if line and cat:
            line_slug = django_slugify(line)
            cat_slug = django_slugify(cat)
            if line_slug and cat_slug:
                allowed_line_category.add((line_slug, cat_slug))
    # (line_slug, category_slug, formula) — formula = normalized lower
    norm = _shacman_normalize_formula
    raw = (
        base.values("model_variant__line", "category__slug", "wheel_formula")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .exclude(category__slug__isnull=True)
    )
    combo_counts = Counter()
    for row in raw:
        line = (row.get("model_variant__line") or "").strip()
        cat = (row.get("category__slug") or "").strip()
        formula_raw = (row.get("wheel_formula") or "").strip().lower()
        formula = norm(formula_raw)
        if line and cat and formula:
            line_slug = django_slugify(line)
            cat_slug = django_slugify(cat)
            if line_slug and cat_slug:
                key = (line_slug, cat_slug, formula)
                combo_counts[key] = combo_counts.get(key, 0) + row["cnt"]
    allowed_line_category_formula = set()
    for (line_sl, cat_sl, formula), cnt in combo_counts.most_common(SHACMAN_COMBO_HUB_CAP):
        if cnt >= 2:
            allowed_line_category_formula.add((line_sl, cat_sl, formula))
    return ShacmanComboAllowed(lc=allowed_line_category, lcf=allowed_line_category_formula)


def _shacman_category_line_allowed_from_db(min_count=1):
    """
    Allowed category-first line+category: (category_slug, line_slug) with count >= min_count.
    For view: min_count=1 (200 + noindex if < HUB_INDEX_MIN_PRODUCTS). For sitemap: min_count=HUB_INDEX_MIN_PRODUCTS.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_variant__isnull=True).exclude(category__isnull=True)
    qs = (
        base.values("category__slug", "model_variant__line")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=min_count, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .exclude(category__slug__isnull=True)
        .order_by("-cnt")[:SHACMAN_CATEGORY_LINE_CAP]
    )
    out = set()
    for row in qs:
        cat = (row.get("category__slug") or "").strip()
        line = (row.get("model_variant__line") or "").strip()
        if cat and line:
            cat_slug = django_slugify(cat)
            line_slug = django_slugify(line)
            if cat_slug and line_slug:
                out.add((cat_slug, line_slug))
    return out


def _shacman_category_line_indexable():
    """
    (category_slug, line_slug) pairs to include in sitemap: count >= HUB_INDEX_MIN_PRODUCTS OR (force_index + sufficient content).
    Only includes pairs that exist in allowed(min_count=1) so URLs never 404.
    """
    from .models import ShacmanHubSEO

    thick = _shacman_category_line_allowed_from_db(min_count=HUB_INDEX_MIN_PRODUCTS)
    allowed_any = _shacman_category_line_allowed_from_db(min_count=1)
    thin_override = set()
    for rec in ShacmanHubSEO.objects.filter(
        hub_type__in=("category_line", "category_line_in_stock"),
        force_index=True,
    ).exclude(category__isnull=True).exclude(facet_key="").select_related("category"):
        if _shacman_hub_seo_content_sufficient(rec):
            key = (rec.category.slug, (rec.facet_key or "").strip())
            if key in allowed_any:
                thin_override.add(key)
    return thick | thin_override


def _shacman_line_formula_indexable():
    """
    (line_slug, formula) pairs to include in sitemap: count >= HUB_INDEX_MIN_PRODUCTS OR (force_index + sufficient content).
    """
    from .models import ShacmanHubSEO

    thick = _shacman_line_formula_allowed_from_db(min_count=HUB_INDEX_MIN_PRODUCTS)
    allowed_any = _shacman_line_formula_allowed_from_db(min_count=1)
    thin_override = set()
    for rec in ShacmanHubSEO.objects.filter(
        hub_type__in=("line_formula", "line_formula_in_stock"),
        category__isnull=True,
    ).exclude(facet_key=""):
        if getattr(rec, "force_index", False) and _shacman_hub_seo_content_sufficient(rec):
            key = tuple((rec.facet_key or "").strip().split(":", 1))  # line_slug, formula
            if len(key) == 2 and key in allowed_any:
                thin_override.add(key)
    return thick | thin_override


def _shacman_category_formula_indexable():
    """
    (category_slug, formula) pairs to include in sitemap: count >= HUB_INDEX_MIN_PRODUCTS OR (force_index + sufficient content).
    """
    from .models import ShacmanHubSEO

    thick = _shacman_category_formula_allowed_from_db(min_count=HUB_INDEX_MIN_PRODUCTS)
    allowed_any = _shacman_category_formula_allowed_from_db(min_count=1)
    thin_override = set()
    for rec in ShacmanHubSEO.objects.filter(
        hub_type__in=("category_formula_explicit", "category_formula_explicit_in_stock"),
    ).exclude(category__isnull=True).exclude(facet_key="").select_related("category"):
        if getattr(rec, "force_index", False) and _shacman_hub_seo_content_sufficient(rec):
            key = (rec.category.slug, (rec.facet_key or "").strip())
            if key in allowed_any:
                thin_override.add(key)
    return thick | thin_override


def _shacman_category_line_formula_allowed_from_db(min_count=1):
    """
    Allowed category+line+formula: (category_slug, line_slug, formula) with count >= min_count.
    For view: min_count=1 (200 + noindex if < HUB_INDEX_MIN_PRODUCTS). For sitemap: min_count=HUB_INDEX_MIN_PRODUCTS.
    formula normalized via _shacman_normalize_formula.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_variant__isnull=True).exclude(category__isnull=True)
    qs = (
        base.values("category__slug", "model_variant__line", "wheel_formula")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=min_count, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .exclude(category__slug__isnull=True)
        .order_by("-cnt")[:SHACMAN_CATEGORY_LINE_FORMULA_CAP]
    )
    norm = _shacman_normalize_formula
    out = set()
    for row in qs:
        cat = (row.get("category__slug") or "").strip()
        line = (row.get("model_variant__line") or "").strip()
        formula_raw = (row.get("wheel_formula") or "").strip()
        formula = norm(formula_raw)
        if cat and line and formula:
            cat_slug = django_slugify(cat)
            line_slug = django_slugify(line)
            if cat_slug and line_slug:
                out.add((cat_slug, line_slug, formula))
    return out


def _shacman_category_line_formula_indexable():
    """
    (category_slug, line_slug, formula) triples to include in sitemap: count >= HUB_INDEX_MIN_PRODUCTS OR (force_index + sufficient content).
    """
    from .models import ShacmanHubSEO

    thick = _shacman_category_line_formula_allowed_from_db(min_count=HUB_INDEX_MIN_PRODUCTS)
    allowed_any = _shacman_category_line_formula_allowed_from_db(min_count=1)
    thin_override = set()
    for rec in ShacmanHubSEO.objects.filter(
        hub_type__in=("category_line_formula", "category_line_formula_in_stock"),
    ).exclude(category__isnull=True).exclude(facet_key="").select_related("category"):
        if getattr(rec, "force_index", False) and _shacman_hub_seo_content_sufficient(rec):
            parts = (rec.facet_key or "").strip().split(":", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                key = (rec.category.slug, parts[0].strip(), parts[1].strip())
                if key in allowed_any:
                    thin_override.add(key)
    return thick | thin_override


def _shacman_line_formula_allowed_from_db(min_count=1):
    """
    Allowed line+formula (no category): (line_slug, formula) with count >= min_count.
    formula normalized via _shacman_normalize_formula. For sitemap use min_count=HUB_INDEX_MIN_PRODUCTS.
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_variant__isnull=True).exclude(category__isnull=True)
    qs = (
        base.values("model_variant__line", "wheel_formula")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=min_count, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .order_by("-cnt")[:SHACMAN_LINE_FORMULA_CAP]
    )
    norm = _shacman_normalize_formula
    out = set()
    for row in qs:
        line = (row.get("model_variant__line") or "").strip()
        formula_raw = (row.get("wheel_formula") or "").strip()
        formula = norm(formula_raw)
        if line and formula:
            line_slug = django_slugify(line)
            if line_slug:
                out.add((line_slug, formula))
    return out


def _shacman_model_code_slugify(raw: str) -> str:
    """Normalize model_code to URL slug (same as Product slug generation)."""
    from django.utils.text import slugify as django_slugify
    return (django_slugify((raw or "").lower()) or "").strip()


def _shacman_model_code_allowed_from_db(min_count=1):
    """
    Allowed model_code slugs for /shacman/model/<model_code_slug>/: set of slug strings with count >= min_count.
    """
    from django.db.models import Count
    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_code__isnull=True).exclude(model_code="")
    qs = (
        base.values("model_code")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=min_count)
        .order_by("-cnt")[:SHACMAN_MODEL_CODE_CAP]
    )
    out = set()
    for row in qs:
        code = (row.get("model_code") or "").strip()
        if code:
            slug = _shacman_model_code_slugify(code)
            if slug:
                out.add(slug)
    return out


def _shacman_model_code_slug_to_raw(model_code_slug: str):
    """Return list of raw model_code values that slugify to model_code_slug (for Shacman products)."""
    series = _shacman_series()
    if not series:
        return []
    codes = list(
        Product.objects.filter(
            series=series,
            is_active=True,
        )
        .exclude(model_code__isnull=True)
        .exclude(model_code="")
        .values_list("model_code", flat=True)
        .distinct()
    )
    return [c for c in codes if (c and _shacman_model_code_slugify(c) == model_code_slug)]


def _shacman_model_code_hub_queryset(model_code_slug: str, in_stock_only=False):
    """Products for /shacman/model/<model_code_slug>/ (and in-stock)."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    raw_codes = _shacman_model_code_slug_to_raw(model_code_slug)
    if not raw_codes:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, model_code__in=raw_codes)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _shacman_model_code_indexable():
    """model_code_slug set to include in sitemap: count >= HUB_INDEX_MIN_PRODUCTS OR (force_index + sufficient content)."""
    from .models import ShacmanHubSEO

    thick = _shacman_model_code_allowed_from_db(min_count=HUB_INDEX_MIN_PRODUCTS)
    allowed_any = _shacman_model_code_allowed_from_db(min_count=1)
    thin_override = set()
    for rec in ShacmanHubSEO.objects.filter(
        hub_type__in=("model_code", "model_code_in_stock"),
        category__isnull=True,
    ).exclude(facet_key=""):
        if getattr(rec, "force_index", False) and _shacman_hub_seo_content_sufficient(rec):
            key = (rec.facet_key or "").strip()
            if key in allowed_any:
                thin_override.add(key)
    return thick | thin_override


def _shacman_line_category_hub_queryset(line_slug, category_slug, formula=None, in_stock_only=False):
    """Products for /shacman/line/<line_slug>/<category_slug>/ or +/<formula>/ (combo hub).
    Uses _shacman_line_allowed_from_db() raw line value for filter (not slug comparison).
    """
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    line_mapping = _shacman_line_allowed_from_db()
    if line_slug not in line_mapping:
        return Product.objects.none()
    raw_line = (line_mapping[line_slug] or "").strip()
    if not raw_line:
        return Product.objects.none()
    category = Category.objects.filter(slug__iexact=category_slug).first()
    if not category:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, category=category, model_variant__isnull=False)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    model_variant_ids = [
        mv.id for mv in ModelVariant.objects.filter(brand=series)
        if (getattr(mv, "line", None) or "").strip() == raw_line
    ]
    qs = qs.filter(model_variant_id__in=model_variant_ids) if model_variant_ids else Product.objects.none()
    if formula:
        norm = _shacman_normalize_formula(formula)
        if norm:
            from django.db.models import Q
            qs = qs.filter(
                Q(wheel_formula__iexact=norm) | Q(wheel_formula__iexact=norm.replace("x", "\u00d7"))
            )
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _shacman_line_formula_hub_queryset(line_slug, formula, in_stock_only=False):
    """Products for /shacman/line/<line_slug>/formula/<formula>/ (no category). Formula normalized."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    line_mapping = _shacman_line_allowed_from_db()
    if line_slug not in line_mapping:
        return Product.objects.none()
    raw_line = (line_mapping[line_slug] or "").strip()
    if not raw_line:
        return Product.objects.none()
    norm = _shacman_normalize_formula(formula)
    if not norm:
        return Product.objects.none()
    from django.db.models import Q

    model_variant_ids = [
        mv.id for mv in ModelVariant.objects.filter(brand=series)
        if (getattr(mv, "line", None) or "").strip() == raw_line
    ]
    qs = (
        Product.objects.public()
        .filter(series=series, model_variant_id__in=model_variant_ids if model_variant_ids else [])
        .filter(Q(wheel_formula__iexact=norm) | Q(wheel_formula__iexact=norm.replace("x", "\u00d7")))
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    if not model_variant_ids:
        qs = Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _shacman_category_line_formula_hub_queryset(category_slug, line_slug, formula, in_stock_only=False):
    """Products for /shacman/category/<category_slug>/line/<line_slug>/formula/<formula_slug>/ (category-first). Delegates to line+category+formula."""
    return _shacman_line_category_hub_queryset(
        line_slug, category_slug, formula=formula, in_stock_only=in_stock_only
    )


def _get_shacman_combo_hub_seo_content(line_label, category_name, formula=None, in_stock=False):
    """SEO content for combo hubs: title, description, h1 from unified meta generator."""
    hub_type = "line_category_in_stock" if in_stock else "line_category"
    meta = build_shacman_hub_meta(
        hub_type,
        line_label=line_label,
        category_name=category_name,
        formula=formula,
        in_stock=in_stock,
    )
    faq_items = []
    default_also = "Также ищут: Шакман / Shacman / Shaanxi"
    return {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "seo_intro_html": "",
        "seo_body_html": "",
        "faq_items": faq_items,
        "also_search_line": default_also,
    }


def _get_shacman_combo_hub_seo_content_from_db(hub_type: str, category=None, facet_key: str = ""):
    """
    Load SEO content for combo hub types from ShacmanHubSEO (category_line, line_formula, category_formula_explicit + in_stock).
    facet_key: for category_line = line_slug; for line_formula = "line_slug:formula"; for category_formula_explicit = formula.
    Returns dict with meta_title, meta_description, meta_h1, seo_text, seo_intro_html, seo_body_html, faq_items, also_search_line.
    Fallback from build_shacman_hub_meta when no record.
    """
    from .models import ShacmanHubSEO

    rec = ShacmanHubSEO.objects.filter(
        hub_type=hub_type,
        category=category,
        facet_key__iexact=(facet_key or "").strip(),
    ).first()

    # Meta fallbacks by type
    if hub_type in ("category_line", "category_line_in_stock"):
        line_label = facet_key or ""
        category_name = category.name if category else ""
        meta = build_shacman_hub_meta(
            hub_type,
            line_label=line_label,
            category_name=category_name,
            in_stock=(hub_type == "category_line_in_stock"),
        )
    elif hub_type in ("line_formula", "line_formula_in_stock"):
        parts = (facet_key or "").split(":", 1)
        line_label = parts[0] if len(parts) >= 1 else ""
        formula = parts[1] if len(parts) >= 2 else ""
        meta = build_shacman_hub_meta(
            hub_type,
            line_label=line_label,
            formula=formula,
            in_stock=(hub_type == "line_formula_in_stock"),
        )
    elif hub_type in ("category_line_formula", "category_line_formula_in_stock"):
        parts = (facet_key or "").split(":", 1)
        line_label = parts[0] if len(parts) >= 1 else ""
        formula = parts[1] if len(parts) >= 2 else ""
        category_name = category.name if category else ""
        meta = build_shacman_hub_meta(
            hub_type,
            line_label=line_label,
            category_name=category_name,
            formula=formula,
            in_stock=(hub_type == "category_line_formula_in_stock"),
        )
    else:
        # category_formula_explicit / category_formula_explicit_in_stock
        category_name = category.name if category else ""
        meta = build_shacman_hub_meta(
            hub_type,
            category_name=category_name,
            formula=(facet_key or "").strip(),
            in_stock=(hub_type == "category_formula_explicit_in_stock"),
        )

    default_also = "Также ищут: Шакман / Shacman / Shaanxi"
    seo_text = ""
    faq_items = []
    if rec:
        seo_text = (rec.seo_text or "").strip() or ""
        faq_items = _parse_seo_faq(rec.faq or "")
        if not faq_items:
            faq_items = DEFAULT_SHACMAN_HUB_FAQ
        body_html = deduplicate_additional_info_heading((rec.seo_body_html or "").strip())
        text_final = seo_text or DEFAULT_SHACMAN_HUB_SEO_TEXT.strip()
        return {
            "meta_title": (rec.meta_title or "").strip() or meta["title"],
            "meta_description": (rec.meta_description or "").strip() or meta["description"],
            "meta_h1": meta["h1"],
            "seo_text": deduplicate_additional_info_heading(text_final),
            "seo_intro_html": (rec.seo_intro_html or "").strip(),
            "seo_body_html": body_html,
            "faq_items": faq_items,
            "also_search_line": (rec.also_search_line or "").strip() or default_also,
        }
    return {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": deduplicate_additional_info_heading(seo_text or ""),
        "seo_intro_html": "",
        "seo_body_html": "",
        "faq_items": DEFAULT_SHACMAN_HUB_FAQ,
        "also_search_line": default_also,
    }


SHACMAN_COMBO_LINKS_CAP = 20


def _shacman_combo_links_for_display(line_slug=None, category_slug=None):
    """
    Links to combo hubs for "Связанные подборки" block. Only from allow-list (count>=2).
    Filter by line_slug and/or category_slug if provided. Cap SHACMAN_COMBO_LINKS_CAP.
    Returns list of {"url": str, "label": str}.
    """
    allowed = _shacman_combo_allowed_from_db()
    line_labels = _shacman_line_allowed_from_db()
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in={
        cat_slug for (_, cat_slug) in allowed.lc
    } | {cat_slug for (_, cat_slug, _) in allowed.lcf})}
    out = []
    seen = set()
    for (line_sl, cat_sl) in allowed.lc:
        if line_slug is not None and line_sl != line_slug:
            continue
        if category_slug is not None and cat_sl != category_slug:
            continue
        key = ("lc", line_sl, cat_sl, None)
        if key in seen:
            continue
        seen.add(key)
        label_line = line_labels.get(line_sl) or line_sl
        label_cat = category_slugs_to_name.get(cat_sl) or cat_sl
        out.append({
            "url": reverse("shacman_line_category_hub", kwargs={"line_slug": line_sl, "category_slug": cat_sl}),
            "label": f"{label_line} {label_cat}",
        })
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    for (line_sl, cat_sl, formula) in allowed.lcf:
        if line_slug is not None and line_sl != line_slug:
            continue
        if category_slug is not None and cat_sl != category_slug:
            continue
        key = ("lcf", line_sl, cat_sl, formula)
        if key in seen:
            continue
        seen.add(key)
        label_line = line_labels.get(line_sl) or line_sl
        label_cat = category_slugs_to_name.get(cat_sl) or cat_sl
        out.append({
            "url": reverse(
                "shacman_line_category_formula_hub",
                kwargs={"line_slug": line_sl, "category_slug": cat_sl, "formula": formula},
            ),
            "label": f"{label_line} {label_cat} {formula}",
        })
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_engine_combo_links_for_display(engine_slug=None, exclude_url=None):
    """
    Links to engine+category hubs for "Связанные подборки" on engine pages. Only from allow-list (count>=2).
    Filter by engine_slug if provided. Exclude exclude_url from list. Cap SHACMAN_COMBO_LINKS_CAP.
    Returns list of {"url": str, "label": str}.
    """
    allowed_ec = _shacman_engine_category_allowed_from_db()
    engine_labels = _shacman_engine_allowed_from_db()
    category_slugs = {cat_slug for (_, cat_slug) in allowed_ec}
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in=category_slugs)}
    out = []
    for (eng_sl, cat_sl) in sorted(allowed_ec):
        if engine_slug is not None and eng_sl != engine_slug:
            continue
        url = reverse(
            "shacman_engine_category_hub",
            kwargs={"engine_slug": eng_sl, "category_slug": cat_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        label_eng = engine_labels.get(eng_sl) or eng_sl
        label_cat = category_slugs_to_name.get(cat_sl) or cat_sl
        out.append({"url": url, "label": f"{label_eng} {label_cat}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_line_engine_links_for_display(line_slug=None, engine_slug=None, exclude_url=None):
    """
    Links to line+engine hubs for "Связанные подборки". Only from allow-list (count>=2).
    Filter by line_slug and/or engine_slug if provided. Exclude exclude_url. Cap SHACMAN_COMBO_LINKS_CAP.
    """
    allowed = _shacman_line_engine_allowed_from_db()
    line_labels = _shacman_line_allowed_from_db()
    engine_labels = _shacman_engine_allowed_from_db()
    out = []
    for (line_sl, eng_sl) in sorted(allowed):
        if line_slug is not None and line_sl != line_slug:
            continue
        if engine_slug is not None and eng_sl != engine_slug:
            continue
        url = reverse(
            "shacman_line_engine_hub",
            kwargs={"line_slug": line_sl, "engine_slug": eng_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        label_line = line_labels.get(line_sl) or line_sl
        label_eng = engine_labels.get(eng_sl) or eng_sl
        out.append({"url": url, "label": f"{label_line} {label_eng}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_category_formula_links_for_display(category_slug=None, exclude_url=None):
    """
    Links to category+formula hubs for "Связанные подборки". Only from allow-list (count>=2).
    Filter by category_slug if provided. Exclude exclude_url. Cap SHACMAN_COMBO_LINKS_CAP.
    """
    allowed = _shacman_category_formula_allowed_from_db()
    category_slugs = {cat_slug for (cat_slug, _) in allowed}
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in=category_slugs)}
    out = []
    for (cat_sl, formula) in sorted(allowed):
        if category_slug is not None and cat_sl != category_slug:
            continue
        url = reverse(
            "shacman_category_formula_hub",
            kwargs={"category_slug": cat_sl, "formula": formula},
        )
        if exclude_url and url == exclude_url:
            continue
        label_cat = category_slugs_to_name.get(cat_sl) or cat_sl
        out.append({"url": url, "label": f"{label_cat} {formula}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_category_line_popular_links(category_slug, line_slug, exclude_url=None):
    """
    "Популярные подборки" for category+line hub: formulas (explicit), other lines, in-stock. Only allowed pairs.
    """
    out = []
    allowed_cl = _shacman_category_line_allowed_from_db(min_count=1)
    allowed_cf = _shacman_category_formula_allowed_from_db(min_count=1)
    line_labels = _shacman_line_allowed_from_db()
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in={category_slug})}
    label_cat = category_slugs_to_name.get(category_slug) or category_slug
    label_line = line_labels.get(line_slug) or line_slug
    # In-stock same category+line
    if (category_slug, line_slug) in allowed_cl:
        url = reverse(
            "shacman_category_line_in_stock_hub",
            kwargs={"category_slug": category_slug, "line_slug": line_slug},
        )
        if not exclude_url or url != exclude_url:
            out.append({"url": url, "label": f"{label_cat} {label_line} — в наличии"})
    for (cat_sl, formula) in sorted(allowed_cf):
        if cat_sl != category_slug:
            continue
        url = reverse(
            "shacman_category_formula_explicit_hub",
            kwargs={"category_slug": cat_sl, "formula_slug": formula},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_cat} {formula}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    for (cat_sl, line_sl) in sorted(allowed_cl):
        if cat_sl != category_slug or line_sl == line_slug:
            continue
        url = reverse(
            "shacman_category_line_hub",
            kwargs={"category_slug": cat_sl, "line_slug": line_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        lbl = line_labels.get(line_sl) or line_sl
        out.append({"url": url, "label": f"{label_cat} {lbl}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_line_formula_popular_links(line_slug, formula, exclude_url=None):
    """
    "Популярные подборки" for line+formula hub: line+category, other formulas, in-stock. Only allowed pairs.
    """
    out = []
    allowed_lc = _shacman_combo_allowed_from_db().lc
    allowed_lf = _shacman_line_formula_allowed_from_db(min_count=1)
    line_labels = _shacman_line_allowed_from_db()
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(
        slug__in={cat_sl for (_, cat_sl) in allowed_lc}
    )}
    label_line = line_labels.get(line_slug) or line_slug
    # In-stock same line+formula
    if (line_slug, formula) in allowed_lf:
        url = reverse(
            "shacman_line_formula_in_stock_hub",
            kwargs={"line_slug": line_slug, "formula_slug": formula},
        )
        if not exclude_url or url != exclude_url:
            out.append({"url": url, "label": f"{label_line} {formula} — в наличии"})
    for (line_sl, cat_sl) in sorted(allowed_lc):
        if line_sl != line_slug:
            continue
        url = reverse(
            "shacman_line_category_hub",
            kwargs={"line_slug": line_sl, "category_slug": cat_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        label_cat = category_slugs_to_name.get(cat_sl) or cat_sl
        out.append({"url": url, "label": f"{label_line} {label_cat}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    for (line_sl, form) in sorted(allowed_lf):
        if line_sl != line_slug or form == formula:
            continue
        url = reverse(
            "shacman_line_formula_hub",
            kwargs={"line_slug": line_sl, "formula_slug": form},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_line} {form}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_category_formula_explicit_popular_links(category_slug, formula, exclude_url=None):
    """
    "Популярные подборки" for category+formula (explicit) hub: lines, other formulas, in-stock. Only allowed pairs.
    """
    out = []
    allowed_cl = _shacman_category_line_allowed_from_db(min_count=1)
    allowed_cf = _shacman_category_formula_allowed_from_db(min_count=1)
    line_labels = _shacman_line_allowed_from_db()
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in={category_slug})}
    label_cat = category_slugs_to_name.get(category_slug) or category_slug
    # In-stock same category+formula
    if (category_slug, formula) in allowed_cf:
        url = reverse(
            "shacman_category_formula_explicit_in_stock_hub",
            kwargs={"category_slug": category_slug, "formula_slug": formula},
        )
        if not exclude_url or url != exclude_url:
            out.append({"url": url, "label": f"{label_cat} {formula} — в наличии"})
    for (cat_sl, line_sl) in sorted(allowed_cl):
        if cat_sl != category_slug:
            continue
        url = reverse(
            "shacman_category_line_hub",
            kwargs={"category_slug": cat_sl, "line_slug": line_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        lbl = line_labels.get(line_sl) or line_sl
        out.append({"url": url, "label": f"{label_cat} {lbl}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    for (cat_sl, form) in sorted(allowed_cf):
        if cat_sl != category_slug or form == formula:
            continue
        url = reverse(
            "shacman_category_formula_explicit_hub",
            kwargs={"category_slug": cat_sl, "formula_slug": form},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_cat} {form}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_category_line_formula_popular_links(category_slug, line_slug, formula, exclude_url=None):
    """
    "Популярные подборки" for category+line+formula hub: in-stock same triple, neighbor formulas (same category+line),
    category+line (no formula), line+formula (no category). Only allowed pairs/triples; exclude current URL.
    """
    out = []
    allowed_clf = _shacman_category_line_formula_allowed_from_db(min_count=1)
    allowed_cl = _shacman_category_line_allowed_from_db(min_count=1)
    allowed_lf = _shacman_line_formula_allowed_from_db(min_count=1)
    line_labels = _shacman_line_allowed_from_db()
    category_slugs_to_name = {c.slug: c.name for c in Category.objects.filter(slug__in={category_slug})}
    label_cat = category_slugs_to_name.get(category_slug) or category_slug
    label_line = line_labels.get(line_slug) or line_slug
    # In-stock same category+line+formula
    if (category_slug, line_slug, formula) in allowed_clf:
        url = reverse(
            "shacman_category_line_formula_in_stock_hub",
            kwargs={"category_slug": category_slug, "line_slug": line_slug, "formula_slug": formula},
        )
        if not exclude_url or url != exclude_url:
            out.append({"url": url, "label": f"{label_cat} {label_line} {formula} — в наличии"})
    # Neighbor formulas (same category+line)
    for (cat_sl, line_sl, form) in sorted(allowed_clf):
        if cat_sl != category_slug or line_sl != line_slug or form == formula:
            continue
        url = reverse(
            "shacman_category_line_formula_hub",
            kwargs={"category_slug": cat_sl, "line_slug": line_sl, "formula_slug": form},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_cat} {label_line} {form}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    # Category+line (no formula)
    for (cat_sl, line_sl) in sorted(allowed_cl):
        if cat_sl != category_slug or line_sl != line_slug:
            continue
        url = reverse(
            "shacman_category_line_hub",
            kwargs={"category_slug": cat_sl, "line_slug": line_sl},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_cat} {label_line}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    # Line+formula (no category)
    for (line_sl, form) in sorted(allowed_lf):
        if line_sl != line_slug or form != formula:
            continue
        url = reverse(
            "shacman_line_formula_hub",
            kwargs={"line_slug": line_sl, "formula_slug": form},
        )
        if exclude_url and url == exclude_url:
            continue
        out.append({"url": url, "label": f"{label_line} {form}"})
        if len(out) >= SHACMAN_COMBO_LINKS_CAP:
            return out
    return out


def _shacman_formula_hub_queryset(formula, in_stock_only=False):
    """Products for /shacman/formula/<formula>/ (normalized wheel_formula)."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    norm = _shacman_normalize_formula(formula)
    if not norm:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series)
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    from django.db.models import Q
    # Match normalized wheel_formula (4x2, 6x4, 8x4 or with ×)
    qs = qs.filter(
        Q(wheel_formula__iexact=norm)
        | Q(wheel_formula__iexact=norm.replace("x", "\u00d7"))
    )
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _shacman_engine_hub_queryset(engine_slug, in_stock_only=False):
    """Products for /shacman/engine/<engine_slug>/ (engine_model normalized: dot->hyphen then slugify)."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series)
        .exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    ids = [
        p.id
        for p in Product.objects.public()
        .filter(series=series)
        .exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        if _shacman_engine_slug(p.engine_model) == engine_slug
    ]
    qs = qs.filter(id__in=ids) if ids else Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def get_engine_in_stock_qs(engine_slug):
    """
    Single source of truth: queryset for /shacman/engine/<engine_slug>/in-stock/.
    View and sitemap use this; include in sitemap only when .exists() is True.
    """
    return _shacman_engine_hub_queryset(engine_slug, in_stock_only=True)


def _shacman_engine_category_hub_queryset(engine_slug, category_slug, in_stock_only=False):
    """Products for /shacman/engine/<engine_slug>/<category_slug>/ (and in-stock)."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    category = Category.objects.filter(slug__iexact=category_slug).first()
    if not category:
        return Product.objects.none()
    engine_mapping = _shacman_engine_allowed_from_db()
    if engine_slug not in engine_mapping:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, category=category)
        .exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    ids = [
        p.id
        for p in Product.objects.public()
        .filter(series=series, category=category)
        .exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        if _shacman_engine_slug(p.engine_model) == engine_slug
    ]
    qs = qs.filter(id__in=ids) if ids else Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


SHACMAN_LINE_ENGINE_CAP = 50


def _shacman_line_engine_allowed_from_db():
    """
    Allowed line+engine hubs: (line_slug, engine_slug) with >=2 products. DB only, no cache.
    Cap SHACMAN_LINE_ENGINE_CAP. line_slug=slugify(line), engine_slug as in URL (_shacman_engine_slug).
    Line filter by raw_line via mapping (like line_category).
    """
    from django.db.models import Count
    from django.utils.text import slugify as django_slugify

    base = Product.objects.filter(
        series__slug__iexact="shacman",
        is_active=True,
    ).exclude(series__isnull=True).exclude(model_variant__isnull=True).exclude(engine_model__isnull=True).exclude(engine_model="")
    qs = (
        base.values("model_variant__line", "engine_model")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2, model_variant__line__isnull=False)
        .exclude(model_variant__line="")
        .order_by("-cnt")[:SHACMAN_LINE_ENGINE_CAP]
    )
    out = set()
    for row in qs:
        line = (row.get("model_variant__line") or "").strip()
        em = (row.get("engine_model") or "").strip()
        if line and em:
            line_slug = django_slugify(line)
            eng_slug = _shacman_engine_slug(em)
            if line_slug and eng_slug:
                out.add((line_slug, eng_slug))
    return out


def _shacman_line_engine_hub_queryset(line_slug, engine_slug, in_stock_only=False):
    """Products for /shacman/line/<line_slug>/engine/<engine_slug>/ (and in-stock). Uses raw_line mapping."""
    series = _shacman_series()
    if not series:
        return Product.objects.none()
    line_mapping = _shacman_line_allowed_from_db()
    if line_slug not in line_mapping:
        return Product.objects.none()
    raw_line = (line_mapping[line_slug] or "").strip()
    if not raw_line:
        return Product.objects.none()
    qs = (
        Product.objects.public()
        .filter(series=series, model_variant__isnull=False)
        .exclude(engine_model__isnull=True)
        .exclude(engine_model="")
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")
    )
    model_variant_ids = [
        mv.id for mv in ModelVariant.objects.filter(brand=series)
        if (getattr(mv, "line", None) or "").strip() == raw_line
    ]
    qs = qs.filter(model_variant_id__in=model_variant_ids) if model_variant_ids else Product.objects.none()
    ids = [
        p.id for p in qs
        if _shacman_engine_slug(p.engine_model) == engine_slug
    ]
    qs = qs.filter(id__in=ids) if ids else Product.objects.none()
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def shacman_series_hub(request, series_slug):
    """301 redirect to canonical /shacman/line/<line_slug>/ (avoid series/line cannibalization)."""
    line_mapping = _shacman_line_allowed_from_db()
    if series_slug not in line_mapping:
        raise Http404
    line_url = reverse("shacman_line_hub", kwargs={"line_slug": series_slug})
    return HttpResponseRedirect(line_url, status=301)


def shacman_series_in_stock_hub(request, series_slug):
    """301 redirect to canonical /shacman/line/<line_slug>/in-stock/ (avoid series/line cannibalization)."""
    line_mapping = _shacman_line_allowed_from_db()
    if series_slug not in line_mapping:
        raise Http404
    line_url = reverse("shacman_line_in_stock_hub", kwargs={"line_slug": series_slug})
    return HttpResponseRedirect(line_url, status=301)


def _shacman_model_code_popular_links(model_code_slug: str, exclude_url=None):
    """Popular links for model_code hub: in-stock same code, main hub, in-stock hub."""
    out = []
    allowed = _shacman_model_code_allowed_from_db(min_count=1)
    if model_code_slug not in allowed:
        return out
    try:
        url_in_stock = reverse("shacman_model_code_in_stock_hub", kwargs={"model_code_slug": model_code_slug})
        if not exclude_url or url_in_stock != exclude_url:
            out.append({"url": url_in_stock, "label": f"SHACMAN {model_code_slug.upper()} — в наличии"})
    except Exception:
        pass
    try:
        url_main = reverse("shacman_hub")
        if not exclude_url or url_main != exclude_url:
            out.append({"url": url_main, "label": "Весь каталог SHACMAN"})
    except Exception:
        pass
    try:
        url_stock = reverse("shacman_in_stock")
        if not exclude_url or url_stock != exclude_url:
            out.append({"url": url_stock, "label": "SHACMAN в наличии"})
    except Exception:
        pass
    return out[:SHACMAN_COMBO_LINKS_CAP]


def shacman_model_code_hub(request, model_code_slug):
    """SHACMAN by model code: /shacman/model/<model_code_slug>/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    allowed = _shacman_model_code_allowed_from_db(min_count=1)
    if model_code_slug not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_model_code_hub"
            return resp
        raise Http404
    redirect_response = _redirect_page_one(
        request,
        reverse("shacman_model_code_hub", kwargs={"model_code_slug": model_code_slug}),
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("model_code", model_code_slug)
    faq_items = facet_seo.get("faq_items") or []
    label = (model_code_slug or "").upper()
    meta = build_shacman_hub_meta("model_code", model_code_label=label)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_model_code_hub_queryset(model_code_slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "model_code", category=None, facet_key=model_code_slug
    )
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/model/{model_code_slug}/",
        title,
        description,
        qs,
        faq_items,
        h1=meta["h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман / Shacman / Shaanxi",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["shacman_combo_links"] = _shacman_model_code_popular_links(
        model_code_slug,
        exclude_url=reverse("shacman_model_code_hub", kwargs={"model_code_slug": model_code_slug}),
    )
    context["category"] = None
    context["current_category_slug"] = None
    context["hub_label"] = label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_model_code_in_stock_hub(request, model_code_slug):
    """SHACMAN model code in stock: /shacman/model/<model_code_slug>/in-stock/ — 200 if allowed; noindex when thin."""
    allowed = _shacman_model_code_allowed_from_db(min_count=1)
    if model_code_slug not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_model_code_in_stock_hub"
            return resp
        raise Http404
    redirect_response = _redirect_page_one(
        request,
        reverse("shacman_model_code_in_stock_hub", kwargs={"model_code_slug": model_code_slug}),
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("model_code_in_stock", model_code_slug)
    faq_items = facet_seo.get("faq_items") or []
    label = (model_code_slug or "").upper()
    meta = build_shacman_hub_meta("model_code_in_stock", model_code_label=label, in_stock=True)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_model_code_hub_queryset(model_code_slug, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "model_code_in_stock", category=None, facet_key=model_code_slug
    )
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/model/{model_code_slug}/in-stock/",
        title,
        description,
        qs,
        faq_items,
        h1=meta["h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман / Shacman",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["shacman_combo_links"] = _shacman_model_code_popular_links(
        model_code_slug,
        exclude_url=reverse("shacman_model_code_in_stock_hub", kwargs={"model_code_slug": model_code_slug}),
    )
    context["category"] = None
    context["current_category_slug"] = None
    context["hub_label"] = label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_formula_hub(request, formula):
    """SHACMAN by formula: /shacman/formula/<formula>/"""
    allowed = _shacman_allowed_clusters()
    norm = _shacman_normalize_formula(formula)
    if norm not in allowed["formulas"]:
        raise Http404
    redirect_response = _redirect_page_one(
        request, reverse("shacman_formula_hub", kwargs={"formula": formula})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("formula", norm)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("formula", formula=norm)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_formula_hub_queryset(formula, in_stock_only=False)
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/formula/{formula}/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман / Shacman",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["category"] = None
    context["hub_label"] = norm
    return render(request, "catalog/shacman_hub.html", context)


def shacman_formula_in_stock_hub(request, formula):
    """SHACMAN formula in stock: /shacman/formula/<formula>/in-stock/"""
    allowed = _shacman_allowed_clusters()
    norm = _shacman_normalize_formula(formula)
    if norm not in allowed["formulas"]:
        raise Http404
    redirect_response = _redirect_page_one(
        request, reverse("shacman_formula_in_stock_hub", kwargs={"formula": formula})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("formula_in_stock", norm)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("formula_in_stock", formula=norm)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_formula_hub_queryset(formula, in_stock_only=True)
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/formula/{formula}/in-stock/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["category"] = None
    context["hub_label"] = norm
    return render(request, "catalog/shacman_hub.html", context)


def shacman_engine_hub(request, engine_slug):
    """SHACMAN by engine: /shacman/engine/<engine_slug>/ (200/404 from DB only, no cache)."""
    diag = _shacman_hub_diag(request)
    try:
        mapping = _shacman_engine_allowed_from_db()
    except Exception:
        logger.exception("shacman_engine_allowed_from_db failed")
        raise
    if diag:
        logger.warning("shacman_engine_hub diag: mapping_len=%s slug=%s slug_in_mapping=%s", len(mapping), engine_slug, engine_slug in mapping)
    if engine_slug not in mapping:
        _log_shacman_hub_404_diagnostic(engine_slug=engine_slug, mapping_engine=mapping, hub_type="engine")
        extra = {"X-Diag-Mapping-Len": str(len(mapping)), "X-Diag-Slug-In-Mapping": "0"} if diag else {}
        return _shacman_404_response(request, "shacman_engine_hub", "engine_not_allowed", **extra)
    label = mapping[engine_slug]
    redirect_response = _redirect_page_one(
        request, reverse("shacman_engine_hub", kwargs={"engine_slug": engine_slug})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("engine", engine_slug)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("engine", engine_label=label)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_engine_hub_queryset(engine_slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else "?"
    if diag:
        logger.warning("shacman_engine_hub diag: qs.count=%s before _shacman_hub_context", qs_count)
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/engine/{engine_slug}/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if diag:
        logger.warning("shacman_engine_hub diag: redirect_out=%s", redirect_out is not None)
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    current_path = reverse("shacman_engine_hub", kwargs={"engine_slug": engine_slug})
    context["shacman_combo_links"] = (
        _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
        + _shacman_line_engine_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["category"] = None
    context["hub_label"] = label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_engine_in_stock_hub(request, engine_slug):
    """SHACMAN engine in stock: /shacman/engine/<engine_slug>/in-stock/ — 200 only if get_engine_in_stock_qs().exists(), else 404."""
    diag = _shacman_hub_diag(request)
    try:
        qs = get_engine_in_stock_qs(engine_slug)
    except Exception:
        logger.exception("get_engine_in_stock_qs(%r) failed", engine_slug)
        return _shacman_404_response(
            request, "shacman_engine_in_stock_hub", "qs_error", **({"X-Diag-Step": "qs_error"} if diag else {})
        )
    if not qs.exists():
        _log_shacman_hub_404_diagnostic(engine_slug=engine_slug, mapping_engine={}, hub_type="engine")
        return _shacman_404_response(
            request, "shacman_engine_in_stock_hub", "qs_empty", **({"X-Diag-QS-Count": "0"} if diag else {})
        )
    try:
        mapping = _shacman_engine_allowed_from_db()
        label = mapping.get(engine_slug) or engine_slug
    except Exception:
        label = engine_slug
    redirect_response = _redirect_page_one(
        request, reverse("shacman_engine_in_stock_hub", kwargs={"engine_slug": engine_slug})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("engine_in_stock", engine_slug)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("engine_in_stock", engine_label=label)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/engine/{engine_slug}/in-stock/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    current_path = reverse("shacman_engine_in_stock_hub", kwargs={"engine_slug": engine_slug})
    context["shacman_combo_links"] = (
        _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
        + _shacman_line_engine_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["category"] = None
    context["hub_label"] = label
    context["current_category_slug"] = None
    return render(request, "catalog/shacman_hub.html", context)


def shacman_engine_category_hub(request, engine_slug, category_slug):
    """Combo: /shacman/engine/<engine_slug>/<category_slug>/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_engine_category_allowed_from_db()
    key = (engine_slug, category_slug)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_engine_category_hub"
            resp["X-Diag-Allowed-EC"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_engine_category_hub",
            kwargs={"engine_slug": engine_slug, "category_slug": category.slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_engine_category_hub_queryset(engine_slug, category.slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_engine_category_hub"
            resp["X-Diag-Allowed-EC"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    meta = build_shacman_hub_meta("engine_category", engine_label=engine_label, category_name=category.name)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/engine/{engine_slug}/{category.slug}/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_engine_category_hub",
        kwargs={"engine_slug": engine_slug, "category_slug": category.slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = engine_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_engine_category_hub"
        response["X-Diag-Allowed-EC"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_engine_category_in_stock_hub(request, engine_slug, category_slug):
    """Combo: /shacman/engine/<engine_slug>/<category_slug>/in-stock/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_engine_category_allowed_from_db()
    key = (engine_slug, category_slug)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_engine_category_in_stock_hub"
            resp["X-Diag-Allowed-EC"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_engine_category_in_stock_hub",
            kwargs={"engine_slug": engine_slug, "category_slug": category.slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_engine_category_hub_queryset(engine_slug, category.slug, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_engine_category_in_stock_hub"
            resp["X-Diag-Allowed-EC"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    meta = build_shacman_hub_meta("engine_category_in_stock", engine_label=engine_label, category_name=category.name, in_stock=True)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/engine/{engine_slug}/{category.slug}/in-stock/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_engine_category_in_stock_hub",
        kwargs={"engine_slug": engine_slug, "category_slug": category.slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = engine_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_engine_category_in_stock_hub"
        response["X-Diag-Allowed-EC"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_category_engine_hub(request, category_slug, engine_slug):
    """Combo (category-first): /shacman/category/<category_slug>/engine/<engine_slug>/ — 200 if >=1 product (noindex when 1), else 404."""
    allowed = _shacman_engine_category_allowed_from_db()
    key = (engine_slug, category_slug)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_engine_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_engine_hub",
            kwargs={"category_slug": category.slug, "engine_slug": engine_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_engine_category_hub_queryset(engine_slug, category.slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 1:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_engine_hub"
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    noindex_for_thin = qs_count == 1
    meta = build_shacman_hub_meta("engine_category", engine_label=engine_label, category_name=category.name)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    base_path = f"/shacman/category/{category.slug}/engine/{engine_slug}/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_engine_hub",
        kwargs={"category_slug": category.slug, "engine_slug": engine_slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = engine_label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_engine_in_stock_hub(request, category_slug, engine_slug):
    """Combo (category-first): /shacman/category/<category_slug>/engine/<engine_slug>/in-stock/ — 200 if >=1 product (noindex when 1), else 404."""
    allowed = _shacman_engine_category_allowed_from_db()
    key = (engine_slug, category_slug)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_engine_in_stock_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_engine_in_stock_hub",
            kwargs={"category_slug": category.slug, "engine_slug": engine_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_engine_category_hub_queryset(engine_slug, category.slug, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 1:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_engine_in_stock_hub"
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    noindex_for_thin = qs_count == 1
    meta = build_shacman_hub_meta("engine_category", engine_label=engine_label, category_name=category.name)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    base_path = f"/shacman/category/{category.slug}/engine/{engine_slug}/in-stock/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_engine_in_stock_hub",
        kwargs={"category_slug": category.slug, "engine_slug": engine_slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_engine_combo_links_for_display(engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = engine_label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_line_hub(request, category_slug, line_slug):
    """Category-first line+category: /shacman/category/<category_slug>/line/<line_slug>/ — 200 always if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    allowed = _shacman_category_line_allowed_from_db(min_count=1)
    key = (category_slug, line_slug)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_line_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_line_hub",
            kwargs={"category_slug": category.slug, "line_slug": line_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=None, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_line", category=category, facet_key=line_slug
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_line", category=category, facet_key=line_slug
    )
    base_path = f"/shacman/category/{category.slug}/line/{line_slug}/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_line_hub",
        kwargs={"category_slug": category.slug, "line_slug": line_slug},
    )
    context["shacman_combo_links"] = _shacman_category_line_popular_links(
        category.slug, line_slug, exclude_url=current_path
    )
    context["hub_label"] = line_label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_line_in_stock_hub(request, category_slug, line_slug):
    """Category-first line+category in-stock: /shacman/category/<category_slug>/line/<line_slug>/in-stock/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    allowed = _shacman_category_line_allowed_from_db(min_count=1)
    key = (category_slug, line_slug)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_line_in_stock_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_line_in_stock_hub",
            kwargs={"category_slug": category.slug, "line_slug": line_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=None, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_line_in_stock", category=category, facet_key=line_slug
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_line_in_stock", category=category, facet_key=line_slug
    )
    base_path = f"/shacman/category/{category.slug}/line/{line_slug}/in-stock/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_line_in_stock_hub",
        kwargs={"category_slug": category.slug, "line_slug": line_slug},
    )
    context["shacman_combo_links"] = _shacman_category_line_popular_links(
        category.slug, line_slug, exclude_url=current_path
    )
    context["hub_label"] = line_label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_line_formula_hub(request, category_slug, line_slug, formula_slug):
    """Category+line+formula: /shacman/category/<category_slug>/line/<line_slug>/formula/<formula_slug>/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_category_line_formula_allowed_from_db(min_count=1)
    key = (category_slug, line_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_line_formula_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_line_formula_hub",
            kwargs={"category_slug": category.slug, "line_slug": line_slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_line_formula_hub_queryset(category.slug, line_slug, norm, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    facet_key_combo = f"{line_slug}:{norm}"
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_line_formula", category=category, facet_key=facet_key_combo
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_line_formula", category=category, facet_key=facet_key_combo
    )
    base_path = f"/shacman/category/{category.slug}/line/{line_slug}/formula/{formula_slug}/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_line_formula_hub",
        kwargs={"category_slug": category.slug, "line_slug": line_slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_category_line_formula_popular_links(
        category.slug, line_slug, norm, exclude_url=current_path
    )
    context["hub_label"] = f"{line_label} {norm}"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_line_formula_in_stock_hub(request, category_slug, line_slug, formula_slug):
    """Category+line+formula in-stock: /shacman/category/<category_slug>/line/<line_slug>/formula/<formula_slug>/in-stock/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_category_line_formula_allowed_from_db(min_count=1)
    key = (category_slug, line_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_line_formula_in_stock_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_line_formula_in_stock_hub",
            kwargs={"category_slug": category.slug, "line_slug": line_slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_line_formula_hub_queryset(category.slug, line_slug, norm, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    facet_key_combo = f"{line_slug}:{norm}"
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_line_formula_in_stock", category=category, facet_key=facet_key_combo
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_line_formula_in_stock", category=category, facet_key=facet_key_combo
    )
    base_path = f"/shacman/category/{category.slug}/line/{line_slug}/formula/{formula_slug}/in-stock/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_line_formula_in_stock_hub",
        kwargs={"category_slug": category.slug, "line_slug": line_slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_category_line_formula_popular_links(
        category.slug, line_slug, norm, exclude_url=current_path
    )
    context["hub_label"] = f"{line_label} {norm}"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_line_formula_hub(request, line_slug, formula_slug):
    """Line+formula (no category): /shacman/line/<line_slug>/formula/<formula_slug>/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_line_formula_allowed_from_db(min_count=1)
    key = (line_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_formula_hub"
            return resp
        raise Http404
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_formula_hub",
            kwargs={"line_slug": line_slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_formula_hub_queryset(line_slug, norm, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    facet_key_combo = f"{line_slug}:{norm}"
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "line_formula", category=None, facet_key=facet_key_combo
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "line_formula", category=None, facet_key=facet_key_combo
    )
    base_path = f"/shacman/line/{line_slug}/formula/{formula_slug}/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = None
    context["current_category_slug"] = None
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=None)
    current_path = reverse(
        "shacman_line_formula_hub",
        kwargs={"line_slug": line_slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_line_formula_popular_links(
        line_slug, norm, exclude_url=current_path
    )
    context["hub_label"] = f"{line_label} {norm}"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_line_formula_in_stock_hub(request, line_slug, formula_slug):
    """Line+formula in-stock: /shacman/line/<line_slug>/formula/<formula_slug>/in-stock/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_line_formula_allowed_from_db(min_count=1)
    key = (line_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_formula_in_stock_hub"
            return resp
        raise Http404
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_formula_in_stock_hub",
            kwargs={"line_slug": line_slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_formula_hub_queryset(line_slug, norm, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    facet_key_combo = f"{line_slug}:{norm}"
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "line_formula_in_stock", category=None, facet_key=facet_key_combo
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "line_formula_in_stock", category=None, facet_key=facet_key_combo
    )
    base_path = f"/shacman/line/{line_slug}/formula/{formula_slug}/in-stock/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = None
    context["current_category_slug"] = None
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=None)
    current_path = reverse(
        "shacman_line_formula_in_stock_hub",
        kwargs={"line_slug": line_slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_line_formula_popular_links(
        line_slug, norm, exclude_url=current_path
    )
    context["hub_label"] = f"{line_label} {norm}"
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_formula_explicit_hub(request, category_slug, formula_slug):
    """Category+formula explicit path: /shacman/category/<category_slug>/formula/<formula_slug>/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_category_formula_allowed_from_db(min_count=1)
    key = (category_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_formula_explicit_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_formula_explicit_hub",
            kwargs={"category_slug": category.slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_formula_hub_queryset(category.slug, norm, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_formula_explicit", category=category, facet_key=norm
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_formula_explicit", category=category, facet_key=norm
    )
    base_path = f"/shacman/category/{category.slug}/formula/{formula_slug}/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_formula_explicit_hub",
        kwargs={"category_slug": category.slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_category_formula_explicit_popular_links(
        category.slug, norm, exclude_url=current_path
    )
    context["hub_label"] = norm
    return render(request, "catalog/shacman_hub.html", context)


def shacman_category_formula_explicit_in_stock_hub(request, category_slug, formula_slug):
    """Category+formula explicit in-stock: /shacman/category/<category_slug>/formula/<formula_slug>/in-stock/ — 200 if allowed; noindex when < HUB_INDEX_MIN_PRODUCTS."""
    norm = _shacman_normalize_formula(formula_slug)
    if not norm:
        raise Http404
    allowed = _shacman_category_formula_allowed_from_db(min_count=1)
    key = (category_slug, norm)
    if key not in allowed:
        if _shacman_hub_diag(request):
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_category_formula_explicit_in_stock_hub"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_category_formula_explicit_in_stock_hub",
            kwargs={"category_slug": category.slug, "formula_slug": formula_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_category_formula_hub_queryset(category.slug, norm, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    noindex_for_thin = (qs_count < HUB_INDEX_MIN_PRODUCTS) and not _shacman_hub_force_index_override(
        "category_formula_explicit_in_stock", category=category, facet_key=norm
    )
    hub_seo = _get_shacman_combo_hub_seo_content_from_db(
        "category_formula_explicit_in_stock", category=category, facet_key=norm
    )
    base_path = f"/shacman/category/{category.slug}/formula/{formula_slug}/in-stock/"
    redirect_out, context = _shacman_hub_context(
        request,
        base_path,
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
        noindex_for_thin=noindex_for_thin,
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_category_formula_explicit_in_stock_hub",
        kwargs={"category_slug": category.slug, "formula_slug": formula_slug},
    )
    context["shacman_combo_links"] = _shacman_category_formula_explicit_popular_links(
        category.slug, norm, exclude_url=current_path
    )
    context["hub_label"] = norm
    return render(request, "catalog/shacman_hub.html", context)


def shacman_line_hub(request, line_slug):
    """SHACMAN by line: /shacman/line/<line_slug>/ (200/404 from DB only, no cache)."""
    diag = _shacman_hub_diag(request)
    try:
        mapping = _shacman_line_allowed_from_db()
    except Exception:
        logger.exception("shacman_line_allowed_from_db failed")
        raise
    if diag:
        logger.warning("shacman_line_hub diag: mapping_len=%s slug=%s slug_in_mapping=%s", len(mapping), line_slug, line_slug in mapping)
    if line_slug not in mapping:
        _log_shacman_hub_404_diagnostic(line_slug=line_slug, mapping_line=mapping, hub_type="line")
        extra = {"X-Diag-Mapping-Len": str(len(mapping)), "X-Diag-Slug-In-Mapping": "0"} if diag else {}
        return _shacman_404_response(request, "shacman_line_hub", "line_not_allowed", **extra)
    label = mapping[line_slug]
    redirect_response = _redirect_page_one(
        request, reverse("shacman_line_hub", kwargs={"line_slug": line_slug})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("line", line_slug)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("line", line_label=label)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_line_hub_queryset(line_slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else "?"
    if diag:
        logger.warning("shacman_line_hub diag: qs.count=%s before _shacman_hub_context", qs_count)
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/line/{line_slug}/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if diag:
        logger.warning("shacman_line_hub diag: redirect_out=%s", redirect_out is not None)
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман / Shacman / Shaanxi",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        + _shacman_line_engine_links_for_display(line_slug=line_slug)
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["category"] = None
    context["current_category_slug"] = None
    context["hub_label"] = label
    return render(request, "catalog/shacman_hub.html", context)


def shacman_line_in_stock_hub(request, line_slug):
    """SHACMAN line in stock: /shacman/line/<line_slug>/in-stock/ (200/404 from DB only)."""
    diag = _shacman_hub_diag(request)
    try:
        mapping = _shacman_line_allowed_from_db()
    except Exception:
        logger.exception("shacman_line_allowed_from_db failed")
        raise
    if line_slug not in mapping:
        _log_shacman_hub_404_diagnostic(line_slug=line_slug, mapping_line=mapping, hub_type="line")
        extra = {"X-Diag-Mapping-Len": str(len(mapping)), "X-Diag-Slug-In-Mapping": "0"} if diag else {}
        return _shacman_404_response(request, "shacman_line_in_stock_hub", "line_not_allowed", **extra)
    label = mapping[line_slug]
    redirect_response = _redirect_page_one(
        request, reverse("shacman_line_in_stock_hub", kwargs={"line_slug": line_slug})
    )
    if redirect_response:
        return redirect_response
    facet_seo = _get_shacman_facet_seo_content("line_in_stock", line_slug)
    faq_items = facet_seo.get("faq_items") or []
    meta = build_shacman_hub_meta("line_in_stock", line_label=label)
    title = facet_seo.get("meta_title") or meta["title"]
    description = facet_seo.get("meta_description") or meta["description"]
    qs = _shacman_line_hub_queryset(line_slug, in_stock_only=True)
    redirect_out, context = _shacman_hub_context(
        request, f"/shacman/line/{line_slug}/in-stock/", title, description, qs, faq_items, h1=meta["h1"]
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = {
        "seo_text": "",
        "faq_items": faq_items,
        "also_search_line": "Также ищут: Шакман / Shacman",
        "seo_intro_html": facet_seo.get("seo_intro_html") or "",
        "seo_body_html": facet_seo.get("seo_body_html") or "",
    }
    if not request.GET and faq_items:
        context["page_schema_payload"] = json.dumps(
            [_build_faq_schema(faq_items)], ensure_ascii=False
        )[1:-1]
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    context["shacman_combo_links"] = (
        _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        + _shacman_line_engine_links_for_display(line_slug=line_slug)
    )[:SHACMAN_COMBO_LINKS_CAP]
    context["category"] = None
    context["hub_label"] = label
    context["current_category_slug"] = None
    return render(request, "catalog/shacman_hub.html", context)


def shacman_line_engine_hub(request, line_slug, engine_slug):
    """Line+engine: /shacman/line/<line_slug>/engine/<engine_slug>/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_line_engine_allowed_from_db()
    key = (line_slug, engine_slug)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_engine_hub"
            resp["X-Diag-Allowed-LE"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_engine_hub",
            kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_engine_hub_queryset(line_slug, engine_slug, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_engine_hub"
            resp["X-Diag-Allowed-LE"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    meta = build_shacman_hub_meta("line_engine", line_label=line_label, engine_label=engine_label)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/engine/{engine_slug}/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = None
    context["current_category_slug"] = None
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    current_path = reverse(
        "shacman_line_engine_hub",
        kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_line_engine_links_for_display(line_slug=line_slug, engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = f"{line_label} {engine_label}"
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_engine_hub"
        response["X-Diag-Allowed-LE"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_line_engine_in_stock_hub(request, line_slug, engine_slug):
    """Line+engine: /shacman/line/<line_slug>/engine/<engine_slug>/in-stock/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_line_engine_allowed_from_db()
    key = (line_slug, engine_slug)
    if key not in allowed:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_engine_in_stock_hub"
            resp["X-Diag-Allowed-LE"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    engine_label = _shacman_engine_allowed_from_db().get(engine_slug) or engine_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_engine_in_stock_hub",
            kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_engine_hub_queryset(line_slug, engine_slug, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_engine_in_stock_hub"
            resp["X-Diag-Allowed-LE"] = str(len(allowed))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    meta = build_shacman_hub_meta("line_engine_in_stock", line_label=line_label, engine_label=engine_label)
    hub_seo = {
        "meta_title": meta["title"],
        "meta_description": meta["description"],
        "meta_h1": meta["h1"],
        "seo_text": "",
        "faq_items": [],
        "also_search_line": "Также ищут: Шакман",
    }
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/engine/{engine_slug}/in-stock/",
        hub_seo["meta_title"],
        hub_seo["meta_description"],
        qs,
        hub_seo["faq_items"],
        h1=hub_seo["meta_h1"],
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = None
    context["current_category_slug"] = None
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12)
    current_path = reverse(
        "shacman_line_engine_in_stock_hub",
        kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_line_engine_links_for_display(line_slug=line_slug, engine_slug=engine_slug, exclude_url=current_path)
    ]
    context["hub_label"] = f"{line_label} {engine_label}"
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_engine_in_stock_hub"
        response["X-Diag-Allowed-LE"] = str(len(allowed))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_line_category_hub(request, line_slug, category_slug):
    """Combo: /shacman/line/<line_slug>/<category_slug>/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_combo_allowed_from_db()
    key = (line_slug, category_slug)
    if key not in allowed.lc:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse("shacman_line_category_hub", kwargs={"line_slug": line_slug, "category_slug": category.slug}),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=None, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    hub_seo = _get_shacman_combo_hub_seo_content(line_label, category.name, formula=None, in_stock=False)
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/{category.slug}/",
        title,
        description,
        qs,
        hub_seo["faq_items"],
        h1=hub_seo.get("meta_h1"),
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse("shacman_line_category_hub", kwargs={"line_slug": line_slug, "category_slug": category.slug})
    context["shacman_combo_links"] = [
        l for l in _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        if l["url"] != current_path
    ]
    context["hub_label"] = line_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_category_hub"
        response["X-Diag-Allowed-LC"] = str(len(allowed.lc))
        response["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_line_category_in_stock_hub(request, line_slug, category_slug):
    """Combo: /shacman/line/<line_slug>/<category_slug>/in-stock/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    allowed = _shacman_combo_allowed_from_db()
    key = (line_slug, category_slug)
    if key not in allowed.lc:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_in_stock_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_category_in_stock_hub",
            kwargs={"line_slug": line_slug, "category_slug": category.slug},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=None, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_in_stock_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    hub_seo = _get_shacman_combo_hub_seo_content(line_label, category.name, formula=None, in_stock=True)
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/{category.slug}/in-stock/",
        title,
        description,
        qs,
        hub_seo["faq_items"],
        h1=hub_seo.get("meta_h1"),
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_line_category_in_stock_hub",
        kwargs={"line_slug": line_slug, "category_slug": category.slug},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        if l["url"] != current_path
    ]
    context["hub_label"] = line_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_category_in_stock_hub"
        response["X-Diag-Allowed-LC"] = str(len(allowed.lc))
        response["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_line_category_formula_hub(request, line_slug, category_slug, formula):
    """Combo: /shacman/line/<line_slug>/<category_slug>/<formula>/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    norm_formula = _shacman_normalize_formula(formula)
    if not norm_formula:
        raise Http404
    allowed = _shacman_combo_allowed_from_db()
    key = (line_slug, category_slug, norm_formula)
    if key not in allowed.lcf:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_formula_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_category_formula_hub",
            kwargs={"line_slug": line_slug, "category_slug": category.slug, "formula": norm_formula},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=norm_formula, in_stock_only=False)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_formula_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    hub_seo = _get_shacman_combo_hub_seo_content(line_label, category.name, formula=norm_formula, in_stock=False)
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/{category.slug}/{norm_formula}/",
        title,
        description,
        qs,
        hub_seo["faq_items"],
        h1=hub_seo.get("meta_h1"),
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_line_category_formula_hub",
        kwargs={"line_slug": line_slug, "category_slug": category.slug, "formula": norm_formula},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        if l["url"] != current_path
    ]
    context["hub_label"] = line_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_category_formula_hub"
        response["X-Diag-Allowed-LC"] = str(len(allowed.lc))
        response["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def shacman_line_category_formula_in_stock_hub(request, line_slug, category_slug, formula):
    """Combo: /shacman/line/<line_slug>/<category_slug>/<formula>/in-stock/ — 200 only if >=2 products, else 404."""
    diag = _shacman_hub_diag(request)
    norm_formula = _shacman_normalize_formula(formula)
    if not norm_formula:
        raise Http404
    allowed = _shacman_combo_allowed_from_db()
    key = (line_slug, category_slug, norm_formula)
    if key not in allowed.lcf:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_formula_in_stock_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = "0"
            return resp
        raise Http404
    category = get_object_or_404(Category.objects, slug__iexact=category_slug)
    line_label = _shacman_line_allowed_from_db().get(line_slug) or line_slug
    redirect_response = _redirect_page_one(
        request,
        reverse(
            "shacman_line_category_formula_in_stock_hub",
            kwargs={"line_slug": line_slug, "category_slug": category.slug, "formula": norm_formula},
        ),
    )
    if redirect_response:
        return redirect_response
    qs = _shacman_line_category_hub_queryset(line_slug, category.slug, formula=norm_formula, in_stock_only=True)
    qs_count = qs.count() if hasattr(qs, "count") else 0
    if qs_count < 2:
        if diag:
            resp = HttpResponseNotFound(b"404")
            resp["X-Diag-Resolver-View"] = "shacman_line_category_formula_in_stock_hub"
            resp["X-Diag-Allowed-LC"] = str(len(allowed.lc))
            resp["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
            resp["X-Diag-QS-Count"] = str(qs_count)
            return resp
        raise Http404
    hub_seo = _get_shacman_combo_hub_seo_content(line_label, category.name, formula=norm_formula, in_stock=True)
    title = hub_seo["meta_title"]
    description = hub_seo["meta_description"]
    redirect_out, context = _shacman_hub_context(
        request,
        f"/shacman/line/{line_slug}/{category.slug}/{norm_formula}/in-stock/",
        title,
        description,
        qs,
        hub_seo["faq_items"],
        h1=hub_seo.get("meta_h1"),
    )
    if redirect_out:
        return redirect_out
    context["hub_seo"] = hub_seo
    context["category"] = category
    context["current_category_slug"] = category.slug
    context["shacman_hub_categories"] = _shacman_hub_categories()
    context["shacman_top_products"] = _shacman_top_products(limit=12, category=category)
    current_path = reverse(
        "shacman_line_category_formula_in_stock_hub",
        kwargs={"line_slug": line_slug, "category_slug": category.slug, "formula": norm_formula},
    )
    context["shacman_combo_links"] = [
        l for l in _shacman_combo_links_for_display(line_slug=line_slug, category_slug=None)
        if l["url"] != current_path
    ]
    context["hub_label"] = line_label
    response = render(request, "catalog/shacman_hub.html", context)
    if diag:
        response["X-Diag-Resolver-View"] = "shacman_line_category_formula_in_stock_hub"
        response["X-Diag-Allowed-LC"] = str(len(allowed.lc))
        response["X-Diag-Allowed-LCF"] = str(len(allowed.lcf))
        response["X-Diag-QS-Count"] = str(qs_count)
    return response


def brand_list(request):
    series = Series.objects.public()
    context = {"series_list": series}
    context.update(_seo_context(_("Бренды"), _("Бренды техники CARFAST"), request))
    return render(request, "catalog/brand_list.html", context)


def brand_detail(request, slug):
    series = get_object_or_404(Series.objects.public(), slug__iexact=slug)
    text = (getattr(series, "history", "") or series.description_ru or "").strip()
    meta_desc = (text[:160] if text else f"Техника {series.name}. В наличии и под заказ.")
    brand_logo_static = BRAND_LOGO_STATIC.get((series.slug or "").lower())
    popular_products = (
        Product.objects.public().filter(series=series)
        .select_related("series", "category", "model_variant")
        .with_stock_stats()
        .prefetch_related("images")
        .order_by("-total_qty", "-updated_at", "-id")[:8]
    )
    title = f"{series.name} — CARFAST"
    context = {
        "series": series,
        "popular_products": popular_products,
        "brand_logo_static": brand_logo_static,
    }
    context.update(_seo_context(title, meta_desc, request, obj=series))
    return render(request, "catalog/brand_detail.html", context)


def product_detail(request, slug):
    offers_qs = (
        Offer.objects.filter(is_active=True)
        .select_related("city")
        .order_by("city__sort_order", "city__name", "-updated_at", "-id")
    )
    product = get_object_or_404(
        Product.objects.public()
        .select_related("series", "category", "model_variant", "canonical_product")
        .with_stock_stats()
        .prefetch_related("images", Prefetch("offers", queryset=offers_qs, to_attr="active_offers")),
        slug=slug,
    )
    # 301 to hub URL or to canonical product (aliases/redirects not in sitemap)
    redirect_url = (product.redirect_to_url or "").strip()
    if redirect_url:
        return redirect(redirect_url, permanent=True)
    if product.canonical_product_id:
        return redirect(product.canonical_product.get_absolute_url(), permanent=True)
    try:
        Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)
    except (OperationalError, DatabaseError) as exc:
        logger.warning(
            "Failed to update views_count for product %s: %s", product.pk, exc
        )
    product_schema = product.to_schemaorg(request)
    settings_obj = get_site_settings_safe()
    whatsapp_link = generate_whatsapp_link(
        getattr(settings_obj, "whatsapp_number", None) if settings_obj else None,
        product.model_name_ru
    )
    
    def _extract_option_value(options: object, key_part: str) -> str:
        if not isinstance(options, dict):
            return ""
        for k, v in options.items():
            if key_part not in str(k).lower():
                continue
            if isinstance(v, (list, tuple)):
                if len(v) == 3 and str(v[0]).strip().lower() == "pair":
                    return str(v[2]).strip()
                return ", ".join(str(item).strip() for item in v if str(item).strip())
            return str(v).strip()
        return ""

    cabin_value = _extract_option_value(product.options, "кабин")
    engine_value = product.engine_model or _extract_option_value(product.options, "двиг")

    # SEO title and description (generator + overrides)
    seo_title = build_product_seo_title(product)
    seo_description = build_product_seo_description(product)
    product_seo_h1 = build_product_h1(product)
    product_seo_image_alt = build_product_image_alt(product)

    def _normalize_options_value(value):
        """
        Normalize options value that may contain "pair" markers.
        Returns normalized dict {key: value} or {key: [values]}.
        """
        if not isinstance(value, (list, tuple)):
            return value
        
        value_list = list(value)
        
        # Check if this is a flat sequence with "pair" markers
        has_pair_markers = False
        for item in value_list:
            if not isinstance(item, (list, tuple, dict)) and str(item).strip().lower() == "pair":
                has_pair_markers = True
                break
        
        if not has_pair_markers:
            return value
        
        # Parse flat sequence: "pair", key, value, "pair", key, value, ...
        normalized = {}
        i = 0
        while i < len(value_list):
            item = value_list[i]
            item_str = str(item).strip().lower()
            
            if item_str == "pair":
                # Check if we have enough elements for a complete triplet
                if i + 2 < len(value_list):
                    key = str(value_list[i + 1]).strip()
                    val = value_list[i + 2]
                    
                    if key:
                        # If key already exists, accumulate values
                        if key in normalized:
                            if not isinstance(normalized[key], list):
                                normalized[key] = [normalized[key]]
                            if isinstance(val, (list, tuple)):
                                normalized[key].extend([str(v).strip() for v in val if str(v).strip()])
                            else:
                                val_str = str(val).strip()
                                if val_str and val_str.lower() != "pair":
                                    normalized[key].append(val_str)
                        else:
                            if isinstance(val, (list, tuple)):
                                normalized[key] = [str(v).strip() for v in val if str(v).strip() and str(v).strip().lower() != "pair"]
                            else:
                                val_str = str(val).strip()
                                if val_str and val_str.lower() != "pair":
                                    normalized[key] = val_str
                    i += 3
                    continue
                else:
                    # Incomplete triplet, skip
                    i += 1
                    continue
            
            # Check if element is a triplet list: ["pair", key, value]
            if isinstance(item, (list, tuple)) and len(item) == 3 and str(item[0]).strip().lower() == "pair":
                key = str(item[1]).strip()
                val = item[2]
                if key:
                    if key in normalized:
                        if not isinstance(normalized[key], list):
                            normalized[key] = [normalized[key]]
                        if isinstance(val, (list, tuple)):
                            normalized[key].extend([str(v).strip() for v in val if str(v).strip()])
                        else:
                            val_str = str(val).strip()
                            if val_str and val_str.lower() != "pair":
                                normalized[key].append(val_str)
                    else:
                        if isinstance(val, (list, tuple)):
                            normalized[key] = [str(v).strip() for v in val if str(v).strip() and str(v).strip().lower() != "pair"]
                        else:
                            val_str = str(val).strip()
                            if val_str and val_str.lower() != "pair":
                                normalized[key] = val_str
                i += 1
                continue
            
            # Skip standalone "pair" strings
            if item_str == "pair":
                i += 1
                continue
            
            i += 1
        
        return normalized if normalized else value
    
    # Normalize product.options before processing
    normalized_options = {}
    raw_options = getattr(product, "options", None)
    
    if isinstance(raw_options, (list, tuple)):
        # Top-level list with "pair" markers
        normalized = _normalize_options_value(raw_options)
        if isinstance(normalized, dict):
            normalized_options = normalized
        else:
            # Fallback: treat as empty
            normalized_options = {}
    elif isinstance(raw_options, dict):
        # Dict with potentially "pair" markers in values
        for key, value in raw_options.items():
            normalized = _normalize_options_value(value)
            if isinstance(normalized, dict):
                # Merge normalized pairs into result
                for nkey, nval in normalized.items():
                    normalized_options[nkey] = nval
            else:
                # Keep original value if normalization didn't produce dict
                normalized_options[key] = normalized
    
    # Build options_rows from normalized_options
    options_rows = []
    for key, value in normalized_options.items():
        label = str(key).strip()
        if not label:
            continue
        
        # Skip if label is "pair"
        if label.lower() == "pair":
            continue
        
        if isinstance(value, (list, tuple)):
            # Filter out "pair" from list values
            items = [str(item).strip() for item in value if str(item).strip() and str(item).strip().lower() != "pair"]
            if not items:
                continue
            options_rows.append(
                {"label": label, "value": items, "is_list": True}
            )
        else:
            value_str = str(value).strip()
            if not value_str or value_str.lower() == "pair":
                continue
            options_rows.append(
                {"label": label, "value": value_str, "is_list": False}
            )

    config_items = []
    if product.config:
        for line in product.config.splitlines():
            item = line.strip()
            if item:
                config_items.append(item)

    related_products = []
    related_qs = Product.objects.public().with_stock_stats()
    if product.series_id and product.category_id:
        related_qs = related_qs.filter(series_id=product.series_id, category_id=product.category_id)
    elif product.series_id:
        related_qs = related_qs.filter(series_id=product.series_id)
    elif product.category_id:
        related_qs = related_qs.filter(category_id=product.category_id)
    else:
        related_qs = related_qs.none()
    if related_qs.exists():
        related_products = (
            related_qs.exclude(pk=product.pk)
            .select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("-total_qty", "-updated_at", "-id")[:12]
        )

    is_in_stock = bool(getattr(product, "total_qty", 0) and product.total_qty > 0)
    brand_name = clean_text(product.series.name) if product.series else ""
    category_name = clean_text(product.category.name) if product.category else ""
    model_line = clean_text(product.model_variant.line) if product.model_variant else ""

    manual_description = clean_text(product.description_ru or "")
    description_paragraphs = []
    if manual_description:
        description_paragraphs.append(manual_description)
    else:
        description_paragraphs.append(build_product_first_block(product))

    description_paragraphs.append(
        "Подходит для автопарков и подрядчиков, которым важны стабильные сроки поставки, "
        "понятные условия и техническая поддержка на всех этапах."
    )
    description_bullets = [
        "Лизинг и гибкие условия оплаты под проект.",
        "Сервисное сопровождение и гарантийная поддержка.",
        "Поставка в регионы и помощь с логистикой.",
    ]

    eta_text = "1–3 дня" if is_in_stock else "4–8 недель"
    faq_override = (getattr(product, "seo_faq_override", None) or "").strip()
    if faq_override:
        faq_items = _parse_seo_faq(faq_override)
    else:
        faq_items = [
            {
                "question": "Какие сроки поставки?",
                "answer": (
                    f"{product.model_name_ru} доступен {('в наличии' if is_in_stock else 'под заказ')}. "
                    f"Ориентировочный срок поставки — {eta_text}."
                ),
            },
            {
                "question": "Какие варианты оплаты доступны?",
                "answer": "Безналичный расчёт, лизинг и поэтапные платежи по согласованию.",
            },
            {
                "question": "Какие документы нужны для лизинга?",
                "answer": "Стандартный пакет для юрлиц: анкета, учредительные документы и финансовая отчётность.",
            },
            {
                "question": "Есть ли гарантия и сервис?",
                "answer": "Да, обеспечиваем гарантийное обслуживание и сервисное сопровождение техники.",
            },
        ]

    breadcrumb_items = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "Главная",
            "item": request.build_absolute_uri(reverse("catalog:home")),
        },
        {
            "@type": "ListItem",
            "position": 2,
            "name": "Каталог",
            "item": request.build_absolute_uri(reverse("catalog:catalog_list")),
        },
    ]
    position = 3
    if product.series:
        series_url = reverse("catalog:catalog_series", kwargs={"slug": product.series.slug})
        breadcrumb_items.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": product.series.name,
                "item": request.build_absolute_uri(series_url),
            }
        )
        position += 1
    if product.category:
        if product.series:
            category_url = reverse(
                "catalog:catalog_series_category",
                kwargs={
                    "series_slug": product.series.slug,
                    "category_slug": product.category.slug,
                },
            )
        else:
            category_url = reverse(
                "catalog:catalog_category",
                kwargs={"slug": product.category.slug},
            )
        breadcrumb_items.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": product.category.name,
                "item": request.build_absolute_uri(category_url),
            }
        )
        position += 1
    breadcrumb_items.append(
        {
            "@type": "ListItem",
            "position": position,
            "name": product.model_name_ru,
            "item": request.build_absolute_uri(product.get_absolute_url()),
        }
    )
    breadcrumb_schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumb_items,
    }
    schema_items = [product_schema, breadcrumb_schema]
    if faq_items:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["question"],
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": item["answer"],
                    },
                }
                for item in faq_items
            ],
        }
        schema_items.append(faq_schema)
    # JSON-LD only on clean URL (no GET params)
    if not request.GET:
        schema_json = json.dumps(schema_items, ensure_ascii=False)
        page_schema_payload = schema_json[1:-1].strip() if schema_items else ""
    else:
        page_schema_payload = ""

    # Same model/code: other products by model_code or model_variant+wheel_formula
    same_model_products = []
    if product.model_code or (product.model_variant_id and product.wheel_formula):
        same_qs = Product.objects.public().with_stock_stats().exclude(pk=product.pk)
        if product.model_code:
            same_qs = same_qs.filter(model_code=product.model_code)
        elif product.model_variant_id and product.wheel_formula:
            same_qs = same_qs.filter(
                model_variant_id=product.model_variant_id,
                wheel_formula__iexact=product.wheel_formula,
            )
        same_model_products = list(
            same_qs.select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("-total_qty", "-updated_at")[:6]
        )

    # Hub/service links for internal linking
    seo_hub_links = [
        {"url": reverse("catalog:leasing"), "label": "Лизинг"},
        {"url": reverse("catalog:payment_delivery"), "label": "Доставка"},
        {"url": reverse("catalog:contacts"), "label": "Контакты"},
    ]
    if product.series and (product.series.slug or "").lower() == "shacman":
        try:
            idx = 0
            seo_hub_links.insert(idx, {"url": reverse("shacman_hub"), "label": "SHACMAN — каталог"})
            idx += 1
            if product.category:
                seo_hub_links.insert(idx, {
                    "url": reverse("shacman_category", kwargs={"category_slug": product.category.slug}),
                    "label": f"SHACMAN {product.category.name}",
                })
                idx += 1
            if is_in_stock:
                seo_hub_links.insert(idx, {"url": reverse("shacman_in_stock"), "label": "SHACMAN в наличии"})
                idx += 1
                if product.category:
                    seo_hub_links.insert(idx, {
                        "url": reverse("shacman_category_in_stock", kwargs={"category_slug": product.category.slug}),
                        "label": f"SHACMAN {product.category.name} в наличии",
                    })
            # B3 hubs: formula / engine / line (only if in allowed clusters)
            clusters = _shacman_allowed_clusters()
            norm_formula = _shacman_normalize_formula(product.wheel_formula or "")
            if norm_formula and norm_formula in clusters["formulas"]:
                seo_hub_links.append({
                    "url": reverse("shacman_formula_hub", kwargs={"formula": norm_formula}),
                    "label": f"SHACMAN {norm_formula}",
                })
            engine_slug = _shacman_engine_slug(product.engine_model or "")
            if engine_slug and engine_slug in clusters["engine_slugs"]:
                seo_hub_links.append({
                    "url": reverse("shacman_engine_hub", kwargs={"engine_slug": engine_slug}),
                    "label": f"SHACMAN двигатель {product.engine_model or engine_slug}",
                })
            from django.utils.text import slugify as django_slugify
            if product.model_variant and (product.model_variant.line or "").strip():
                line_slug = django_slugify((product.model_variant.line or "").strip())
                if line_slug and line_slug in clusters["line_slugs"]:
                    seo_hub_links.append({
                        "url": reverse("shacman_line_hub", kwargs={"line_slug": line_slug}),
                        "label": f"SHACMAN {product.model_variant.line or line_slug}",
                    })
        except Exception:
            pass

    context = {
        "product": product,
        "offers": getattr(product, "active_offers", []),
        "page_schema_payload": page_schema_payload,
        "whatsapp_link": whatsapp_link,
        "options_rows": options_rows,
        "config_primary": config_items[:10],
        "config_more": config_items[10:],
        "description_paragraphs": description_paragraphs,
        "description_bullets": description_bullets,
        "faq_items": faq_items,
        "related_products": related_products,
        "product_seo_h1": product_seo_h1,
        "product_seo_image_alt": product_seo_image_alt,
        "same_model_products": same_model_products,
        "seo_hub_links": seo_hub_links,
    }
    context.update(
        _seo_context(
            seo_title,
            seo_description,
            request,
            obj=product,
        )
    )
    return render(request, "catalog/product_detail.html", context)


def simple_page(request, slug):
    titles = {
        "about": _("О компании"),
        "service": _("Сервис"),
        "parts": _("Запчасти"),
        "news": _("Новости"),
        "privacy": _("Политика конфиденциальности"),
    }
    descriptions = {
        "about": _("Официальный дилер SHACMAN: подбор техники, поставка и сопровождение по РФ."),
        "news": _("Новости, обзоры и материалы по коммерческой технике CARFAST."),
        "privacy": _("Политика конфиденциальности и обработка персональных данных CARFAST."),
    }
    # For privacy page, H1/title must be RU and stable regardless of slug/meta.
    title = "Политика конфиденциальности" if slug == "privacy" else titles.get(slug) or slug
    description = descriptions.get(slug) or _("CARFAST страница")
    context = _seo_context(title, description, request)
    context["page_slug"] = slug
    context["h1_title"] = title
    if slug == "privacy":
        if not request.GET:
            context["meta_robots"] = "index, follow"
        canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        canonical_url = f"https://{canonical_host}/privacy/"
        context["canonical"] = canonical_url
        context["og_url"] = canonical_url
    if slug == "news":
        news_schema = {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Новости CARFAST",
            "itemListElement": [],
        }
        context["page_schema_payload"] = json.dumps([news_schema], ensure_ascii=False)[1:-1]
    return render(request, "pages/page.html", context)


def info_page(request, slug):
    def _leasing_display_name(name: str) -> str:
        lower_name = (name or "").lower()
        if "лизинг" in lower_name or "автолизинг" in lower_name:
            return name
        return f"{name} Лизинг"

    pages = {
        "parts": {
            "title": "Запчасти",
            "template": "pages/parts.html",
            "description": (
                "Запчасти для китайских грузовиков и спецтехники: подбор по VIN/табличке, "
                "оригинал и проверенные аналоги, контроль совместимости, наличие и доставка по РФ."
            ),
        },
        "service": {
            "title": "Сервис",
            "template": "pages/service.html",
            "description": (
                "Сервис китайских грузовиков и спецтехники: диагностика, план работ, "
                "запчасти под ремонт и рекомендации для снижения простоев и рисков."
            ),
        },
        "leasing": {
            "title": "Лизинг",
            "template": "pages/leasing.html",
            "description": "Подберём лизинговую программу под задачу и бюджет.",
        },
        "used": {
            "title": "Б/У техника",
            "template": "pages/used.html",
            "description": (
                "Б/у техника для бизнеса: подбор по партнёрским стокам, 3–7 вариантов под задачу, "
                "чек-лист проверки, помощь с осмотром и сопровождение выбора."
            ),
        },
        "payment-delivery": {
            "title": "Оплата и доставка",
            "template": "pages/payment_delivery.html",
            "description": "Прозрачные условия оплаты и логистики по РФ.",
        },
        "blog": {
            "title": "Блог",
            "template": "pages/blog.html",
            "description": "Новости, обзоры и полезные материалы по технике.",
        },
    }
    page = pages.get(slug)
    if not page:
        raise Http404
    context = _seo_context(page["title"], page["description"], request)
    context["page_slug"] = slug
    context["h1_title"] = page["title"]

    # StaticPageSEO: управляемый intro/body/FAQ и meta для leasing, used, service, parts, payment-delivery
    static_seo_slugs = {"leasing", "used", "service", "parts", "payment-delivery"}
    context["static_seo_intro_html"] = ""
    context["static_seo_body_html"] = ""
    context["static_faq_items"] = []
    context["schema_allowed"] = len(request.GET) == 0
    if slug in static_seo_slugs:
        static_seo = StaticPageSEO.objects.filter(slug=slug).first()
        if static_seo:
            if (static_seo.meta_title or "").strip():
                context["meta_title"] = (static_seo.meta_title or "").strip()
            if (static_seo.meta_description or "").strip():
                context["meta_description"] = (static_seo.meta_description or "").strip()
            context["static_seo_intro_html"] = (static_seo.seo_intro_html or "").strip()
            context["static_seo_body_html"] = (static_seo.seo_body_html or "").strip()
            context["static_faq_items"] = _parse_seo_faq(static_seo.faq_items or "")
            if context["schema_allowed"] and context["static_faq_items"]:
                faq_schema = _build_faq_schema(context["static_faq_items"])
                context["page_schema_payload"] = json.dumps([faq_schema], ensure_ascii=False)[1:-1]
    if not context.get("schema_allowed"):
        context.pop("page_schema_payload", None)

    if slug == "blog":
        context["meta_robots"] = "noindex,follow"
    if slug == "used":
        context["used_products"] = (
            Product.objects.public()
            .filter(is_used=True)
            .with_stock_stats()
            .select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("-updated_at", "-created_at")
        )
    if slug == "leasing":
        partners_primary = [
            {
                "key": "sberleasing",
                "name": "СберЛизинг",
                "description": "Лизинговые программы для бизнеса: транспорт и спецтехника.",
            },
            {
                "key": "rshb-leasing",
                "name": "Россельхозбанк",
                "description": "Лизинг транспорта и спецтехники для бизнеса.",
            },
            {
                "key": "reso-leasing",
                "name": "РЕСО-Лизинг",
                "description": "Подбор графика и условий под задачу.",
            },
            {
                "key": "interleasing",
                "name": "ИнтерЛизинг",
                "description": "Решения для обновления парка техники.",
            },
            {
                "key": "carcade",
                "name": "Каркаде",
                "description": "Лизинг для корпоративных клиентов.",
            },
            {
                "key": "europlan",
                "name": "Европлан",
                "description": "Гибкие условия и сопровождение сделки.",
            },
            {
                "key": "gpb-autoleasing",
                "name": "Газпромбанк Автолизинг",
                "description": "Поддержка сделки на всех этапах.",
            },
            {
                "key": "baltic-leasing",
                "name": "Балтийский Лизинг",
                "description": "Программы для транспорта и спецтехники.",
            },
            {
                "key": "realist",
                "name": "Реалист",
                "description": "Подбор параметров лизинга под бюджет.",
            },
        ]
        partners_more = [
            {
                "key": "alfa-leasing",
                "name": "Альфа",
                "description": "Лизинговые решения для бизнеса.",
            },
            {
                "key": "fleet-leasing",
                "name": "Флит",
                "description": "Сопровождение и подбор условий.",
            },
            {
                "key": "evolyutsiya-leasing",
                "name": "Эволюция",
                "description": "Гибкие программы для техники.",
            },
            {
                "key": "alliance-leasing",
                "name": "Альянс",
                "description": "Лизинг транспорта и спецтехники.",
            },
            {
                "key": "rosbank-leasing",
                "name": "Росбанк",
                "description": "Индивидуальные условия сделки.",
            },
            {
                "key": "vtb-leasing",
                "name": "ВТБ",
                "description": "Подбор графика и параметров.",
            },
            {
                "key": "baikalinvest-leasing",
                "name": "БайкалИнвест",
                "description": "Лизинговые программы под задачу.",
            },
            {
                "key": "psb-leasing",
                "name": "ПСБ Лизинг",
                "description": "Поддержка на этапе согласований.",
            },
            {
                "key": "asia-leasing",
                "name": "Азия Лизинг",
                "description": "Решения для обновления парка.",
            },
            {
                "key": "sovcombank-leasing",
                "name": "Совкомбанк",
                "description": "Условия, адаптированные под бизнес.",
            },
            {
                "key": "rodelen",
                "name": "Роделен",
                "description": "Программы для транспорта и спецтехники.",
            },
            {
                "key": "element-leasing",
                "name": "Элемент Лизинг",
                "description": "Сопровождение сделки и документов.",
            },
        ]
        def _decorate(items: list[dict]) -> list[dict]:
            result = []
            for item in items:
                display_name = _leasing_display_name(item["name"])
                result.append(
                    {
                        **item,
                        "display_name": display_name,
                        "logo_png_path": f"img/leasing/{item['key']}.png",
                        "logo_webp_path": f"img/leasing/{item['key']}.webp",
                    }
                )
            return result

        context["leasing_partners_primary"] = _decorate(partners_primary)
        context["leasing_partners_more"] = _decorate(partners_more)
    return render(request, page["template"], context)


def contacts(request):
    form = ContactsLeadForm(request.POST or None)
    if request.method == "POST":
        # Throttling: minimum 1 submission per minute per IP/session (same policy as lead_page)
        client_ip = _get_client_ip(request)
        cache_key = f"contacts_throttle_ip_{client_ip}"
        last_submission_time = _cache_get_safe(cache_key)
        session_limit = request.session.get("last_contacts_ts")

        current_time = time.time()
        throttle_seconds = 60

        if last_submission_time and (current_time - last_submission_time) < throttle_seconds:
            form.add_error(None, _("Слишком часто, попробуйте позже"))
        elif session_limit and (current_time - session_limit) < throttle_seconds:
            form.add_error(None, _("Слишком часто, попробуйте позже"))
        elif form.is_valid():
            name = form.cleaned_data.get("name") or "Не указано"
            phone = form.cleaned_data["phone"]
            city = form.cleaned_data.get("city") or ""
            message = form.cleaned_data.get("message") or ""

            parts: list[str] = []
            if city:
                parts.append(f"Город: {city}")
            if message:
                parts.append(message)
            final_message = "\n".join(parts)

            lead = Lead.objects.create(
                name=name,
                phone=phone,
                email="",
                message=final_message,
                source="contacts",
            )

            request.session["last_contacts_ts"] = current_time
            _cache_set_safe(cache_key, current_time, throttle_seconds)

            _notify_lead(lead, request, extra_data={"city": city, "message": message})
            messages.success(
                request,
                _("Спасибо! Заявка отправлена — мы свяжемся с вами в ближайшее время."),
            )
            return redirect(reverse("catalog:contacts") + "#feedback")

    context = {"form": form}
    context.update(
        _seo_context(
            _("Контакты"),
            _("Контакты CARFAST: телефон, email, адреса и форма связи."),
            request,
        )
    )
    return render(request, "pages/contacts.html", context)


def admin_guide(request):
    if not (settings.DEBUG or request.user.is_staff):
        raise Http404
    context = _seo_context(
        _("Гайд по админке"),
        _("Инструкция по наполнению сайта (бренды, категории, товары, контакты)."),
        request,
    )
    return render(request, "pages/admin_guide.html", context)


def _get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "")
    return ip


def lead_page(request):
    return _lead_common(request, template="catalog/lead_page.html")


def lead_thank_you(request):
    """Thank you page after successful lead submission."""
    context = _seo_context(
        "Спасибо за заявку — CARFAST",
        "Ваша заявка принята. Мы свяжемся с вами в ближайшее время.",
        request,
    )
    return render(request, "catalog/lead_thank_you.html", context)


def _lead_common(request, template="catalog/lead_page.html"):
    """
    Common handler for lead page. Always returns 200, even with invalid product parameter.
    Accepts product_slug, product_id, or product (sku) for backward compatibility.
    """
    product_param = (
        request.GET.get("product")
        or request.GET.get("product_slug")
        or request.GET.get("product_id")
    )
    initial = {}
    initial_product = None
    
    if product_param:
        try:
            product_param = str(product_param).strip()
            # Avoid pathological inputs (still keep behavior for normal slugs/SKUs)
            if len(product_param) > 255:
                product_param = product_param[:255]

            # Try by slug first (most common)
            initial_product = (
                Product.objects.public().filter(slug__iexact=product_param).first()
            )
            # Try by ID if slug didn't match
            if not initial_product:
                try:
                    product_id = int(product_param)
                    initial_product = (
                        Product.objects.public().filter(pk=product_id).first()
                    )
                except (ValueError, TypeError):
                    pass
            # Try by SKU for backward compatibility
            if not initial_product:
                initial_product = (
                    Product.objects.public().filter(sku__iexact=product_param).first()
                )

            if initial_product:
                initial["product"] = initial_product
        except Exception as exc:
            logger.warning(
                "Lead page: failed to resolve product param=%r: %s",
                product_param,
                exc,
                exc_info=True,
            )
    
    source = (request.GET.get("source") or "").strip()
    if source:
        initial["source"] = source[:255]
    form = LeadForm(request.POST or None, initial=initial)
    if initial_product:
        form.instance.product = initial_product
    
    # Throttling: check both session and IP-based cache
    client_ip = _get_client_ip(request)
    cache_key = f"lead_throttle_ip_{client_ip}"
    last_submission_time = _cache_get_safe(cache_key)
    session_limit = request.session.get("last_lead_ts")
    
    if request.method == "POST":
        # Check throttling: minimum 1 request per minute per IP
        current_time = time.time()
        throttle_seconds = 60
        
        if last_submission_time and (current_time - last_submission_time) < throttle_seconds:
            form.add_error(None, _("Слишком часто, попробуйте позже"))
        elif session_limit and (current_time - session_limit) < throttle_seconds:
            form.add_error(None, _("Слишком часто, попробуйте позже"))
        elif form.is_valid():
            lead = form.save(commit=False)
            
            # Save UTM parameters from GET or POST (POST takes precedence)
            utm_source = request.POST.get("utm_source") or request.GET.get("utm_source", "")
            utm_medium = request.POST.get("utm_medium") or request.GET.get("utm_medium", "")
            utm_campaign = request.POST.get("utm_campaign") or request.GET.get("utm_campaign", "")
            utm_term = request.POST.get("utm_term") or request.GET.get("utm_term", "")
            utm_content = request.POST.get("utm_content") or request.GET.get("utm_content", "")
            
            lead.utm_source = utm_source[:255]
            lead.utm_medium = utm_medium[:255]
            lead.utm_campaign = utm_campaign[:255]
            lead.utm_term = utm_term[:255]
            lead.utm_content = utm_content[:255]
            
            # Save referrer
            referrer = request.META.get("HTTP_REFERER", "")
            if referrer and not lead.source:
                lead.source = referrer[:255]
            
            lead.save()
            
            # Update throttling
            request.session["last_lead_ts"] = current_time
            _cache_set_safe(cache_key, current_time, throttle_seconds)
            
            _notify_lead(lead, request)
            is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
            if is_ajax:
                return HttpResponse(status=201)
            # Redirect to thank you page
            return redirect(reverse("catalog:lead_thank_you"))
    context = {"form": form}
    return render(request, template, context)


def _notify_lead(lead: Lead, request=None, extra_data=None):
    lead_data = {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "message": lead.message,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "utm_term": lead.utm_term,
        "utm_content": lead.utm_content,
        "source": lead.source,
    }
    if extra_data:
        lead_data.update(extra_data)

    if request:
        lead_data["page"] = request.path
        lead_data["page_url"] = request.build_absolute_uri(request.get_full_path())
        lead_data["user_agent"] = request.META.get("HTTP_USER_AGENT", "")
        lead_data["ip"] = _get_client_ip(request)
        lead_data["referrer"] = request.META.get("HTTP_REFERER", "")

    send_lead_notification(lead_data, source=lead.source or lead_data.get("page", "lead"))


def version_view(request):
    """Return build ID as JSON."""
    from carfst_site.build_id import get_build_id

    response = JsonResponse({"build_id": get_build_id()})
    # Prevent caching
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response
