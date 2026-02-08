"""
Cross-linking: hubs ↔ blog. Clean indexable URLs only (no utm).
"""
from django.urls import reverse

# Keywords for matching blog posts to show on /shacman/* (Полезные материалы)
SHACMAN_RELATED_KEYWORDS = (
    "shacman", "шахман", "шакман", "самосвал", "тягач", "лизинг", "двигатель",
    "8x4", "6x4", "4x2", "x3000", "x5000", "x6000", "wp12", "wp13",
)

# Hub links for blog "Подбор техники" — (keyword_substring, url_name, kwargs)
HUB_LINKS_BY_KEYWORD = [
    ("shacman", "shacman_hub", {}),
    ("в наличии", "shacman_in_stock", {}),
    ("самосвал", "shacman_category", {"category_slug": "samosvaly"}),
    ("тягач", "shacman_category", {"category_slug": "sedelnye-tyagachi"}),
    ("автобетоносмеситель", "shacman_category", {"category_slug": "avtobetonosmesiteli"}),
    ("6x4", "shacman_formula_hub", {"formula": "6x4"}),
    ("8x4", "shacman_formula_hub", {"formula": "8x4"}),
    ("4x2", "shacman_formula_hub", {"formula": "4x2"}),
    ("x3000", "shacman_line_hub", {"line_slug": "x3000"}),
    ("x5000", "shacman_line_hub", {"line_slug": "x5000"}),
    ("x6000", "shacman_line_hub", {"line_slug": "x6000"}),
    ("l3000", "shacman_line_hub", {"line_slug": "l3000"}),
]


def get_related_blog_posts_for_shacman(limit: int = 5):
    """
    Return up to `limit` published blog posts relevant to SHACMAN (by topics or title/content).
    For use on /shacman/* pages (Полезные материалы). URLs are clean (no utm).
    """
    try:
        from blog.models import BlogPost
    except ImportError:
        return []
    qs = BlogPost.objects.published().order_by("-published_at")[: limit * 3]
    result = []
    seen_pk = set()
    for post in qs:
        if len(result) >= limit:
            break
        if post.pk in seen_pk:
            continue
        text = " ".join([
            (post.title or ""),
            (post.excerpt or ""),
            (post.content_html or "")[:2000],
        ]).lower()
        topics = getattr(post, "topics", None) or []
        topic_text = " ".join(str(t).lower() for t in topics)
        combined = text + " " + topic_text
        if any(kw.lower() in combined for kw in SHACMAN_RELATED_KEYWORDS):
            result.append(post)
            seen_pk.add(post.pk)
    return result[:limit]


def get_hub_links_for_blog_post(post) -> list[dict]:
    """
    Return list of {url, label} for "Подбор техники" on blog post.
    URL is clean (indexable, no utm). Deduplicated by URL.
    """
    try:
        from django.urls import NoReverseMatch
    except ImportError:
        return []
    text = " ".join([
        (post.title or ""),
        (post.excerpt or ""),
        (post.content_html or "")[:3000],
    ]).lower()
    topics = getattr(post, "topics", None) or []
    topic_text = " ".join(str(t).lower() for t in topics)
    combined = text + " " + topic_text

    seen_urls = set()
    links = []
    for keyword, url_name, kwargs in HUB_LINKS_BY_KEYWORD:
        if keyword.lower() not in combined:
            continue
        try:
            url = reverse(url_name, kwargs=kwargs)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            label = _hub_label(url_name, kwargs)
            links.append({"url": url, "label": label})
        except Exception:
            continue
    return links[:8]


def _hub_label(url_name: str, kwargs: dict) -> str:
    if url_name == "shacman_hub":
        return "Каталог SHACMAN"
    if url_name == "shacman_in_stock":
        return "SHACMAN в наличии"
    if url_name == "shacman_category":
        slug = kwargs.get("category_slug", "")
        labels = {"samosvaly": "Самосвалы SHACMAN", "sedelnye-tyagachi": "Седельные тягачи SHACMAN", "avtobetonosmesiteli": "Автобетоносмесители SHACMAN"}
        return labels.get(slug, "SHACMAN")
    if url_name == "shacman_formula_hub":
        return f"SHACMAN {kwargs.get('formula', '')}"
    if url_name == "shacman_line_hub":
        return f"SHACMAN {kwargs.get('line_slug', '').upper()}"
    return "SHACMAN"
