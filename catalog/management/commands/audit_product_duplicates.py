"""
Audit product duplicates: group by meta_title / h1 and suggest canonical for marking in admin.

Usage:
  python manage.py audit_product_duplicates
  python manage.py audit_product_duplicates --min-group 3  # only groups with at least 3 products
  python manage.py audit_product_duplicates --csv reports/duplicates.csv  # CSV with suggested actions
"""
import csv
from collections import defaultdict
from urllib.parse import urljoin

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Product
from catalog.seo_product import build_product_seo_title


def _normalize_title_for_grouping(title: str) -> str:
    """Normalize title for grouping (strip suffix, lowercase)."""
    if not title:
        return ""
    t = (title or "").strip()
    for suffix in (" | CARFAST", "| CARFAST"):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return t.lower()


def _score_canonical(product: Product) -> int:
    """Higher = better candidate for canonical (more complete card)."""
    score = 0
    if (product.description_ru or "").strip():
        score += 10
    if product.price is not None:
        score += 5
    images_count = product.images.count() if hasattr(product, "images") else 0
    score += min(images_count, 5)  # up to 5 points for images
    if (product.short_description_ru or "").strip():
        score += 2
    if (product.seo_title_override or "").strip():
        score += 1
    return score


class Command(BaseCommand):
    help = "Group products by meta_title/h1, output duplicate groups and recommended canonical."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-group",
            type=int,
            default=2,
            help="Minimum group size to output (default: 2).",
        )
        parser.add_argument(
            "--csv",
            default="",
            help="Write CSV to this path (columns: group_key, product_id, url, title, price, photos_count, description_len, recommended_canon, suggested_action).",
        )

    def handle(self, *args, **options):
        min_group = options["min_group"]
        csv_path = (options.get("csv") or "").strip()
        qs = (
            Product.objects.public()
            .select_related("series", "category", "model_variant")
            .prefetch_related("images")
            .order_by("slug")
        )
        products = list(qs)
        by_title: dict[str, list[Product]] = defaultdict(list)
        for p in products:
            title = build_product_seo_title(p)
            key = _normalize_title_for_grouping(title)
            if key:
                by_title[key].append(p)

        groups = [(key, prods) for key, prods in by_title.items() if len(prods) >= min_group]
        groups.sort(key=lambda x: -len(x[1]))

        base_url = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        if not base_url.startswith("http"):
            base_url = "https://" + base_url
        base_url = base_url.rstrip("/") + "/"

        if csv_path:
            self._write_csv(csv_path, groups, base_url)
            self.stdout.write("CSV записан: %s" % csv_path)
            return

        if not groups:
            self.stdout.write("Дублей не найдено (группы с >= %s товарами по meta_title)." % min_group)
            return

        self.stdout.write("Группы дублей (по meta_title), рекомендуемый канонический — самый «полный» карточка:\n")
        for key, prods in groups:
            self.stdout.write("---")
            def _key(p):
                is_alias = bool(p.canonical_product_id or (p.redirect_to_url or "").strip())
                return (is_alias, -_score_canonical(p))
            prods_sorted = sorted(prods, key=_key)
            recommended = prods_sorted[0]
            with_scores = [(p, _score_canonical(p)) for p in prods_sorted]
            self.stdout.write("Рекомендуемый канонический: %s (slug=%s, score=%s)" % (
                recommended.model_name_ru or recommended.sku,
                recommended.slug,
                _score_canonical(recommended),
            ))
            for p, sc in with_scores:
                alias_note = ""
                if p.canonical_product_id or (p.redirect_to_url or "").strip():
                    alias_note = " [уже алиас/редирект]"
                marker = " ← канонический" if p == recommended else " → задать canonical_product или redirect_to_url"
                self.stdout.write("  [%s] %s (slug=%s, score=%s)%s%s" % (
                    p.pk, p.model_name_ru or p.sku, p.slug, sc, alias_note, marker,
                ))
            self.stdout.write("")

    def _write_csv(self, path: str, groups: list, base_url: str) -> None:
        rows = []
        for group_key, prods in groups:
            def _key(p):
                is_alias = bool(p.canonical_product_id or (p.redirect_to_url or "").strip())
                return (is_alias, -_score_canonical(p))
            prods_sorted = sorted(prods, key=_key)
            recommended = prods_sorted[0]
            rec_slug = recommended.slug
            for p in prods_sorted:
                url = urljoin(base_url, p.get_absolute_url().lstrip("/"))
                title = (p.model_name_ru or p.sku or "")[:255]
                price = str(p.price) if p.price is not None else ""
                photos_count = p.images.count() if hasattr(p, "images") else 0
                description_len = len((p.description_ru or "").strip())
                recommended_canon = "1" if p.pk == recommended.pk else "0"
                if p.canonical_product_id or (p.redirect_to_url or "").strip():
                    suggested_action = "skip"
                elif p.pk == recommended.pk:
                    suggested_action = "canonical"
                else:
                    suggested_action = "redirect"
                rows.append({
                    "group_key": group_key[:200],
                    "product_id": p.pk,
                    "url": url,
                    "title": title,
                    "price": price,
                    "photos_count": photos_count,
                    "description_len": description_len,
                    "recommended_canon": recommended_canon,
                    "suggested_action": suggested_action,
                })
        fieldnames = ["group_key", "product_id", "url", "title", "price", "photos_count", "description_len", "recommended_canon", "suggested_action"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
