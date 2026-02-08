"""
List Shacman hubs with qs_count < HUB_INDEX_MIN_PRODUCTS (noindex) and output CSV template for ShacmanHubSEO.

Usage:
  python manage.py list_shacman_thin_hubs
  python manage.py list_shacman_thin_hubs --format=csv
  python manage.py list_shacman_thin_hubs --format=csv --output=thin_hubs.csv

Shows which thin hubs can be safely switched to index when content is filled (force_index + sufficient).
Sitemap includes thin hubs ONLY when force_index=True and content sufficient (unchanged).
"""
import csv
import sys
from io import StringIO

from django.core.management.base import BaseCommand
from django.urls import reverse

from catalog.models import Category, ShacmanHubSEO
from catalog.views import (
    FORCE_INDEX_MIN_BODY_CHARS,
    FORCE_INDEX_MIN_FAQ,
    HUB_INDEX_MIN_PRODUCTS,
    _shacman_category_formula_allowed_from_db,
    _shacman_category_formula_hub_queryset,
    _shacman_category_line_allowed_from_db,
    _shacman_category_line_formula_allowed_from_db,
    _shacman_category_line_formula_hub_queryset,
    _shacman_hub_seo_content_sufficient,
    _shacman_line_category_hub_queryset,
    _shacman_line_formula_allowed_from_db,
    _shacman_line_formula_hub_queryset,
    _shacman_model_code_allowed_from_db,
    _shacman_model_code_hub_queryset,
)


def _thin_hub_rows():
    """Yield (hub_type, category_slug, facet_key, url, qs_count, can_index_with_content, force_index)."""
    # Category+line (main + in_stock)
    for (cat_slug, line_slug) in sorted(_shacman_category_line_allowed_from_db(min_count=1)):
        for in_stock, hub_type in [(False, "category_line"), (True, "category_line_in_stock")]:
            qs = _shacman_line_category_hub_queryset(line_slug, cat_slug, formula=None, in_stock_only=in_stock)
            cnt = qs.count() if hasattr(qs, "count") else 0
            if cnt >= HUB_INDEX_MIN_PRODUCTS:
                continue
            if in_stock:
                url = reverse("shacman_category_line_in_stock_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug})
            else:
                url = reverse("shacman_category_line_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug})
            cat = Category.objects.filter(slug=cat_slug).first()
            rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category=cat, facet_key__iexact=line_slug).first()
            force_index = bool(rec and getattr(rec, "force_index", False))
            can_index = bool(rec and force_index and _shacman_hub_seo_content_sufficient(rec))
            yield (hub_type, cat_slug, line_slug, url, cnt, can_index, force_index)

    # Line+formula
    for (line_slug, formula) in sorted(_shacman_line_formula_allowed_from_db(min_count=1)):
        for in_stock, hub_type in [(False, "line_formula"), (True, "line_formula_in_stock")]:
            qs = _shacman_line_formula_hub_queryset(line_slug, formula, in_stock_only=in_stock)
            cnt = qs.count() if hasattr(qs, "count") else 0
            if cnt >= HUB_INDEX_MIN_PRODUCTS:
                continue
            facet_key = f"{line_slug}:{formula}"
            if in_stock:
                url = reverse("shacman_line_formula_in_stock_hub", kwargs={"line_slug": line_slug, "formula_slug": formula})
            else:
                url = reverse("shacman_line_formula_hub", kwargs={"line_slug": line_slug, "formula_slug": formula})
            rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category__isnull=True, facet_key__iexact=facet_key).first()
            force_index = bool(rec and getattr(rec, "force_index", False))
            can_index = bool(rec and force_index and _shacman_hub_seo_content_sufficient(rec))
            yield (hub_type, "", facet_key, url, cnt, can_index, force_index)

    # Category+formula (explicit)
    for (cat_slug, formula) in sorted(_shacman_category_formula_allowed_from_db(min_count=1)):
        for in_stock, hub_type in [(False, "category_formula_explicit"), (True, "category_formula_explicit_in_stock")]:
            qs = _shacman_category_formula_hub_queryset(cat_slug, formula, in_stock_only=in_stock)
            cnt = qs.count() if hasattr(qs, "count") else 0
            if cnt >= HUB_INDEX_MIN_PRODUCTS:
                continue
            cat = Category.objects.filter(slug=cat_slug).first()
            rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category=cat, facet_key__iexact=formula).first()
            force_index = bool(rec and getattr(rec, "force_index", False))
            can_index = bool(rec and force_index and _shacman_hub_seo_content_sufficient(rec))
            url = (
                reverse("shacman_category_formula_explicit_in_stock_hub", kwargs={"category_slug": cat_slug, "formula_slug": formula})
                if in_stock
                else reverse("shacman_category_formula_explicit_hub", kwargs={"category_slug": cat_slug, "formula_slug": formula})
            )
            yield (hub_type, cat_slug, formula, url, cnt, can_index, force_index)

    # Category+line+formula
    for (cat_slug, line_slug, formula) in sorted(_shacman_category_line_formula_allowed_from_db(min_count=1)):
        for in_stock, hub_type in [(False, "category_line_formula"), (True, "category_line_formula_in_stock")]:
            qs = _shacman_category_line_formula_hub_queryset(cat_slug, line_slug, formula, in_stock_only=in_stock)
            cnt = qs.count() if hasattr(qs, "count") else 0
            if cnt >= HUB_INDEX_MIN_PRODUCTS:
                continue
            facet_key = f"{line_slug}:{formula}"
            cat = Category.objects.filter(slug=cat_slug).first()
            rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category=cat, facet_key__iexact=facet_key).first()
            force_index = bool(rec and getattr(rec, "force_index", False))
            can_index = bool(rec and force_index and _shacman_hub_seo_content_sufficient(rec))
            url = (
                reverse(
                    "shacman_category_line_formula_in_stock_hub",
                    kwargs={"category_slug": cat_slug, "line_slug": line_slug, "formula_slug": formula},
                )
                if in_stock
                else reverse(
                    "shacman_category_line_formula_hub",
                    kwargs={"category_slug": cat_slug, "line_slug": line_slug, "formula_slug": formula},
                )
            )
            yield (hub_type, cat_slug, facet_key, url, cnt, can_index, force_index)

    # Model code
    for model_code_slug in sorted(_shacman_model_code_allowed_from_db(min_count=1)):
        for in_stock, hub_type in [(False, "model_code"), (True, "model_code_in_stock")]:
            qs = _shacman_model_code_hub_queryset(model_code_slug, in_stock_only=in_stock)
            cnt = qs.count() if hasattr(qs, "count") else 0
            if cnt >= HUB_INDEX_MIN_PRODUCTS:
                continue
            rec = ShacmanHubSEO.objects.filter(hub_type=hub_type, category__isnull=True, facet_key__iexact=model_code_slug).first()
            force_index = bool(rec and getattr(rec, "force_index", False))
            can_index = bool(rec and force_index and _shacman_hub_seo_content_sufficient(rec))
            url = (
                reverse("shacman_model_code_in_stock_hub", kwargs={"model_code_slug": model_code_slug})
                if in_stock
                else reverse("shacman_model_code_hub", kwargs={"model_code_slug": model_code_slug})
            )
            yield (hub_type, "", model_code_slug, url, cnt, can_index, force_index)


class Command(BaseCommand):
    help = "List Shacman hubs with qs_count < HUB_INDEX_MIN_PRODUCTS and output CSV template for ShacmanHubSEO"

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            type=str,
            default="table",
            choices=["table", "csv"],
            help="Output format (default: table)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Write CSV to file (default: stdout)",
        )

    def handle(self, *args, **options):
        fmt = options["format"]
        output_path = (options["output"] or "").strip()
        rows = list(_thin_hub_rows())

        if fmt == "table":
            self.stdout.write(f"Thin hubs (qs_count < {HUB_INDEX_MIN_PRODUCTS}), noindex. Can index with force_index + content (≥{FORCE_INDEX_MIN_BODY_CHARS} chars or ≥{FORCE_INDEX_MIN_FAQ} FAQ).\n")
            if not rows:
                self.stdout.write("No thin hubs found.")
                return
            for (hub_type, cat_slug, facet_key, url, cnt, can_index, force_index) in rows:
                self.stdout.write(f"  {hub_type} | cat={cat_slug!r} facet={facet_key!r} | count={cnt} | can_index={can_index} | force_index={force_index} | {url}")
            self.stdout.write(f"\nTotal: {len(rows)}. Fill ShacmanHubSEO (meta_title, meta_description, seo_body_html, faq, force_index=True) and ensure content sufficient to include in sitemap.")
        else:
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "hub_type", "category_slug", "facet_key", "url", "qs_count", "can_index_with_content", "force_index",
                "meta_title", "meta_description", "meta_h1", "seo_body_html", "faq_items",
            ])
            for (hub_type, cat_slug, facet_key, url, cnt, can_index, force_index) in rows:
                writer.writerow([
                    hub_type, cat_slug, facet_key, url, cnt, can_index, force_index,
                    "", "", "", "", "",
                ])
            csv_content = buf.getvalue()
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(csv_content)
                self.stdout.write(f"Wrote {len(rows)} rows to {output_path}")
            else:
                sys.stdout.write(csv_content)
