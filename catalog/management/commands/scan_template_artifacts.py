from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db.models import Q


@dataclass(frozen=True)
class _ModelScan:
    label: str
    model_path: tuple[str, str]  # (app_label, model_name)
    fields: tuple[str, ...]


SCANS: tuple[_ModelScan, ...] = (
    _ModelScan(
        label="Series",
        model_path=("catalog", "Series"),
        fields=("name", "description_ru", "description_en", "history", "logo_alt_ru"),
    ),
    _ModelScan(
        label="Category",
        model_path=("catalog", "Category"),
        fields=("name", "cover_alt_ru"),
    ),
    _ModelScan(
        label="ModelVariant",
        model_path=("catalog", "ModelVariant"),
        fields=("name", "line", "wheel_formula"),
    ),
    _ModelScan(
        label="Product",
        model_path=("catalog", "Product"),
        fields=(
            "model_name_ru",
            "model_name_en",
            "short_description_ru",
            "short_description_en",
            "description_ru",
            "description_en",
            "config",
            "model_code",
        ),
    ),
    _ModelScan(
        label="ProductImage",
        model_path=("catalog", "ProductImage"),
        fields=("alt_ru", "alt_en"),
    ),
    _ModelScan(
        label="SiteSettings",
        model_path=("catalog", "SiteSettings"),
        fields=(
            "email",
            "phone",
            "address",
            "work_hours",
            "map_embed",
            "telegram_chat_id",
            "whatsapp_number",
            "analytics_code",
        ),
    ),
)


NEEDLES: tuple[str, ...] = (
    "Inline SVG placeholder",
    "{# Inline SVG",
    "{#",
    "#}",
    "###",  # Markdown header artifacts (3+ hash symbols)
)


class Command(BaseCommand):
    help = "Scan DB for template artifacts like '{# ... #}', 'Inline SVG placeholder', and markdown headers (3+ hash symbols)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max rows to print per model (default: 50).",
        )

    def handle(self, *args, **options):
        limit: int = options["limit"]
        self.stdout.write("Scanning DB for template artifacts...")
        self.stdout.write("Needles: " + ", ".join(repr(x) for x in NEEDLES))

        from django.apps import apps

        total_hits = 0
        for scan in SCANS:
            Model = apps.get_model(*scan.model_path)
            q = Q()
            for field in scan.fields:
                for needle in NEEDLES:
                    q |= Q(**{f"{field}__icontains": needle})

            qs = Model.objects.filter(q)
            count = qs.count()
            total_hits += count
            self.stdout.write(f"- {scan.label}: {count} rows")
            if not count:
                continue

            for obj in qs.only("id")[:limit]:
                self.stdout.write(f"  - id={obj.pk}")

            if count > limit:
                self.stdout.write(f"  ... truncated, showing first {limit} rows")

        self.stdout.write(f"TOTAL rows matched (not deduped across models): {total_hits}")
