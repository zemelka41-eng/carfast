#!/usr/bin/env python3
"""
Build static/img/hero/shacman_mein.v3.webp from a source image (cache-busting v3).
Accepts any format Pillow can open (WebP, JPEG, PNG, etc.).
Does not overwrite v3 if source looks like a dark placeholder (unless --force).

Usage:
  python scripts/build_hero_v2.py [path_to_source_image]
  python scripts/build_hero_v2.py --force [path_to_source_image]

If path not given, uses static/img/hero/shacman_mein.webp.

Placeholder check (skipped with --force):
  - Opens image and computes mean brightness (luma) and histogram entropy.
  - If (brightness very low AND entropy very low) -> abort "looks like placeholder".
  - Prevents using a tiny dark stub image; real optimized photos pass.

Output: max 2400px on long side, WebP quality 85, prints source/output paths and sizes.
"""
import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERO_DIR = ROOT / "static" / "img" / "hero"
SOURCE_DEFAULT = HERO_DIR / "shacman_mein.webp"
V3 = HERO_DIR / "shacman_mein.v3.webp"
MAX_SIZE = 2400
WEBP_QUALITY = 85
# Placeholder heuristic: reject if image is very dark and has very low color variety
BRIGHTNESS_THRESHOLD = 28   # mean luma (0–255); below = likely dark placeholder
ENTROPY_THRESHOLD = 3.8    # bits; below = very few distinct intensities


def mean_luma_entropy(pixels_flat):
    """
    Compute mean luma (0–255) and histogram entropy (bits) from RGB pixel data.
    pixels_flat: sequence of (R,G,B) from PIL Image.getdata().
    """
    n = len(pixels_flat)
    if n == 0:
        return 0.0, 0.0
    total = 0.0
    hist = [0] * 256
    for p in pixels_flat:
        if hasattr(p, "__len__") and len(p) >= 3:
            r, g, b = p[0], p[1], p[2]
        else:
            r = g = b = p
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        v = int(round(min(255, max(0, luma))))
        hist[v] += 1
        total += v
    mean_luma = total / n
    entropy = 0.0
    for c in hist:
        if c > 0:
            p = c / n
            entropy -= p * math.log2(p)
    return mean_luma, entropy


def looks_like_placeholder(img) -> bool:
    """True if image appears to be a dark placeholder (low brightness and low entropy)."""
    try:
        rgb = img.convert("RGB")
    except Exception:
        return True
    w, h = rgb.size
    pixels = list(rgb.getdata())
    mean_luma, entropy = mean_luma_entropy(pixels)
    if mean_luma < BRIGHTNESS_THRESHOLD and entropy < ENTROPY_THRESHOLD:
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Build hero v2 WebP from source image; optional placeholder check."
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to source image (default: static/img/hero/shacman_mein.webp)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip placeholder check and build v2 anyway",
    )
    args = parser.parse_args()

    source = Path(args.source).resolve() if args.source else SOURCE_DEFAULT
    if not source.is_absolute():
        source = ROOT / source

    if not source.exists():
        print(
            "Upload real photo to static/img/hero/shacman_mein.webp or pass path as argument.",
            file=sys.stderr,
        )
        print("Example: python scripts/build_hero_v2.py /path/to/shacman_mein.webp", file=sys.stderr)
        sys.exit(1)

    size_bytes = source.stat().st_size
    HERO_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
    except ImportError:
        print("PIL/Pillow required: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    try:
        img = Image.open(source).convert("RGB")
    except Exception as e:
        print(f"Failed to open image: {e}", file=sys.stderr)
        sys.exit(1)

    w, h = img.size
    print(f"Source: {source} ({size_bytes} bytes, {w}x{h})")

    if not args.force and looks_like_placeholder(img):
        print(
            "Image looks like a dark placeholder (low brightness and low entropy). "
            "Use a real photo or run with --force to override.",
            file=sys.stderr,
        )
        sys.exit(1)

    if max(w, h) > MAX_SIZE:
        if w >= h:
            new_w, new_h = MAX_SIZE, int(h * MAX_SIZE / w)
        else:
            new_w, new_h = int(w * MAX_SIZE / h), MAX_SIZE
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        w, h = new_w, new_h

    img.save(V3, "WEBP", quality=WEBP_QUALITY)
    out_size = V3.stat().st_size
    print(f"Saved {V3} ({out_size} bytes, {w}x{h})")


if __name__ == "__main__":
    main()
