from django.core.management.base import BaseCommand

from pathlib import Path

from django.core.files import File

from catalog.models import Category, Product, ProductImage, Series


class Command(BaseCommand):
    help = "Создаёт базовые серии и товары"

    def handle(self, *args, **options):
        series_list = [
            ("Серия A", "series-a"),
            ("Серия B", "series-b"),
            ("Серия C", "series-c"),
            ("Серия D", "series-d"),
            ("Серия E", "series-e"),
        ]
        categories = [("Грузовики", "trucks"), ("Спецтехника", "special")]
        for name, slug in series_list:
            Series.objects.get_or_create(name=name, slug=slug)
        for name, slug in categories:
            Category.objects.get_or_create(name=name, slug=slug)

        for idx in range(1, 11):
            series = Series.objects.order_by("?").first()
            category = Category.objects.order_by("?").first()
            product, _ = Product.objects.get_or_create(
                sku=f"SKU{idx:03}",
                slug=f"product-{idx}",
                defaults={
                    "series": series,
                    "category": category,
                    "model_name_ru": f"Модель {idx}",
                    "model_name_en": f"Model {idx}",
                    "short_description_ru": "Краткое описание",
                    "short_description_en": "Short description",
                    "description_ru": "Подробное описание товара",
                    "description_en": "Detailed description",
                    "price": 100000 + idx * 1000,
                    "power_hp": 300 + idx,
                    "payload_tons": 5 + idx / 10,
                },
            )
            seed_dir = Path("media/seed")
            sample = next(seed_dir.glob("*.jpg"), None) or next(seed_dir.glob("*.png"), None)
            if sample and not product.images.exists():
                ProductImage.objects.create(
                    product=product, order=0, image=File(open(sample, "rb")), alt_ru="Демо"
                )
        self.stdout.write(self.style.SUCCESS("Данные успешно созданы"))

