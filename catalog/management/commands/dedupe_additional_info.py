"""
Idempotent deduplication of "Дополнительная информация" in seo_body_html across models.

Usage:
  python manage.py dedupe_additional_info --dry-run
  python manage.py dedupe_additional_info --apply --backup-dir=./backups
"""
import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import (
    CatalogLandingSEO,
    Category,
    Series,
    SeriesCategorySEO,
    ShacmanHubSEO,
    StaticPageSEO,
)
from catalog.seo_html import deduplicate_additional_info_heading


# (model, queryset_callable, id_field_name)
def _get_models_with_seo_body():
    return [
        (Series, lambda: Series.objects.public(), "slug"),
        (Category, lambda: Category.objects.all(), "slug"),
        (SeriesCategorySEO, lambda: SeriesCategorySEO.objects.select_related("series", "category").all(), None),
        (ShacmanHubSEO, lambda: ShacmanHubSEO.objects.all(), None),
        (StaticPageSEO, lambda: StaticPageSEO.objects.all(), "slug"),
        (CatalogLandingSEO, lambda: CatalogLandingSEO.objects.all(), "landing_key"),
    ]


def _obj_identifier(obj, id_field):
    if id_field and hasattr(obj, id_field):
        return str(getattr(obj, id_field))
    if id_field is None and hasattr(obj, "pk"):
        if hasattr(obj, "series") and hasattr(obj, "category"):
            return f"{obj.series.slug}/{obj.category.slug}"
        if hasattr(obj, "hub_type") and hasattr(obj, "facet_key"):
            return f"{obj.get_hub_type_display()}({getattr(obj, 'facet_key', '') or ''})"
    return f"pk={obj.pk}"


class Command(BaseCommand):
    help = "Deduplicate 'Дополнительная информация' in seo_body_html (idempotent; use --apply to write)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be changed",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply fixes and optionally save backups",
        )
        parser.add_argument(
            "--backup-dir",
            type=str,
            default="",
            help="Directory for backup files when --apply (e.g. ./backups)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apply = options["apply"]
        backup_dir = (options["backup_dir"] or "").strip()

        if not dry_run and not apply:
            self.stdout.write("Specify --dry-run or --apply.")
            return

        if apply and backup_dir:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)

        total_fixed = 0
        for model, qs_callable, id_field in _get_models_with_seo_body():
            label = model.__name__
            qs = qs_callable()
            for obj in qs:
                raw = (getattr(obj, "seo_body_html", None) or "").strip()
                if not raw:
                    continue
                deduped = deduplicate_additional_info_heading(raw)
                if deduped == raw:
                    continue
                ident = _obj_identifier(obj, id_field)
                total_fixed += 1
                if dry_run:
                    self.stdout.write(f"[dry-run] {label} {ident}: would fix duplicate heading")
                    continue
                # --apply: backup then update
                if backup_dir:
                    safe_ident = ident.replace("/", "_").replace("\\", "_")[:100]
                    backup_path = os.path.join(backup_dir, f"{label}_{safe_ident}_{obj.pk}.html")
                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write(raw)
                    self.stdout.write(f"Backup: {backup_path}")
                with transaction.atomic():
                    obj.seo_body_html = deduped
                    obj.save(update_fields=["seo_body_html"])
                self.stdout.write(f"Fixed: {label} {ident}")

        if dry_run:
            self.stdout.write(f"Would fix {total_fixed} record(s). Run with --apply to apply.")
        else:
            self.stdout.write(f"Fixed {total_fixed} record(s).")
