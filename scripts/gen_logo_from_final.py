from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
src = root / 'static' / 'img' / 'carfast-logo-final-128.webp'
print('SRC', src, src.exists())
img = Image.open(src).convert('RGBA')

for size, name in [(64, 'logo-h64.webp'), (128, 'logo-h128.webp')]:
    out = root / 'static' / 'img' / name
    resized = img.copy().resize((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    resized.save(out, format='WEBP', quality=95)
    print('Saved', out, 'size', size)
