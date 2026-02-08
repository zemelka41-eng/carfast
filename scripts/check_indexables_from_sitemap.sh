#!/usr/bin/env bash
# Check that all URLs from sitemap are indexable: HTTP 200, no noindex, canonical = self (or page).
# Usage: ./scripts/check_indexables_from_sitemap.sh [base_url]
# Default base_url: https://carfst.ru

set -euo pipefail

BASE_URL="${1:-https://carfst.ru}"
BASE_URL="${BASE_URL%/}"

SITEMAP_URL="${BASE_URL}/sitemap.xml"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

failed=0
checked=0
TMPFILE="/tmp/check_idx_$$.html"
trap 'rm -f "$TMPFILE"' EXIT

# Curl options: follow redirects, decompress gzip/br, fail silently on errors, timeouts
CURL_OPTS="-sSL --compressed --connect-timeout 10 --max-time 30"

# Fetch sitemap (may be index with sub-sitemaps)
body=$(curl $CURL_OPTS "${SITEMAP_URL}" 2>/dev/null || true)
if [ -z "$body" ]; then
  log_fail "Could not fetch ${SITEMAP_URL}"
  exit 1
fi

# If sitemap index, get first level of <loc> and fetch each; then collect all <loc> from sub-sitemaps
all_locs=""
if echo "$body" | grep -q '<sitemapindex'; then
  sub_urls=$(echo "$body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
  for sub in $sub_urls; do
    sub_body=$(curl $CURL_OPTS "$sub" 2>/dev/null || true)
    if [ -n "$sub_body" ]; then
      locs=$(echo "$sub_body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
      all_locs="${all_locs}${locs}"$'\n'
    fi
  done
else
  all_locs=$(echo "$body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
fi

# Normalize to one URL per line, strip empty
urls=$(echo "$all_locs" | grep -v '^$' | sort -u)

for url in $urls; do
  [ -z "$url" ] && continue
  checked=$((checked + 1))
  
  # Fetch page with full options: follow redirects, decompress, get final URL and HTTP code
  http_code=$(curl $CURL_OPTS -o "$TMPFILE" -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  effective_url=$(curl $CURL_OPTS -o /dev/null -w "%{url_effective}" "$url" 2>/dev/null || echo "$url")
  
  if [ "$http_code" != "200" ]; then
    log_fail "HTTP $http_code: $url (effective: $effective_url)"
    failed=$((failed + 1))
    continue
  fi
  
  # Read from file to avoid SIGPIPE (exit 141) when piping large HTML to head/grep
  # Skip non-HTML content (e.g., XML sitemaps that somehow got in)
  content_type_hint=$(head -c 500 "$TMPFILE" 2>/dev/null || true)
  if echo "$content_type_hint" | grep -qE '^\s*<\?xml|<urlset|<sitemapindex'; then
    log_warn "Skipping non-HTML content: $url"
    continue
  fi

  # Check noindex
  if grep -qi 'noindex' "$TMPFILE" 2>/dev/null; then
    log_fail "noindex present: $url"
    failed=$((failed + 1))
    continue
  fi

  # Check canonical (grep -m1 avoids pipe to head, prevents SIGPIPE)
  canonical=$(grep -m1 -oE 'rel="canonical" href="[^"]*"' "$TMPFILE" 2>/dev/null | sed -n 's/.*href="\([^"]*\)".*/\1/p')
  if [ -n "$canonical" ]; then
    url_norm=$(echo "$url" | sed 's/#.*//;s/\/$//')
    can_norm=$(echo "$canonical" | sed 's/#.*//;s/\/$//')
    if [ "$url_norm" != "$can_norm" ]; then
      # Allow ?page=N for pagination
      if echo "$url_norm" | grep -q '?page='; then
        : # accept self-canonical with page
      else
        log_fail "canonical mismatch: $url (canonical=$canonical)"
        failed=$((failed + 1))
        continue
      fi
    fi
  fi
  
  # SEO zone check (ensure SEO content is present on applicable pages)
  seo_zone_id=""
  if echo "$url" | grep -qE '/catalog/in-stock/?(\?|$)'; then
    seo_zone_id="catalog-in-stock-seo-zone"
  elif echo "$url" | grep -qE '/catalog/series/[^/]+/[^/]+/?(\?|$)'; then
    seo_zone_id="catalog-seo-zone"
  elif echo "$url" | grep -qE '/catalog/(series|category)/[^/]+/?(\?|$)'; then
    seo_zone_id="catalog-seo-zone"
  elif echo "$url" | grep -qE '/(leasing|used|service|parts|payment-delivery)/?(\?|$)'; then
    seo_zone_id="static-seo-zone"
  elif echo "$url" | grep -qE '/shacman/'; then
    seo_zone_id="shacman-hub-seo-zone"
  fi
  
  if [ -n "$seo_zone_id" ]; then
    # Use grep -F on file (no pipe of large content, avoids SIGPIPE)
    if ! grep -Fq "id=\"$seo_zone_id\"" "$TMPFILE" 2>/dev/null; then
      log_fail "Missing SEO zone id=\"$seo_zone_id\": $url (effective: $effective_url, http: $http_code)"
      failed=$((failed + 1))
    else
      # Check if zone has non-trivial content (at least one <p> tag in the document)
      para_found=$(grep -c '<p[^>]*>' "$TMPFILE" 2>/dev/null || true)
      if [ "$para_found" -eq 0 ]; then
        log_fail "SEO zone \"$seo_zone_id\" appears empty (no <p> tags): $url"
        failed=$((failed + 1))
      fi
    fi
  fi
  
  if [ $((checked % 50)) -eq 0 ] && [ $checked -gt 0 ]; then
    log_ok "checked $checked URLs..."
  fi
done

if [ $failed -gt 0 ]; then
  log_fail "checked $checked URLs, $failed failures"
  exit 1
fi
log_ok "checked $checked URLs, 0 failures"
exit 0
