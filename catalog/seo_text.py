"""
Shared SEO text metrics for audit and seed.

Single source of truth for "visible text" length: strip_tags + normalize whitespace.
Used by seo_content_audit and seed_seo_content_full so body length is comparable.
"""
import re

from django.utils.html import strip_tags


def visible_text(html: str) -> str:
    """
    Extract visible text from HTML: strip tags and normalize whitespace to single spaces.
    """
    if not html:
        return ""
    s = strip_tags(html).strip()
    return re.sub(r"\s+", " ", s).strip()


def visible_len(html: str) -> int:
    """Length of visible text (same metric as audit uses for body/intro)."""
    return len(visible_text(html))
