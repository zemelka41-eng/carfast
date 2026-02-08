"""
WSGI-level probe for SHACMAN hub URLs. Uses django.test.Client with env close to nginx→gunicorn.
Run: python manage.py shacman_http_probe
Prints: resolve() result, status_code, Location, and top-level urlpatterns (to verify engine/line routes).
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import get_resolver, resolve, Resolver404


def _list_url_routes(resolver, prefix="", max_items=30):
    """List route strings and names from URLResolver (top-level)."""
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
                out.append((prefix + str(route), name))
            else:
                out.append((f"<{type(p).__name__}>", ""))
        except Exception as e:
            out.append((f"<error: {e}>", ""))
    return out


class Command(BaseCommand):
    help = "Probe SHACMAN hub URLs via Client (HTTP_HOST=carfst.ru, secure). Print resolve + status + urlpatterns."

    def handle(self, *args, **options):
        host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        extra = {
            "HTTP_HOST": host,
            "HTTP_X_FORWARDED_PROTO": "https",
            "SERVER_PORT": "8001",
        }

        self.stdout.write("ROOT_URLCONF = %s" % getattr(settings, "ROOT_URLCONF", ""))
        self.stdout.write("")

        # Top-level urlpatterns (verify shacman/engine and shacman/line exist)
        resolver = get_resolver()
        routes = _list_url_routes(resolver)
        self.stdout.write("--- Top-level urlpatterns (first 25) ---")
        for route, name in routes[:25]:
            self.stdout.write("  %s  name=%s" % (route, name))
        shacman_engine = [r for r, n in routes if "shacman/engine" in r]
        shacman_line = [r for r, n in routes if "shacman/line" in r]
        self.stdout.write("")
        self.stdout.write("  shacman/engine/* in list: %s" % bool(shacman_engine))
        self.stdout.write("  shacman/line/* in list: %s" % bool(shacman_line))
        self.stdout.write("")

        paths = [
            "/shacman/engine/wp13-550e501/",
            "/shacman/line/x3000/",
            "/shacman/formula/6x4/",
        ]
        client = Client()

        for path in paths:
            self.stdout.write("--- %s ---" % path)
            # Resolve (as in shell)
            try:
                r = resolve(path)
                self.stdout.write(
                    "  resolve: view=%s url_name=%s kwargs=%s"
                    % (r.func.__name__, getattr(r, "url_name", None), r.kwargs)
                )
            except Resolver404 as e:
                self.stdout.write(self.style.ERROR("  resolve: Resolver404"))
                self.stdout.write("")
                continue

            # Client request (WSGI-like)
            try:
                response = client.get(
                    path,
                    secure=True,
                    HTTP_HOST=host,
                    HTTP_X_FORWARDED_PROTO="https",
                    SERVER_PORT="8001",
                )
                self.stdout.write("  status_code: %s" % response.status_code)
                self.stdout.write("  Location: %s" % response.get("Location", ""))
                if response.status_code == 404:
                    for h in ("X-Diag-Step", "X-Diag-Resolver", "X-Diag-Mapping-Len", "X-Diag-Slug-In-Mapping", "X-Diag-QS-Count"):
                        if h in response:
                            self.stdout.write("  %s: %s" % (h, response[h]))
                    # Repeat with X-Carfast-Diag: 1 to get diagnostic headers from view
                    resp2 = client.get(
                        path,
                        secure=True,
                        HTTP_HOST=host,
                        HTTP_X_FORWARDED_PROTO="https",
                        HTTP_X_CARFAST_DIAG="1",
                    )
                    if resp2.status_code == 404:
                        self.stdout.write("  (with X-Carfast-Diag:1)")
                        for h in ("X-Diag-Step", "X-Diag-Resolver", "X-Diag-Mapping-Len", "X-Diag-Slug-In-Mapping"):
                            if h in resp2:
                                self.stdout.write("    %s: %s" % (h, resp2[h]))
            except Exception as e:
                self.stdout.write(self.style.ERROR("  client.get: %s" % e))
            self.stdout.write("")

        self.stdout.write("Done.")
