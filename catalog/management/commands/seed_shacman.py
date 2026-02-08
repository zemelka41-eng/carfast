from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from catalog.models import Category, City, ModelVariant, Series


SHACMAN_CATEGORIES: list[str] = [
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
]

SHACMAN_MODELS: list[str] = [
    "X6000 4x2",
    "X6000 6x4",
    "X5000 6x4",
    "X5000 6x6",
    "X5000 8x4",
    "X3000 8x4",
    "X3000 4x2",
    "X3000 6x4",
]

SEED_CITIES: list[str] = [
    "Москва",
    "Санкт-Петербург",
    "Екатеринбург",
]


_RU_TRANSLIT: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _transliterate_ru(text: str) -> str:
    out: list[str] = []
    for ch in str(text):
        lower = ch.lower()
        if lower in _RU_TRANSLIT:
            out.append(_RU_TRANSLIT[lower])
        else:
            out.append(ch)
    return "".join(out)


def _slugify_any(text: str) -> str:
    """Slugify for ASCII slugs, with RU transliteration fallback."""
    base = slugify(text)
    if base:
        return base
    return slugify(_transliterate_ru(text))


class Command(BaseCommand):
    help = "Seed SHACMAN (категории + модели + города). Idempotent."

    def handle(self, *args, **options):
        created_series = updated_series = skipped_series = 0
        created_categories = updated_categories = skipped_categories = 0
        created_models = updated_models = skipped_models = 0
        created_cities = updated_cities = skipped_cities = 0

        with transaction.atomic():
            brand = Series.objects.filter(slug__iexact="shacman").first()
            if brand is None:
                brand = Series.objects.create(slug="shacman", name="SHACMAN")
                created_series += 1
            else:
                brand_update_fields: list[str] = []
                if (brand.slug or "").lower() == "shacman" and brand.slug != "shacman":
                    brand.slug = "shacman"
                    brand_update_fields.append("slug")
                if brand.name != "SHACMAN":
                    brand.name = "SHACMAN"
                    brand_update_fields.append("name")
                if brand_update_fields:
                    brand.save(update_fields=brand_update_fields)
                    updated_series += 1
                else:
                    skipped_series += 1

            for name in SHACMAN_CATEGORIES:
                slug = _slugify_any(name)
                if not slug:
                    raise CommandError(f"Не удалось построить slug для категории: {name!r}")

                obj = Category.objects.filter(slug__iexact=slug).first()
                if obj is None:
                    Category.objects.create(slug=slug, name=name)
                    created_categories += 1
                    continue

                update_fields: list[str] = []
                if (obj.slug or "").lower() == slug and obj.slug != slug:
                    obj.slug = slug
                    update_fields.append("slug")
                if obj.name != name:
                    obj.name = name
                    update_fields.append("name")
                if update_fields:
                    obj.save(update_fields=update_fields)
                    updated_categories += 1
                else:
                    skipped_categories += 1

            for idx, raw in enumerate(SHACMAN_MODELS, start=1):
                name = (raw or "").strip()
                if not name:
                    continue
                if " " not in name:
                    raise CommandError(
                        f"Некорректная строка модели {raw!r}. Ожидается формат вида 'X6000 6x4'."
                    )

                line, wheel_formula = name.rsplit(" ", 1)
                slug = slugify(f"{line}-{wheel_formula}")
                if not slug:
                    raise CommandError(f"Не удалось построить slug для модели: {name!r}")
                sort_order = idx * 10

                obj = ModelVariant.objects.filter(slug__iexact=slug).first()
                if obj is None:
                    ModelVariant.objects.create(
                        brand=brand,
                        name=name,
                        slug=slug,
                        line=line,
                        wheel_formula=wheel_formula,
                        sort_order=sort_order,
                    )
                    created_models += 1
                    continue

                update_fields: list[str] = []
                if obj.brand_id != brand.id:
                    obj.brand = brand
                    update_fields.append("brand")
                if (obj.slug or "").lower() == slug and obj.slug != slug:
                    obj.slug = slug
                    update_fields.append("slug")
                if obj.name != name:
                    obj.name = name
                    update_fields.append("name")
                if obj.line != line:
                    obj.line = line
                    update_fields.append("line")
                if obj.wheel_formula != wheel_formula:
                    obj.wheel_formula = wheel_formula
                    update_fields.append("wheel_formula")
                if getattr(obj, "sort_order", None) != sort_order:
                    obj.sort_order = sort_order
                    update_fields.append("sort_order")
                if update_fields:
                    obj.save(update_fields=update_fields)
                    updated_models += 1
                else:
                    skipped_models += 1

            for idx, name in enumerate(SEED_CITIES, start=1):
                slug = _slugify_any(name)
                if not slug:
                    raise CommandError(f"Не удалось построить slug для города: {name!r}")
                sort_order = idx * 10

                obj = City.objects.filter(slug__iexact=slug).first()
                if obj is None:
                    City.objects.create(
                        slug=slug,
                        name=name,
                        sort_order=sort_order,
                        is_active=True,
                    )
                    created_cities += 1
                    continue

                update_fields: list[str] = []
                if (obj.slug or "").lower() == slug and obj.slug != slug:
                    obj.slug = slug
                    update_fields.append("slug")
                if obj.name != name:
                    obj.name = name
                    update_fields.append("name")
                if getattr(obj, "sort_order", None) != sort_order:
                    obj.sort_order = sort_order
                    update_fields.append("sort_order")
                if obj.is_active is not True:
                    obj.is_active = True
                    update_fields.append("is_active")
                if update_fields:
                    obj.save(update_fields=update_fields)
                    updated_cities += 1
                else:
                    skipped_cities += 1

        self.stdout.write(self.style.SUCCESS("seed_shacman: OK"))
        self.stdout.write(
            "Series: "
            f"created={created_series}, updated={updated_series}, skipped={skipped_series}"
        )
        self.stdout.write(
            "Categories: "
            f"created={created_categories}, updated={updated_categories}, skipped={skipped_categories}"
        )
        self.stdout.write(
            "ModelVariant: "
            f"created={created_models}, updated={updated_models}, skipped={skipped_models}"
        )
        self.stdout.write(
            "City: "
            f"created={created_cities}, updated={updated_cities}, skipped={skipped_cities}"
        )
