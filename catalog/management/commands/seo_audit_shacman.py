"""
SEO audit: SHACMAN in-stock inventory and duplicate/cannibalization report.

Usage:
  python manage.py seo_audit_shacman
  python manage.py seo_audit_shacman --csv reports/shacman_inventory_YYYYMMDD.csv
  python manage.py seo_audit_shacman --no-duplicates  # skip duplicate groups section
"""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Max, Min

from catalog.models import Offer, Product

# B1 Semantic matrix: intents and entities for SEO coverage (SHACMAN)
SEO_INTENTS = (
    "купить", "цена", "в наличии", "под заказ", "лизинг", "доставка",
    "гарантия", "сервис", "КП", "коммерческое предложение",
)
SEO_ENTITIES_BRAND = ("SHACMAN", "Шакман")
SEO_ENTITIES_TYPE = ("самосвал", "тягач", "седельный тягач", "автобетоносмеситель")
SEO_ENTITIES_MODEL_VARIANT = ("X3000", "X6000", "L3000", "X5000")
SEO_ENTITIES_WHEEL = ("4x2", "6x4", "8x4", "4×2", "6×4", "8×4")
SEO_ENTITIES_ENGINE_PREFIX = ("WP13", "WP12", "Cummins", "WP")
SEO_ENTITIES_MODEL_CODE_PREFIX = ("SX",)


def _normalize_wheel_formula(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value).strip().lower().replace("×", "x").replace("х", "x").replace(" ", "")
    return "".join(c for c in raw if c in "0123456789x")


def _shacman_queryset(in_stock_only=False):
    """Products: SHACMAN, public; optionally filter total_qty > 0."""
    qs = (
        Product.objects.public()
        .filter(series__slug__iexact="shacman")
        .with_stock_stats()
        .select_related("series", "category", "model_variant")
        .order_by("category__name", "model_variant__name", "slug")
    )
    if in_stock_only:
        qs = qs.filter(total_qty__gt=0)
    return qs


def _offer_year_agg(product_id_list):
    """Return dict product_id -> (min_year, max_year) from active offers."""
    from django.db.models import IntegerField, Value

    agg = (
        Offer.objects.filter(product_id__in=product_id_list, is_active=True)
        .values("product_id")
        .annotate(
            min_year=Min("year"),
            max_year=Max("year"),
        )
    )
    return {r["product_id"]: (r["min_year"], r["max_year"]) for r in agg}


class Command(BaseCommand):
    help = "SHACMAN in-stock inventory and duplicate/cannibalization report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default="",
            help="Write inventory rows to this CSV path (e.g. reports/shacman_inventory_YYYYMMDD.csv).",
        )
        parser.add_argument(
            "--no-duplicates",
            action="store_true",
            help="Skip duplicate groups section.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include all SHACMAN products (not only in-stock) for inventory.",
        )

    def handle(self, *args, **options):
        today = date.today().isoformat().replace("-", "")
        in_stock_only = not options.get("all", False)
        products = list(_shacman_queryset(in_stock_only=in_stock_only))
        product_ids = [p.id for p in products]
        year_map = _offer_year_agg(product_ids) if product_ids else {}

        base_path = "/product/"
        rows = []
        for p in products:
            min_year, max_year = year_map.get(p.id, (None, None))
            year_str = ""
            if min_year is not None and max_year is not None:
                year_str = str(max_year) if min_year == max_year else f"{min_year}-{max_year}"
            elif max_year is not None:
                year_str = str(max_year)
            elif min_year is not None:
                year_str = str(min_year)

            cat_slug = getattr(p.category, "slug", "") or ""
            cat_name = getattr(p.category, "name", "") or ""
            model_var = getattr(p.model_variant, "name", "") or ""
            line = (getattr(p.model_variant, "line", None) or "").strip() or ""
            wf = _normalize_wheel_formula(p.wheel_formula or "")
            engine = (p.engine_model or "").strip()
            dup_key = (cat_slug, (p.model_code or "").strip(), wf, engine, year_str)
            in_stock = bool(getattr(p, "total_qty", 0) or 0)

            row = {
                "url": base_path + (p.slug or "") + "/",
                "slug": p.slug or "",
                "category": cat_name or cat_slug,
                "category_slug": cat_slug,
                "series_model": model_var,
                "line": line,
                "wheel_formula": wf,
                "engine": engine,
                "model_code": (p.model_code or "").strip(),
                "year": year_str,
                "in_stock": in_stock,
                "availability": p.availability or ("in_stock" if in_stock else "out_of_stock"),
                "price": str(p.display_price) if p.display_price is not None else "",
                "product_id": p.id,
                "is_active": p.is_active,
            }
            rows.append(row)

        # Mark duplicate_group for CSV (group id when category+model_code+wheel+engine+year has >1)
        key_to_rows = defaultdict(list)
        for r in rows:
            k = (r["category_slug"], r["model_code"], r["wheel_formula"], r["engine"], r["year"])
            key_to_rows[k].append(r)
        group_id = 0
        for k, group in key_to_rows.items():
            if len(group) > 1:
                group_id += 1
                for r in group:
                    r["duplicate_group"] = str(group_id)
            else:
                for r in group:
                    r["duplicate_group"] = ""

        # Summary
        self.stdout.write("")
        self.stdout.write("## SHACMAN inventory")
        self.stdout.write("")
        self.stdout.write(f"**Total SHACMAN:** {len(products)}" + (" (in-stock only)" if in_stock_only else " (all public)"))
        if rows:
            in_stock_count = sum(1 for r in rows if r.get("in_stock"))
            self.stdout.write(f"**In stock:** {in_stock_count}")
        self.stdout.write("")

        # By category
        by_cat = defaultdict(int)
        for r in rows:
            by_cat[r.get("category") or "(no category)"] += 1
        self.stdout.write("**By category:**")
        for name, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  - {name}: {count}")
        self.stdout.write("")

        # By model_variant (series_model)
        by_var = defaultdict(int)
        for r in rows:
            by_var[r["series_model"] or "(no variant)"] += 1
        self.stdout.write("**By model_variant (series_model):**")
        for name, count in sorted(by_var.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  - {name}: {count}")
        self.stdout.write("")

        # By line (model_variant.line: X3000, X6000, etc.)
        by_line = defaultdict(int)
        for r in rows:
            by_line[r.get("line") or "(no line)"] += 1
        self.stdout.write("**By line (model_variant.line):**")
        for name, count in sorted(by_line.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  - {name}: {count}")
        self.stdout.write("")

        # By wheel_formula (4x2, 6x4, 8x4)
        by_wf = defaultdict(int)
        for r in rows:
            by_wf[r.get("wheel_formula") or "(no formula)"] += 1
        self.stdout.write("**By wheel formula:**")
        for name, count in sorted(by_wf.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  - {name}: {count}")
        self.stdout.write("")

        # By engine
        by_engine = defaultdict(int)
        for r in rows:
            by_engine[r.get("engine") or "(no engine)"] += 1
        self.stdout.write("**By engine:**")
        for name, count in sorted(by_engine.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  - {name}: {count}")
        self.stdout.write("")

        # Top combinations: category × model_variant × wheel_formula × engine
        combo = defaultdict(list)
        for r in rows:
            key = (r["category_slug"], r["series_model"], r["wheel_formula"], r["engine"] or "-")
            combo[key].append(r["url"])
        top_combos = sorted(combo.items(), key=lambda x: -len(x[1]))[:15]
        self.stdout.write("**Top combinations (category | model_variant | wheel_formula | engine):**")
        for (cat, var, wf, eng), urls in top_combos:
            self.stdout.write(f"  - {cat} | {var} | {wf} | {eng}: {len(urls)} — {urls[0]}")
        self.stdout.write("")

        # CSV
        csv_path = (options.get("csv") or "").strip()
        if not csv_path and rows:
            csv_path = f"reports/shacman_inventory_{today}.csv"
        if csv_path:
            path = Path(csv_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = [
                "url", "slug", "category", "category_slug", "series_model", "line",
                "wheel_formula", "engine", "model_code", "year", "in_stock", "availability", "price",
                "duplicate_group", "product_id", "is_active",
            ]
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            self.stdout.write(self.style.SUCCESS(f"CSV written: {path}"))
            self.stdout.write("")

        # B1 Semantic matrix (summary)
        self.stdout.write("## Semantic matrix (SEO coverage)")
        self.stdout.write("")
        self.stdout.write("**Intents:** " + ", ".join(SEO_INTENTS))
        self.stdout.write("**Brand:** " + ", ".join(SEO_ENTITIES_BRAND))
        self.stdout.write("**Type:** " + ", ".join(SEO_ENTITIES_TYPE))
        self.stdout.write("**Model variant:** " + ", ".join(SEO_ENTITIES_MODEL_VARIANT))
        self.stdout.write("**Wheel formula:** " + ", ".join(s.replace("\u00d7", "x") for s in SEO_ENTITIES_WHEEL))
        self.stdout.write("**Engine prefix:** " + ", ".join(SEO_ENTITIES_ENGINE_PREFIX))
        self.stdout.write("**Model code prefix:** " + ", ".join(SEO_ENTITIES_MODEL_CODE_PREFIX))
        self.stdout.write("")

        # A2 Duplicate / cannibalization report
        if not options.get("no_duplicates"):
            self._report_duplicates(rows)

        return

    def _report_duplicates(self, rows):
        """Group by category + model_code + wheel_formula + engine + year; report groups with >1."""
        key_to_rows = defaultdict(list)
        for r in rows:
            key = (
                r["category_slug"],
                r["model_code"] or "-",
                r["wheel_formula"] or "-",
                r["engine"] or "-",
                r["year"] or "-",
            )
            key_to_rows[key].append(r)

        dup_groups = [(k, key_to_rows[k]) for k in key_to_rows if len(key_to_rows[k]) > 1]
        if not dup_groups:
            self.stdout.write("## Duplicate / cannibalization")
            self.stdout.write("")
            self.stdout.write("No groups with more than one card (same category + model_code + wheel_formula + engine + year).")
            self.stdout.write("")
            return

        self.stdout.write("## Duplicate / cannibalization (potential)")
        self.stdout.write("")
        self.stdout.write("Groups where **category + model_code + wheel_formula + engine + year** match and count > 1:")
        self.stdout.write("")
        for (cat, code, wf, eng, yr), group_rows in sorted(dup_groups, key=lambda x: -len(x[1])):
            self.stdout.write(f"- **{cat} | {code} | {wf} | {eng} | {yr}** — {len(group_rows)} URLs:")
            for r in group_rows:
                self.stdout.write(f"  - {r['url']} (slug={r['slug']}, price={r['price']})")
            self.stdout.write("")
        return
