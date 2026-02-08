from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import City


@dataclass(frozen=True)
class CitySeed:
    name: str
    slug: str
    sort_order: int


SEED_CITIES: list[CitySeed] = [
    CitySeed(name="Москва", slug="moskva", sort_order=10),
    CitySeed(name="Саратов", slug="saratov", sort_order=20),
]


class Command(BaseCommand):
    help = "Seed cities (Москва, Саратов). Idempotent."

    def handle(self, *args, **options):
        totals: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0}

        with transaction.atomic():
            for seed in SEED_CITIES:
                status, note = self._ensure_city(seed)
                totals[status] += 1
                suffix = f" ({note})" if note else ""
                self.stdout.write(f"{seed.name}: {status}{suffix}")

        self.stdout.write(self.style.SUCCESS("seed_cities: OK"))
        self.stdout.write(
            "City: "
            f"created={totals['created']}, updated={totals['updated']}, skipped={totals['skipped']}"
        )

    def _ensure_city(self, seed: CitySeed) -> tuple[str, str]:
        desired_name = seed.name
        desired_slug = seed.slug
        desired_sort_order = seed.sort_order

        obj = City.objects.filter(slug__iexact=desired_slug).first()
        if obj is None:
            obj = City.objects.filter(name__iexact=desired_name).order_by("id").first()
            if obj is None:
                City.objects.create(
                    name=desired_name,
                    slug=desired_slug,
                    sort_order=desired_sort_order,
                    is_active=True,
                )
                return "created", ""

            return self._update_city_by_name_match(obj=obj, seed=seed)

        return self._update_city(obj=obj, seed=seed)

    def _update_city_by_name_match(self, *, obj: City, seed: CitySeed) -> tuple[str, str]:
        desired_slug = seed.slug

        note = ""
        update_fields: list[str] = []

        current_slug = obj.slug or ""
        if current_slug.lower() != desired_slug:
            slug_taken = City.objects.exclude(pk=obj.pk).filter(slug__iexact=desired_slug).exists()
            if not slug_taken:
                obj.slug = desired_slug
                update_fields.append("slug")
            else:
                note = f"slug '{desired_slug}' already taken; keeping '{obj.slug}'"

        return self._update_city(obj=obj, seed=seed, update_fields=update_fields, note=note)

    def _update_city(
        self,
        *,
        obj: City,
        seed: CitySeed,
        update_fields: list[str] | None = None,
        note: str = "",
    ) -> tuple[str, str]:
        desired_name = seed.name
        desired_slug = seed.slug
        desired_sort_order = seed.sort_order

        update_fields = list(update_fields or [])

        if (obj.slug or "").lower() == desired_slug and obj.slug != desired_slug:
            obj.slug = desired_slug
            update_fields.append("slug")
        if obj.name != desired_name:
            obj.name = desired_name
            update_fields.append("name")
        if obj.sort_order != desired_sort_order:
            obj.sort_order = desired_sort_order
            update_fields.append("sort_order")
        if obj.is_active is not True:
            obj.is_active = True
            update_fields.append("is_active")

        if update_fields:
            obj.save(update_fields=update_fields)
            return "updated", note

        return "skipped", note
