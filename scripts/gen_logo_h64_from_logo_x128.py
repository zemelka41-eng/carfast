from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
src = root / 'static' / 'img' / 'logo_x128.webp'
print('SRC', src, src.exists())
img = Image.open(src).convert('RGBA')

out = root / 'static' / 'img' / 'logo-h64.webp'
resized = img.copy().resize((64, 64), Image.LANCZOS)
out.parent.mkdir(parents=True, exist_ok=True)
resized.save(out, format='WEBP', quality=95)
print('Saved', out)
