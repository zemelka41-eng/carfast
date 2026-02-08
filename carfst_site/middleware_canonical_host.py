"""
Middleware for canonical host redirect (www/non-www normalization).

Redirects requests to non-canonical hosts (e.g., www.carfst.ru -> carfst.ru)
to the canonical host with 301 redirect, preserving path and query string.

Does not redirect localhost/127.0.0.1 for local development.
"""

from typing import Callable

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponsePermanentRedirect,
)


class CanonicalHostMiddleware:
    """
    Redirects to canonical host if request host is in allowed variants but not canonical.
    
    Settings:
    - CANONICAL_HOST: canonical hostname (default: "carfst.ru")
    - ALLOWED_HOST_VARIANTS: list of host variants that should redirect (default: ["carfst.ru", "www.carfst.ru"])
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response
        self.canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        self.allowed_variants = getattr(
            settings,
            "ALLOWED_HOST_VARIANTS",
            ["carfst.ru", "www.carfst.ru"],
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path_info or request.path or ""
        safe = (
            path in ("/sitemap.xml", "/robots.txt")
            or path.rstrip("/") in ("/sitemap.xml", "/robots.txt")
            or path.startswith(("/sitemap-", "/robots"))
        )
        raw_host = (
            request.META.get("HTTP_HOST")
            or request.META.get("SERVER_NAME")
            or ""
        ).split(":")[0].lower()
        allowed_hosts = [h.lower() for h in getattr(settings, "ALLOWED_HOSTS", [])]

        def _is_allowed_host(host: str) -> bool:
            if not host:
                return False
            if "*" in allowed_hosts:
                return True
            for pattern in allowed_hosts:
                if pattern == host:
                    return True
                if pattern.startswith(".") and host.endswith(pattern):
                    return True
            return False

        if safe:
            if not _is_allowed_host(raw_host):
                request.META["HTTP_HOST"] = self.canonical_host
                request.META["HTTP_X_FORWARDED_HOST"] = self.canonical_host
                request.META["HTTP_X_FORWARDED_PROTO"] = "https"
                request.META["wsgi.url_scheme"] = "https"
                request.META["SERVER_PORT"] = "443"
            return self.get_response(request)
        try:
            host = request.get_host()
        except DisallowedHost:
            # Avoid noisy stacktraces for invalid Host headers.
            return HttpResponseBadRequest("Invalid Host header.")
        
        # Skip redirect for localhost/127.0.0.1
        if host in ("localhost", "127.0.0.1") or host.startswith(("localhost:", "127.0.0.1:")):
            return self.get_response(request)
        
        # Skip if already canonical
        if host == self.canonical_host:
            return self.get_response(request)
        
        # Only redirect if host is in allowed variants
        if host not in self.allowed_variants:
            return self.get_response(request)
        
        # Build canonical URL
        scheme = "https" if request.is_secure() else "http"
        canonical_url = f"{scheme}://{self.canonical_host}{request.get_full_path()}"
        
        return HttpResponsePermanentRedirect(canonical_url)
