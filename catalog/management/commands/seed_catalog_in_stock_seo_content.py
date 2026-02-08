"""
Seed CatalogLandingSEO record for /catalog/in-stock/.

Creates the record if missing. Does NOT auto-fill with placeholder text (dry-run shows template).

Usage:
  python manage.py seed_catalog_in_stock_seo_content --dry-run   # show what would be done + template
  python manage.py seed_catalog_in_stock_seo_content             # create record if missing
"""
from django.core.management.base import BaseCommand

from catalog.models import CatalogLandingSEO

TEMPLATE_INTRO = """\
<p>Техника в наличии на складе CARFAST — готова к отгрузке и осмотру.</p>
<p>Все позиции подтверждены: комплектация и сроки фиксируются в КП.</p>
"""

TEMPLATE_BODY = """\
<h2>Почему выбирают технику в наличии</h2>
<p>Минимум ожидания: техника на складе, можно осмотреть и забрать в короткие сроки.</p>
<p>Прозрачные условия: цена, комплектация и документы фиксируются в КП.</p>
<h2>Что дальше</h2>
<p>Запросите коммерческое предложение — подготовим расчёт с учётом региона и способа оплаты.</p>
"""

TEMPLATE_FAQ = """\
Какие сроки отгрузки техники в наличии?|Техника на складе готова к отгрузке: сроки зависят от региона доставки.
Можно ли осмотреть технику перед покупкой?|Да, организуем осмотр по договорённости.
Какие варианты оплаты?|Работаем по предоплате и в лизинг — уточняем в КП.
Как оформить заказ?|Оставьте заявку — перезвоним и подготовим КП.
"""


class Command(BaseCommand):
    help = "Create CatalogLandingSEO record for /catalog/in-stock/ if missing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be done, do not save. Shows template for SEO content.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        landing_key = CatalogLandingSEO.LandingKey.CATALOG_IN_STOCK
        existing = CatalogLandingSEO.objects.filter(landing_key=landing_key).first()

        if existing:
            self.stdout.write("CatalogLandingSEO for '%s' already exists (id=%s)." % (landing_key, existing.pk))
            if dry_run:
                self._print_template()
            return

        if dry_run:
            self.stdout.write("DRY-RUN: Would create CatalogLandingSEO for '%s'." % landing_key)
            self._print_template()
            return

        obj = CatalogLandingSEO.objects.create(
            landing_key=landing_key,
            meta_title="",
            meta_description="",
            seo_intro_html="",
            seo_body_html="",
            faq_items="",
        )
        self.stdout.write(self.style.SUCCESS("Created CatalogLandingSEO for '%s' (id=%s)." % (landing_key, obj.pk)))
        self.stdout.write("Fill in the SEO fields in the admin panel.")

    def _print_template(self):
        self.stdout.write("\n--- Template for SEO content (copy to admin) ---")
        self.stdout.write("\nseo_intro_html:")
        self.stdout.write(TEMPLATE_INTRO)
        self.stdout.write("\nseo_body_html:")
        self.stdout.write(TEMPLATE_BODY)
        self.stdout.write("\nfaq_items (вопрос|ответ по строкам):")
        self.stdout.write(TEMPLATE_FAQ)
        self.stdout.write("--- End of template ---\n")
