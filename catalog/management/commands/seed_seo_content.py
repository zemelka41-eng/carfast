"""
Seed empty SEO content records with template placeholders for quick editing.

Creates/updates empty Series, Category, SeriesCategorySEO, ShacmanHubSEO for:
- shacman: hub, in-stock, categories + in-stock, formula 4x2/6x4/8x4 (+ in-stock),
  engine wp12/wp13 (+ in-stock), line x3000/x6000/x5000/l3000 (+ in-stock)
- catalog: series shacman, categories (samosvaly, sedelnye-tyagachi, avtobetonosmesiteli), series+category

Fills empty intro/body/faq with short safe placeholder text. Does not touch meta invariants or schema.

Usage:
  python manage.py seed_seo_content --dry-run   # show what would be done
  python manage.py seed_seo_content             # create/update
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, Series, SeriesCategorySEO, ShacmanHubSEO

# Template "fish" — short safe placeholders (replace with real content in admin)
INTRO_FISH = "<p>Здесь краткий вводный текст над карточками. Замените на актуальный контент.</p>"
BODY_FISH = "<p>Развёрнутый блок под карточками. Добавьте описание, преимущества, призыв к действию.</p>"
FAQ_FISH = "Какие сроки поставки?|Сроки зависят от наличия и комплектации.\nКакие варианты оплаты?|Работаем по предоплате и в лизинг."


class Command(BaseCommand):
    help = "Seed empty SEO content records with placeholder text for key catalog/shacman pages."

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

        # 1) ShacmanHubSEO: main, in_stock (no category, no facet_key)
        for hub_type in (ShacmanHubSEO.HubType.MAIN, ShacmanHubSEO.HubType.IN_STOCK):
            obj, created = ShacmanHubSEO.objects.get_or_create(
                hub_type=hub_type,
                category=None,
                defaults={"meta_title": "", "meta_description": ""},
            )
            if created:
                created_count += 1
                self.stdout.write("  Created ShacmanHubSEO: %s" % hub_type)
            if _fill_shacman_hub_seo(obj, dry_run):
                updated_count += 1
                if not dry_run:
                    obj.save()
                self.stdout.write("  Updated ShacmanHubSEO: %s" % hub_type)

        # 2) ShacmanHubSEO: categories (need Category by slug)
        category_slugs = ["samosvaly", "sedelnye-tyagachi", "avtobetonosmesiteli"]
        for slug in category_slugs:
            cat = Category.objects.filter(slug=slug).first()
            if not cat:
                if not dry_run:
                    cat = Category.objects.create(name=slug.replace("-", " ").title(), slug=slug)
                    created_count += 1
                    self.stdout.write("  Created Category: %s" % slug)
                else:
                    self.stdout.write("  [dry-run] Would create Category: %s" % slug)
                    continue
            for hub_type in (ShacmanHubSEO.HubType.CATEGORY, ShacmanHubSEO.HubType.CATEGORY_IN_STOCK):
                obj, created = ShacmanHubSEO.objects.get_or_create(
                    hub_type=hub_type,
                    category=cat,
                    defaults={"meta_title": "", "meta_description": ""},
                )
                if created:
                    created_count += 1
                    self.stdout.write("  Created ShacmanHubSEO: %s category=%s" % (hub_type, slug))
                if _fill_shacman_hub_seo(obj, dry_run):
                    updated_count += 1
                    if not dry_run:
                        obj.save()
                    self.stdout.write("  Updated ShacmanHubSEO: %s category=%s" % (hub_type, slug))

        # 3) ShacmanHubSEO: formula 4x2, 6x4, 8x4 + in_stock
        for formula in ("4x2", "6x4", "8x4"):
            for hub_type in (ShacmanHubSEO.HubType.FORMULA, ShacmanHubSEO.HubType.FORMULA_IN_STOCK):
                obj, created = ShacmanHubSEO.objects.get_or_create(
                    hub_type=hub_type,
                    facet_key=formula,
                    defaults={"meta_title": "", "meta_description": ""},
                )
                if created:
                    created_count += 1
                    self.stdout.write("  Created ShacmanHubSEO: %s facet=%s" % (hub_type, formula))
                if _fill_shacman_hub_seo(obj, dry_run):
                    updated_count += 1
                    if not dry_run:
                        obj.save()
                    self.stdout.write("  Updated ShacmanHubSEO: %s facet=%s" % (hub_type, formula))

        # 4) ShacmanHubSEO: engine wp12, wp13 + in_stock
        for engine in ("wp12", "wp13"):
            for hub_type in (ShacmanHubSEO.HubType.ENGINE, ShacmanHubSEO.HubType.ENGINE_IN_STOCK):
                obj, created = ShacmanHubSEO.objects.get_or_create(
                    hub_type=hub_type,
                    facet_key=engine,
                    defaults={"meta_title": "", "meta_description": ""},
                )
                if created:
                    created_count += 1
                    self.stdout.write("  Created ShacmanHubSEO: %s facet=%s" % (hub_type, engine))
                if _fill_shacman_hub_seo(obj, dry_run):
                    updated_count += 1
                    if not dry_run:
                        obj.save()
                    self.stdout.write("  Updated ShacmanHubSEO: %s facet=%s" % (hub_type, engine))

        # 5) ShacmanHubSEO: line x3000, x6000, x5000, l3000 + in_stock
        for line in ("x3000", "x6000", "x5000", "l3000"):
            for hub_type in (ShacmanHubSEO.HubType.LINE, ShacmanHubSEO.HubType.LINE_IN_STOCK):
                obj, created = ShacmanHubSEO.objects.get_or_create(
                    hub_type=hub_type,
                    facet_key=line,
                    defaults={"meta_title": "", "meta_description": ""},
                )
                if created:
                    created_count += 1
                    self.stdout.write("  Created ShacmanHubSEO: %s facet=%s" % (hub_type, line))
                if _fill_shacman_hub_seo(obj, dry_run):
                    updated_count += 1
                    if not dry_run:
                        obj.save()
                    self.stdout.write("  Updated ShacmanHubSEO: %s facet=%s" % (hub_type, line))

        # 6) Series shacman (catalog)
        series = Series.objects.filter(slug__iexact="shacman").first()
        if not series and not dry_run:
            series = Series.objects.create(name="SHACMAN", slug="shacman", description_ru="", description_en="", history="")
            created_count += 1
            self.stdout.write("  Created Series: shacman")
        elif not series and dry_run:
            self.stdout.write("  [dry-run] Would create Series: shacman")
        if series and _fill_series_seo(series, dry_run):
            updated_count += 1
            if not dry_run:
                series.save()
            self.stdout.write("  Updated Series: shacman")

        # 7) SeriesCategorySEO: shacman + each category
        if series:
            for slug in category_slugs:
                cat = Category.objects.filter(slug=slug).first()
                if not cat:
                    continue
                obj, created = SeriesCategorySEO.objects.get_or_create(
                    series=series,
                    category=cat,
                    defaults={},
                )
                if created:
                    created_count += 1
                    self.stdout.write("  Created SeriesCategorySEO: shacman + %s" % slug)
                if _fill_series_category_seo(obj, dry_run):
                    updated_count += 1
                    if not dry_run:
                        obj.save()
                    self.stdout.write("  Updated SeriesCategorySEO: shacman + %s" % slug)

        self.stdout.write("Done. Created: %s, Updated: %s" % (created_count, updated_count))


def _fill_shacman_hub_seo(obj: ShacmanHubSEO, dry_run: bool) -> bool:
    changed = False
    if not (getattr(obj, "seo_intro_html", None) or "").strip():
        obj.seo_intro_html = INTRO_FISH
        changed = True
    if not (getattr(obj, "seo_body_html", None) or "").strip():
        obj.seo_body_html = BODY_FISH
        changed = True
    if not (getattr(obj, "faq", None) or "").strip():
        obj.faq = FAQ_FISH
        changed = True
    return changed


def _fill_series_seo(obj: Series, dry_run: bool) -> bool:
    changed = False
    if not (getattr(obj, "seo_intro_html", None) or "").strip():
        obj.seo_intro_html = INTRO_FISH
        changed = True
    if not (getattr(obj, "seo_body_html", None) or "").strip():
        obj.seo_body_html = BODY_FISH
        changed = True
    if not (getattr(obj, "seo_faq", None) or "").strip():
        obj.seo_faq = FAQ_FISH
        changed = True
    return changed


def _fill_series_category_seo(obj: SeriesCategorySEO, dry_run: bool) -> bool:
    changed = False
    if not (getattr(obj, "seo_intro_html", None) or "").strip():
        obj.seo_intro_html = INTRO_FISH
        changed = True
    if not (getattr(obj, "seo_body_html", None) or "").strip():
        obj.seo_body_html = BODY_FISH
        changed = True
    if not (getattr(obj, "seo_faq", None) or "").strip():
        obj.seo_faq = FAQ_FISH
        changed = True
    return changed
