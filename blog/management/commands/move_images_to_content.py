"""
Management command to move images from gallery to specific places in blog post content.
Idempotent: safe to run multiple times (won't duplicate images).
"""
import os
import re
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.html import escape

from blog.models import BlogPost, BlogPostImage


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, replace typographic quotes, ×→x, collapse whitespace."""
    if not text:
        return ""
    
    # Replace typographic quotes with regular quotes
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace('«', '"').replace('»', '"')
    text = text.replace('„', '"').replace('"', '"')
    text = text.replace('‚', "'").replace('\u2019', "'")  # Right single quotation mark
    # Replace multiplication sign with x
    text = text.replace('×', 'x').replace('×', 'x')
    text = text.replace('✕', 'x').replace('✖', 'x')
    # Replace &nbsp; and other HTML entities with space
    text = text.replace('&nbsp;', ' ')
    text = text.replace('\xa0', ' ')  # Non-breaking space
    text = text.replace('\u2009', ' ')  # Thin space
    text = text.replace('\u202f', ' ')  # Narrow no-break space
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    # Lowercase
    text = text.lower()
    return text.strip()


def _extract_text_from_html(html: str) -> str:
    """Extract text content from HTML, removing tags."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html)
    # Decode HTML entities (basic ones)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    return text


def _find_html_block(
    content_html: str,
    tag_pattern: str,
    text_keywords: list[str],
    diagnostic_keywords: list[str] = None,
) -> int | None:
    """
    Find HTML block (heading/paragraph) containing normalized text keywords.
    
    Returns position after closing tag, or None if not found.
    Handles nested tags by counting opening/closing tags.
    """
    if diagnostic_keywords is None:
        diagnostic_keywords = text_keywords
    
    # Pattern to match opening tag (e.g., h2, h3, h4, p)
    opening_pattern = re.compile(
        rf'<({tag_pattern})[^>]*>',
        re.IGNORECASE,
    )
    
    # Find all opening tags
    pos = 0
    while pos < len(content_html):
        opening_match = opening_pattern.search(content_html, pos)
        if not opening_match:
            break
        
        tag_name = opening_match.group(1).lower()
        content_start = opening_match.end()
        
        # Find matching closing tag, handling nested tags of the same type
        tag_count = 1
        search_pos = content_start
        
        while tag_count > 0 and search_pos < len(content_html):
            # Look for opening tag of same type
            next_open_match = re.search(
                rf'<{re.escape(tag_name)}[^>]*>',
                content_html[search_pos:],
                re.IGNORECASE,
            )
            # Look for closing tag
            next_close_match = re.search(
                rf'</{re.escape(tag_name)}>',
                content_html[search_pos:],
                re.IGNORECASE,
            )
            
            if next_open_match and next_close_match:
                if next_open_match.start() < next_close_match.start():
                    # Found nested opening tag
                    tag_count += 1
                    search_pos += next_open_match.end()
                else:
                    # Found closing tag
                    tag_count -= 1
                    if tag_count == 0:
                        # This is our matching closing tag
                        tag_end = search_pos + next_close_match.end()
                        # Extract inner content (before closing tag)
                        inner_content = content_html[content_start:search_pos + next_close_match.start()]
                        
                        # Normalize the inner content
                        normalized_inner = _normalize_text(_extract_text_from_html(inner_content))
                        
                        # Check if all keywords are present
                        if all(keyword.lower() in normalized_inner for keyword in text_keywords):
                            # Return position after closing tag
                            return tag_end
                        break
                    search_pos += next_close_match.end()
            elif next_close_match:
                # Only closing tag found
                tag_count -= 1
                if tag_count == 0:
                    tag_end = search_pos + next_close_match.end()
                    inner_content = content_html[content_start:search_pos + next_close_match.start()]
                    normalized_inner = _normalize_text(_extract_text_from_html(inner_content))
                    if all(keyword.lower() in normalized_inner for keyword in text_keywords):
                        return tag_end
                    break
                search_pos += next_close_match.end()
            else:
                # No more tags found, break
                break
        
        # Move to next position
        pos = content_start
    
    return None


def _get_diagnostic_info(content_html: str, keywords: list[str], max_results: int = 5) -> str:
    """Get diagnostic info: similar headings/paragraphs found."""
    info = []
    
    # Find all headings
    heading_pattern = re.compile(r'<h([2-4])[^>]*>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)
    headings = []
    for match in heading_pattern.finditer(content_html):
        text = _extract_text_from_html(match.group(2))
        normalized = _normalize_text(text)
        headings.append((normalized, text[:100], match.start()))
    
    # Find all paragraphs
    para_pattern = re.compile(r'<p[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL)
    paragraphs = []
    for match in para_pattern.finditer(content_html):
        text = _extract_text_from_html(match.group(1))
        normalized = _normalize_text(text)
        paragraphs.append((normalized, text[:100], match.start()))
    
    # Find similar blocks
    keyword_str = ' '.join(k.lower() for k in keywords)
    similar = []
    
    for normalized, text_preview, pos in headings + paragraphs:
        if any(kw.lower() in normalized for kw in keywords):
            similar.append((text_preview, pos))
    
    if similar:
        info.append(f"\nFound {len(similar)} similar blocks (showing first {max_results}):")
        for text_preview, pos in similar[:max_results]:
            # Get context around the match
            start = max(0, pos - 100)
            end = min(len(content_html), pos + 200)
            context = content_html[start:end]
            # Clean context for display
            context = re.sub(r'\s+', ' ', context)
            info.append(f"  At position {pos}: {text_preview[:80]}...")
            info.append(f"    Context: ...{context[:150]}...")
    
    # Find nearest match by keyword
    if keywords:
        keyword = keywords[0].lower()
        best_match = None
        best_pos = None
        min_distance = float('inf')
        
        for normalized, text_preview, pos in headings + paragraphs:
            if keyword in normalized:
                # Simple distance metric (could be improved)
                distance = abs(len(normalized) - len(keyword))
                if distance < min_distance:
                    min_distance = distance
                    best_match = text_preview
                    best_pos = pos
        
        if best_match:
            start = max(0, best_pos - 200)
            end = min(len(content_html), best_pos + 200)
            context = content_html[start:end]
            context = re.sub(r'\s+', ' ', context)
            info.append(f"\nNearest match (position {best_pos}):")
            info.append(f"  Text: {best_match[:100]}")
            info.append(f"  Context (±200 chars): ...{context}...")
    
    return '\n'.join(info) if info else "\nNo similar blocks found."


def _check_image_already_inserted(content_html: str, image_url: str, basename: str) -> bool:
    """Check if image URL or basename already exists in content_html."""
    # Check for data-blog-inline-image attribute with this image URL
    escaped_url = re.escape(image_url)
    figure_pattern = re.compile(
        rf'<figure[^>]*data-blog-inline-image="1"[^>]*>.*?<img[^>]*src=["\']?{escaped_url}',
        re.IGNORECASE | re.DOTALL,
    )
    if figure_pattern.search(content_html):
        return True
    
    # Check if basename (e.g., x3000-8x4-komplektaciya_2.png) appears in content_html
    escaped_basename = re.escape(basename)
    if re.search(escaped_basename, content_html, re.IGNORECASE):
        return True
    
    # Fallback: check if URL exists anywhere
    return bool(re.search(escaped_url, content_html))


def _build_figure_html(image_url: str, alt_text: str, caption_text: str) -> str:
    """Build figure HTML element."""
    parts = [
        '<figure class="blog-inline-image" data-blog-inline-image="1">',
        f'    <img src="{escape(image_url)}" alt="{escape(alt_text)}" loading="lazy" decoding="async" class="img-fluid rounded">',
        f'    <figcaption>{escape(caption_text)}</figcaption>',
        '</figure>',
    ]
    return '\n'.join(parts)


class Command(BaseCommand):
    help = "Move images from gallery to specific places in blog post content HTML. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "slug",
            type=str,
            help="Blog post slug",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without saving.",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        dry_run = options.get("dry_run", False)

        try:
            post = BlogPost.objects.select_for_update().get(slug=slug)
        except BlogPost.DoesNotExist:
            raise CommandError(f"Blog post with slug '{slug}' not found")

        # Build list of base names to search for
        # slug: shacman-x3000-8x4-komplektaciya
        # base without prefix: x3000-8x4-komplektaciya (if slug starts with something-)
        base_names = [slug]
        if '-' in slug:
            # Try without first prefix (e.g., shacman-x3000-8x4-komplektaciya -> x3000-8x4-komplektaciya)
            parts = slug.split('-', 1)
            if len(parts) > 1:
                base_names.append(parts[1])
        
        # Idempotency: if content already has markers for 2/3/4, consider post migrated
        content_html = post.content_html

        def _content_has_all_three_markers(html: str) -> bool:
            return html.count('class="blog-inline-image"') >= 3

        if _content_has_all_three_markers(content_html):
            # Delete any gallery images matching _2/_3/_4 as duplicates (re-added)
            to_remove = []
            for img in post.images.all():
                if not img.image.name:
                    continue
                basename = os.path.basename(img.image.name)
                for base in base_names:
                    if re.match(rf"^{re.escape(base)}_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$", basename, re.IGNORECASE):
                        to_remove.append(img)
                        break
            if to_remove and not dry_run:
                with transaction.atomic():
                    for img in to_remove:
                        img.delete()
                        self.stdout.write(f"✓ Removed duplicate from gallery: {img.image.name}")
            self.stdout.write(
                self.style.SUCCESS("Post already migrated (markers present). Nothing to insert.")
            )
            return

        # Find images matching pattern: {base}_{n}.(png|jpg|jpeg|webp) or {base}_{n}_<any>.(png|jpg|jpeg|webp)
        images_to_move = {}
        all_gallery_basenames = []
        candidates_by_num = {2: [], 3: [], 4: []}

        for img in post.images.all():
            if not img.image.name:
                continue
            
            basename = os.path.basename(img.image.name)
            all_gallery_basenames.append(basename)
            
            # Try each base name
            for base in base_names:
                # Pattern: {base}_{n}.(png|jpg|jpeg|webp) or {base}_{n}_<any>.(png|jpg|jpeg|webp)
                pattern = re.compile(
                    rf'^{re.escape(base)}_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$',
                    re.IGNORECASE,
                )
                match = pattern.match(basename)
                if match:
                    image_num = int(match.group(1))
                    if image_num in [2, 3, 4]:
                        candidates_by_num[image_num].append((basename, img))
                        break
        
        # Check for duplicates and build final mapping
        for num in [2, 3, 4]:
            if len(candidates_by_num[num]) == 0:
                continue
            elif len(candidates_by_num[num]) == 1:
                images_to_move[num] = candidates_by_num[num][0][1]
                self.stdout.write(f"Found image {num}: {candidates_by_num[num][0][0]}")
            else:
                # Multiple candidates - error
                candidate_names = [c[0] for c in candidates_by_num[num]]
                raise CommandError(
                    f"Found {len(candidates_by_num[num])} candidates for image {num}:\n"
                    + "\n".join(f"  - {name}" for name in candidate_names)
                    + f"\n\nExpected exactly one image matching pattern: {{base}}_{num}.(png|jpg|jpeg|webp)"
                )

        if len(images_to_move) != 3:
            found = list(images_to_move.keys())
            missing = [i for i in [2, 3, 4] if i not in found]
            
            error_msg = (
                f"Expected 3 images matching pattern 'any_prefix_{{2|3|4}}(_*)?.(png|jpg|jpeg|webp)', "
                f"found {len(images_to_move)}: {found}. Missing: {missing}.\n\n"
            )
            
            if all_gallery_basenames:
                error_msg += "Images found in gallery:\n"
                for basename in sorted(all_gallery_basenames):
                    error_msg += f"  - {basename}\n"
                error_msg += "\nExpected pattern: any prefix + _{2|3|4} + optional suffix + extension\n"
                error_msg += "Pattern examples:\n"
                error_msg += "  - x3000-8x4-komplektaciya_2.png\n"
                error_msg += "  - anything_2_720.webp\n"
                error_msg += "  - prefix_3.jpg\n"
                error_msg += "  - name_4.jpeg\n"
            else:
                error_msg += "No images found in gallery for this post."
            
            raise CommandError(error_msg)

        image_urls = {}
        image_htmls = {}
        already_inserted = {}

        # Prepare image HTML for each image and check idempotency
        for num, img in images_to_move.items():
            image_url = img.image.url
            image_urls[num] = image_url
            basename = os.path.basename(img.image.name)

            # Check if already inserted (idempotency)
            if _check_image_already_inserted(content_html, image_url, basename):
                already_inserted[num] = True
                self.stdout.write(
                    self.style.WARNING(
                        f"Image {num} already in content_html (idempotency check). Skipping insertion."
                    )
                )
                continue

            # Build figure HTML
            alt_text = {
                2: "Самосвал SHACMAN X3000 8×4 в условиях стройплощадки и карьера",
                3: "ТЗ на самосвал 8×4 — 5 параметров: площадка, плечо, груз, режим, сезонность",
                4: "Чек-лист приёмки нового самосвала: спецификация, кузов/подъём, осмотр, комплектность, документы",
            }.get(num, img.alt or post.title)

            caption_text = {
                2: "X3000 8×4: типовые условия — стройка и карьер",
                3: "ТЗ на самосвал 8×4: что уточнить до подбора комплектации",
                4: "Чек-лист приёмки перед выдачей",
            }.get(num, "")

            figure_html = _build_figure_html(image_url, alt_text, caption_text)
            image_htmls[num] = figure_html

        # If all images already inserted, nothing to do
        if len(already_inserted) == 3:
            self.stdout.write(
                self.style.SUCCESS(
                    "All images already in content_html. Nothing to do (idempotent)."
                )
            )
            return

        # Insert image 2: before "Типовые сценарии" (handles typographic quotes)
        if 2 not in already_inserted:
            # Find position of "Типовые сценарии" - allow attributes, typographic quotes
            # Pattern: (optional opening tag) + "Типовые сценарии" + (any quotes) + "стройка"
            pattern = re.compile(
                r'(?:<h[2-4][^>]*>\s*)?Типовые\s+сценарии[^<]*[""«»„"][^<]*стройка',
                re.IGNORECASE | re.DOTALL,
            )
            match = pattern.search(content_html)
            
            if match:
                insert_pos = match.start()
                content_html = (
                    content_html[:insert_pos]
                    + "\n"
                    + image_htmls[2]
                    + "\n"
                    + content_html[insert_pos:]
                )
                self.stdout.write("✓ Image 2 inserted before 'Типовые сценарии'")
            else:
                # Fallback: just "Типовые сценарии"
                pattern_fallback = re.compile(
                    r'(?:<h[2-4][^>]*>\s*)?Типовые\s+сценарии',
                    re.IGNORECASE,
                )
                match_fallback = pattern_fallback.search(content_html)
                if match_fallback:
                    insert_pos = match_fallback.start()
                    content_html = (
                        content_html[:insert_pos]
                        + "\n"
                        + image_htmls[2]
                        + "\n"
                        + content_html[insert_pos:]
                    )
                    self.stdout.write("✓ Image 2 inserted before 'Типовые сценарии' (fallback)")
                else:
                    diagnostic = _get_diagnostic_info(
                        content_html,
                        ['типовые сценарии', 'стройка'],
                    )
                    raise CommandError(
                        "Could not find insertion point for image 2.\n"
                        "Looking for 'Типовые сценарии ... стройка'"
                        + diagnostic
                    )

        # Insert image 3: before "1) Площадка" (or after paragraph with "5 параметров")
        if 3 not in already_inserted:
            # First try to find "1) Площадка"
            pattern = re.compile(
                r'1\)\s*Площадка',
                re.IGNORECASE,
            )
            match = pattern.search(content_html)
            
            if match:
                insert_pos = match.start()
                content_html = (
                    content_html[:insert_pos]
                    + "\n"
                    + image_htmls[3]
                    + "\n"
                    + content_html[insert_pos:]
                )
                self.stdout.write("✓ Image 3 inserted before '1) Площадка'")
            else:
                # Fallback: find paragraph with "5 параметров" and insert after it
                para_pattern = re.compile(
                    r'<p[^>]*>.*?5\s+параметров.*?</p>',
                    re.IGNORECASE | re.DOTALL,
                )
                para_match = para_pattern.search(content_html)
                
                if para_match:
                    insert_pos = para_match.end()
                    content_html = (
                        content_html[:insert_pos]
                        + "\n"
                        + image_htmls[3]
                        + "\n"
                        + content_html[insert_pos:]
                    )
                    self.stdout.write("✓ Image 3 inserted after '5 параметров' paragraph")
                else:
                    diagnostic = _get_diagnostic_info(
                        content_html,
                        ['5 параметров', '1)', 'площадка'],
                    )
                    raise CommandError(
                        "Could not find insertion point for image 3.\n"
                        "Looking for '1) Площадка' or paragraph with '5 параметров'"
                        + diagnostic
                    )

        # Insert image 4: before "Чек-лист приёмки" (handles е/ё variation)
        if 4 not in already_inserted:
            # Pattern: "Чек-лист при[её]мки" - handles е/ё variation
            pattern = re.compile(
                r'Чек-лист\s+при[её]мки',
                re.IGNORECASE,
            )
            match = pattern.search(content_html)
            
            if match:
                insert_pos = match.start()
                content_html = (
                    content_html[:insert_pos]
                    + "\n"
                    + image_htmls[4]
                    + "\n"
                    + content_html[insert_pos:]
                )
                self.stdout.write("✓ Image 4 inserted before 'Чек-лист приёмки'")
            else:
                diagnostic = _get_diagnostic_info(
                    content_html,
                    ['чек-лист', 'приёмки', 'приемки'],
                )
                raise CommandError(
                    "Could not find insertion point for image 4.\n"
                    "Looking for 'Чек-лист приёмки' or 'Чек-лист приемки'"
                    + diagnostic
                )

        if dry_run:
            self.stdout.write("\n[DRY RUN] Would update content_html and delete images:")
            for num in [2, 3, 4]:
                if num not in already_inserted:
                    self.stdout.write(f"  Image {num}: {image_urls[num]}")
            if already_inserted:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Already in content (skipped): {list(already_inserted.keys())}"
                    )
                )
            return

        # Apply changes in transaction
        with transaction.atomic():
            # Save updated content
            post.content_html = content_html
            post.save(update_fields=["content_html", "updated_at"])

            # Delete images from gallery (only those that were inserted)
            deleted_count = 0
            for num, img in images_to_move.items():
                if num not in already_inserted:
                    img.delete()
                    deleted_count += 1
                    self.stdout.write(f"✓ Deleted image {num} from gallery: {img.image.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully moved {len(image_htmls)} images to content "
                f"and removed {deleted_count} from gallery for post '{slug}'"
            )
        )
