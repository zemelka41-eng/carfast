"""
Print actual engine_slugs and line_slugs from DB (mapping keys) for SHACMAN hubs.
Run on prod: python manage.py shacman_cluster_diagnostic
Use to verify wp13-550e501 and x3000 are in the mappings before testing curl.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from catalog.models import Product
from catalog.views import (
    _shacman_engine_allowed_from_db,
    _shacman_engine_slug,
    _shacman_line_allowed_from_db,
)


class Command(BaseCommand):
    help = "Print SHACMAN engine/line mapping keys from DB (for hub 200/404 and sitemap)."

    def handle(self, *args, **options):
        from django.conf import settings

        db_name = settings.DATABASES.get("default", {}).get("NAME", "")
        self.stdout.write("DB: %s" % db_name)

        shacman_active = Product.objects.filter(
            series__slug__iexact="shacman", is_active=True
        ).count()
        shacman_public = Product.objects.public().filter(
            series__slug__iexact="shacman"
        ).count()
        self.stdout.write("SHACMAN is_active=True: %s" % shacman_active)
        self.stdout.write("SHACMAN public(): %s" % shacman_public)

        self.stdout.write("\n--- Engine mapping (slug -> engine_model) ---")
        try:
            engine_map = _shacman_engine_allowed_from_db()
            keys = sorted(engine_map.keys())
            self.stdout.write("engine_slugs (%s): %s" % (len(keys), keys))
            for slug, label in engine_map.items():
                self.stdout.write("  %r -> %r" % (slug, label))
        except Exception as e:
            self.stdout.write(self.style.ERROR("engine mapping failed: %s" % e))
            import traceback
            traceback.print_exc()

        self.stdout.write("\n--- Line mapping (slug -> line_label) ---")
        try:
            line_map = _shacman_line_allowed_from_db()
            keys = sorted(line_map.keys())
            self.stdout.write("line_slugs (%s): %s" % (len(keys), keys))
            for slug, label in line_map.items():
                self.stdout.write("  %r -> %r" % (slug, label))
        except Exception as e:
            self.stdout.write(self.style.ERROR("line mapping failed: %s" % e))
            import traceback
            traceback.print_exc()

        self.stdout.write("\n--- Raw engine_model counts (is_active, SHACMAN) ---")
        try:
            rows = (
                Product.objects.filter(
                    series__slug__iexact="shacman", is_active=True
                )
                .exclude(engine_model__isnull=True)
                .exclude(engine_model="")
                .values("engine_model")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")
            )
            for row in rows:
                em = row.get("engine_model") or ""
                slug = _shacman_engine_slug(em)
                self.stdout.write("  engine_model=%r slug=%r cnt=%s" % (em, slug, row.get("cnt")))
        except Exception as e:
            self.stdout.write(self.style.ERROR("raw engine counts failed: %s" % e))

        self.stdout.write("\n--- Raw model_variant__line counts (is_active, SHACMAN) ---")
        try:
            rows = (
                Product.objects.filter(
                    series__slug__iexact="shacman", is_active=True
                )
                .exclude(model_variant__isnull=True)
                .values("model_variant__line")
                .annotate(cnt=Count("id"))
                .filter(model_variant__line__isnull=False)
                .exclude(model_variant__line="")
                .order_by("-cnt")
            )
            from django.utils.text import slugify
            for row in rows:
                line = (row.get("model_variant__line") or "").strip()
                slug = slugify(line) if line else ""
                self.stdout.write("  line=%r slug=%r cnt=%s" % (line, slug, row.get("cnt")))
        except Exception as e:
            self.stdout.write(self.style.ERROR("raw line counts failed: %s" % e))

        self.stdout.write("\nDone.")
