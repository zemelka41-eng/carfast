"""
SEO Content Coverage Audit for carfst.ru

Checks completeness and length of SEO fields across all indexable landing pages.
Reports: OK / Missing / Too short + admin links.

Usage:
  python manage.py seo_content_audit [--format=table|csv|json] [--min-intro=600] [--min-body=2500] [--min-faq=6]
  python manage.py seo_content_audit --format=csv > seo_audit.csv
"""
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import strip_tags

from catalog.models import (
    CatalogLandingSEO,
    Category,
    Product,
    Series,
    SeriesCategorySEO,
    ShacmanHubSEO,
    StaticPageSEO,
)
from catalog.seo_text import visible_len, visible_text


def _notes_duplicate_additional_info(body_html: str) -> str:
    """Return audit note if 'Дополнительная информация' appears more than once, else ''."""
    if not (body_html or "").strip():
        return ""
    lower = (body_html or "").strip().lower()
    dup_count = lower.count("дополнительная информация")
    if dup_count <= 1:
        return ""
    return f"Duplicate heading: 'Дополнительная информация' appears {dup_count} times (recommend 0–1)"


@dataclass
class AuditEntry:
    entity_type: str  # CatalogLanding, ShacmanHub, Series, Category, SeriesCategory, StaticPage, Product
    identifier: str  # slug / landing_key / facet_key
    url: str  # frontend URL if available
    admin_url: str  # admin change URL
    meta_title_status: str  # OK / Missing / N/A
    intro_status: str  # OK / Missing / Too short / N/A
    body_status: str  # OK / Missing / Too short / N/A
    faq_status: str  # OK / Missing / Too short / N/A
    intro_len: int
    body_len: int
    faq_count: int
    notes: str = ""


class Command(BaseCommand):
    help = "Audit SEO content coverage across indexable landing pages"

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            type=str,
            default="table",
            choices=["table", "csv", "json"],
            help="Output format (default: table)",
        )
        parser.add_argument(
            "--min-intro",
            type=int,
            default=600,
            help="Minimum intro length in chars (default: 600)",
        )
        parser.add_argument(
            "--min-body",
            type=int,
            default=2500,
            help="Minimum body length in chars (default: 2500)",
        )
        parser.add_argument(
            "--min-faq",
            type=int,
            default=6,
            help="Minimum FAQ count (default: 6)",
        )
        parser.add_argument(
            "--show-ok",
            action="store_true",
            help="Show entries with all fields OK (default: hide)",
        )
        parser.add_argument(
            "--no-product-stats",
            action="store_true",
            help="Skip product statistics (avoids FieldError if images relation changed)",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default="",
            help="Base URL to prepend to admin links (e.g. https://carfst.ru)",
        )
        parser.add_argument(
            "--include-products",
            action="store_true",
            help="Include detailed SEO audit for individual products (may be slow)",
        )

    def handle(self, *args, **options):
        fmt = options["format"]
        min_intro = options["min_intro"]
        min_body = options["min_body"]
        min_faq = options["min_faq"]
        show_ok = options["show_ok"]
        no_product_stats = options.get("no_product_stats", False)
        self.base_url = options.get("base_url", "").rstrip("/")

        entries = []

        # 1. CatalogLandingSEO
        entries.extend(self._audit_catalog_landing(min_intro, min_body, min_faq))

        # 2. ShacmanHubSEO
        entries.extend(self._audit_shacman_hubs(min_intro, min_body, min_faq))

        # 3. Series (brands)
        entries.extend(self._audit_series(min_intro, min_body, min_faq))

        # 4. Category
        entries.extend(self._audit_categories(min_intro, min_body, min_faq))

        # 5. SeriesCategorySEO
        entries.extend(self._audit_series_category(min_intro, min_body, min_faq))

        # 6. StaticPageSEO
        entries.extend(self._audit_static_pages(min_intro, min_body, min_faq))

        # 7. Products (detailed SEO audit if --include-products)
        include_products = options.get("include_products", False)
        if include_products:
            entries.extend(self._audit_products_detailed(min_intro, min_body, min_faq))

        # 8. Products (optional: basic stats)
        product_stats = None
        product_stats_error = None
        if no_product_stats:
            product_stats_error = "skipped (--no-product-stats)"
        else:
            try:
                product_stats = self._audit_products()
            except Exception as exc:
                product_stats_error = f"{type(exc).__name__}: {exc}"

        # Filter out OK entries if not show_ok
        if not show_ok:
            entries = [e for e in entries if not self._is_ok(e)]

        # Output
        if fmt == "table":
            self._output_table(entries, product_stats, product_stats_error)
        elif fmt == "csv":
            self._output_csv(entries)
        elif fmt == "json":
            self._output_json(entries, product_stats, product_stats_error)

    def _is_ok(self, entry: AuditEntry) -> bool:
        """Returns True if all applicable fields are OK."""
        statuses = [
            entry.meta_title_status,
            entry.intro_status,
            entry.body_status,
            entry.faq_status,
        ]
        if not all(s in ("OK", "N/A") for s in statuses):
            return False
        if entry.notes and "force_index" in entry.notes and "insufficient" in entry.notes:
            return False
        return True

    def _get_admin_url(self, obj):
        """
        Generate admin change URL via Django reverse() + urljoin.
        Expects admin mounted at admin/ so reverse yields /admin/catalog/... (not /admincatalog/...).
        """
        path = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
        path = "/" + path.lstrip("/")
        if self.base_url:
            base = self.base_url.rstrip("/") + "/"
            return urljoin(base, path.lstrip("/"))
        return path

    def _audit_catalog_landing(self, min_intro, min_body, min_faq):
        entries = []
        for choice_value, choice_label in CatalogLandingSEO.LandingKey.choices:
            obj = CatalogLandingSEO.objects.filter(landing_key=choice_value).first()
            if obj:
                intro_status, intro_len = self._check_text(obj.seo_intro_html, min_intro)
                body_status, body_len = self._check_text(obj.seo_body_html, min_body)
                faq_status, faq_count = self._check_faq(obj.faq_items, min_faq)
                meta_status = "OK" if (obj.meta_title or "").strip() else "Missing"
                admin_url = self._get_admin_url(obj)
                entries.append(
                    AuditEntry(
                        entity_type="CatalogLanding",
                        identifier=choice_label,
                        url=choice_label,
                        admin_url=admin_url,
                        meta_title_status=meta_status,
                        intro_status=intro_status,
                        body_status=body_status,
                        faq_status=faq_status,
                        intro_len=intro_len,
                        body_len=body_len,
                        faq_count=faq_count,
                    )
                )
            else:
                entries.append(
                    AuditEntry(
                        entity_type="CatalogLanding",
                        identifier=choice_label,
                        url=choice_label,
                        admin_url="",
                        meta_title_status="Missing",
                        intro_status="Missing",
                        body_status="Missing",
                        faq_status="Missing",
                        intro_len=0,
                        body_len=0,
                        faq_count=0,
                        notes="Record does not exist",
                    )
                )
        return entries

    def _shacman_force_index_sufficient(self, hub):
        """True if hub has enough content for force_index (body/text ≥1500 chars or FAQ ≥3)."""
        body_len = max(
            visible_len(hub.seo_body_html or ""),
            visible_len(hub.seo_text or ""),
        )
        if body_len >= 1500:
            return True
        faq_count = len([line for line in (hub.faq or "").strip().split("\n") if "|" in line.strip()])
        return faq_count >= 3

    def _audit_shacman_hubs(self, min_intro, min_body, min_faq):
        entries = []
        hubs = ShacmanHubSEO.objects.all()
        for hub in hubs:
            intro_status, intro_len = self._check_text(hub.seo_intro_html, min_intro)
            body_status, body_len = self._check_text(hub.seo_body_html, min_body)
            faq_status, faq_count = self._check_faq(hub.faq, min_faq)
            meta_status = "OK" if (hub.meta_title or "").strip() else "Missing"
            admin_url = self._get_admin_url(hub)
            identifier = f"{hub.get_hub_type_display()}"
            if hub.category:
                identifier += f" [{hub.category.slug}]"
            if hub.facet_key:
                identifier += f" ({hub.facet_key})"
            notes_list = []
            if getattr(hub, "force_index", False) and not self._shacman_force_index_sufficient(hub):
                notes_list.append(
                    "force_index=True but content insufficient (need body/text ≥1500 chars or FAQ ≥3)"
                )
            if (hub.seo_text or "").strip() and (hub.seo_body_html or "").strip():
                notes_list.append(
                    "Both seo_text and seo_body_html set; template shows single block under cards (body preferred)"
                )
            # Effective body (what template shows: body else text)
            effective_body = (hub.seo_body_html or hub.seo_text or "").strip()
            if effective_body:
                dup_note = _notes_duplicate_additional_info(effective_body)
                if dup_note:
                    notes_list.append(dup_note)
                body_visible = visible_text(effective_body).lower()
                markers = ["купить", "цена", "в наличии", "лизинг"]
                found = sum(1 for m in markers if m in body_visible)
                if found < 2:
                    notes_list.append(
                        f"Few commercial markers (купить/цена/в наличии/лизинг): found {found}, recommend ≥2"
                    )
            notes_str = "; ".join(notes_list) if notes_list else ""
            entries.append(
                AuditEntry(
                    entity_type="ShacmanHub",
                    identifier=identifier,
                    url=f"/shacman/... ({hub.hub_type})",
                    admin_url=admin_url,
                    meta_title_status=meta_status,
                    intro_status=intro_status,
                    body_status=body_status,
                    faq_status=faq_status,
                    intro_len=intro_len,
                    body_len=body_len,
                    faq_count=faq_count,
                    notes=notes_str,
                )
            )
        return entries

    def _audit_series(self, min_intro, min_body, min_faq):
        entries = []
        series_qs = Series.objects.public()
        for s in series_qs:
            intro_status, intro_len = self._check_text(s.seo_intro_html, min_intro)
            body_status, body_len = self._check_text(s.seo_body_html, min_body)
            faq_status, faq_count = self._check_faq(s.seo_faq, min_faq)
            meta_status = "N/A"  # Series doesn't have meta_title override field
            admin_url = self._get_admin_url(s)
            url = f"/catalog/series/{s.slug}/"
            notes_str = _notes_duplicate_additional_info(s.seo_body_html or "")
            entries.append(
                AuditEntry(
                    entity_type="Series",
                    identifier=s.slug,
                    url=url,
                    admin_url=admin_url,
                    meta_title_status=meta_status,
                    intro_status=intro_status,
                    body_status=body_status,
                    faq_status=faq_status,
                    intro_len=intro_len,
                    body_len=body_len,
                    faq_count=faq_count,
                    notes=notes_str,
                )
            )
        return entries

    def _audit_categories(self, min_intro, min_body, min_faq):
        entries = []
        categories = Category.objects.all()
        for cat in categories:
            intro_status, intro_len = self._check_text(cat.seo_intro_html, min_intro)
            body_status, body_len = self._check_text(cat.seo_body_html, min_body)
            faq_status, faq_count = self._check_faq(cat.seo_faq, min_faq)
            meta_status = "N/A"
            admin_url = self._get_admin_url(cat)
            url = f"/catalog/category/{cat.slug}/"
            notes_str = _notes_duplicate_additional_info(cat.seo_body_html or "")
            entries.append(
                AuditEntry(
                    entity_type="Category",
                    identifier=cat.slug,
                    url=url,
                    admin_url=admin_url,
                    meta_title_status=meta_status,
                    intro_status=intro_status,
                    body_status=body_status,
                    faq_status=faq_status,
                    intro_len=intro_len,
                    body_len=body_len,
                    faq_count=faq_count,
                    notes=notes_str,
                )
            )
        return entries

    def _audit_series_category(self, min_intro, min_body, min_faq):
        entries = []
        scs = SeriesCategorySEO.objects.select_related("series", "category").all()
        for sc in scs:
            intro_status, intro_len = self._check_text(sc.seo_intro_html, min_intro)
            body_status, body_len = self._check_text(sc.seo_body_html, min_body)
            faq_status, faq_count = self._check_faq(sc.seo_faq, min_faq)
            meta_status = "N/A"
            admin_url = self._get_admin_url(sc)
            url = f"/catalog/series/{sc.series.slug}/{sc.category.slug}/"
            notes_str = _notes_duplicate_additional_info(sc.seo_body_html or "")
            entries.append(
                AuditEntry(
                    entity_type="SeriesCategory",
                    identifier=f"{sc.series.slug}/{sc.category.slug}",
                    url=url,
                    admin_url=admin_url,
                    meta_title_status=meta_status,
                    intro_status=intro_status,
                    body_status=body_status,
                    faq_status=faq_status,
                    intro_len=intro_len,
                    body_len=body_len,
                    faq_count=faq_count,
                    notes=notes_str,
                )
            )
        return entries

    def _audit_static_pages(self, min_intro, min_body, min_faq):
        entries = []
        expected_slugs = ["leasing", "used", "service", "parts", "payment-delivery"]
        for slug in expected_slugs:
            obj = StaticPageSEO.objects.filter(slug=slug).first()
            if obj:
                intro_status, intro_len = self._check_text(obj.seo_intro_html, min_intro)
                body_status, body_len = self._check_text(obj.seo_body_html, min_body)
                faq_status, faq_count = self._check_faq(obj.faq_items, min_faq)
                meta_status = "OK" if (obj.meta_title or "").strip() else "Missing"
                admin_url = self._get_admin_url(obj)
                entries.append(
                    AuditEntry(
                        entity_type="StaticPage",
                        identifier=slug,
                        url=f"/{slug}/",
                        admin_url=admin_url,
                        meta_title_status=meta_status,
                        intro_status=intro_status,
                        body_status=body_status,
                        faq_status=faq_status,
                        intro_len=intro_len,
                        body_len=body_len,
                        faq_count=faq_count,
                    )
                )
            else:
                entries.append(
                    AuditEntry(
                        entity_type="StaticPage",
                        identifier=slug,
                        url=f"/{slug}/",
                        admin_url="",
                        meta_title_status="Missing",
                        intro_status="Missing",
                        body_status="Missing",
                        faq_status="Missing",
                        intro_len=0,
                        body_len=0,
                        faq_count=0,
                        notes="Record does not exist",
                    )
                )
        return entries

    def _audit_products_detailed(self, min_intro, min_body, min_faq):
        """
        Detailed per-product SEO audit.
        Checks:
        - seo_title_override, seo_description_override (intro), seo_text_override (body), seo_faq_override
        - description_ru (main product description)
        - presence of at least one FAQ (either in override or default)
        - empty blocks detection
        """
        entries = []
        products = Product.objects.public().select_related("series", "category", "model_variant")
        
        for product in products:
            notes = []
            
            # Check SEO override fields
            meta_status = "OK" if (product.seo_title_override or "").strip() else "Missing"
            intro_status, intro_len = self._check_text(product.seo_description_override, min_intro)
            body_status, body_len = self._check_text(product.seo_text_override, min_body)
            faq_status, faq_count = self._check_faq(product.seo_faq_override, min_faq)
            
            # Check main description_ru (should not be empty)
            description_ru = (product.description_ru or "").strip()
            if not description_ru:
                notes.append("Main description (description_ru) is empty")
            else:
                description_len = len(strip_tags(description_ru).strip())
                if description_len < 200:
                    notes.append(f"Main description too short ({description_len} chars, recommended ≥200)")
            
            # Check for empty blocks (headings without content)
            if product.seo_text_override:
                empty_sections = self._detect_empty_sections(product.seo_text_override)
                if empty_sections:
                    notes.append(f"Empty sections detected: {', '.join(empty_sections)}")
            
            # FAQ check: at least some FAQ present (override or minimum default)
            has_any_faq = bool((product.seo_faq_override or "").strip())
            if not has_any_faq and faq_count < 5:
                notes.append("No FAQ content (recommend 5-8 FAQ items)")
            
            admin_url = self._get_admin_url(product)
            
            # Product identifier
            identifier = f"{product.slug}"
            if product.model_name_ru:
                identifier = f"{product.model_name_ru} [{product.slug}]"
            
            notes_str = "; ".join(notes) if notes else ""
            
            entries.append(
                AuditEntry(
                    entity_type="Product",
                    identifier=identifier,
                    url=product.get_absolute_url() if hasattr(product, 'get_absolute_url') else f"/product/{product.slug}/",
                    admin_url=admin_url,
                    meta_title_status=meta_status,
                    intro_status=intro_status,
                    body_status=body_status,
                    faq_status=faq_status,
                    intro_len=intro_len,
                    body_len=body_len,
                    faq_count=faq_count,
                    notes=notes_str,
                )
            )
        
        return entries
    
    def _detect_empty_sections(self, html_text):
        """
        Detect headings followed by no content or another heading immediately.
        Returns list of heading texts that appear to have empty sections.
        """
        import re
        empty_sections = []
        
        # Simple pattern: find <h2>...<h2> or <h3>...<h3> with only whitespace/tags between
        html_clean = (html_text or "").strip()
        if not html_clean:
            return empty_sections
        
        # Extract all headings with their positions
        heading_pattern = re.compile(r'<h([23])>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
        matches = list(heading_pattern.finditer(html_clean))
        
        for i, match in enumerate(matches):
            heading_text = strip_tags(match.group(0)).strip()
            start_pos = match.end()
            
            # Find next heading or end of text
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(html_clean)
            
            # Extract content between this heading and next
            content_between = html_clean[start_pos:end_pos].strip()
            content_text = strip_tags(content_between).strip()
            
            # If content is empty or very short (< 20 chars), mark as empty
            if len(content_text) < 20:
                empty_sections.append(heading_text[:50])  # Truncate long headings
        
        return empty_sections

    def _audit_products(self):
        """Basic product stats (not per-product audit)."""
        total = Product.objects.public().count()
        with_description = Product.objects.public().filter(~Q(description_ru="")).count()
        with_photos = (
            Product.objects.public()
            .annotate(photo_count=Count("images", distinct=True))
            .filter(photo_count__gt=0)
            .count()
        )
        return {
            "total_public": total,
            "with_description": with_description,
            "with_photos": with_photos,
            "description_coverage": round(with_description / total * 100, 1) if total else 0,
            "photo_coverage": round(with_photos / total * 100, 1) if total else 0,
        }

    def _check_text(self, text, min_len):
        """Returns (status, length). Length via visible_len (shared with seed)."""
        raw = (text or "").strip()
        if not raw:
            return "Missing", 0
        length = visible_len(raw)
        if length < min_len:
            return "Too short", length
        return "OK", length

    def _check_faq(self, faq_text, min_count):
        """Returns (status, count)."""
        faq_clean = (faq_text or "").strip()
        if not faq_clean:
            return "Missing", 0
        lines = [line.strip() for line in faq_clean.split("\n") if "|" in line]
        count = len(lines)
        if count < min_count:
            return "Too short", count
        return "OK", count

    def _output_table(self, entries, product_stats, product_stats_error=None):
        """Print human-readable table to stdout."""
        self.stdout.write(self.style.SUCCESS("\n=== SEO Content Coverage Audit ===\n"))
        if not entries:
            self.stdout.write("No issues found. All content is complete.")
            self._print_product_stats(product_stats, product_stats_error)
            return

        # Group by entity_type
        by_type = defaultdict(list)
        for e in entries:
            by_type[e.entity_type].append(e)

        for entity_type, items in sorted(by_type.items()):
            self.stdout.write(self.style.WARNING(f"\n--- {entity_type} ({len(items)}) ---"))
            for e in items:
                self.stdout.write(f"\n{e.identifier} ({e.url})")
                if e.meta_title_status != "N/A":
                    self.stdout.write(f"  Meta Title: {e.meta_title_status}")
                self.stdout.write(f"  Intro: {e.intro_status} ({e.intro_len} chars)")
                self.stdout.write(f"  Body: {e.body_status} ({e.body_len} chars)")
                self.stdout.write(f"  FAQ: {e.faq_status} ({e.faq_count} items)")
                if e.admin_url:
                    self.stdout.write(f"  Admin: {e.admin_url}")
                if e.notes:
                    self.stdout.write(f"  Notes: {e.notes}")

        self._print_product_stats(product_stats, product_stats_error)

    def _print_product_stats(self, stats, error=None):
        self.stdout.write(self.style.SUCCESS("\n--- Product Stats ---"))
        if error:
            self.stdout.write(f"Product stats: N/A (reason: {error})")
            return
        if not stats:
            self.stdout.write("Product stats: N/A (no data)")
            return
        self.stdout.write(f"Total public products: {stats['total_public']}")
        self.stdout.write(f"With description: {stats['with_description']} ({stats['description_coverage']}%)")
        self.stdout.write(f"With photos: {stats['with_photos']} ({stats['photo_coverage']}%)")

    def _output_csv(self, entries):
        """Print CSV to stdout."""
        import csv

        writer = csv.writer(sys.stdout)
        writer.writerow(
            [
                "Entity Type",
                "Identifier",
                "URL",
                "Admin URL",
                "Meta Title",
                "Intro Status",
                "Intro Len",
                "Body Status",
                "Body Len",
                "FAQ Status",
                "FAQ Count",
                "Notes",
            ]
        )
        for e in entries:
            writer.writerow(
                [
                    e.entity_type,
                    e.identifier,
                    e.url,
                    e.admin_url,
                    e.meta_title_status,
                    e.intro_status,
                    e.intro_len,
                    e.body_status,
                    e.body_len,
                    e.faq_status,
                    e.faq_count,
                    e.notes,
                ]
            )

    def _output_json(self, entries, product_stats, product_stats_error=None):
        """Print JSON to stdout."""
        data = {
            "entries": [
                {
                    "entity_type": e.entity_type,
                    "identifier": e.identifier,
                    "url": e.url,
                    "admin_url": e.admin_url,
                    "meta_title_status": e.meta_title_status,
                    "intro_status": e.intro_status,
                    "intro_len": e.intro_len,
                    "body_status": e.body_status,
                    "body_len": e.body_len,
                    "faq_status": e.faq_status,
                    "faq_count": e.faq_count,
                    "notes": e.notes,
                }
                for e in entries
            ],
            "product_stats": product_stats if not product_stats_error else None,
            "product_stats_error": product_stats_error,
        }
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
