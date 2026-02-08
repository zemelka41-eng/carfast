#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$ROOT_DIR/static/img/leasing/_src"
OUT_DIR="$ROOT_DIR/static/img/leasing"

if command -v magick >/dev/null 2>&1; then
  IM_CMD="magick"
elif command -v convert >/dev/null 2>&1; then
  IM_CMD="convert"
else
  echo "ImageMagick not found (magick/convert). Install it first." >&2
  exit 1
fi

if [ ! -d "$SRC_DIR" ]; then
  echo "Source directory not found: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

declare -A FILES=(
  ["sberleasing"]="СберЛизинг.jfif"
  ["rshb-leasing"]="Россельхозбанк Лизинг.png"
  ["reso-leasing"]="РЕСО-Лизинг.png"
  ["interleasing"]="ИнтерЛизинг.png"
  ["carcade"]="Каркаде Лизинг.png"
  ["europlan"]="Европлан Лизинг.png"
  ["gpb-autoleasing"]="Газпромбанк Автолизинг.jfif"
  ["baltic-leasing"]="Балтийский Лизинг.png"
  ["realist"]="Реалист Лизинг.png"
  ["alfa-leasing"]="Альфа Лизинг.png"
  ["fleet-leasing"]="Флит Лизинг.png"
  ["evolyutsiya-leasing"]="Эволюция Лизинг.png"
  ["alliance-leasing"]="Альянс Лизинг.jfif"
  ["rosbank-leasing"]="Росбанк Лизинг.png"
  ["vtb-leasing"]="ВТБ Лизинг.png"
  ["baikalinvest-leasing"]="БайкалИнвест Лизинг.png"
  ["psb-leasing"]="ПСБ Лизинг.jfif"
  ["asia-leasing"]="Азия Лизинг.jfif"
  ["sovcombank-leasing"]="Совкомбанк Лизинг.png"
  ["rodelen"]="Роделен Лизинг.png"
  ["element-leasing"]="Элемент Лизинг.jfif"
)

for key in "${!FILES[@]}"; do
  src="$SRC_DIR/${FILES[$key]}"
  if [ ! -f "$src" ]; then
    echo "Missing source file: $src" >&2
    exit 1
  fi

  out_png="$OUT_DIR/${key}.png"
  out_webp="$OUT_DIR/${key}.webp"

  "$IM_CMD" "$src" \
    -auto-orient \
    -strip \
    -fuzz 3% -trim +repage \
    -resize 272x80\> \
    -background none -gravity center -extent 320x128 \
    "$out_png"

  "$IM_CMD" "$out_png" -quality 84 "$out_webp"
  echo "Generated: $out_png, $out_webp"
done
