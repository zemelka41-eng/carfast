"""
SEO HTML utilities for catalog pages.
Deduplication of repeated headings (e.g. "Дополнительная информация") to avoid SEO body duplicates.
"""
import re


def deduplicate_additional_info_heading(html: str) -> str:
    """
    Ensure "Дополнительная информация" appears at most once in the effective SEO body.
    Removes 2nd and later <h2> or <h3> headings that contain exactly that text (case-insensitive).
    """
    if not (html or "").strip():
        return html or ""
    text = (html or "").strip()
    if "дополнительная информация" not in text.lower():
        return text
    if text.lower().count("дополнительная информация") <= 1:
        return text
    pattern = re.compile(
        r"<h[23][^>]*>\s*Дополнительная информация\s*</h[23]>",
        re.IGNORECASE,
    )
    seen = [False]

    def replace_second_plus(match):
        if not seen[0]:
            seen[0] = True
            return match.group(0)
        return ""

    return pattern.sub(replace_second_plus, text)
