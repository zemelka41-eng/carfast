from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db.models import CharField, TextField, Q

from catalog.models import (
    Series,
    Category,
    ModelVariant,
    Product,
    ProductImage,
    SiteSettings,
    City,
    Offer,
    Lead,
)


@dataclass(frozen=True)
class _ModelScan:
    label: str
    model_class: type
    fields: tuple[str, ...]


SCANS: tuple[_ModelScan, ...] = (
    _ModelScan(
        label="Series",
        model_class=Series,
        fields=("name", "description_ru", "description_en", "history", "logo_alt_ru"),
    ),
    _ModelScan(
        label="Category",
        model_class=Category,
        fields=("name", "cover_alt_ru"),
    ),
    _ModelScan(
        label="ModelVariant",
        model_class=ModelVariant,
        fields=("name", "line", "wheel_formula"),
    ),
    _ModelScan(
        label="Product",
        model_class=Product,
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
        model_class=ProductImage,
        fields=("alt_ru", "alt_en"),
    ),
    _ModelScan(
        label="SiteSettings",
        model_class=SiteSettings,
        fields=(
            "email",
            "phone",
            "address",
            "work_hours",
            "map_embed",
            "telegram_chat_id",
            "whatsapp_number",
            "analytics_code",
            "legal_address",
            "office_address_1",
            "office_address_2",
        ),
    ),
    _ModelScan(
        label="City",
        model_class=City,
        fields=("name",),
    ),
    _ModelScan(
        label="Lead",
        model_class=Lead,
        fields=("name", "phone", "email", "message", "source"),
    ),
    _ModelScan(
        label="Offer",
        model_class=Offer,
        fields=("vat", "source_file", "source_row_hash", "batch_token"),
    ),
)


NEEDLES: tuple[str, ...] = (
    "###",  # Search for 3+ hash symbols (markdown header artifacts)
    "{#",
    "Inline SVG placeholder",
)

# Regex pattern for sequences of 3+ hashes
HASHES_PATTERN = re.compile(r'#{3,}')


class Command(BaseCommand):
    help = "Scan DB for artifacts like markdown headers (3+ hash symbols), '{#', 'Inline SVG placeholder' in CharField/TextField."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply safe cleanup (remove artifacts and save). Default is --dry-run.",
        )

    def handle(self, *args, **options):
        dry_run = not options.get("apply", False)

        self.stdout.write("Scanning DB for artifacts...")
        self.stdout.write("Needles: " + ", ".join(repr(x) for x in NEEDLES) + " + regex #{3,}")
        self.stdout.write(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")

        total_cleaned = 0

        for scan in SCANS:
            Model = scan.model_class
            # Build query to find fields containing any needle
            q = Q()
            for field in scan.fields:
                for needle in NEEDLES:
                    q |= Q(**{f"{field}__icontains": needle})
                # Also check for sequences of 3+ hashes (search for "###" as indicator)
                q |= Q(**{f"{field}__icontains": "###"})

            qs = Model.objects.filter(q).distinct()
            count = qs.count()
            if not count:
                self.stdout.write(f"- {scan.label}: 0 rows")
                continue

            self.stdout.write(f"- {scan.label}: {count} rows with artifacts")

            for obj in qs:
                cleaned_fields = []
                for field in scan.fields:
                    field_obj = Model._meta.get_field(field)
                    # Only process CharField and TextField
                    if not isinstance(field_obj, (CharField, TextField)):
                        continue

                    value = getattr(obj, field)
                    if not value:
                        continue

                    original_value = value
                    # Remove artifacts
                    cleaned_value = value
                    for needle in NEEDLES:
                        if needle == "###":
                            # Remove sequences of 3+ hash symbols (markdown header artifacts)
                            cleaned_value = HASHES_PATTERN.sub("", cleaned_value)
                        elif needle == "{#":
                            # Remove Django template comment markers
                            cleaned_value = re.sub(r'\{#.*?#\}', '', cleaned_value, flags=re.DOTALL)
                            cleaned_value = cleaned_value.replace("{#", "").replace("#}", "")
                        elif needle == "Inline SVG placeholder":
                            # Remove placeholder text
                            cleaned_value = re.sub(
                                r'Inline\s+SVG\s+placeholder(?:\s+for\s+cases\s+when\s+product\s+has\s+no\s+images)?',
                                '',
                                cleaned_value,
                                flags=re.IGNORECASE
                            )
                    
                    # Also remove sequences of 3+ hashes (additional check)
                    cleaned_value = HASHES_PATTERN.sub("", cleaned_value)
                    # Clean up extra whitespace
                    cleaned_value = re.sub(r'\s+', ' ', cleaned_value)
                    cleaned_value = cleaned_value.strip()
                    
                    if cleaned_value != original_value:
                        snippet = original_value[:80] + ("..." if len(original_value) > 80 else "")
                        cleaned_fields.append((field, original_value, cleaned_value, snippet))
                        if not dry_run:
                            setattr(obj, field, cleaned_value)

                if cleaned_fields:
                    self.stdout.write(f"  - {scan.label} pk={obj.pk}:")
                    for field, orig_value, cleaned_value, snippet in cleaned_fields:
                        self.stdout.write(f"    {field}: {repr(snippet)}")
                        self.stdout.write(f"      -> {repr(cleaned_value[:100])}")
                    if not dry_run:
                        try:
                            obj.save()
                            total_cleaned += 1
                        except Exception as e:
                            self.stderr.write(
                                self.style.ERROR(f"    ERROR saving {scan.label} pk={obj.pk}: {e}")
                            )

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY-RUN mode: no changes applied. Use --apply to clean artifacts."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nAPPLIED: cleaned {total_cleaned} objects."))
