from __future__ import annotations

from django.core.management.base import BaseCommand

from catalog.models import Offer, Product, Series


class Command(BaseCommand):
    help = "Скрыть/удалить бренд SITRAK и связанные данные (для очистки БД)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что будет сделано, без изменений в БД",
        )
        parser.add_argument(
            "--delete-series",
            action="store_true",
            help="Удалить Series со slug 'sitrak' после архивации товаров",
        )

    def handle(self, *args, **options):
        series = Series.objects.filter(slug__iexact="sitrak").first()
        if series is None:
            self.stdout.write(self.style.WARNING("Series 'sitrak' не найден. Нечего удалять."))
            return

        products_qs = Product.objects.filter(series__slug__iexact="sitrak")
        offers_qs = Offer.objects.filter(product__series__slug__iexact="sitrak")

        products_count = products_qs.count()
        offers_count = offers_qs.count()

        self.stdout.write(f"Найден бренд: {series.name} (slug={series.slug})")
        self.stdout.write(f"Связанных товаров (Product): {products_count}")
        self.stdout.write(f"Связанных предложений/остатков (Offer): {offers_count}")

        if options.get("dry_run"):
            self.stdout.write(self.style.WARNING("DRY-RUN: изменения НЕ применены."))
            self.stdout.write("План действий:")
            self.stdout.write("- Product: published=False, is_active=False")
            self.stdout.write("- Offer: is_active=False")
            if options.get("delete_series"):
                self.stdout.write("- Series: delete")
            return

        updated_products = products_qs.update(published=False, is_active=False)
        updated_offers = offers_qs.update(is_active=False)

        self.stdout.write(self.style.SUCCESS(f"Обновлено товаров: {updated_products}"))
        self.stdout.write(self.style.SUCCESS(f"Деактивировано предложений: {updated_offers}"))

        if options.get("delete_series"):
            series.delete()
            self.stdout.write(self.style.SUCCESS("Series 'sitrak' удалён."))
