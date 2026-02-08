"""
Export SHACMAN semantics from DB: clusters (line/category/formula/engine), counts, and combo URLs.

Usage:
  python manage.py shacman_semantic_export
  python manage.py shacman_semantic_export --diagnose-url /shacman/line/x3000/samosvaly/

Output: _exports/shacman_semantics.csv, _exports/shacman_semantics.json
Prints TOP 20 combinations by count (category+line+formula, category+line, category+engine).
--diagnose-url: print resolve(), Client.get().status_code, resolver_match, and allowed combo keys.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.test import Client
from django.urls import resolve, Resolver404
from django.utils.text import slugify as django_slugify

from catalog.models import Category, Product


def _normalize_formula(value):
    if not value:
        return ""
    raw = str(value).strip().lower().replace("\u00d7", "x").replace("\u0445", "x").replace(" ", "")
    return "".join(c for c in raw if c in "0123456789x") or ""


def _engine_slug(engine_model):
    if not engine_model:
        return ""
    raw = (engine_model or "").strip().replace(".", "-")
    return django_slugify(raw) or ""


def _line_slug(product):
    line = (getattr(product.model_variant, "line", None) or "").strip() if product.model_variant else ""
    return django_slugify(line) if line else ""


class Command(BaseCommand):
    help = "Export SHACMAN semantics: clusters, counts, proposed combo URLs; CSV and JSON to _exports/."

    def _diagnose_url(self, path: str):
        path = (path or "").strip() or "/shacman/line/x3000/samosvaly/"
        if not path.startswith("/"):
            path = "/" + path
        self.stdout.write(f"Diagnosing path: {path!r}")
        try:
            match = resolve(path)
            self.stdout.write(f"  resolve(): {match.func.__name__!r} (url_name={getattr(match, 'url_name', None)!r})")
            self.stdout.write(f"  kwargs: {match.kwargs!r}")
            kwargs = getattr(match, "kwargs", {})
        except Resolver404 as e:
            self.stdout.write(self.style.ERROR(f"  resolve(): Resolver404 - {e}"))
            kwargs = {}
        client = Client()
        response = client.get(path)
        self.stdout.write(f"  Client.get(): status_code={response.status_code} (curl-equivalent: HTTP {response.status_code})")
        allowed = None
        try:
            from catalog.views import _shacman_combo_allowed_from_db
            allowed = _shacman_combo_allowed_from_db()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  _shacman_combo_allowed_from_db: {e}"))
        if allowed is not None:
            self.stdout.write(f"  len(lc)={len(allowed.lc)} len(lcf)={len(allowed.lcf)}")
            key_lc = ("x3000", "samosvaly")
            key_lcf = ("x3000", "samosvaly", "8x4")
            self.stdout.write(f"  ('x3000','samosvaly') in lc: {key_lc in allowed.lc}")
            self.stdout.write(f"  ('x3000','samosvaly','8x4') in lcf: {key_lcf in allowed.lcf}")
            line_slug = kwargs.get("line_slug")
            category_slug = kwargs.get("category_slug")
            formula = kwargs.get("formula")
            if line_slug and category_slug:
                from catalog.views import _shacman_normalize_formula
                key_from_path = (line_slug, category_slug)
                norm_formula = _shacman_normalize_formula(formula) if formula else None
                self.stdout.write(f"  From path kwargs: ({line_slug!r},{category_slug!r}) in lc: {key_from_path in allowed.lc}")
                if norm_formula:
                    key_formula = (line_slug, category_slug, norm_formula)
                    self.stdout.write(f"  From path kwargs: ({line_slug!r},{category_slug!r},{norm_formula!r}) in lcf: {key_formula in allowed.lcf}")
            if allowed.lc:
                sample = list(allowed.lc)[:5]
                self.stdout.write(f"  lc sample: {sample!r}")
            if allowed.lcf:
                sample = list(allowed.lcf)[:5]
                self.stdout.write(f"  lcf sample: {sample!r}")

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default="_exports",
            help="Directory for shacman_semantics.csv and .json (default: _exports)",
        )
        parser.add_argument(
            "--diagnose-url",
            default="",
            help="Path to diagnose: resolve(), Client.get().status_code, resolver_match, allowed combo keys (e.g. /shacman/line/x3000/samosvaly/)",
        )

    def handle(self, *args, **options):
        if options.get("diagnose_url"):
            self._diagnose_url(options["diagnose_url"])
            return
        out_dir = Path(options["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        base = (
            Product.objects.filter(series__slug__iexact="shacman", is_active=True)
            .exclude(series__isnull=True)
            .select_related("series", "category", "model_variant")
        )
        products = list(base)
        if not products:
            self.stdout.write(self.style.WARNING("No active SHACMAN products found."))
            return

        # Build row per product for aggregates
        rows = []
        for p in products:
            cat_slug = (p.category.slug or "").strip() if p.category else ""
            line_sl = _line_slug(p)
            formula = _normalize_formula(p.wheel_formula or "")
            eng_slug = _engine_slug(p.engine_model or "")
            model_code = (p.model_code or "").strip()
            series_slug = (p.series.slug or "").strip() if p.series else "shacman"
            rows.append({
                "product_id": p.id,
                "slug": p.slug or "",
                "category_slug": cat_slug,
                "line_slug": line_sl,
                "formula": formula,
                "engine_slug": eng_slug,
                "model_code": model_code,
                "series_slug": series_slug,
            })

        # Clusters: single dimension
        clusters = {
            "line_slug": defaultdict(lambda: {"active_count": 0, "product_slugs": []}),
            "category_slug": defaultdict(lambda: {"active_count": 0, "product_slugs": []}),
            "formula": defaultdict(lambda: {"active_count": 0, "product_slugs": []}),
            "engine_slug": defaultdict(lambda: {"active_count": 0, "product_slugs": []}),
        }
        for r in rows:
            for key in ("line_slug", "category_slug", "formula", "engine_slug"):
                v = r[key]
                if not v:
                    continue
                c = clusters[key][v]
                c["active_count"] += 1
                if len(c["product_slugs"]) < 5 and r["slug"]:
                    c["product_slugs"].append(r["slug"])

        # Existing hub URLs: line/engine/formula/category with >=2 products (same rules as views)
        allowed_line = {k for k, v in clusters["line_slug"].items() if v["active_count"] >= 2}
        allowed_engine = {k for k, v in clusters["engine_slug"].items() if v["active_count"] >= 2}
        allowed_formulas = {k for k, v in clusters["formula"].items() if v["active_count"] >= 2}
        categories_with_shacman = {k for k, v in clusters["category_slug"].items() if v["active_count"] >= 1}

        def existing_url(kind, **kwargs):
            if kind == "line" and kwargs.get("line_slug") in allowed_line:
                return f"/shacman/line/{kwargs['line_slug']}/"
            if kind == "engine" and kwargs.get("engine_slug") in allowed_engine:
                return f"/shacman/engine/{kwargs['engine_slug']}/"
            if kind == "formula" and kwargs.get("formula") in allowed_formulas:
                return f"/shacman/formula/{kwargs['formula']}/"
            if kind == "category" and kwargs.get("category_slug") in categories_with_shacman:
                return f"/shacman/{kwargs['category_slug']}/"
            return ""

        # Combo aggregates: (line_slug, category_slug), (line_slug, category_slug, formula), (category_slug, engine_slug)
        combo_line_cat = defaultdict(lambda: {"active_count": 0, "product_slugs": []})
        combo_line_cat_formula = defaultdict(lambda: {"active_count": 0, "product_slugs": []})
        combo_cat_engine = defaultdict(lambda: {"active_count": 0, "product_slugs": []})
        combo_line_engine = defaultdict(lambda: {"active_count": 0, "product_slugs": []})
        combo_cat_formula = defaultdict(lambda: {"active_count": 0, "product_slugs": []})
        for r in rows:
            line_sl, cat_slug, formula, eng_slug = r["line_slug"], r["category_slug"], r["formula"], r["engine_slug"]
            if line_sl and cat_slug:
                k = (line_sl, cat_slug)
                combo_line_cat[k]["active_count"] += 1
                if len(combo_line_cat[k]["product_slugs"]) < 5 and r["slug"]:
                    combo_line_cat[k]["product_slugs"].append(r["slug"])
            if line_sl and cat_slug and formula:
                k = (line_sl, cat_slug, formula)
                combo_line_cat_formula[k]["active_count"] += 1
                if len(combo_line_cat_formula[k]["product_slugs"]) < 5 and r["slug"]:
                    combo_line_cat_formula[k]["product_slugs"].append(r["slug"])
            if cat_slug and eng_slug:
                k = (cat_slug, eng_slug)
                combo_cat_engine[k]["active_count"] += 1
                if len(combo_cat_engine[k]["product_slugs"]) < 5 and r["slug"]:
                    combo_cat_engine[k]["product_slugs"].append(r["slug"])
            if line_sl and eng_slug:
                k = (line_sl, eng_slug)
                combo_line_engine[k]["active_count"] += 1
                if len(combo_line_engine[k]["product_slugs"]) < 5 and r["slug"]:
                    combo_line_engine[k]["product_slugs"].append(r["slug"])
            if cat_slug and formula:
                k = (cat_slug, formula)
                combo_cat_formula[k]["active_count"] += 1
                if len(combo_cat_formula[k]["product_slugs"]) < 5 and r["slug"]:
                    combo_cat_formula[k]["product_slugs"].append(r["slug"])

        # Build export structures with existing_url and proposed_combo_url
        export_clusters = []
        for dim, data in clusters.items():
            for key, val in data.items():
                if not key:
                    continue
                rec = {
                    "cluster_type": dim,
                    "key": key,
                    "active_count": val["active_count"],
                    "top_product_slugs": val["product_slugs"][:5],
                    "existing_url": "",
                    "proposed_combo_url": "",
                }
                if dim == "line_slug":
                    rec["existing_url"] = existing_url("line", line_slug=key)
                elif dim == "engine_slug":
                    rec["existing_url"] = existing_url("engine", engine_slug=key)
                elif dim == "formula":
                    rec["existing_url"] = existing_url("formula", formula=key)
                elif dim == "category_slug":
                    rec["existing_url"] = existing_url("category", category_slug=key)
                export_clusters.append(rec)

        # Top combinations for report and proposed_combo_url
        top_combos = []
        for (line_sl, cat_slug), val in combo_line_cat.items():
            if val["active_count"] >= 2:
                top_combos.append({
                    "combo_type": "category+line",
                    "keys": {"line_slug": line_sl, "category_slug": cat_slug},
                    "count": val["active_count"],
                    "existing_url": "",
                    "proposed_combo_url": f"/shacman/line/{line_sl}/{cat_slug}/",
                    "top_product_slugs": val["product_slugs"][:5],
                })
        for (line_sl, cat_slug, formula), val in combo_line_cat_formula.items():
            if val["active_count"] >= 2:
                top_combos.append({
                    "combo_type": "category+formula+line",
                    "keys": {"line_slug": line_sl, "category_slug": cat_slug, "formula": formula},
                    "count": val["active_count"],
                    "existing_url": "",
                    "proposed_combo_url": f"/shacman/line/{line_sl}/{cat_slug}/{formula}/",
                    "top_product_slugs": val["product_slugs"][:5],
                })
        for (cat_slug, eng_slug), val in combo_cat_engine.items():
            if val["active_count"] >= 2:
                top_combos.append({
                    "combo_type": "category+engine",
                    "keys": {"category_slug": cat_slug, "engine_slug": eng_slug},
                    "count": val["active_count"],
                    "existing_url": "",
                    "proposed_combo_url": f"/shacman/engine/{eng_slug}/{cat_slug}/",
                    "top_product_slugs": val["product_slugs"][:5],
                })
        for (line_sl, eng_slug), val in combo_line_engine.items():
            if val["active_count"] >= 2:
                top_combos.append({
                    "combo_type": "line+engine",
                    "keys": {"line_slug": line_sl, "engine_slug": eng_slug},
                    "count": val["active_count"],
                    "existing_url": "",
                    "proposed_combo_url": f"/shacman/line/{line_sl}/engine/{eng_slug}/",
                    "top_product_slugs": val["product_slugs"][:5],
                })
        for (cat_slug, formula), val in combo_cat_formula.items():
            if val["active_count"] >= 2:
                top_combos.append({
                    "combo_type": "category+formula",
                    "keys": {"category_slug": cat_slug, "formula": formula},
                    "count": val["active_count"],
                    "existing_url": "",
                    "proposed_combo_url": f"/shacman/{cat_slug}/{formula}/",
                    "top_product_slugs": val["product_slugs"][:5],
                })

        top_combos.sort(key=lambda x: -x["count"])
        top_20 = top_combos[:20]
        top_line_engine = [c for c in top_combos if c["combo_type"] == "line+engine"][:20]
        top_category_formula = [c for c in top_combos if c["combo_type"] == "category+formula"][:20]

        # CSV: clusters + top combos
        csv_path = out_dir / "shacman_semantics.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "cluster_type", "key", "active_count", "top_product_slugs", "existing_url", "proposed_combo_url"
            ])
            for rec in export_clusters:
                writer.writerow([
                    rec["cluster_type"],
                    rec["key"],
                    rec["active_count"],
                    "|".join(rec["top_product_slugs"]),
                    rec["existing_url"],
                    rec["proposed_combo_url"],
                ])
            writer.writerow([])
            writer.writerow(["combo_type", "keys", "count", "proposed_combo_url", "top_product_slugs"])
            for c in top_combos:
                writer.writerow([
                    c["combo_type"],
                    json.dumps(c["keys"], ensure_ascii=False),
                    c["count"],
                    c["proposed_combo_url"],
                    "|".join(c["top_product_slugs"][:5]),
                ])

        # JSON
        json_path = out_dir / "shacman_semantics.json"
        payload = {
            "clusters": export_clusters,
            "top_combos": top_combos,
            "top_20_by_count": [
                {
                    "combo_type": c["combo_type"],
                    "keys": c["keys"],
                    "count": c["count"],
                    "proposed_combo_url": c["proposed_combo_url"],
                }
                for c in top_20
            ],
            "top_line_engine": [
                {"keys": c["keys"], "count": c["count"], "proposed_combo_url": c["proposed_combo_url"]}
                for c in top_line_engine
            ],
            "top_category_formula": [
                {"keys": c["keys"], "count": c["count"], "proposed_combo_url": c["proposed_combo_url"]}
                for c in top_category_formula
            ],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(f"Wrote {csv_path} and {json_path}"))
        self.stdout.write("TOP 20 combinations by count:")
        for i, c in enumerate(top_20, 1):
            self.stdout.write(
                f"  {i}. {c['combo_type']} count={c['count']} {c.get('proposed_combo_url') or c['keys']}"
            )
        if top_line_engine:
            self.stdout.write("TOP line+engine (count>=2):")
            for i, c in enumerate(top_line_engine[:10], 1):
                self.stdout.write(f"  {i}. {c['keys']} count={c['count']} {c['proposed_combo_url']}")
        if top_category_formula:
            self.stdout.write("TOP category+formula (count>=2):")
            for i, c in enumerate(top_category_formula[:10], 1):
                self.stdout.write(f"  {i}. {c['keys']} count={c['count']} {c['proposed_combo_url']}")
