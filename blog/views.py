import html as html_stdlib
import json
import math
import re

from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils.html import strip_tags

from .models import BlogPost

try:
    from lxml import etree, html as lxml_html
    HAS_LXML = True
except ImportError:
    HAS_LXML = False
    etree = None
    lxml_html = None


def _canonical_url(path: str) -> str:
    canonical_host = getattr(settings, "CANONICAL_HOST", "carfst.ru")
    return f"https://{canonical_host}{path}"


def _build_breadcrumb_schema(request, items: list[dict]) -> dict:
    """
    Build BreadcrumbList JSON-LD schema.
    
    Args:
        request: Django request object
        items: List of dicts with 'name' and 'url' keys
    
    Returns:
        BreadcrumbList schema dict
    """
    breadcrumb_items = []
    for position, item in enumerate(items, start=1):
        breadcrumb_items.append({
            "@type": "ListItem",
            "position": position,
            "name": item["name"],
            "item": request.build_absolute_uri(item["url"]),
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumb_items,
    }


def _reading_time_minutes(html: str) -> int:
    text = strip_tags(html or "")
    words = [w for w in re.split(r"\s+", text) if w]
    if not words:
        return 1
    return max(1, math.ceil(len(words) / 180))


def _normalize_anchor(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _extract_anchor_and_caption(caption: str | None) -> tuple[str | None, str | None]:
    if not caption or "@after:" not in caption:
        return None, None
    _, raw = caption.split("@after:", 1)
    raw = raw.strip()
    if not raw:
        return None, None
    for sep in (" | ", " — ", " - "):
        if sep in raw:
            anchor, figcaption = raw.split(sep, 1)
            return anchor.strip(), figcaption.strip()
    return raw, None


# Regex to find <h2...> or <h3...> opening tag; group 1 is tag name
_HEADING_OPEN = re.compile(r"<(h2|h3)(\s[^>]*)?>", re.IGNORECASE)


def _find_headings_stdio(html: str) -> list[tuple[int, str]]:
    """
    Find all h2/h3 blocks; return list of (end_position, inner_text).
    Uses regex + balance for closing tag. No lxml.
    """
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(html):
        m = _HEADING_OPEN.search(html, i)
        if not m:
            break
        tag = m.group(1).lower()
        start_inner = m.end()
        close_tag = f"</{tag}>"
        depth = 1
        pos = start_inner
        while depth > 0 and pos < len(html):
            next_open = html.find(f"<{tag}", pos)
            next_close = html.find(close_tag, pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 1
            else:
                depth -= 1
                if depth == 0:
                    end_inner = next_close
                    end_outer = next_close + len(close_tag)
                    inner_html = html[start_inner:end_inner]
                    inner_text = strip_tags(inner_html)
                    out.append((end_outer, inner_text))
                    i = end_outer
                    break
                pos = next_close + len(close_tag)
        else:
            i = start_inner + 1
    return out


def _inject_images_stdlib(html: str, images) -> tuple[str, list[int]]:
    """Fallback when lxml is not installed: regex-based h2/h3 find + string insert."""
    if not html or not images:
        return html, []

    headings = _find_headings_stdio(html)
    # (end_position, list of (figure_html, image_id))
    insertions: list[tuple[int, list[tuple[str, int]]]] = []
    used_ids: list[int] = []

    for img in images:
        anchor, figcaption = _extract_anchor_and_caption(img.caption)
        if not anchor:
            continue
        anchor_norm = _normalize_anchor(anchor)
        for end_pos, heading_text in headings:
            if anchor_norm and anchor_norm in _normalize_anchor(heading_text):
                src = html_stdlib.escape(img.image.url, quote=True)
                alt = html_stdlib.escape(img.alt or img.post.title, quote=True)
                fig_html = f'<figcaption>{html_stdlib.escape(figcaption)}</figcaption>' if figcaption else ""
                figure_html = (
                    f'<figure class="blog-inline-image" data-blog-inline-image="1">'
                    f'<img src="{src}" alt="{alt}" class="img-fluid" loading="lazy" decoding="async">'
                    f"{fig_html}</figure>"
                )
                found = False
                for idx, (pos, figs) in enumerate(insertions):
                    if pos == end_pos:
                        figs.append((figure_html, img.id))
                        found = True
                        break
                if not found:
                    insertions.append((end_pos, [(figure_html, img.id)]))
                used_ids.append(img.id)
                break

    if not insertions:
        return html, used_ids

    insertions.sort(key=lambda x: x[0])
    parts: list[str] = []
    prev = 0
    for pos, figs in insertions:
        parts.append(html[prev:pos])
        for figure_html, _ in figs:
            parts.append(figure_html)
        prev = pos
    parts.append(html[prev:])
    return "".join(parts), used_ids


def inject_images_into_html(html: str, images) -> tuple[str, list[int]]:
    if not html or not images:
        return html, []

    if HAS_LXML:
        return _inject_images_lxml(html, images)
    return _inject_images_stdlib(html, images)


def _inject_images_lxml(html: str, images) -> tuple[str, list[int]]:
    """Requires lxml (used only when HAS_LXML is True)."""
    container = lxml_html.fragment_fromstring(html, create_parent="div")
    headings = container.xpath(".//h2|.//h3")
    used_ids: list[int] = []
    last_by_heading: dict = {}

    for img in images:
        anchor, figcaption = _extract_anchor_and_caption(img.caption)
        if not anchor:
            continue
        anchor_norm = _normalize_anchor(anchor)
        target = None
        for heading in headings:
            heading_text = _normalize_anchor(" ".join(heading.itertext()))
            if anchor_norm and anchor_norm in heading_text:
                target = heading
                break
        if target is None:
            continue

        figure = lxml_html.Element(
            "figure",
            {"class": "blog-inline-image", "data-blog-inline-image": "1"},
        )
        img_el = lxml_html.Element(
            "img",
            src=img.image.url,
            alt=img.alt or img.post.title,
            loading="lazy",
            decoding="async",
        )
        img_el.set("class", "img-fluid")
        figure.append(img_el)
        if figcaption:
            caption_el = lxml_html.Element("figcaption")
            caption_el.text = figcaption
            figure.append(caption_el)

        insert_after = last_by_heading.get(target, target)
        insert_after.addnext(figure)
        last_by_heading[target] = figure
        used_ids.append(img.id)

    html_parts = [
        etree.tostring(child, encoding="unicode", method="html")
        for child in container
    ]
    return "".join(html_parts).strip(), used_ids


def blog_list(request):
    posts = BlogPost.objects.published()
    paginator = Paginator(posts, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    canonical = _canonical_url("/blog/")
    meta_robots = "index, follow"
    if request.GET:
        meta_robots = "noindex, follow"

    # Build breadcrumb schema - only on clean URLs (no GET params) - SEO invariant
    from django.urls import reverse
    breadcrumb_items = [
        {"name": "Главная", "url": reverse("catalog:home")},
        {"name": "Блог", "url": "/blog/"},
    ]
    
    if not request.GET:
        breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
        schema_items = [breadcrumb_schema]
        page_schema_payload = json.dumps(schema_items, ensure_ascii=False)[1:-1]
    else:
        page_schema_payload = ""

    context = {
        "page_obj": page_obj,
        "meta_title": "Блог — CARFAST",
        "meta_description": "Практичные материалы по коммерческой технике, финансированию и эксплуатации.",
        "canonical": canonical,
        "meta_robots": meta_robots,
        "og_title": "Блог — CARFAST",
        "og_description": "Практичные материалы по коммерческой технике, финансированию и эксплуатации.",
        "og_url": canonical,
        "og_type": "website",
        "page_schema_payload": page_schema_payload,
    }
    return render(request, "blog/blog_list.html", context)


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost.objects.published(), slug=slug)
    canonical = _canonical_url(post.get_absolute_url())

    from catalog.blog_crosslink import get_hub_links_for_blog_post
    hub_links = get_hub_links_for_blog_post(post)

    meta_robots = "index, follow"
    if request.GET:
        meta_robots = "noindex, follow"

    og_image = post.cover_image.url if post.cover_image else None

    images = list(post.images.order_by("sort_order", "id"))
    content_with_images, used_ids = inject_images_into_html(
        post.content_html, images
    )
    remaining_images = [img for img in images if img.id not in used_ids]

    # Build BlogPosting JSON-LD schema
    blogposting_schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": post.excerpt,
        "url": canonical,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical,
        },
        "datePublished": post.published_at.isoformat() if post.published_at else None,
        "dateModified": post.updated_at.isoformat(),
        "author": {
            "@type": "Organization",
            "@id": "https://carfst.ru/#organization",
            "name": "CARFAST",
        },
        "publisher": {
            "@type": "Organization",
            "@id": "https://carfst.ru/#organization",
            "name": "CARFAST",
        },
    }
    if og_image:
        blogposting_schema["image"] = request.build_absolute_uri(og_image)
    
    # Build breadcrumb schema
    from django.urls import reverse
    breadcrumb_items = [
        {"name": "Главная", "url": reverse("catalog:home")},
        {"name": "Блог", "url": "/blog/"},
        {"name": post.title, "url": post.get_absolute_url()},
    ]
    breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
    
    # JSON-LD schema only on clean URLs (no GET params) - SEO invariant
    if not request.GET:
        schema_items = [blogposting_schema, breadcrumb_schema]
        page_schema_payload = json.dumps(schema_items, ensure_ascii=False)[1:-1].strip()
    else:
        page_schema_payload = ""

    # Truncate meta description to 155 chars
    from catalog.templatetags.catalog_format import truncate_meta_description
    meta_description = truncate_meta_description(post.excerpt, 155)

    context = {
        "post": post,
        "meta_title": f"{post.title} — CARFAST",
        "meta_description": meta_description,
        "canonical": canonical,
        "meta_robots": meta_robots,
        "og_title": post.title,
        "og_description": meta_description,
        "og_url": canonical,
        "og_type": "article",
        "og_image": og_image,
        "reading_time": _reading_time_minutes(post.content_html),
        "content_with_images": content_with_images,
        "remaining_images": remaining_images,
        "page_schema_payload": page_schema_payload,
        "hub_links": hub_links,
    }
    return render(request, "blog/blog_detail.html", context)
