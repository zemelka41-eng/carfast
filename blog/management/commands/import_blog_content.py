import html
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from blog.models import BlogPost

try:
    import docx
except ImportError as exc:  # pragma: no cover - guarded by requirements
    raise CommandError("python-docx is required to import .docx content") from exc


_RU_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _transliterate_ru(text: str) -> str:
    out: list[str] = []
    for ch in str(text):
        lower = ch.lower()
        if lower in _RU_TRANSLIT:
            out.append(_RU_TRANSLIT[lower])
        else:
            out.append(ch)
    return "".join(out)


def _slugify_any(text: str) -> str:
    base = slugify(text)
    if base:
        return base
    return slugify(_transliterate_ru(text))


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if text.lower().startswith(prefix):
            return text[len(prefix) :].strip()
    return text.strip()


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if title.lower().startswith("carfast"):
        title = title[len("carfast") :].lstrip(" -—:")
    if len(title) > 80 and "диагностика пневмосистемы" in title.lower():
        prefix = title.split(":", 1)[0].strip()
        title = f"{prefix}: диагностика пневмосистемы"
    if len(title) <= 80:
        return title
    for sep in (" — ", " - ", ": "):
        if sep in title:
            candidate = title.split(sep)[0].strip()
            if 60 <= len(candidate) <= 80:
                return candidate
    if len(title) > 80:
        trimmed = title[:80].rsplit(" ", 1)[0].rstrip(" -—:")
        if trimmed:
            last_word = trimmed.split()[-1].lower()
            if last_word in {"на", "в", "по", "с", "к", "из", "от", "и", "но", "для", "без", "при", "о"}:
                trimmed = " ".join(trimmed.split()[:-1]).rstrip(" -—:")
        return trimmed if trimmed else title[:80]
    return title


def _inject_internal_links(content_html: str) -> str:
    if "/service/" in content_html and "/parts/" in content_html:
        return content_html
    link_text = (
        'Если нужен сервис, смотрите раздел <a href="/service/">Сервис</a>. '
        'Запчасти и расходники — в разделе <a href="/parts/">Запчасти</a>.'
    )
    link_block = f"<p>{link_text}</p>"
    if "</p>" in content_html:
        return content_html.replace("</p>", "</p>\n" + link_block, 1)
    return content_html + "\n" + link_block


def _parse_date(value: str):
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return timezone.make_aware(timezone.datetime.strptime(value, fmt))
        except ValueError:
            continue
    return None


def _flush_list(parts: list[str], list_items: list[str], list_tag: str | None):
    if not list_items or not list_tag:
        return
    items_html = "".join(f"<li>{item}</li>" for item in list_items)
    parts.append(f"<{list_tag}>{items_html}</{list_tag}>")
    list_items.clear()


def _paragraphs_to_html(paragraphs: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    for style, text in paragraphs:
        if not text:
            continue
        heading_match = re.match(r"^H[1-6][.:]\s*", text, flags=re.IGNORECASE)
        if heading_match:
            text = text[heading_match.end() :].strip()

        if style.startswith("List Bullet"):
            if list_tag not in (None, "ul"):
                _flush_list(parts, list_items, list_tag)
            list_tag = "ul"
            list_items.append(html.escape(text))
            continue
        if style.startswith("List Number"):
            if list_tag not in (None, "ol"):
                _flush_list(parts, list_items, list_tag)
            list_tag = "ol"
            list_items.append(html.escape(text))
            continue

        _flush_list(parts, list_items, list_tag)
        list_tag = None

        if style.startswith("Heading 1"):
            tag = "h2"
        elif style.startswith("Heading 2"):
            tag = "h2"
        elif style.startswith("Heading 3"):
            tag = "h3"
        else:
            tag = "p"
        parts.append(f"<{tag}>{html.escape(text)}</{tag}>")

    _flush_list(parts, list_items, list_tag)
    html_out = "\n".join(parts).strip()
    # Post-process: ensure at least one <h2> if content has multiple paragraphs (for quality)
    if "<h2>" not in html_out and "<p>" in html_out:
        html_out = _ensure_h2_in_content(html_out)
    return html_out


def _ensure_h2_in_content(content_html: str) -> str:
    """Ensure content has at least one <h2> by promoting first paragraph to h2 if missing."""
    if "<h2>" in content_html:
        return content_html
    # Replace first <p>...</p> with <h2>...</h2>
    first_p = re.search(r"<p[^>]*>(.*?)</p>", content_html, re.DOTALL | re.IGNORECASE)
    if first_p:
        return content_html[: first_p.start()] + "<h2>" + first_p.group(1) + "</h2>" + content_html[first_p.end() :]
    return content_html


def parse_docx_file(path: Path) -> dict:
    doc = docx.Document(str(path))
    paragraphs = [
        (p.style.name if p.style else "Normal", p.text.strip())
        for p in doc.paragraphs
        if p.text and p.text.strip()
    ]

    title = None
    description = None
    published_at = None
    explicit_slug = None
    body: list[tuple[str, str]] = []
    first_paragraph = None

    for style, text in paragraphs:
        normalized = text.strip()
        if explicit_slug is None and normalized.lower().startswith("slug:"):
            explicit_slug = _strip_prefix(normalized, ("slug:",))
            continue
        if title is None and (
            style.lower() == "title"
            or normalized.lower().startswith("title:")
            or normalized.lower().startswith("h1.")
            or normalized.lower().startswith("h1:")
        ):
            title = _strip_prefix(normalized, ("title:", "h1.", "h1:"))
            continue

        if description is None and (
            normalized.lower().startswith("description:")
            or normalized.lower().startswith("описание:")
        ):
            description = _strip_prefix(normalized, ("description:", "описание:"))
            continue

        if published_at is None and (
            normalized.lower().startswith("date:")
            or normalized.lower().startswith("дата:")
        ):
            published_at = _parse_date(_strip_prefix(normalized, ("date:", "дата:")))
            continue

        body.append((style, normalized))
        if first_paragraph is None and style.startswith("Normal"):
            first_paragraph = normalized

    if not title:
        for style, text in body:
            if style.startswith("Heading 1"):
                title = text
                body.remove((style, text))
                break
    if not title:
        raise CommandError(f"Title not found in {path.name}")
    title = _normalize_title(title)

    content_html = _paragraphs_to_html(body)
    if not content_html:
        raise CommandError(f"No content extracted from {path.name}")

    if not description:
        text = first_paragraph or strip_tags(content_html)
        text = re.sub(r"\s+", " ", text).strip()
        description = text[:240].rsplit(" ", 1)[0] if len(text) > 240 else text

    if description:
        description = re.sub(r"\s+", " ", description).strip()
        description = re.sub(r"^[^A-Za-zА-Яа-яЁё]+", "", description)
        match = re.search(r"вступление[:\s]+", description, flags=re.IGNORECASE)
        if match and match.start() <= 10:
            description = description[match.end() :].strip()
        if len(description) > 240:
            description = description[:240].rsplit(" ", 1)[0]
        if len(description) < 140:
            full_text = re.sub(r"\s+", " ", strip_tags(content_html)).strip()
            description = full_text[:240].rsplit(" ", 1)[0] if len(full_text) > 240 else full_text
        if description.lower().startswith("вступление "):
            description = description[len("вступление ") :].strip()

    content_html = _inject_internal_links(content_html)

    return {
        "title": title,
        "description": description,
        "content_html": content_html,
        "published_at": published_at,
        "explicit_slug": explicit_slug,
    }


def get_source_files(
    base_dir: Path | None = None, include_all: bool = False
) -> tuple[list[Path], list[Path]]:
    base_dir = base_dir or Path(getattr(settings, "BASE_DIR", Path.cwd()))
    content_dir = base_dir / "_content"
    if not content_dir.exists():
        raise CommandError(f"Content directory not found: {content_dir}")
    all_files = [f for f in content_dir.iterdir() if f.suffix.lower() == ".docx"]
    all_files = [
        f for f in all_files if f.name != "CARFAST_lizing_kredit_2026.docx"
    ]
    legacy_files = [
        f for f in all_files if not f.name.lower().startswith("carfst_")
    ]
    files = all_files if include_all else [f for f in all_files if f not in legacy_files]
    if not files:
        raise CommandError("No docx files found for import.")
    return sorted(files), sorted(legacy_files)


def _resolve_slug(title: str, check_db: bool = True) -> str:
    base = _slugify_any(title)
    if not base:
        raise CommandError("Unable to generate slug for title.")
    slug = base
    if check_db:
        index = 2
        while BlogPost.objects.filter(slug=slug).exclude(title=title).exists():
            slug = f"{base}-{index}"
            index += 1
    return slug


class Command(BaseCommand):
    help = "Import blog posts from _content/*.docx"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without writing to DB.",
        )
        parser.add_argument(
            "--files",
            nargs="*",
            help="Optional list of docx filenames from _content/ to import.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Import all .docx files (including legacy ones).",
        )

    def handle(self, *args, **options):
        base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        dry_run = options["dry_run"]
        file_names = options.get("files") or []
        include_all = options.get("all", False)

        if file_names:
            files = []
            for name in file_names:
                path = base_dir / "_content" / name
                if not path.exists():
                    raise CommandError(f"File not found: {path}")
                files.append(path)
        else:
            files, legacy_files = get_source_files(base_dir, include_all=include_all)

            if legacy_files and not include_all:
                for legacy in legacy_files:
                    self.stdout.write(f"Skipped (legacy): {legacy.name}")

        self.stdout.write(f"Found {len(files)} files to import.")

        for path in files:
            data = parse_docx_file(path)
            if data.get("explicit_slug"):
                slug = data["explicit_slug"]
            else:
                slug = _resolve_slug(data["title"], check_db=not dry_run)
            published_at = data["published_at"] or timezone.now()

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] {path.name} -> {slug} ({data['title']})"
                )
                continue

            post, created = BlogPost.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": data["title"],
                    "excerpt": data["description"],
                    "content_html": data["content_html"],
                    "is_published": True,
                    "published_at": published_at,
                },
            )

            if not created:
                updated_fields = []
                for field, value in {
                    "title": data["title"],
                    "excerpt": data["description"],
                    "content_html": data["content_html"],
                    "is_published": True,
                    "published_at": published_at,
                }.items():
                    if getattr(post, field) != value:
                        setattr(post, field, value)
                        updated_fields.append(field)
                if updated_fields:
                    post.save(update_fields=updated_fields + ["updated_at"])
                self.stdout.write(f"Updated {slug} ({path.name})")
            else:
                self.stdout.write(f"Created {slug} ({path.name})")
