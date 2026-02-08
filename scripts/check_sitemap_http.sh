#!/usr/bin/env bash
# Download sitemap(s), iterate <loc> URLs, verify 200 (or 3xx) and report 404/non-2xx.
# Usage: ./scripts/check_sitemap_http.sh [base_url] [limit]
# Default base_url: https://carfst.ru
# limit: max URLs to check (default: no limit). Use e.g. 50 for a quick check.

set -euo pipefail

BASE_URL="${1:-https://carfst.ru}"
LIMIT="${2:-}"

SITEMAP_XML="$(curl -fsSL "${BASE_URL%/}/sitemap.xml" 2>/dev/null || true)"
if [ -z "$SITEMAP_XML" ]; then
    echo "ERROR: Could not fetch ${BASE_URL}/sitemap.xml" >&2
    exit 1
fi

# If sitemap is an index, fetch sub-sitemaps
if echo "$SITEMAP_XML" | grep -q '<sitemapindex'; then
    SUB_LOCS=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
    ALL_XML="$SITEMAP_XML"
    for sub_url in $SUB_LOCS; do
        ALL_XML="$ALL_XML
$(curl -fsSL "$sub_url" 2>/dev/null || true)"
    done
    SITEMAP_XML="$ALL_XML"
fi

URLS=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
if [ -n "${LIMIT:-}" ] && [ "$LIMIT" -gt 0 ] 2>/dev/null; then
    URLS=$(echo "$URLS" | head -n "$LIMIT")
fi

FAILED=""
OK=0
TOTAL=0
while IFS= read -r url; do
    [ -z "$url" ] && continue
    TOTAL=$((TOTAL + 1))
    code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
    if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
        OK=$((OK + 1))
    else
        FAILED="${FAILED}${url} (${code})
"
    fi
done <<< "$URLS"

echo "Checked $TOTAL URLs: $OK OK (200/3xx)."
if [ -n "$FAILED" ]; then
    echo "Failed or non-200/3xx:"
    echo "$FAILED"
    exit 1
fi
exit 0
