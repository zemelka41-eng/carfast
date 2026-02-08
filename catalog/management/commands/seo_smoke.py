import json
import re
import urllib.request
from urllib.error import HTTPError, URLError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class Command(BaseCommand):
    help = "Run SEO smoke checks for JSON-LD, robots.txt, and sitemap.xml."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default="https://carfst.ru",
            help="Base URL for checks (default: https://carfst.ru).",
        )
        parser.add_argument(
            "--product-slug",
            default="",
            help="Product slug to check (optional).",
        )
        parser.add_argument(
            "--product-url",
            default="",
            help="Explicit product URL to check (optional).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=20,
            help="Request timeout in seconds (default: 20).",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")
        product_slug = (options["product_slug"] or "").strip()
        product_url = (options["product_url"] or "").strip()
        timeout = options["timeout"]

        canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
        canonical_prefix = f"https://{canonical_host}/"

        home_html = self._fetch_text(f"{base_url}/", timeout)
        home_items = self._check_json_ld(
            home_html, required_types={"Organization", "WebSite"}
        )
        website = next(
            (item for item in home_items if item.get("@type") == "WebSite"), None
        )
        if not website:
            raise CommandError("WebSite schema missing on home page.")
        potential_action = website.get("potentialAction", {})
        if potential_action.get("@type") != "SearchAction":
            raise CommandError("SearchAction missing on home page.")

        robots_txt = self._fetch_text(f"{base_url}/robots.txt", timeout)
        expected_line = f"Sitemap: {canonical_prefix}sitemap.xml"
        if expected_line not in robots_txt:
            raise CommandError("robots.txt missing sitemap line.")

        sitemap_xml = self._fetch_text(f"{base_url}/sitemap.xml", timeout)
        locs = re.findall(r"<loc>(.*?)</loc>", sitemap_xml)
        if not locs:
            raise CommandError("sitemap.xml has no <loc> entries.")
        bad_locs = [loc for loc in locs if not loc.startswith(canonical_prefix)]
        if bad_locs:
            raise CommandError("sitemap.xml contains non-canonical <loc> URLs.")

        if not product_url and product_slug:
            product_url = f"{base_url}/product/{product_slug}/"
        if not product_url:
            product_url = self._pick_product_url(sitemap_xml, canonical_prefix)
        if not product_url:
            raise CommandError("Cannot determine product URL for checks.")

        product_html = self._fetch_text(product_url, timeout)
        product_items = self._check_json_ld(
            product_html, required_types={"Product", "BreadcrumbList"}
        )
        product_schema = next(
            (item for item in product_items if item.get("@type") == "Product"), None
        )
        if not product_schema:
            raise CommandError("Product schema missing on product page.")
        offer = product_schema.get("offers", {})
        if offer.get("priceCurrency") != "RUB":
            raise CommandError("Offer priceCurrency must be RUB.")
        if offer.get("availability") != "https://schema.org/InStock":
            raise CommandError("Offer availability must be InStock.")
        if "FAQ" in product_html or "productFaq" in product_html:
            types = {item.get("@type") for item in product_items if isinstance(item, dict)}
            if "FAQPage" not in types:
                raise CommandError("FAQPage schema missing on product page.")
        if "@type\": \"Offer" not in product_html:
            raise CommandError("Offer schema missing on product page.")

        self.stdout.write(self.style.SUCCESS("SEO smoke checks passed."))

    def _fetch_text(self, url: str, timeout: int) -> str:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "carfst-seo-smoke"}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "ignore")
        except HTTPError as exc:
            raise CommandError(f"HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            raise CommandError(f"Failed to fetch {url}: {exc}") from exc

    def _check_json_ld(self, html: str, required_types: set[str]) -> list[dict]:
        scripts = JSON_LD_PATTERN.findall(html)
        if not scripts:
            raise CommandError("JSON-LD script tag not found.")
        if len(scripts) > 2:
            raise CommandError("Too many JSON-LD scripts (expected <= 2).")

        payload_items = []
        for script in scripts:
            data = json.loads(script)
            if isinstance(data, list):
                payload_items.extend(data)
            else:
                payload_items.append(data)

        types = {item.get("@type") for item in payload_items if isinstance(item, dict)}
        missing = required_types - types
        if missing:
            raise CommandError(f"JSON-LD missing types: {', '.join(sorted(missing))}")
        return payload_items

    def _pick_product_url(self, sitemap_xml: str, canonical_prefix: str) -> str:
        match = re.search(rf"{re.escape(canonical_prefix)}product/[^<]+", sitemap_xml)
        return match.group(0) if match else ""
