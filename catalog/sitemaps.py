import logging

from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .models import Category, Product, Series

logger = logging.getLogger(__name__)


# /catalog/ section (catalog_list, catalog_series, catalog_category, catalog_series_category)
# is NOT included in sitemap per project invariants.


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        # Only canonical products: exclude aliases (canonical_product set) and redirects (redirect_to_url set)
        return (
            Product.objects.public()
            .filter(canonical_product__isnull=True)
            .filter(redirect_to_url="")
            .order_by("pk")
        )

    def location(self, obj):
        return obj.get_absolute_url()

    def lastmod(self, obj):
        return obj.updated_at


class SeriesSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        queryset = (
            Series.objects.public().filter(products__published=True, products__is_active=True)
            .annotate(latest_product=Max("products__updated_at"))
            .distinct()
            .order_by("pk")
        )
        return queryset

    def location(self, obj):
        return reverse("catalog:catalog_series", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return getattr(obj, "latest_product", None)


class CategorySitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        queryset = (
            Category.objects.filter(products__published=True, products__is_active=True)
            .annotate(latest_product=Max("products__updated_at"))
            .distinct()
            .order_by("pk")
        )
        return queryset

    def location(self, obj):
        return reverse("catalog:catalog_category", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return getattr(obj, "latest_product", None)


class SeriesCategorySitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        # Use values() instead of values_list() to include annotated field
        pairs = (
            Product.objects.public()
            .exclude(series__slug__isnull=True)
            .exclude(category__slug__isnull=True)
            .values("series__slug", "category__slug")
            .annotate(latest_product=Max("updated_at"))
            .order_by()
            .distinct()
        )
        # Return tuples with (series_slug, category_slug, latest_product)
        return [
            (item["series__slug"], item["category__slug"], item["latest_product"])
            for item in pairs
            if item["series__slug"] and item["category__slug"]
        ]

    def location(self, obj):
        series_slug, category_slug = obj[0], obj[1]
        return reverse(
            "catalog:catalog_series_category",
            kwargs={"series_slug": series_slug, "category_slug": category_slug},
        )

    def lastmod(self, obj):
        """Return the latest updated_at timestamp for products in this series+category pair."""
        if len(obj) >= 3:
            return obj[2]
        return None


class ShacmanHubSitemap(Sitemap):
    """Clean URL hubs /shacman/* for SEO. lastmod from latest product in segment."""
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        from django.db.models import Max

        from catalog.views import (
            _shacman_allowed_clusters,
            _shacman_engine_allowed_from_db,
            _shacman_line_allowed_from_db,
            get_engine_in_stock_qs,
        )

        out = []
        out.append(("hub", None, None))
        out.append(("in_stock", None, None))
        try:
            clusters = _shacman_allowed_clusters()
        except Exception as e:
            logger.warning("ShacmanHubSitemap.items: _shacman_allowed_clusters failed: %s", e)
            clusters = {"formulas": []}
        for formula in clusters.get("formulas") or []:
            if formula and isinstance(formula, str) and formula.strip():
                out.append(("formula", formula.strip(), None))
                out.append(("formula_in_stock", formula.strip(), None))
        try:
            engine_slugs = _shacman_engine_allowed_from_db()
        except Exception as e:
            logger.warning("ShacmanHubSitemap.items: _shacman_engine_allowed_from_db failed: %s", e)
            engine_slugs = {}
        for slug in (list(engine_slugs.keys()) if isinstance(engine_slugs, dict) else list(engine_slugs or [])):
            if not slug or not str(slug).strip():
                continue
            slug = str(slug).strip()
            out.append(("engine", slug, None))
            try:
                if get_engine_in_stock_qs(slug).exists():
                    out.append(("engine_in_stock", slug, None))
            except Exception as e:
                logger.debug("ShacmanHubSitemap.items: get_engine_in_stock_qs(%r).exists() failed: %s", slug, e)
        try:
            line_slugs = _shacman_line_allowed_from_db()
        except Exception as e:
            logger.warning("ShacmanHubSitemap.items: _shacman_line_allowed_from_db failed: %s", e)
            line_slugs = {}
        for slug in (list(line_slugs.keys()) if isinstance(line_slugs, dict) else list(line_slugs or [])):
            if not slug or not str(slug).strip():
                continue
            slug = str(slug).strip()
            out.append(("line", slug, None))
            out.append(("line_in_stock", slug, None))
        try:
            categories_with_shacman = (
                Category.objects.filter(
                    products__series__slug__iexact="shacman",
                    products__published=True,
                    products__is_active=True,
                )
                .annotate(latest=Max("products__updated_at"))
                .distinct()
                .order_by("name")
            )
            for cat in categories_with_shacman:
                slug = getattr(cat, "slug", None)
                if slug and str(slug).strip():
                    out.append(("category", slug, getattr(cat, "latest", None)))
                    out.append(("category_in_stock", slug, getattr(cat, "latest", None)))
        except Exception as e:
            logger.warning("ShacmanHubSitemap.items: categories_with_shacman failed: %s", e)
        return out

    def location(self, item):
        kind, key, _ = item
        try:
            if kind == "hub":
                return reverse("shacman_hub")
            if kind == "in_stock":
                return reverse("shacman_in_stock")
            if kind == "formula" and key and str(key).strip():
                return reverse("shacman_formula_hub", kwargs={"formula": str(key).strip()})
            if kind == "formula_in_stock" and key and str(key).strip():
                return reverse("shacman_formula_in_stock_hub", kwargs={"formula": str(key).strip()})
            if kind == "engine" and key and str(key).strip():
                return reverse("shacman_engine_hub", kwargs={"engine_slug": str(key).strip()})
            if kind == "engine_in_stock" and key and str(key).strip():
                return reverse("shacman_engine_in_stock_hub", kwargs={"engine_slug": str(key).strip()})
            if kind == "line" and key and str(key).strip():
                return reverse("shacman_line_hub", kwargs={"line_slug": str(key).strip()})
            if kind == "line_in_stock" and key and str(key).strip():
                return reverse("shacman_line_in_stock_hub", kwargs={"line_slug": str(key).strip()})
            if kind == "category" and key and str(key).strip():
                return reverse("shacman_category", kwargs={"category_slug": str(key).strip()})
            if kind == "category_in_stock" and key and str(key).strip():
                return reverse("shacman_category_in_stock", kwargs={"category_slug": str(key).strip()})
            return reverse("shacman_hub")
        except NoReverseMatch as e:
            logger.warning("ShacmanHubSitemap.location: NoReverseMatch kind=%r key=%r: %s", kind, key, e)
            return reverse("shacman_hub")
        except Exception as e:
            logger.warning("ShacmanHubSitemap.location: unexpected error kind=%r key=%r: %s", kind, key, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        _, _, latest = item
        return latest


class ShacmanComboHubSitemap(Sitemap):
    """Combo hubs /shacman/line/<line>/<category>/ and +/<formula>/ (only count>=2, cap 50).
    Uses same allow-source as combo views: _shacman_combo_allowed_from_db() (slug-form keys, no cache).
    """
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_combo_allowed_from_db

            allowed = _shacman_combo_allowed_from_db()
            out = []
            for (line_slug, category_slug) in getattr(allowed, "lc", []):
                if line_slug and category_slug and str(line_slug).strip() and str(category_slug).strip():
                    out.append(("line_category", str(line_slug).strip(), str(category_slug).strip(), None))
                    out.append(("line_category_in_stock", str(line_slug).strip(), str(category_slug).strip(), None))
            for (line_slug, category_slug, formula) in getattr(allowed, "lcf", []):
                if line_slug and category_slug and formula and str(formula).strip():
                    out.append(("line_category_formula", line_slug, category_slug, str(formula).strip()))
                    out.append(("line_category_formula_in_stock", line_slug, category_slug, str(formula).strip()))
            return out
        except Exception as e:
            logger.warning("ShacmanComboHubSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            kind, line_slug, category_slug, formula = item
            if not line_slug or not category_slug:
                return reverse("shacman_hub")
            if kind == "line_category":
                return reverse("shacman_line_category_hub", kwargs={"line_slug": line_slug, "category_slug": category_slug})
            if kind == "line_category_in_stock":
                return reverse(
                    "shacman_line_category_in_stock_hub",
                    kwargs={"line_slug": line_slug, "category_slug": category_slug},
                )
            if kind == "line_category_formula" and formula:
                return reverse(
                    "shacman_line_category_formula_hub",
                    kwargs={"line_slug": line_slug, "category_slug": category_slug, "formula": formula},
                )
            if kind == "line_category_formula_in_stock" and formula:
                return reverse(
                    "shacman_line_category_formula_in_stock_hub",
                    kwargs={"line_slug": line_slug, "category_slug": category_slug, "formula": formula},
                )
            return reverse("shacman_hub")
        except Exception as e:
            logger.warning("ShacmanComboHubSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanEngineCategorySitemap(Sitemap):
    """Engine+category hubs /shacman/engine/<engine_slug>/<category_slug>/ (only count>=2, cap 50)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_engine_category_allowed_from_db

            allowed = _shacman_engine_category_allowed_from_db()
            out = []
            for (engine_slug, category_slug) in sorted(allowed or []):
                if engine_slug and category_slug and str(engine_slug).strip() and str(category_slug).strip():
                    out.append((str(engine_slug).strip(), str(category_slug).strip(), "main"))
                    out.append((str(engine_slug).strip(), str(category_slug).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanEngineCategorySitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            engine_slug, category_slug, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_engine_category_in_stock_hub",
                    kwargs={"engine_slug": engine_slug, "category_slug": category_slug},
                )
            return reverse(
                "shacman_engine_category_hub",
                kwargs={"engine_slug": engine_slug, "category_slug": category_slug},
            )
        except Exception as e:
            logger.warning("ShacmanEngineCategorySitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanLineEngineSitemap(Sitemap):
    """Line+engine hubs /shacman/line/<line_slug>/engine/<engine_slug>/ (only count>=2, cap 50)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_line_engine_allowed_from_db

            allowed = _shacman_line_engine_allowed_from_db()
            out = []
            for (line_slug, engine_slug) in sorted(allowed or []):
                if line_slug and engine_slug and str(line_slug).strip() and str(engine_slug).strip():
                    out.append((str(line_slug).strip(), str(engine_slug).strip(), "main"))
                    out.append((str(line_slug).strip(), str(engine_slug).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanLineEngineSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            line_slug, engine_slug, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_line_engine_in_stock_hub",
                    kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
                )
            return reverse(
                "shacman_line_engine_hub",
                kwargs={"line_slug": line_slug, "engine_slug": engine_slug},
            )
        except Exception as e:
            logger.warning("ShacmanLineEngineSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanCategoryEngineSitemap(Sitemap):
    """Category-first engine hubs /shacman/category/<category_slug>/engine/<engine_slug>/.
    Items built only from _shacman_engine_category_allowed_from_db() (engine in engine list + >=1 product per pair).
    No 404 URLs in sitemap."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_engine_category_allowed_from_db

            allowed = _shacman_engine_category_allowed_from_db()
            out = []
            for (engine_slug, category_slug) in sorted(allowed or []):
                if engine_slug and category_slug and str(engine_slug).strip() and str(category_slug).strip():
                    out.append((str(category_slug).strip(), str(engine_slug).strip(), "main"))
                    out.append((str(category_slug).strip(), str(engine_slug).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanCategoryEngineSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            category_slug, engine_slug, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_category_engine_in_stock_hub",
                    kwargs={"category_slug": category_slug, "engine_slug": engine_slug},
                )
            return reverse(
                "shacman_category_engine_hub",
                kwargs={"category_slug": category_slug, "engine_slug": engine_slug},
            )
        except Exception as e:
            logger.warning("ShacmanCategoryEngineSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanCategoryLineSitemap(Sitemap):
    """Category-first line+category: /shacman/category/<category_slug>/line/<line_slug>/ (count>=min OR force_index+sufficient)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_category_line_indexable

            allowed = _shacman_category_line_indexable()
            out = []
            for (category_slug, line_slug) in sorted(allowed or []):
                if category_slug and line_slug and str(category_slug).strip() and str(line_slug).strip():
                    out.append((str(category_slug).strip(), str(line_slug).strip(), "main"))
                    out.append((str(category_slug).strip(), str(line_slug).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanCategoryLineSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            category_slug, line_slug, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_category_line_in_stock_hub",
                    kwargs={"category_slug": category_slug, "line_slug": line_slug},
                )
            return reverse(
                "shacman_category_line_hub",
                kwargs={"category_slug": category_slug, "line_slug": line_slug},
            )
        except Exception as e:
            logger.warning("ShacmanCategoryLineSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanLineFormulaSitemap(Sitemap):
    """Line+formula: /shacman/line/<line_slug>/formula/<formula_slug>/ (count>=min OR force_index+sufficient)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_line_formula_indexable

            allowed = _shacman_line_formula_indexable()
            out = []
            for (line_slug, formula) in sorted(allowed or []):
                if line_slug and formula and str(line_slug).strip() and str(formula).strip():
                    out.append((str(line_slug).strip(), str(formula).strip(), "main"))
                    out.append((str(line_slug).strip(), str(formula).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanLineFormulaSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            line_slug, formula, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_line_formula_in_stock_hub",
                    kwargs={"line_slug": line_slug, "formula_slug": formula},
                )
            return reverse(
                "shacman_line_formula_hub",
                kwargs={"line_slug": line_slug, "formula_slug": formula},
            )
        except Exception as e:
            logger.warning("ShacmanLineFormulaSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanCategoryFormulaSitemap(Sitemap):
    """Category+formula hubs /shacman/category/<category_slug>/formula/<formula_slug>/ (count>=min OR force_index+sufficient)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_category_formula_indexable

            allowed = _shacman_category_formula_indexable()
            out = []
            for (category_slug, formula) in sorted(allowed or []):
                if category_slug and formula and str(category_slug).strip() and str(formula).strip():
                    out.append((str(category_slug).strip(), str(formula).strip(), "main"))
                    out.append((str(category_slug).strip(), str(formula).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanCategoryFormulaSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            category_slug, formula, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_category_formula_explicit_in_stock_hub",
                    kwargs={"category_slug": category_slug, "formula_slug": formula},
                )
            return reverse(
                "shacman_category_formula_explicit_hub",
                kwargs={"category_slug": category_slug, "formula_slug": formula},
            )
        except Exception as e:
            logger.warning("ShacmanCategoryFormulaSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanModelCodeSitemap(Sitemap):
    """Model code: /shacman/model/<model_code_slug>/ (count>=min OR force_index+sufficient)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_model_code_indexable

            allowed = _shacman_model_code_indexable()
            out = []
            for model_code_slug in sorted(allowed or []):
                if model_code_slug and str(model_code_slug).strip():
                    out.append((str(model_code_slug).strip(), "main"))
                    out.append((str(model_code_slug).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanModelCodeSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            model_code_slug, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_model_code_in_stock_hub",
                    kwargs={"model_code_slug": model_code_slug},
                )
            return reverse(
                "shacman_model_code_hub",
                kwargs={"model_code_slug": model_code_slug},
            )
        except Exception as e:
            logger.warning("ShacmanModelCodeSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class ShacmanCategoryLineFormulaSitemap(Sitemap):
    """Category+line+formula: /shacman/category/<cat>/line/<line>/formula/<formula>/ (count>=min OR force_index+sufficient)."""
    changefreq = "weekly"
    priority = 0.65

    def items(self):
        try:
            from catalog.views import _shacman_category_line_formula_indexable

            allowed = _shacman_category_line_formula_indexable()
            out = []
            for (category_slug, line_slug, formula) in sorted(allowed or []):
                if category_slug and line_slug and formula and str(category_slug).strip() and str(line_slug).strip() and str(formula).strip():
                    out.append((str(category_slug).strip(), str(line_slug).strip(), str(formula).strip(), "main"))
                    out.append((str(category_slug).strip(), str(line_slug).strip(), str(formula).strip(), "in_stock"))
            return out
        except Exception as e:
            logger.warning("ShacmanCategoryLineFormulaSitemap.items failed: %s", e)
            return []

    def location(self, item):
        try:
            category_slug, line_slug, formula, kind = item
            if kind == "in_stock":
                return reverse(
                    "shacman_category_line_formula_in_stock_hub",
                    kwargs={"category_slug": category_slug, "line_slug": line_slug, "formula_slug": formula},
                )
            return reverse(
                "shacman_category_line_formula_hub",
                kwargs={"category_slug": category_slug, "line_slug": line_slug, "formula_slug": formula},
            )
        except Exception as e:
            logger.warning("ShacmanCategoryLineFormulaSitemap.location item=%r: %s", item, e)
            return reverse("shacman_hub")

    def lastmod(self, item):
        return None


class StaticViewSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        """Return only URL names that can be successfully reversed."""
        url_names = [
            "catalog:home",
            "catalog:catalog_in_stock",
            "catalog:about",
            "catalog:service",
            "catalog:leasing",
            "catalog:parts",
            "catalog:used",
            "catalog:payment_delivery",
            "catalog:contacts",
            "catalog:privacy",
            "catalog:news",
        ]
        # Filter out URL names that cannot be reversed
        valid_urls = []
        for url_name in url_names:
            try:
                reverse(url_name)
                valid_urls.append(url_name)
            except NoReverseMatch:
                # Skip invalid URL names to prevent sitemap errors
                continue
        return valid_urls

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        """Static pages: use current time so crawlers see periodic updates."""
        return timezone.now()

