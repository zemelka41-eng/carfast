"""
Prioritize Shacman hubs for content filling using Wordstat (or similar) CSV: aggregate demand by target_url,
output top URLs + demand, match to hubs and thin hubs to form a content backlog.

Usage:
  python manage.py prioritize_shacman_hubs_from_wordstat wordstat_sale_queries_carfstru.csv
  python manage.py prioritize_shacman_hubs_from_wordstat /path/to.csv --url-column=url --demand-column=shows
  python manage.py prioritize_shacman_hubs_from_wordstat /path/to.csv --top=50

CSV: expected columns (by default) "target_url" or "url" for URL, "demand" or "impressions" or "shows" for numeric demand.
Output: top URLs by aggregated demand; for hub URLs — which ShacmanHubSEO fields to fill; thin hubs with high demand as backlog.
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.urls import reverse

from catalog.models import Category, ShacmanHubSEO
from catalog.views import (
    HUB_INDEX_MIN_PRODUCTS,
    _shacman_category_formula_allowed_from_db,
    _shacman_category_line_allowed_from_db,
    _shacman_category_line_formula_allowed_from_db,
    _shacman_line_formula_allowed_from_db,
    _shacman_line_category_hub_queryset,
    _shacman_line_formula_hub_queryset,
    _shacman_category_formula_hub_queryset,
    _shacman_category_line_formula_hub_queryset,
    _shacman_model_code_allowed_from_db,
)


def _normalize_path(url_or_path: str) -> str:
    """Strip scheme/host, trailing slash, query. Return path like /shacman/line/x3000/."""
    s = (url_or_path or "").strip()
    if not s:
        return ""
    m = re.match(r"https?://[^/]+(/.*?)(?:\?|$)", s)
    if m:
        s = m.group(1)
    elif not s.startswith("/"):
        s = "/" + s
    return s.rstrip("/") or "/"


def _all_shacman_hub_paths():
    """Set of normalized paths for all Shacman hub URLs we can reverse."""
    paths = set()
    try:
        paths.add(_normalize_path(reverse("shacman_hub")))
        paths.add(_normalize_path(reverse("shacman_in_stock")))
    except Exception:
        pass
    for cat in Category.objects.filter(slug__isnull=False).values_list("slug", flat=True)[:100]:
        try:
            paths.add(_normalize_path(reverse("shacman_category", kwargs={"category_slug": cat})))
            paths.add(_normalize_path(reverse("shacman_category_in_stock", kwargs={"category_slug": cat})))
        except Exception:
            pass
    for (cat_slug, line_slug) in _shacman_category_line_allowed_from_db(min_count=1):
        try:
            paths.add(_normalize_path(reverse("shacman_category_line_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug})))
            paths.add(_normalize_path(reverse("shacman_category_line_in_stock_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug})))
        except Exception:
            pass
    for (line_slug, formula) in _shacman_line_formula_allowed_from_db(min_count=1):
        try:
            paths.add(_normalize_path(reverse("shacman_line_formula_hub", kwargs={"line_slug": line_slug, "formula_slug": formula})))
            paths.add(_normalize_path(reverse("shacman_line_formula_in_stock_hub", kwargs={"line_slug": line_slug, "formula_slug": formula})))
        except Exception:
            pass
    for (cat_slug, formula) in _shacman_category_formula_allowed_from_db(min_count=1):
        try:
            paths.add(_normalize_path(reverse("shacman_category_formula_explicit_hub", kwargs={"category_slug": cat_slug, "formula_slug": formula})))
            paths.add(_normalize_path(reverse("shacman_category_formula_explicit_in_stock_hub", kwargs={"category_slug": cat_slug, "formula_slug": formula})))
        except Exception:
            pass
    for (cat_slug, line_slug, formula) in _shacman_category_line_formula_allowed_from_db(min_count=1):
        try:
            paths.add(_normalize_path(reverse("shacman_category_line_formula_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug, "formula_slug": formula})))
            paths.add(_normalize_path(reverse("shacman_category_line_formula_in_stock_hub", kwargs={"category_slug": cat_slug, "line_slug": line_slug, "formula_slug": formula})))
        except Exception:
            pass
    for model_code_slug in _shacman_model_code_allowed_from_db(min_count=1):
        try:
            paths.add(_normalize_path(reverse("shacman_model_code_hub", kwargs={"model_code_slug": model_code_slug})))
            paths.add(_normalize_path(reverse("shacman_model_code_in_stock_hub", kwargs={"model_code_slug": model_code_slug})))
        except Exception:
            pass
    return paths


def _thin_hub_paths_with_count():
    """Dict path -> (hub_type, category_slug, facet_key, qs_count) for thin hubs."""
    out = {}
    for (hub_type, cat_slug, facet_key, url, cnt, _can, _force) in _thin_hub_rows():
        path = _normalize_path(url)
        out[path] = (hub_type, cat_slug, facet_key, cnt)
    return out


def _thin_hub_rows():
    """Yield same 7-tuple as list_shacman_thin_hubs._thin_hub_rows for reuse."""
    from catalog.management.commands.list_shacman_thin_hubs import _thin_hub_rows as _rows
    return list(_rows())


class Command(BaseCommand):
    help = "Prioritize Shacman hubs from Wordstat CSV: aggregate by target_url, output top URLs and content backlog"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to CSV (e.g. wordstat_sale_queries_carfstru.csv)")
        parser.add_argument(
            "--url-column",
            type=str,
            default="",
            help="CSV column for URL (default: try target_url, url)",
        )
        parser.add_argument(
            "--demand-column",
            type=str,
            default="",
            help="CSV column for demand (default: try demand, impressions, shows)",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=100,
            help="Number of top URLs to show (default: 100)",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]
        url_col = (options["url_column"] or "").strip()
        demand_col = (options["demand_column"] or "").strip()
        top_n = max(1, options["top"])

        path = Path(csv_path)
        if not path.is_file():
            self.stderr.write(self.style.ERROR(f"File not found: {csv_path}"))
            return

        # Aggregate demand by normalized path
        path_demand = defaultdict(lambda: 0)
        candidates_url = ["target_url", "url", "Target URL", "URL", "target_url"]
        candidates_demand = ["demand", "impressions", "shows", "Demand", "Impressions", "Shows"]
        if url_col:
            candidates_url = [url_col]
        if demand_col:
            candidates_demand = [demand_col]

        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            try:
                reader = csv.DictReader(f)
                headers = [h.strip() for h in (reader.fieldnames or [])]
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"CSV read failed: {e}"))
                return
            url_key = next((h for h in candidates_url if h in headers), None)
            demand_key = next((h for h in candidates_demand if h in headers), None)
            if not url_key:
                self.stderr.write(self.style.ERROR(f"URL column not found. Headers: {headers}"))
                return
            if not demand_key:
                demand_key = next((h for h in headers if h and h not in (url_key,)), None)
            for row in reader:
                u = (row.get(url_key) or "").strip()
                if not u:
                    continue
                path_norm = _normalize_path(u)
                if not path_norm or "/shacman/" not in path_norm:
                    continue
                try:
                    val = int(float(str(row.get(demand_key) or "0").replace(",", ".").split()[0] or 0))
                except (ValueError, TypeError):
                    val = 0
                path_demand[path_norm] += val

        # Sort by demand desc
        sorted_paths = sorted(path_demand.items(), key=lambda x: -x[1])[:top_n]
        hub_paths = _all_shacman_hub_paths()
        thin_info = _thin_hub_paths_with_count()

        self.stdout.write(self.style.SUCCESS(f"\n--- Top {top_n} URLs by demand (Shacman) ---\n"))
        for path, demand in sorted_paths:
            is_hub = path in hub_paths
            thin = thin_info.get(path)
            hint = ""
            if is_hub:
                hint = " [HUB: fill ShacmanHubSEO: meta_title, meta_description, seo_body_html, faq, force_index if thin]"
            if thin:
                hub_type, cat_slug, facet_key, qs_count = thin
                hint = f" [THIN HUB: {hub_type} cat={cat_slug} facet={facet_key} qs_count={qs_count} → fill content + force_index=True]"
            self.stdout.write(f"  {demand:>8}  {path}{hint}")

        self.stdout.write(self.style.SUCCESS("\n--- Content backlog: thin hubs with high demand ---\n"))
        thin_with_demand = [(p, path_demand.get(p, 0), thin_info[p]) for p in thin_info if path_demand.get(p, 0) > 0]
        thin_with_demand.sort(key=lambda x: -x[1])
        for path, demand, (hub_type, cat_slug, facet_key, qs_count) in thin_with_demand[:50]:
            self.stdout.write(
                f"  {demand:>8}  {path}  → hub_type={hub_type} category_slug={cat_slug!r} facet_key={facet_key!r} qs_count={qs_count}"
            )
            self.stdout.write("           Fill in admin: meta_title, meta_description, seo_body_html (≥1500 chars), faq (≥3), force_index=True")
        if not thin_with_demand:
            self.stdout.write("  (none: no thin hub paths found in CSV or no demand)")
        self.stdout.write("")
