from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
src = root / 'static' / 'img' / 'carfast-logo-source.jpg'
if not src.exists():
    raise SystemExit(f'Source not found: {src}')

img = Image.open(src).convert('RGBA')

for size, name in [(64, 'logo-h64.webp'), (128, 'logo-h128.webp')]:
    out = root / 'static' / 'img' / name
    resized = img.copy()
    resized.thumbnail((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    resized.save(out, format='WEBP', quality=95)
    print(f'Saved {out} ({size}x{size})')
