"""
Find and optionally remove orphaned media files.

Referenced files: Category.cover_image, Series.logo, ProductImage.image,
BlogPost.cover_image, BlogPostImage.image (when blog app is installed).
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Category, ProductImage, Series


def get_referenced_media_paths():
    """Collect all file paths stored in DB (ImageField/FileField) under MEDIA_ROOT."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    referenced = set()

    # Catalog: Category.cover_image, Series.logo, ProductImage.image
    for rel_path in Category.objects.values_list("cover_image", flat=True):
        if rel_path:
            referenced.add((media_root / rel_path).resolve())
    for rel_path in Series.objects.values_list("logo", flat=True):
        if rel_path:
            referenced.add((media_root / rel_path).resolve())
    for rel_path in ProductImage.objects.values_list("image", flat=True):
        if rel_path:
            referenced.add((media_root / rel_path).resolve())

    # Blog (optional)
    try:
        from blog.models import BlogPost, BlogPostImage

        for rel_path in BlogPost.objects.values_list("cover_image", flat=True):
            if rel_path:
                referenced.add((media_root / rel_path).resolve())
        for rel_path in BlogPostImage.objects.values_list("image", flat=True):
            if rel_path:
                referenced.add((media_root / rel_path).resolve())
    except ImportError:
        pass

    return referenced, media_root


def scan_media_files(media_root: Path, path_prefix: str | None) -> set[Path]:
    """List all files under media_root (optionally under path_prefix)."""
    if path_prefix:
        prefix = path_prefix.strip("/").replace("media/", "")  # allow "media/products"
        scan_dir = media_root / prefix if prefix else media_root
    else:
        scan_dir = media_root
    if not scan_dir.exists() or not scan_dir.is_dir():
        return set()
    files = set()
    for path in scan_dir.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            files.add(path.resolve())
    return files


def is_safe_under_media(path: Path, media_root: Path) -> bool:
    """Ensure path is normalized and strictly under media_root (no traversal)."""
    try:
        resolved = path.resolve()
        root_str = str(media_root)
        path_str = str(resolved)
        return path_str == root_str or path_str.startswith(root_str + os.sep)
    except (ValueError, OSError):
        return False


class Command(BaseCommand):
    help = (
        "Report and optionally delete orphaned media files. "
        "Referenced = Category/Series/ProductImage (and Blog if installed)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Only report, do not delete (default).",
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            dest="delete",
            help="Delete unreferenced files (only within MEDIA_ROOT).",
        )
        parser.add_argument(
            "--path-prefix",
            type=str,
            default=None,
            metavar="PREFIX",
            help="Limit scan to MEDIA_ROOT/PREFIX (e.g. 'products' or 'media/products').",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            metavar="N",
            help="Max number of paths to print per list (default 50). Counts always full.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", True)
        do_delete = options.get("delete", False)
        if do_delete:
            dry_run = False
        path_prefix = options.get("path_prefix")
        limit = max(0, options.get("limit", 50))

        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not media_root.exists():
            self.stderr.write(self.style.ERROR(f"MEDIA_ROOT does not exist: {media_root}"))
            return

        referenced, _ = get_referenced_media_paths()
        on_disk = scan_media_files(media_root, path_prefix)

        missing_files = sorted(str(p) for p in referenced if not p.exists())
        unreferenced_paths = sorted(on_disk - referenced)
        unreferenced_files = [str(p) for p in unreferenced_paths]

        # Report
        self.stdout.write("Orphaned media report")
        self.stdout.write(f"  Referenced in DB (count): {len(referenced)}")
        self.stdout.write(f"  Missing on disk (count): {len(missing_files)}")
        self.stdout.write(f"  Unreferenced on disk (count): {len(unreferenced_files)}")

        if missing_files:
            self.stdout.write(self.style.WARNING("\nMissing files (DB points to missing path):"))
            for p in missing_files[:limit]:
                self.stdout.write(f"  {p}")
            if len(missing_files) > limit:
                self.stdout.write(f"  ... and {len(missing_files) - limit} more")

        if unreferenced_files:
            self.stdout.write(self.style.WARNING("\nUnreferenced files (on disk, not in DB):"))
            for p in unreferenced_files[:limit]:
                self.stdout.write(f"  {p}")
            if len(unreferenced_files) > limit:
                self.stdout.write(f"  ... and {len(unreferenced_files) - limit} more")

        if do_delete and unreferenced_files:
            self.stdout.write("\n--delete: removing unreferenced files (inside MEDIA_ROOT only).")
            deleted = 0
            for path in unreferenced_paths:
                if not is_safe_under_media(path, media_root):
                    self.stderr.write(self.style.ERROR(f"Skip (unsafe path): {path}"))
                    continue
                try:
                    path.unlink()
                    deleted += 1
                    self.stdout.write(f"  Deleted: {path}")
                except OSError as e:
                    self.stderr.write(self.style.ERROR(f"  Failed to delete {path}: {e}"))
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} file(s)."))
        elif dry_run and (missing_files or unreferenced_files):
            self.stdout.write("\nDry run. Use --delete to remove unreferenced files.")
