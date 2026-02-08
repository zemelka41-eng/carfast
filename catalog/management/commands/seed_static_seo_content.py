"""
Seed StaticPageSEO records for info pages: leasing, used, service, parts, payment-delivery.

Creates empty records if missing; fills empty seo_intro_html, seo_body_html, faq_items with placeholder text.
Does not overwrite existing content.

Usage:
  python manage.py seed_static_seo_content --dry-run   # show what would be done
  python manage.py seed_static_seo_content             # create/update
"""
from django.core.management.base import BaseCommand

from catalog.models import StaticPageSEO

STATIC_SLUGS = ("leasing", "used", "service", "parts", "payment-delivery")

INTRO_FISH = "<p>Краткий вводный блок над контентом страницы. Замените на актуальный текст.</p>"
BODY_FISH = "<p>Развёрнутый блок внизу страницы. Добавьте описание, преимущества, призыв к действию.</p>"
FAQ_FISH = "Какие сроки?|Сроки зависят от задачи и наличия.\nКакие варианты оплаты?|Работаем по безналу и в лизинг."


class Command(BaseCommand):
    help = "Seed StaticPageSEO for leasing, used, service, parts, payment-delivery with placeholder text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be created/updated, do not save.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write("DRY-RUN: no changes will be saved.")

        created_count = 0
        updated_count = 0

        for slug in STATIC_SLUGS:
            obj, created = StaticPageSEO.objects.get_or_create(
                slug=slug,
                defaults={
                    "meta_title": "",
                    "meta_description": "",
                    "seo_intro_html": "",
                    "seo_body_html": "",
                    "faq_items": "",
                },
            )
            if created:
                created_count += 1
                self.stdout.write("  Created StaticPageSEO: %s" % slug)
            if _fill_static_seo(obj, dry_run):
                updated_count += 1
                if not dry_run:
                    obj.save()
                self.stdout.write("  Updated StaticPageSEO: %s" % slug)

        self.stdout.write("Done. Created: %s, Updated: %s" % (created_count, updated_count))


def _fill_static_seo(obj: StaticPageSEO, dry_run: bool) -> bool:
    changed = False
    if not (obj.seo_intro_html or "").strip():
        obj.seo_intro_html = INTRO_FISH
        changed = True
    if not (obj.seo_body_html or "").strip():
        obj.seo_body_html = BODY_FISH
        changed = True
    if not (obj.faq_items or "").strip():
        obj.faq_items = FAQ_FISH
        changed = True
    return changed
