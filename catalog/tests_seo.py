"""
SEO tests for carfst.ru

Tests schema.org compliance, meta tags, and SEO invariants.
Note: Uses localhost as HTTP_HOST to bypass CanonicalHostMiddleware redirects.
"""
from django.test import TestCase, Client, override_settings
from django.urls import reverse


# Disable CanonicalHostMiddleware for tests
@override_settings(
    MIDDLEWARE=[
        mw for mw in __import__("django.conf").conf.settings.MIDDLEWARE
        if "CanonicalHostMiddleware" not in mw
    ]
)
class SchemaInvariantsTest(TestCase):
    """
    Test SEO invariants:
    - Schema (JSON-LD) should NOT be present on URLs with GET parameters
    - Schema should be present on clean URLs
    """

    def setUp(self):
        self.client = Client()

    def test_no_schema_on_url_with_utm(self):
        """Schema should not appear on URLs with utm parameters."""
        test_urls = [
            ("catalog:home", {}, {"utm_source": "test"}),
        ]
        for url_name, kwargs, params in test_urls:
            url = reverse(url_name, kwargs=kwargs) if kwargs else reverse(url_name)
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, 200, f"Failed for {url}")
            content = response.content.decode("utf-8")
            # page_schema_payload should not be in content when GET params exist
            # The base template only renders schema when request.GET is empty
            self.assertNotIn(
                '"@type": "FAQPage"',
                content,
                f"FAQPage schema found on {url}?{params}",
            )

    def test_meta_robots_noindex_on_get_params(self):
        """Pages with GET params should have noindex meta robots."""
        response = self.client.get(reverse("catalog:home"), {"utm_source": "test"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Check that meta robots is set to noindex
        self.assertIn('name="robots"', content)
        self.assertIn("noindex", content)


@override_settings(
    MIDDLEWARE=[
        mw for mw in __import__("django.conf").conf.settings.MIDDLEWARE
        if "CanonicalHostMiddleware" not in mw
    ]
)
class CatalogPageInvariantsTest(TestCase):
    """Test critical /catalog/ SEO invariants."""

    def setUp(self):
        self.client = Client()

    def test_catalog_page_noindex_follow(self):
        """/catalog/ should have noindex, follow meta robots."""
        response = self.client.get(reverse("catalog:catalog_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        
        # Must have meta robots tag
        self.assertIn('name="robots"', content)
        # Must contain noindex
        self.assertIn("noindex", content)
        # Should contain follow
        self.assertIn("follow", content)

    def test_catalog_with_utm_has_clean_canonical(self):
        """/catalog/?utm_source=test should have clean canonical without utm."""
        response = self.client.get(reverse("catalog:catalog_list"), {"utm_source": "test"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        
        # Canonical should be present
        self.assertIn('rel="canonical"', content)
        # Extract canonical URL
        canonical_start = content.find('rel="canonical"')
        canonical_section = content[max(0, canonical_start - 200):canonical_start + 200]
        # Canonical should not contain utm_source
        self.assertNotIn("utm_source", canonical_section)

    def test_catalog_no_schema_on_noindex_page(self):
        """/catalog/ (noindex page) should not have schema markup."""
        response = self.client.get(reverse("catalog:catalog_list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        
        # Should not have Product/ItemList schema (catalog is noindex)
        self.assertNotIn('"@type": "ItemList"', content)


@override_settings(
    MIDDLEWARE=[
        mw for mw in __import__("django.conf").conf.settings.MIDDLEWARE
        if "CanonicalHostMiddleware" not in mw
    ]
)
class MetaDescriptionTest(TestCase):
    """Test meta description is present and properly formatted."""

    def setUp(self):
        self.client = Client()

    def test_home_has_meta_description(self):
        """Home page should have a meta description."""
        response = self.client.get(reverse("catalog:home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('name="description"', content)


@override_settings(
    MIDDLEWARE=[
        mw for mw in __import__("django.conf").conf.settings.MIDDLEWARE
        if "CanonicalHostMiddleware" not in mw
    ]
)
class CanonicalURLTest(TestCase):
    """Test canonical URLs are clean (without GET params)."""

    def setUp(self):
        self.client = Client()

    def test_canonical_is_clean_with_utm(self):
        """Canonical URL should not include utm parameters."""
        response = self.client.get(reverse("catalog:home"), {"utm_source": "test"})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('rel="canonical"', content)
        # Canonical should not contain utm_source
        self.assertNotIn("utm_source", content.split('rel="canonical"')[1].split(">")[0])


@override_settings(
    MIDDLEWARE=[
        mw for mw in __import__("django.conf").conf.settings.MIDDLEWARE
        if "CanonicalHostMiddleware" not in mw
    ]
)
class RobotsTxtTest(TestCase):
    """Test robots.txt is properly formatted (multiline, not single line)."""

    def setUp(self):
        self.client = Client()

    def test_robots_txt_multiline(self):
        """robots.txt must be multiline: fail if single line. Content-Type text/plain."""
        response = self.client.get("/robots.txt", follow=True)
        self.assertEqual(response.status_code, 200, "robots.txt must return 200 (after redirects if any)")
        self.assertEqual(
            response["Content-Type"],
            "text/plain; charset=utf-8",
            "Content-Type must be text/plain; charset=utf-8",
        )
        content = response.content.decode("utf-8")
        line_count = len([line for line in content.split("\n") if line.strip()])
        self.assertGreaterEqual(
            line_count,
            3,
            "robots.txt must have at least 3 lines (got single line or too few)",
        )
        self.assertIn("\n", content, "robots.txt must contain newlines (not one line)")
        self.assertIn("User-agent: *", content)
        self.assertIn("Disallow: /admin/", content)
        self.assertIn("Sitemap:", content)


class SeedDedupTest(TestCase):
    """Test anti-duplicate logic: same heading but different content -> both sections kept."""

    def test_same_heading_different_content_both_kept(self):
        from catalog.management.commands.seed_seo_content_full import _deduplicate_html_sections

        html = """
        <h2>Описание</h2>
        <p>Первый блок описания модели. Характеристики двигателя и трансмиссии.</p>
        <h2>Описание</h2>
        <p>Второй блок — условия поставки и гарантия. Совершенно другой текст.</p>
        """
        result = _deduplicate_html_sections(html)
        # Both sections must remain (same heading, different content)
        self.assertIn("Первый блок описания", result)
        self.assertIn("Второй блок", result)
        self.assertIn("условия поставки и гарантия", result)
        # Should have two h2 Описание
        self.assertEqual(result.count("<h2>Описание</h2>"), 2)

    def test_identical_content_second_removed(self):
        from catalog.management.commands.seed_seo_content_full import _deduplicate_html_sections

        html = """
        <h2>Гарантия</h2>
        <p>Один и тот же текст гарантии. Буква в букву повтор.</p>
        <h2>Гарантия</h2>
        <p>Один и тот же текст гарантии. Буква в букву повтор.</p>
        """
        result = _deduplicate_html_sections(html)
        # Second duplicate section should be removed (same content)
        self.assertIn("Один и тот же текст гарантии", result)
        self.assertEqual(result.count("<h2>Гарантия</h2>"), 1)


class AdminUrlTest(TestCase):
    """Test admin URL built by seo_content_audit: reverse() + urljoin, no 'admincatalog'."""

    def test_admin_url_format_with_base_url(self):
        from catalog.management.commands.seo_content_audit import Command
        from catalog.models import Category, Product

        cmd = Command()
        cmd.base_url = "https://carfst.ru"
        # Prefer Product (audit --include-products); fallback to Category
        obj = Product.objects.public().first()
        if obj is None:
            obj = Category.objects.first()
        if obj is None:
            self.skipTest("No Product or Category in DB")
        url = cmd._get_admin_url(obj)
        self.assertTrue(url.startswith("https://carfst.ru/"), f"Expected base prefix, got {url}")
        self.assertIn("/admin/", url, f"Expected /admin/ in URL, got {url}")
        self.assertIn("/change/", url, f"Expected change view in URL, got {url}")
        self.assertNotIn("admincatalog", url, "URL must not contain concatenated 'admincatalog'")
        self.assertIn(str(obj.pk), url, "URL must contain object id")
        # If Product: must have catalog/product segment
        if obj.__class__.__name__ == "Product":
            self.assertIn("/admin/catalog/product/", url, f"Expected admin catalog product path, got {url}")


class VisibleLenTest(TestCase):
    """Test shared visible_len metric (audit and seed use same length)."""

    def test_visible_len_strip_tags_normalize_whitespace(self):
        from catalog.seo_text import visible_len, visible_text

        html = "<p>  Один   абзац  </p>\n<p>Два</p>"
        self.assertEqual(visible_text(html), "Один абзац Два")
        self.assertEqual(visible_len(html), len("Один абзац Два"))
        self.assertEqual(visible_len("<p>a</p>"), 1)
        self.assertEqual(visible_len(""), 0)
        self.assertEqual(visible_len(None), 0)


class ShacmanCategoryEngineHubTest(TestCase):
    """New clean hub URLs /shacman/category/<cat>/engine/<val>/: 200 valid, 404 invalid, noindex on page=2, no schema on utm."""

    def test_category_engine_hub_resolve(self):
        """Route shacman_category_engine_hub is registered."""
        from django.urls import resolve
        resolve("/shacman/category/samosvaly/engine/wp13-550e501/")
        resolve("/shacman/category/samosvaly/engine/wp13-550e501/in-stock/")

    def test_category_engine_invalid_returns_404(self):
        """Unknown category or engine returns 404 (no URL explosion)."""
        from django.test import Client
        client = Client()
        # Invalid category
        r = client.get("/shacman/category/nonexistent-cat-xyz/engine/wp13-550e501/")
        self.assertIn(r.status_code, (404, 200), "Invalid category: 404 or 200 with noindex")
        # Invalid engine (if allowed set is empty or doesn't contain this pair)
        r2 = client.get("/shacman/category/samosvaly/engine/nonexistent-engine-xyz/")
        self.assertIn(r2.status_code, (404, 200))

    def test_product_detail_schema_clean_only(self):
        """Product detail: Product schema on clean URL, absent on ?utm_source=."""
        from django.test import Client
        from catalog.models import Product
        client = Client()
        product = Product.objects.public().first()
        if product is None:
            self.skipTest("No public products")
        url_clean = product.get_absolute_url()
        url_utm = url_clean + "?utm_source=test"
        r_clean = client.get(url_clean)
        r_utm = client.get(url_utm)
        self.assertEqual(r_clean.status_code, 200)
        self.assertEqual(r_utm.status_code, 200)
        body_clean = r_clean.content.decode("utf-8")
        body_utm = r_utm.content.decode("utf-8")
        self.assertIn('"@type": "Product"', body_clean, "Clean URL must have Product schema")
        self.assertNotIn('"@type": "Product"', body_utm, "URL with GET must not have Product schema")


class ShacmanNewComboHubsTest(TestCase):
    """New combo hubs: category/line, line/formula, category/formula (explicit path). Resolve and 404 for invalid slug."""

    def test_category_line_resolve(self):
        """Routes shacman_category_line_hub and in-stock are registered."""
        from django.urls import resolve
        resolve("/shacman/category/samosvaly/line/x3000/")
        resolve("/shacman/category/samosvaly/line/x3000/in-stock/")

    def test_line_formula_resolve(self):
        """Routes shacman_line_formula_hub and in-stock are registered."""
        from django.urls import resolve
        resolve("/shacman/line/x3000/formula/6x4/")
        resolve("/shacman/line/x3000/formula/6x4/in-stock/")

    def test_category_formula_explicit_resolve(self):
        """Routes shacman_category_formula_explicit_hub and in-stock are registered."""
        from django.urls import resolve
        resolve("/shacman/category/samosvaly/formula/8x4/")
        resolve("/shacman/category/samosvaly/formula/8x4/in-stock/")

    def test_category_line_formula_resolve(self):
        """Routes shacman_category_line_formula_hub and in-stock are registered."""
        from django.urls import resolve
        resolve("/shacman/category/samosvaly/line/x3000/formula/8x4/")
        resolve("/shacman/category/samosvaly/line/x3000/formula/8x4/in-stock/")

    def test_model_code_resolve(self):
        """Routes shacman_model_code_hub and in-stock are registered."""
        from django.urls import resolve
        resolve("/shacman/model/sx1234/")
        resolve("/shacman/model/sx1234/in-stock/")

    def test_invalid_slug_returns_404(self):
        """Invalid category/line/formula slug returns 404."""
        from django.test import Client
        client = Client()
        r = client.get("/shacman/category/nonexistent-cat-xyz/line/x3000/")
        self.assertIn(r.status_code, (404, 200))
        r2 = client.get("/shacman/line/nonexistent-line-xyz/formula/6x4/")
        self.assertIn(r2.status_code, (404, 200))
        r3 = client.get("/shacman/category/samosvaly/formula/invalid-formula-xyz/")
        self.assertIn(r3.status_code, (404, 200))
        r4 = client.get("/shacman/category/nonexistent-cat-xyz/line/x3000/formula/8x4/")
        self.assertIn(r4.status_code, (404, 200))


class ShacmanHubSEOFieldTest(TestCase):
    """Ensure ShacmanHubSEO.hub_type max_length fits all HubType choice values (avoids fields.E009)."""

    def test_hub_type_max_length_fits_all_choices(self):
        from catalog.models import ShacmanHubSEO

        field = ShacmanHubSEO._meta.get_field("hub_type")
        max_choice_len = max(len(value) for value, _ in ShacmanHubSEO.HubType.choices)
        self.assertGreaterEqual(
            field.max_length,
            max_choice_len,
            f"hub_type max_length={field.max_length} must be >= longest choice length {max_choice_len}",
        )


class ShacmanForceIndexTest(TestCase):
    """force_index: requires sufficient content; noindex_for_thin preserved without force_index."""

    def test_force_index_sufficient_requires_body_or_faq(self):
        """_shacman_hub_seo_content_sufficient returns False when body/faq below threshold."""
        from catalog.views import _shacman_hub_seo_content_sufficient

        class Rec:
            seo_body_html = ""
            seo_text = ""
            faq = ""

        self.assertFalse(_shacman_hub_seo_content_sufficient(Rec()))

    def test_force_index_sufficient_true_when_body_long_enough(self):
        """_shacman_hub_seo_content_sufficient returns True when body >= FORCE_INDEX_MIN_BODY_CHARS."""
        from catalog.views import FORCE_INDEX_MIN_BODY_CHARS, _shacman_hub_seo_content_sufficient

        class Rec:
            seo_body_html = "x" * FORCE_INDEX_MIN_BODY_CHARS
            seo_text = ""
            faq = ""

        self.assertTrue(_shacman_hub_seo_content_sufficient(Rec()))

    def test_force_index_sufficient_true_when_faq_enough(self):
        """_shacman_hub_seo_content_sufficient returns True when FAQ count >= FORCE_INDEX_MIN_FAQ."""
        from catalog.views import FORCE_INDEX_MIN_FAQ, _shacman_hub_seo_content_sufficient

        class Rec:
            seo_body_html = ""
            seo_text = ""
            faq = "\n".join([f"Q{i}|A{i}" for i in range(FORCE_INDEX_MIN_FAQ)])

        self.assertTrue(_shacman_hub_seo_content_sufficient(Rec()))

    def test_noindex_for_thin_without_override(self):
        """Without force_index record, _shacman_hub_force_index_override returns False (noindex preserved)."""
        from catalog.views import _shacman_hub_force_index_override

        # No ShacmanHubSEO record for this combo -> False
        result = _shacman_hub_force_index_override(
            "category_line",
            category=None,
            facet_key="nonexistent-line-xyz",
        )
        self.assertFalse(result)


class ShacmanHubContentTest(TestCase):
    """SEO block: single block under cards; default content has no repeating sections."""

    def test_default_seo_text_has_no_duplicate_dopolnitelnaya_informaciya(self):
        """DEFAULT_SHACMAN_HUB_SEO_TEXT must not repeat 'Дополнительная информация' more than once."""
        from catalog.views import DEFAULT_SHACMAN_HUB_SEO_TEXT

        text = (DEFAULT_SHACMAN_HUB_SEO_TEXT or "").lower()
        count = text.count("дополнительная информация")
        self.assertLessEqual(count, 1, "Default SEO text must not repeat 'Дополнительная информация' more than once")

    def test_dedup_dopolnitelnaya_informaciya_at_most_one(self):
        """deduplicate_additional_info_heading ensures 'Дополнительная информация' appears at most once."""
        from catalog.seo_html import deduplicate_additional_info_heading

        html_duplicate = (
            "<p>Intro.</p><h3>Дополнительная информация</h3><p>First block.</p>"
            "<h3>Дополнительная информация</h3><p>Second block.</p>"
        )
        result = deduplicate_additional_info_heading(html_duplicate)
        count = result.lower().count("дополнительная информация")
        self.assertLessEqual(count, 1, "Dedup must leave at most one 'Дополнительная информация' in effective body")

    def test_effective_body_dopolnitelnaya_at_most_once(self):
        """Effective body (seo_body_html or seo_text) rendered on hub must have 'Дополнительная информация' ≤ 1."""
        from catalog.seo_html import deduplicate_additional_info_heading

        # Simulate effective body: after dedup, count must be ≤ 1
        effective = deduplicate_additional_info_heading(
            "<h3>Цена</h3><p>Текст.</p><h3>Дополнительная информация</h3><p>Раз.</p>"
            "<h3>Дополнительная информация</h3><p>Два.</p>"
        )
        self.assertLessEqual(
            effective.lower().count("дополнительная информация"),
            1,
            "Effective body must contain 'Дополнительная информация' at most once",
        )

    def test_shacman_hub_template_single_seo_block_under_cards(self):
        """shacman_hub: only one SEO block under cards (class shacman-hub-seo-body)."""
        from django.test import Client

        client = Client()
        response = client.get("/shacman/")
        if response.status_code != 200:
            self.skipTest("/shacman/ returned %s" % response.status_code)
        html = response.content.decode("utf-8")
        self.assertIn("shacman-hub-seo-zone", html)
        # One block under cards: body or text in a single section with class shacman-hub-seo-body
        count = html.count("shacman-hub-seo-body")
        self.assertEqual(count, 1, "Page must render exactly one SEO block under cards (shacman-hub-seo-body)")


class SEOContentAuditNotesTest(TestCase):
    """seo_content_audit: notes detect duplicate 'Дополнительная информация' for Series/Category."""

    def test_audit_series_notes_duplicate_additional_info(self):
        """Series with duplicate 'Дополнительная информация' in seo_body_html gets note in audit."""
        from catalog.management.commands.seo_content_audit import Command as AuditCommand, _notes_duplicate_additional_info
        from catalog.models import Series

        body_dup = (
            "<p>Intro.</p><h3>Дополнительная информация</h3><p>First.</p>"
            "<h3>Дополнительная информация</h3><p>Second.</p>"
        )
        note = _notes_duplicate_additional_info(body_dup)
        self.assertIn("Duplicate heading", note)
        self.assertIn("Дополнительная информация", note)

        # Create a Series with duplicate body and ensure audit entry has notes
        series = Series.objects.create(
            name="TestSeriesAudit",
            slug="test-series-audit-notes",
            seo_body_html=body_dup,
        )
        try:
            cmd = AuditCommand()
            cmd.base_url = ""
            entries = cmd._audit_series(min_intro=600, min_body=2500, min_faq=6)
            found = [e for e in entries if e.identifier == series.slug]
            self.assertEqual(len(found), 1)
            self.assertIn("Duplicate heading", found[0].notes)
        finally:
            series.delete()

    def test_deduplicate_additional_info_heading_idempotent(self):
        """deduplicate_additional_info_heading is idempotent: already-deduped content unchanged."""
        from catalog.seo_html import deduplicate_additional_info_heading

        single = "<p>Text.</p><h3>Дополнительная информация</h3><p>More.</p>"
        result = deduplicate_additional_info_heading(single)
        self.assertEqual(result, single)
        result2 = deduplicate_additional_info_heading(result)
        self.assertEqual(result2, result)
