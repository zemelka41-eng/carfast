"""
Diagnostic: URL resolution for /shacman/ and urlpatterns order.
Run on server with: set -a; source /etc/carfst/carfst.env; set +a
  /home/carfst/app/cursor_work/.venv/bin/python manage.py url_resolve_diagnostic

To isolate 404 (gunicorn vs nginx):
  curl -sSI -H 'Host: carfst.ru' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8001/shacman/engine/wp13-550e501/
  curl -sSI -H 'Host: carfst.ru' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8001/shacman/line/x3000/
  If gunicorn=200 and nginx=404: nginx config (location/try_files). Check: nginx -T | grep -nE 'shacman/(engine|line)|location |try_files|error_page'
"""
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand
from django.http import Http404
from django.test import Client, RequestFactory
from django.urls import get_resolver, resolve, Resolver404, reverse


def _list_top_patterns(resolver, prefix="", max_items=50):
    """List top-level pattern routes (and names) from root URLResolver."""
    out = []
    patterns = getattr(resolver, "url_patterns", None) or []
    for i, p in enumerate(patterns):
        if i >= max_items:
            out.append("  ...")
            break
        try:
            if hasattr(p, "pattern"):
                route = getattr(p.pattern, "_route", str(p.pattern))
                name = getattr(p, "name", None) or ""
                out.append(f"  {prefix}{route!r}  name={name!r}")
            else:
                out.append(f"  {type(p).__name__}")
        except Exception as e:
            out.append(f"  <error: {e}>")
    return out


class Command(BaseCommand):
    help = "Diagnose URL resolution for /shacman/ and print urlpatterns order."

    def handle(self, *args, **options):
        self.stdout.write("=== URL resolve diagnostic ===\n")

        # 1) resolve paths (Django strips leading slash; try both for compatibility)
        for path in ["/shacman/", "shacman/", "ru/shacman/"]:
            try:
                r = resolve(path)
                self.stdout.write(
                    f"resolve({path!r}) -> {r.func.__name__}  url_name={getattr(r, 'url_name', None)!r}  kwargs={r.kwargs}"
                )
            except Resolver404:
                self.stdout.write(self.style.ERROR(f"resolve({path!r}) -> 404"))

        # 2) reverse
        try:
            url = reverse("shacman_hub")
            self.stdout.write(f"reverse('shacman_hub') -> {url!r}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"reverse('shacman_hub') -> {e}"))

        # 3) Order of root urlpatterns
        self.stdout.write("\n--- Root urlpatterns order (carfst_site.urls) ---")
        resolver = get_resolver()
        for line in _list_top_patterns(resolver, max_items=50):
            self.stdout.write(line)

        # 4) RequestFactory: call shacman_hub view and catch Http404 (use path that resolves)
        self.stdout.write("\n--- RequestFactory: GET /shacman/ -> view ---")
        try:
            for try_path in ["/shacman/", "shacman/"]:
                try:
                    r = resolve(try_path)
                    break
                except Resolver404:
                    continue
            else:
                self.stdout.write(self.style.ERROR("resolve('/shacman/') and resolve('shacman/') -> Resolver404 (view not reached)"))
                self.stdout.write("\nDone.")
                return
            view_func = r.func
            request = RequestFactory().get("/shacman/")
            request.resolver_match = r
            response = view_func(request)
            self.stdout.write(f"view {view_func.__name__} returned status_code={response.status_code}")
        except Http404 as e:
            self.stdout.write(self.style.ERROR(f"view raised Http404: {e}"))
            self.stdout.write("Traceback:")
            for line in traceback.format_exc().splitlines():
                self.stdout.write("  " + line)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"view raised {type(e).__name__}: {e}"))
            for line in traceback.format_exc().splitlines():
                self.stdout.write("  " + line)

        # 5) B3 hubs: formula/6x4/, engine/wp13-550e501/, line/x3000/ — resolve + RequestFactory
        b3_paths = [
            "/shacman/formula/6x4/",
            "/shacman/engine/wp13-550e501/",
            "/shacman/line/x3000/",
        ]
        self.stdout.write("\n--- B3 hub paths: resolve + view ---")
        for path in b3_paths:
            path_with_slash = path if path.startswith("/") else "/" + path
            self.stdout.write(f"\n  {path_with_slash}")
            try:
                r = resolve(path_with_slash)
                self.stdout.write(
                    f"    resolve({path_with_slash!r}) -> {r.func.__name__}  kwargs={r.kwargs}"
                )
                view_func = r.func
                request = RequestFactory().get(path_with_slash)
                request.resolver_match = r
                response = view_func(request, **r.kwargs)
                self.stdout.write(self.style.SUCCESS(f"    view returned status_code={response.status_code}"))
            except Resolver404:
                self.stdout.write(self.style.ERROR(f"    resolve({path_with_slash!r}) -> 404"))
            except Http404 as e:
                self.stdout.write(self.style.ERROR(f"    view raised Http404: {e}"))
                for line in traceback.format_exc().splitlines():
                    self.stdout.write("      " + line)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    view raised {type(e).__name__}: {e}"))
                for line in traceback.format_exc().splitlines():
                    self.stdout.write("      " + line)

        # 6) Cache backend (LocMem = per-process; workers don't share; fallback in views self-heals)
        cache_conf = getattr(settings, "CACHES", {})
        default_backend = cache_conf.get("default", {}).get("BACKEND", "")
        self.stdout.write("\n--- CACHES default BACKEND ---")
        self.stdout.write("  %s" % (default_backend or "(not set)"))

        # 7) Cluster format: type and len of engine_slugs / line_slugs (to spot old cache format on prod)
        self.stdout.write("\n--- Cluster format (engine_slugs / line_slugs) ---")
        try:
            from catalog.views import _shacman_allowed_clusters
            clusters = _shacman_allowed_clusters()
            es = clusters.get("engine_slugs")
            ls = clusters.get("line_slugs")
            self.stdout.write(
                f"  engine_slugs: type={type(es).__name__!r} len={len(es) if es is not None else 0}"
            )
            self.stdout.write(
                f"  line_slugs: type={type(ls).__name__!r} len={len(ls) if ls is not None else 0}"
            )
            if es is not None and len(es) > 0:
                sample = next(iter(es), None)
                self.stdout.write(f"  engine_slugs sample: {sample!r}")
            if ls is not None and len(ls) > 0:
                sample = next(iter(ls), None)
                self.stdout.write(f"  line_slugs sample: {sample!r}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  _shacman_allowed_clusters: {e}"))

        # 8) Client (real request simulation): middleware, same process as gunicorn worker
        client_paths = [
            "/shacman/engine/wp13-550e501/",
            "/shacman/line/x3000/",
        ]
        host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        self.stdout.write("\n--- Client (HTTP_HOST=%s, secure=True) ---" % host)
        try:
            client = Client()
            for path in client_paths:
                try:
                    resp = client.get(path, secure=True, HTTP_HOST=host)
                    if resp.status_code == 200:
                        self.stdout.write(self.style.SUCCESS(f"  {path} -> {resp.status_code}"))
                    else:
                        self.stdout.write(self.style.ERROR(f"  {path} -> {resp.status_code}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  {path} -> {type(e).__name__}: {e}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Client: {e}"))

        # 9) Isolate 404: gunicorn direct vs nginx
        self.stdout.write("\n--- Isolate 404: gunicorn direct vs nginx ---")
        self.stdout.write(
            "  curl -sSI -H 'Host: %s' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8001/shacman/engine/wp13-550e501/"
            % host
        )
        self.stdout.write(
            "  If gunicorn=200 and nginx=404: nginx -T | grep -nE 'shacman/(engine|line)|location |try_files'"
        )

        self.stdout.write("\nDone.")
