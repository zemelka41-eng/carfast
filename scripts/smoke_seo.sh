#!/usr/bin/env bash
# SEO smoke tests for CARFAST production site
# Usage: ./scripts/smoke_seo.sh [base_url] [product_slug] [b3_hub_path] [engine_hub_path] [line_hub_path] [single_engine_404_path] [combo_hub_path] [engine_category_hub_path] [line_engine_hub_path] [category_formula_hub_path] [category_line_formula_hub_path]
# Default base_url: https://carfst.ru
# Path args (7–11) may be empty: then paths are auto-discovered from base_url/sitemap.xml for checks 8e/8f/8g/8h/8i0.
# product_slug: run product checks (clean URL has Product schema; ?utm_source=test has no schema).
# b3_hub_path: optional path for one B3 hub check, e.g. shacman/formula/6x4 (no leading/trailing slash).
# engine_hub_path: optional, e.g. shacman/engine/wp13-550e501 — expect 200 + canonical clean.
# line_hub_path: optional, e.g. shacman/line/x3000 — expect 200 + canonical clean.
# single_engine_404_path: optional, e.g. shacman/engine/wp10-336e53 — expect 404.
# combo_hub_path: optional (or from sitemap), e.g. shacman/line/x3000/samosvaly — Check 8e.
# engine_category_hub_path: optional (or from sitemap), e.g. shacman/engine/wp13-550e501/samosvaly — Check 8f.
# line_engine_hub_path: optional (or from sitemap), e.g. shacman/line/x3000/engine/wp13-550e501 — Check 8g.
# category_formula_hub_path: optional (or from sitemap), e.g. shacman/samosvaly/6x4 — Check 8h.
# category_line_formula_hub_path: optional (or from sitemap), e.g. shacman/category/samosvaly/line/x3000/formula/8x4 — Check 8i0.

set -euo pipefail

BASE_URL="${1:-https://carfst.ru}"
PRODUCT_SLUG="${2:-}"
B3_HUB_PATH="${3:-}"
ENGINE_HUB_PATH="${4:-}"
LINE_HUB_PATH="${5:-}"
SINGLE_ENGINE_404_PATH="${6:-}"
COMBO_HUB_PATH="${7:-}"
ENGINE_CATEGORY_HUB_PATH="${8:-}"
LINE_ENGINE_HUB_PATH="${9:-}"
CATEGORY_FORMULA_HUB_PATH="${10:-}"
CATEGORY_LINE_FORMULA_HUB_PATH="${11:-}"

# Load sitemap once for optional auto-discovery of hub paths (8e/8f/8g/8h/8i0)
SITEMAP_XML="$(curl -fsSL "${BASE_URL%/}/sitemap.xml" 2>/dev/null || true)"
# If sitemap is an index, fetch sub-sitemaps that may contain shacman hub URLs (so auto-discover works on prod)
if [ -n "$SITEMAP_XML" ] && echo "$SITEMAP_XML" | grep -q '<sitemapindex'; then
    SUB_LOCS=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -iE 'sitemap.*(shacman|hubs)' || true)
    for sub_url in $SUB_LOCS; do
        SITEMAP_XML="$SITEMAP_XML
$(curl -fsSL "$sub_url" 2>/dev/null || true)"
    done
fi

# Helper: pick first URL from sitemap matching pattern, excluding any line that matches exclude substrings, then return path without domain.
# Usage: _first_path_from_sitemap "<pattern>" "exclude1" "exclude2" ...
# Output: relative path (no leading slash) or empty.
_first_path_from_sitemap() {
    local pattern="$1"
    shift
    local out
    out=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E "$pattern" || true)
    while [ $# -gt 0 ]; do
        [ -z "$1" ] && shift && continue
        out=$(echo "$out" | grep -v "$1" || true)
        shift
    done
    out=$(echo "$out" | head -n 1)
    if [ -n "$out" ]; then
        echo "$out" | sed -E 's|https?://[^/]+/||' | sed 's|/$||'
    fi
}

# Auto-discover hub paths from sitemap when args are empty
if [ -z "${COMBO_HUB_PATH:-}" ] && [ -n "$SITEMAP_XML" ]; then
    COMBO_HUB_PATH=$(_first_path_from_sitemap 'https?://[^<]+/shacman/line/[^/]+/[^/]+/' '/in-stock/' '/engine/' '/4x2/' '/6x4/' '/8x4/') || true
fi
if [ -z "${ENGINE_CATEGORY_HUB_PATH:-}" ] && [ -n "$SITEMAP_XML" ]; then
    ENGINE_CATEGORY_HUB_PATH=$(_first_path_from_sitemap 'https?://[^<]+/shacman/engine/[^/]+/[^/]+/' '/in-stock/') || true
fi
if [ -z "${LINE_ENGINE_HUB_PATH:-}" ] && [ -n "$SITEMAP_XML" ]; then
    LINE_ENGINE_HUB_PATH=$(_first_path_from_sitemap 'https?://[^<]+/shacman/line/[^/]+/engine/[^/]+/' '/in-stock/') || true
fi
if [ -z "${CATEGORY_FORMULA_HUB_PATH:-}" ] && [ -n "$SITEMAP_XML" ]; then
    CATEGORY_FORMULA_HUB_PATH=$(_first_path_from_sitemap 'https?://[^<]+/shacman/[^/]+/(4x2|6x4|8x4)/' '/in-stock/' '/shacman/formula/') || true
fi
if [ -z "${CATEGORY_LINE_FORMULA_HUB_PATH:-}" ] && [ -n "$SITEMAP_XML" ]; then
    CATEGORY_LINE_FORMULA_HUB_PATH=$(_first_path_from_sitemap 'https?://[^<]+/shacman/category/[^/]+/line/[^/]+/formula/[^/]+/' '/in-stock/') || true
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Cleanup function for temp files
cleanup_temp_files() {
    rm -f /tmp/smoke_*_$$_headers.txt /tmp/smoke_*_$$_body.txt 2>/dev/null || true
}

# Register cleanup on exit
trap cleanup_temp_files EXIT

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

check_failed=0

# Helper function to fetch URL and validate HTTP status
# Usage: fetch_url <url> <expected_status> <description> <output_prefix>
# Sets global variables: FETCH_STATUS, FETCH_HEADERS_FILE, FETCH_BODY_FILE
# Returns: 0 on success, 1 on failure
fetch_url() {
    local url="$1"
    local expected_status="${2:-200}"
    local description="${3:-$url}"
    local output_prefix="${4:-/tmp/smoke_fetch_$$}"
    
    FETCH_HEADERS_FILE="${output_prefix}_headers.txt"
    FETCH_BODY_FILE="${output_prefix}_body.txt"
    
    # Fetch with headers and body separately
    # curl -D writes headers to file, -o writes body to file, -w appends http_code to stdout
    local http_code
    http_code=$(curl -sS -w "\n%{http_code}" --max-time 10 -D "$FETCH_HEADERS_FILE" -o "$FETCH_BODY_FILE" "$url" 2>&1 | tail -n1)
    FETCH_STATUS="$http_code"
    
    # Check HTTP status
    if [ "$http_code" != "$expected_status" ]; then
        log_error "FAIL: $description - HTTP $http_code (expected $expected_status)"
        echo "URL: $url" >&2
        echo "Headers:" >&2
        head -n 20 "$FETCH_HEADERS_FILE" >&2
        echo "Body (first 20 lines):" >&2
        head -n 20 "$FETCH_BODY_FILE" >&2
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
        return 1
    fi
    
    # For HTML pages, verify Content-Type
    if [[ "$url" != *"/__version__/"* ]]; then
        local content_type
        content_type=$(grep -i "^content-type:" "$FETCH_HEADERS_FILE" | head -n1 | cut -d: -f2- | tr -d '\r\n ' || echo "")
        if [[ ! "$content_type" =~ text/html ]]; then
            log_error "FAIL: $description - Content-Type is not text/html: $content_type"
            rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
            return 1
        fi
    fi
    
    return 0
}

# Normalize Location header value: strip "Location:" prefix (any case), trim, make absolute if relative
# Usage: normalize_location <raw_header_line>
# Output: absolute URL (or unchanged if already absolute)
normalize_location() {
    local raw="$1"
    raw="$(printf '%s' "$raw" | tr -d '\r')"
    # Strip header name (any case) and colon/spaces — value only
    raw="$(printf '%s' "$raw" | sed -E 's/^[^:]*:[[:space:]]*//')"
    raw="$(printf '%s' "$raw" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [ -n "$raw" ] && [[ "$raw" == /* ]]; then
        raw="${BASE_URL}${raw}"
    fi
    echo "$raw"
}

# Helper to extract canonical from HTML body
# Usage: extract_canonical <body_file>
# Returns: canonical URL or empty
extract_canonical() {
    local body_file="$1"
    grep -o 'rel="canonical" href="[^"]*"' "$body_file" | sed -nE 's/.*href="([^"]+)".*/\1/p' | head -n1
}

# Helper to check robots meta
# Usage: check_robots <body_file> <expected>
# Returns: 0 if matches, 1 otherwise
check_robots() {
    local body_file="$1"
    local expected="$2"
    local found
    found=$(grep -i 'name="robots"' "$body_file" | head -n1 || echo "")
    if [ -z "$found" ]; then
        return 1
    fi
    # Check if expected value is in the content attribute
    if echo "$found" | grep -qi "content=\"[^\"]*${expected}[^\"]*\""; then
        return 0
    fi
    return 1
}

# Helper to check absence of schema types
# Usage: check_no_schema <body_file> <schema_type1> [schema_type2 ...]
# Returns: 0 if none found, 1 if found
check_no_schema() {
    local body_file="$1"
    shift
    local body_content
    body_content=$(cat "$body_file")
    for schema_type in "$@"; do
        # Check for "@type": "SchemaType" pattern (with flexible whitespace)
        if echo "$body_content" | grep -qE "\"@type\"[[:space:]]*:[[:space:]]*\"${schema_type}\""; then
            return 1
        fi
    done
    return 0
}

# Helper to check presence of schema type
# Usage: check_has_schema <body_file> <schema_type>
# Returns: 0 if found, 1 if not found
check_has_schema() {
    local body_file="$1"
    local schema_type="$2"
    if grep -qE "\"@type\"[[:space:]]*:[[:space:]]*\"${schema_type}\"" "$body_file"; then
        return 0
    fi
    return 1
}

# Check 1: BUILD_ID via /__version__/
log_info "Check 1: BUILD_ID via /__version__/"
if ! fetch_url "${BASE_URL}/__version__/" 200 "BUILD_ID endpoint" "/tmp/smoke_version_$$"; then
    check_failed=1
else
    response=$(cat "$FETCH_BODY_FILE")
    build_id=$(echo "$response" | sed -nE 's/.*"build_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)
    
    if [ -z "$build_id" ]; then
        log_error "FAIL: /__version__/ does not contain build_id"
        log_error "Response (first 200 chars): $(echo "$response" | head -c 200)"
        check_failed=1
    else
        # Also check X-Build-ID header from homepage
        if fetch_url "${BASE_URL}/" 200 "Homepage for X-Build-ID" "/tmp/smoke_homepage_$$"; then
            header_build_id=$(grep -i "^x-build-id:" "$FETCH_HEADERS_FILE" | cut -d: -f2- | tr -d '\r\n ' || echo "")
            if [ -n "$header_build_id" ] && [ "$build_id" != "$header_build_id" ]; then
                log_error "FAIL: BUILD_ID mismatch: /__version__/=$build_id, X-Build-ID=$header_build_id"
                check_failed=1
            else
                log_info "OK: build_id=${build_id} (matches X-Build-ID header)"
            fi
            rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
        else
            log_warn "Could not verify X-Build-ID header (homepage check failed)"
            log_info "OK: build_id=${build_id}"
        fi
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 1b: robots.txt multiline (>= 3 lines), Content-Type text/plain, key directives
log_info "Check 1b: robots.txt multiline, text/plain, User-agent/Disallow/Sitemap"
ROBOTS_BODY="/tmp/smoke_robots_$$_body.txt"
ROBOTS_HEADERS="/tmp/smoke_robots_$$_headers.txt"
rm -f "$ROBOTS_BODY" "$ROBOTS_HEADERS"
http_code=$(curl -fsSL -w "%{http_code}" -o "$ROBOTS_BODY" -D "$ROBOTS_HEADERS" --max-time 10 "${BASE_URL}/robots.txt" 2>/dev/null || echo "000")
if [ "$http_code" != "200" ]; then
    log_error "FAIL: /robots.txt returned HTTP $http_code (expected 200)"
    check_failed=1
else
    content_type=$(grep -i "^content-type:" "$ROBOTS_HEADERS" | head -n1 | cut -d: -f2- | tr -d '\r\n ' || echo "")
    if [[ ! "$content_type" =~ text/plain ]]; then
        log_error "FAIL: robots.txt Content-Type must be text/plain; got: $content_type"
        check_failed=1
    fi
    line_count=$(wc -l < "$ROBOTS_BODY" 2>/dev/null || echo "0")
    if [ "${line_count:-0}" -lt 3 ]; then
        log_error "FAIL: robots.txt must have at least 3 lines (got ${line_count:-0}); curl -sS ${BASE_URL}/robots.txt | wc -l should be >= 3"
        check_failed=1
    else
        log_info "OK: robots.txt has ${line_count} lines"
    fi
    if ! grep -q "User-agent: *" "$ROBOTS_BODY" 2>/dev/null; then
        log_error "FAIL: robots.txt must contain 'User-agent: *'"
        check_failed=1
    fi
    if ! grep -q "Disallow: /admin/" "$ROBOTS_BODY" 2>/dev/null; then
        log_error "FAIL: robots.txt must contain 'Disallow: /admin/'"
        check_failed=1
    fi
    if ! grep -q "Sitemap:" "$ROBOTS_BODY" 2>/dev/null; then
        log_error "FAIL: robots.txt must contain 'Sitemap:'"
        check_failed=1
    fi
    [ $check_failed -eq 0 ] && log_info "OK: robots.txt multiline, text/plain, key directives present"
fi
rm -f "$ROBOTS_BODY" "$ROBOTS_HEADERS"

# Check 2: Schema not present on /blog/?page=2 + robots noindex
log_info "Check 2: Schema not present + robots noindex on /blog/?page=2"
if ! fetch_url "${BASE_URL}/blog/?page=2" 200 "Blog list page=2" "/tmp/smoke_blog_$$"; then
    check_failed=1
else
    # Check robots meta
    if ! check_robots "$FETCH_BODY_FILE" "noindex, follow"; then
        log_error "FAIL: /blog/?page=2 should have robots='noindex, follow'"
        check_failed=1
    fi
    
    # Check absence of page-level schemas
    if ! check_no_schema "$FETCH_BODY_FILE" "BreadcrumbList" "BlogPosting"; then
        log_error "FAIL: /blog/?page=2 contains BreadcrumbList or BlogPosting schema"
        check_failed=1
    fi
    
    if [ $check_failed -eq 0 ]; then
        log_info "OK: No BreadcrumbList/BlogPosting schema, robots=noindex, follow"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 3: Schema not present on /news/?utm_source=test
log_info "Check 3: Schema not present on /news/?utm_source=test"
if ! fetch_url "${BASE_URL}/news/?utm_source=test" 200 "News page with utm" "/tmp/smoke_news_$$"; then
    check_failed=1
else
    # Check absence of page-level schemas
    if ! check_no_schema "$FETCH_BODY_FILE" "ItemList" "BreadcrumbList"; then
        log_error "FAIL: /news/?utm_source=test contains ItemList or BreadcrumbList schema"
        check_failed=1
    else
        log_info "OK: No ItemList/BreadcrumbList schema"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 4: Canonical clean on /contacts/?utm_source=test&gclid=1
log_info "Check 4: Canonical clean on /contacts/?utm_source=test&gclid=1"
if ! fetch_url "${BASE_URL}/contacts/?utm_source=test&gclid=1" 200 "Contacts page with utm/gclid" "/tmp/smoke_contacts_utm_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    canonical_count=$(grep -o 'rel="canonical"' "$FETCH_BODY_FILE" | wc -l | tr -d '[:space:]')
    
    if [ "$canonical_count" -eq 0 ]; then
        log_error "FAIL: Canonical link not found on /contacts/?utm_source=test&gclid=1"
        check_failed=1
    elif [ "$canonical_count" -ne 1 ]; then
        log_error "FAIL: Multiple canonical links found ($canonical_count) on /contacts/?utm_source=test&gclid=1"
        check_failed=1
    elif echo "$canonical" | grep -q "utm_source\|gclid"; then
        log_error "FAIL: Canonical contains utm_source or gclid: ${canonical}"
        check_failed=1
    elif echo "$canonical" | grep -q "?"; then
        log_error "FAIL: Canonical contains query string: ${canonical}"
        check_failed=1
    elif [ "$canonical" != "${BASE_URL}/contacts/" ]; then
        log_error "FAIL: Canonical mismatch (expected: ${BASE_URL}/contacts/, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: Canonical is clean: ${canonical}"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 4b: /lead/?utm_source=test — canonical clean, no JSON-LD schema (SEO invariant)
log_info "Check 4b: /lead/?utm_source=test canonical clean, no schema"
if ! fetch_url "${BASE_URL}/lead/?utm_source=test" 200 "Lead page with utm" "/tmp/smoke_lead_utm_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    canonical_count=$(grep -o 'rel="canonical"' "$FETCH_BODY_FILE" | wc -l | tr -d '[:space:]')
    if [ "$canonical_count" -eq 0 ]; then
        log_error "FAIL: Canonical link not found on /lead/?utm_source=test"
        check_failed=1
    elif [ "$canonical_count" -ne 1 ]; then
        log_error "FAIL: Multiple canonical links on /lead/?utm_source=test"
        check_failed=1
    elif echo "$canonical" | grep -q "utm_source\|?"; then
        log_error "FAIL: Canonical must be clean (no GET): ${canonical}"
        check_failed=1
    elif [ "$canonical" != "${BASE_URL}/lead/" ]; then
        log_error "FAIL: Canonical mismatch (expected: ${BASE_URL}/lead/, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: Canonical is clean: ${canonical}"
    fi
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /lead/?utm_source=test must not contain application/ld+json (schema only on clean URL)"
        check_failed=1
    else
        log_info "OK: No JSON-LD schema on /lead/?utm_source=test"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5: Canonical clean on /contacts/?page=2
log_info "Check 5: Canonical clean on /contacts/?page=2"
if ! fetch_url "${BASE_URL}/contacts/?page=2" 200 "Contacts page=2" "/tmp/smoke_contacts_page_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    canonical_count=$(grep -o 'rel="canonical"' "$FETCH_BODY_FILE" | wc -l | tr -d '[:space:]')
    
    if [ "$canonical_count" -eq 0 ]; then
        log_error "FAIL: Canonical link not found on /contacts/?page=2"
        check_failed=1
    elif [ "$canonical_count" -ne 1 ]; then
        log_error "FAIL: Multiple canonical links found ($canonical_count) on /contacts/?page=2"
        check_failed=1
    elif echo "$canonical" | grep -q "?"; then
        log_error "FAIL: Canonical contains query string (should be clean): ${canonical}"
        check_failed=1
    elif [ "$canonical" != "${BASE_URL}/contacts/" ]; then
        log_error "FAIL: Canonical mismatch (expected: ${BASE_URL}/contacts/, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: Canonical is clean: ${canonical}"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5b: /shacman/ returns 200, text/html, canonical clean
log_info "Check 5b: /shacman/ returns 200, content-type html, canonical clean"
if ! fetch_url "${BASE_URL}/shacman/" 200 "SHACMAN hub" "/tmp/smoke_shacman_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -z "$canonical" ]; then
        log_error "FAIL: Canonical link not found on /shacman/"
        check_failed=1
    elif echo "$canonical" | grep -q "?"; then
        log_error "FAIL: /shacman/ canonical should be clean (no query): ${canonical}"
        check_failed=1
    elif [ "$canonical" != "${BASE_URL}/shacman/" ]; then
        log_error "FAIL: /shacman/ canonical mismatch (expected: ${BASE_URL}/shacman/, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: /shacman/ canonical clean: ${canonical}"
    fi
    if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /shacman/ must contain SEO zone (id=shacman-hub-seo-zone)"
        check_failed=1
    else
        log_info "OK: /shacman/ has shacman-hub-seo-zone"
    fi
    # Clean URL must have Organization or LocalBusiness schema
    if ! (grep -qE '"@type"[[:space:]]*:[[:space:]]*"Organization"' "$FETCH_BODY_FILE" 2>/dev/null || grep -qE '"@type"[[:space:]]*:[[:space:]]*"LocalBusiness"' "$FETCH_BODY_FILE" 2>/dev/null); then
        log_error "FAIL: /shacman/ (clean URL) must contain Organization or LocalBusiness schema"
        check_failed=1
    else
        log_info "OK: /shacman/ has Organization/LocalBusiness schema"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5c: /shacman/?page=2 — noindex, self-canonical (?page=2)
log_info "Check 5c: /shacman/?page=2 noindex, self-canonical"
if ! fetch_url "${BASE_URL}/shacman/?page=2" 200 "SHACMAN hub page=2" "/tmp/smoke_shacman_page2_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    expected_canonical="${BASE_URL}/shacman/?page=2"
    if [ -z "$canonical" ]; then
        log_error "FAIL: Canonical link not found on /shacman/?page=2"
        check_failed=1
    elif [ "$canonical" != "$expected_canonical" ]; then
        log_error "FAIL: /shacman/?page=2 should have self-canonical (expected: ${expected_canonical}, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: /shacman/?page=2 self-canonical: ${canonical}"
    fi
    if ! check_robots "$FETCH_BODY_FILE" "noindex, follow"; then
        log_error "FAIL: /shacman/?page=2 should have robots='noindex, follow'"
        check_failed=1
    else
        log_info "OK: /shacman/?page=2 robots noindex, follow"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5d: /sitemap.xml index lists shacman sections, sections contain required URLs
log_info "Check 5d: Sitemap index & sections (shacman-hubs, shacman-category-engine)"
SITEMAP_HEADERS="/tmp/smoke_sitemap_$$_headers.txt"
SITEMAP_BODY="/tmp/smoke_sitemap_$$_body.txt"
rm -f "$SITEMAP_HEADERS" "$SITEMAP_BODY"
http_code=$(curl -sS -w "%{http_code}" -o "$SITEMAP_BODY" -D "$SITEMAP_HEADERS" --max-time 10 "${BASE_URL}/sitemap.xml" 2>/dev/null || echo "000")
if [ "$http_code" != "200" ]; then
    log_error "FAIL: /sitemap.xml returned HTTP $http_code (expected 200)"
    [ -f "$SITEMAP_HEADERS" ] && head -n 15 "$SITEMAP_HEADERS" >&2
    [ -f "$SITEMAP_BODY" ] && head -n 5 "$SITEMAP_BODY" >&2
    check_failed=1
else
    content_type=$(grep -i "^content-type:" "$SITEMAP_HEADERS" | head -n1 | cut -d: -f2- | tr -d '\r\n ' || echo "")
    if [[ ! "$content_type" =~ (application/xml|text/xml) ]]; then
        log_error "FAIL: /sitemap.xml Content-Type is not XML: $content_type"
        check_failed=1
    elif head -n 2 "$SITEMAP_BODY" | grep -q "DOCTYPE html"; then
        log_error "FAIL: /sitemap.xml body looks like HTML (first lines): $(head -n 2 "$SITEMAP_BODY")"
        check_failed=1
    else
        # Check if it's a sitemapindex or a flat urlset
        if grep -q "<sitemapindex" "$SITEMAP_BODY"; then
            # It's an index: check for shacman-hubs and shacman-category-engine sections
            log_info "Detected sitemap index format"
            if ! grep -q "sitemap-shacman-hubs.xml" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml index missing <loc>.../sitemap-shacman-hubs.xml</loc>"
                check_failed=1
            else
                log_info "OK: sitemap index contains sitemap-shacman-hubs.xml"
            fi
            if ! grep -q "sitemap-shacman-category-engine.xml" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml index missing <loc>.../sitemap-shacman-category-engine.xml</loc>"
                check_failed=1
            else
                log_info "OK: sitemap index contains sitemap-shacman-category-engine.xml"
            fi
            if ! grep -q "sitemap-shacman-category-line-formula.xml" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml index missing <loc>.../sitemap-shacman-category-line-formula.xml</loc>"
                check_failed=1
            else
                log_info "OK: sitemap index contains sitemap-shacman-category-line-formula.xml"
            fi
            if ! grep -q "sitemap-shacman-model-code.xml" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml index missing <loc>.../sitemap-shacman-model-code.xml</loc>"
                check_failed=1
            else
                log_info "OK: sitemap index contains sitemap-shacman-model-code.xml"
            fi
            
            # Download and check sitemap-shacman-hubs.xml for engine/line URLs
            SHACMAN_HUBS_BODY="/tmp/smoke_shacman_hubs_$$_body.txt"
            rm -f "$SHACMAN_HUBS_BODY"
            shacman_hubs_code=$(curl -sS -w "%{http_code}" -o "$SHACMAN_HUBS_BODY" --max-time 10 "${BASE_URL}/sitemap-shacman-hubs.xml" 2>/dev/null || echo "000")
            if [ "$shacman_hubs_code" != "200" ]; then
                log_error "FAIL: /sitemap-shacman-hubs.xml returned HTTP $shacman_hubs_code"
                check_failed=1
            else
                if ! grep -q "shacman/engine/" "$SHACMAN_HUBS_BODY"; then
                    log_error "FAIL: sitemap-shacman-hubs.xml does not contain shacman/engine/ URL"
                    check_failed=1
                else
                    log_info "OK: sitemap-shacman-hubs.xml contains shacman/engine/"
                fi
                if ! grep -q "shacman/line/" "$SHACMAN_HUBS_BODY"; then
                    log_error "FAIL: sitemap-shacman-hubs.xml does not contain shacman/line/ URL"
                    check_failed=1
                else
                    log_info "OK: sitemap-shacman-hubs.xml contains shacman/line/"
                fi
            fi
            rm -f "$SHACMAN_HUBS_BODY"
            
            # Download and check sitemap-shacman-category-engine.xml for category+engine URLs
            SHACMAN_CAT_ENG_BODY="/tmp/smoke_shacman_cat_eng_$$_body.txt"
            rm -f "$SHACMAN_CAT_ENG_BODY"
            shacman_cat_eng_code=$(curl -sS -w "%{http_code}" -o "$SHACMAN_CAT_ENG_BODY" --max-time 10 "${BASE_URL}/sitemap-shacman-category-engine.xml" 2>/dev/null || echo "000")
            if [ "$shacman_cat_eng_code" != "200" ]; then
                log_error "FAIL: /sitemap-shacman-category-engine.xml returned HTTP $shacman_cat_eng_code"
                check_failed=1
            else
                if ! grep -q "shacman/category/" "$SHACMAN_CAT_ENG_BODY" || ! grep -q "/engine/" "$SHACMAN_CAT_ENG_BODY"; then
                    log_error "FAIL: sitemap-shacman-category-engine.xml missing shacman/category/.../engine/ URL"
                    check_failed=1
                else
                    log_info "OK: sitemap-shacman-category-engine.xml contains shacman/category/.../engine/"
                fi
            fi
            rm -f "$SHACMAN_CAT_ENG_BODY"

            # New combo sections: index must list them; section 200+XML; if section has URLs, sample one → 200 + SEO zone
            for section_name in "shacman-category-line" "shacman-line-formula" "shacman-category-formula"; do
                if ! grep -q "sitemap-${section_name}.xml" "$SITEMAP_BODY"; then
                    log_error "FAIL: /sitemap.xml index missing sitemap-${section_name}.xml"
                    check_failed=1
                else
                    log_info "OK: sitemap index contains sitemap-${section_name}.xml"
                fi
                sec_body=""
                sec_code=$(curl -sS -w "%{http_code}" -o "/tmp/smoke_sec_${section_name}_$$.xml" --max-time 10 "${BASE_URL}/sitemap-${section_name}.xml" 2>/dev/null || echo "000")
                sec_body=$(cat "/tmp/smoke_sec_${section_name}_$$.xml" 2>/dev/null || true)
                rm -f "/tmp/smoke_sec_${section_name}_$$.xml"
                if [ "$sec_code" != "200" ]; then
                    log_error "FAIL: /sitemap-${section_name}.xml returned HTTP $sec_code"
                    check_failed=1
                elif [ -z "$sec_body" ] || ! echo "$sec_body" | grep -qE '<urlset|<loc>'; then
                    log_info "OK: sitemap-${section_name}.xml returns 200 (empty or no URLs is OK)"
                else
                    first_url=$(echo "$sec_body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E 'shacman/(category/|line/)' | head -n 1)
                    if [ -n "$first_url" ]; then
                        sample_code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$first_url" 2>/dev/null || echo "000")
                        if [ "$sample_code" != "200" ]; then
                            log_error "FAIL: Sample URL from sitemap-${section_name}.xml returned $sample_code: $first_url"
                            check_failed=1
                        elif ! fetch_url "$first_url" 200 "Sample from ${section_name}" "/tmp/smoke_sample_${section_name}_$$"; then
                            check_failed=1
                        else
                            canonical=$(extract_canonical "$FETCH_BODY_FILE")
                            if [ -n "$canonical" ] && echo "$canonical" | grep -q "?"; then
                                log_error "FAIL: Sample hub canonical should be clean: $canonical"
                                check_failed=1
                            fi
                            if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
                                log_error "FAIL: Sample hub must contain id=shacman-hub-seo-zone"
                                check_failed=1
                            else
                                log_info "OK: Sample URL from ${section_name} returns 200, canonical clean, has SEO zone"
                            fi
                            rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
                        fi
                    fi
                fi
            done
        else
            # Flat urlset (backward compat): check for shacman/engine/ and shacman/line/ directly
            log_info "Detected flat urlset format (backward compat)"
            if ! grep -q "shacman/engine/" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml does not contain any shacman/engine/ URL"
                check_failed=1
            elif ! grep -q "shacman/line/" "$SITEMAP_BODY"; then
                log_error "FAIL: /sitemap.xml does not contain any shacman/line/ URL"
                check_failed=1
            else
                log_info "OK: /sitemap.xml 200, Content-Type XML, contains shacman/engine/ and shacman/line/"
            fi
        fi
    fi
fi
rm -f "$SITEMAP_HEADERS" "$SITEMAP_BODY"

# Check 5e: CRITICAL INVARIANT — /catalog/ (noindex page) must have noindex, follow robots
log_info "Check 5e: /catalog/ returns 200 with robots=noindex, follow and clean canonical"
if ! fetch_url "${BASE_URL}/catalog/" 200 "Catalog list page (critical noindex invariant)" "/tmp/smoke_catalog_$$"; then
    check_failed=1
else
    # Check robots meta — MUST be noindex, follow
    if ! check_robots "$FETCH_BODY_FILE" "noindex"; then
        log_error "FAIL: /catalog/ MUST have robots='noindex, follow' (critical SEO invariant)"
        check_failed=1
    else
        log_info "OK: /catalog/ has noindex robots"
    fi
    
    # Check canonical is clean (self)
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    expected_canonical="${BASE_URL}/catalog/"
    if [ -z "$canonical" ]; then
        log_error "FAIL: Canonical link not found on /catalog/"
        check_failed=1
    elif echo "$canonical" | grep -q "?"; then
        log_error "FAIL: /catalog/ canonical should be clean (no query): ${canonical}"
        check_failed=1
    elif [ "$canonical" != "$expected_canonical" ]; then
        log_error "FAIL: /catalog/ canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
        check_failed=1
    else
        log_info "OK: /catalog/ canonical is clean: ${canonical}"
    fi
    
    # Schema should be empty (noindex page)
    if grep -q '"@type": "ItemList"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/ (noindex page) should not contain ItemList schema"
        check_failed=1
    else
        log_info "OK: /catalog/ has no ItemList schema"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5f: /catalog/?utm_source=test also noindex with clean canonical (no utm in canonical)
log_info "Check 5f: /catalog/?utm_source=test noindex with clean canonical"
if ! fetch_url "${BASE_URL}/catalog/?utm_source=test" 200 "Catalog with utm" "/tmp/smoke_catalog_utm_$$"; then
    check_failed=1
else
    if ! check_robots "$FETCH_BODY_FILE" "noindex"; then
        log_error "FAIL: /catalog/?utm_source=test must have noindex"
        check_failed=1
    fi
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -n "$canonical" ] && ( echo "$canonical" | grep -q "utm_source" || echo "$canonical" | grep -q '?' ); then
        log_error "FAIL: /catalog/?utm_source=test canonical must be clean: ${canonical}"
        check_failed=1
    else
        log_info "OK: /catalog/?utm_source=test noindex with clean canonical"
    fi
    # Schema should be absent
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        if ! check_no_schema "$FETCH_BODY_FILE" "ItemList" "BreadcrumbList"; then
            log_error "FAIL: /catalog/?utm_source=test must not contain page-level schema"
            check_failed=1
        fi
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5g: Invalid ?category= and ?series= (anti-garbage) must return 404
log_info "Check 5g: /catalog/?category=invalid and ?series=invalid return 404"
if ! fetch_url "${BASE_URL}/catalog/?category=nonexistent-category-slug-xyz" 404 "Catalog invalid category" "/tmp/smoke_cat_inv_$$"; then
    check_failed=1
else
    log_info "OK: invalid ?category= returns 404"
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi
if ! fetch_url "${BASE_URL}/catalog/?series=nonexistent-series-slug-xyz" 404 "Catalog invalid series" "/tmp/smoke_ser_inv_$$"; then
    check_failed=1
else
    log_info "OK: invalid ?series= returns 404"
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5e: Product URLs in sitemap must return 200 (not 301) — no aliases/redirects in sitemap
log_info "Check 5e: Sample product URLs from sitemap return 200 (no aliases in sitemap)"
# Check if /sitemap.xml is an index; if yes, fetch products from sitemap-products.xml section
PRODUCTS_SITEMAP_BODY=""
if echo "$SITEMAP_XML" | head -n 10 | grep -q "<sitemapindex"; then
    # It's an index: find sitemap-products.xml section
    log_info "Detected sitemap index; fetching sitemap-products.xml section"
    products_section_url=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+sitemap-products\.xml[^<]*</loc>' | head -n1 | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r')
    if [ -z "$products_section_url" ]; then
        log_error "FAIL: sitemap index missing sitemap-products.xml section"
        check_failed=1
    else
        log_info "Fetching products section: $products_section_url"
        PRODUCTS_SITEMAP_BODY=$(curl -fsSL --max-time 10 "$products_section_url" 2>/dev/null || true)
        if [ -z "$PRODUCTS_SITEMAP_BODY" ]; then
            log_error "FAIL: Could not fetch sitemap-products.xml section"
            check_failed=1
        fi
    fi
    product_urls=$(echo "$PRODUCTS_SITEMAP_BODY" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E '/product/[^/]+/?$' | head -n 5)
else
    # Flat urlset (backward compat): extract products directly from $SITEMAP_XML
    log_info "Detected flat sitemap format (backward compat)"
    product_urls=$(echo "$SITEMAP_XML" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E '/product/[^/]+/?$' | head -n 5)
fi

if [ -z "$product_urls" ]; then
    log_error "FAIL: No product URLs found in sitemap (expected at least 1)"
    check_failed=1
else
    sampled_ok=0
    sampled_fail=0
    failed_urls=""
    for url in $product_urls; do
        code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
        # Expect 200; 301 (no -L) would indicate alias/redirect wrongly in sitemap
        if [ "$code" = "200" ]; then
            sampled_ok=$((sampled_ok + 1))
        else
            sampled_fail=$((sampled_fail + 1))
            # Get Location header if redirect
            location_info=$(curl -sSI --max-time 10 "$url" 2>/dev/null | grep -i '^location:' | head -n1 | tr -d '\r' || echo "")
            if [ -n "$location_info" ]; then
                log_error "FAIL: Product URL returned $code (expected 200): $url → $location_info"
            else
                log_error "FAIL: Product URL returned $code (expected 200): $url"
            fi
            failed_urls="${failed_urls}${url} (${code})\n"
        fi
    done
    if [ $sampled_fail -gt 0 ]; then
        check_failed=1
        log_error "Failed product URLs: $(echo -e "$failed_urls" | head -n 10)"
    else
        log_info "OK: Sampled $sampled_ok product URL(s) from sitemap return 200 (no aliases)"
    fi
fi

# Check 5f: /leasing/ (clean) has static-seo-zone
log_info "Check 5f: /leasing/ (clean) returns 200 and contains id=\"static-seo-zone\""
if ! fetch_url "${BASE_URL}/leasing/" 200 "Leasing page (clean)" "/tmp/smoke_leasing_$$"; then
    check_failed=1
else
    if ! grep -q 'id="static-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /leasing/ does not contain id=\"static-seo-zone\""
        check_failed=1
    else
        log_info "OK: /leasing/ contains static-seo-zone"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5g: /leasing/?utm_source=test has no JSON-LD (schema only on clean URL)
log_info "Check 5g: /leasing/?utm_source=test has no application/ld+json"
if ! fetch_url "${BASE_URL}/leasing/?utm_source=test" 200 "Leasing with UTM" "/tmp/smoke_leasing_utm_$$"; then
    check_failed=1
else
    if grep -q "application/ld+json" "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /leasing/?utm_source=test must not contain application/ld+json (schema only on clean URL)"
        check_failed=1
    else
        log_info "OK: /leasing/?utm_source=test has no application/ld+json"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5h: /catalog/in-stock/ (clean) has catalog-in-stock-seo-zone
log_info "Check 5h: /catalog/in-stock/ (clean) returns 200 and contains id=\"catalog-in-stock-seo-zone\""
if ! fetch_url "${BASE_URL}/catalog/in-stock/" 200 "Catalog in-stock (clean)" "/tmp/smoke_instock_clean_$$"; then
    check_failed=1
else
    if ! grep -q 'id="catalog-in-stock-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/in-stock/ does not contain id=\"catalog-in-stock-seo-zone\""
        check_failed=1
    else
        log_info "OK: /catalog/in-stock/ contains catalog-in-stock-seo-zone"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5i: /catalog/in-stock/?utm_source=test has no JSON-LD (schema only on clean URL)
log_info "Check 5i: /catalog/in-stock/?utm_source=test has no application/ld+json"
if ! fetch_url "${BASE_URL}/catalog/in-stock/?utm_source=test" 200 "Catalog in-stock with UTM" "/tmp/smoke_instock_utm_$$"; then
    check_failed=1
else
    if grep -q "application/ld+json" "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/in-stock/?utm_source=test must not contain application/ld+json (schema only on clean URL)"
        check_failed=1
    else
        log_info "OK: /catalog/in-stock/?utm_source=test has no application/ld+json"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 5j: Additional SEO zone content checks (non-empty)
log_info "Check 5j: SEO zones on key pages are non-empty"

# /catalog/in-stock/ should have catalog-in-stock-seo-zone with content
if ! fetch_url "${BASE_URL}/catalog/in-stock/" 200 "Catalog in-stock for SEO zone" "/tmp/smoke_instock_zone_$$"; then
    check_failed=1
else
    if ! grep -q 'id="catalog-in-stock-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/in-stock/ missing id=\"catalog-in-stock-seo-zone\""
        check_failed=1
    else
        # Check if zone has at least some content (look for <p> tag)
        zone_line=$(grep -A 50 'id="catalog-in-stock-seo-zone"' "$FETCH_BODY_FILE" | head -n 50)
        if ! echo "$zone_line" | grep -q '<p'; then
            log_error "FAIL: catalog-in-stock-seo-zone appears empty (no <p> tags found)"
            check_failed=1
        else
            log_info "OK: catalog-in-stock-seo-zone present and non-empty"
        fi
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# /leasing/ should have static-seo-zone with content
if ! fetch_url "${BASE_URL}/leasing/" 200 "Leasing for SEO zone" "/tmp/smoke_leasing_zone_$$"; then
    check_failed=1
else
    if ! grep -q 'id="static-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /leasing/ missing id=\"static-seo-zone\""
        check_failed=1
    else
        zone_line=$(grep -A 50 'id="static-seo-zone"' "$FETCH_BODY_FILE" | head -n 50)
        if ! echo "$zone_line" | grep -q '<p'; then
            log_error "FAIL: static-seo-zone on /leasing/ appears empty (no <p> tags found)"
            check_failed=1
        else
            log_info "OK: static-seo-zone on /leasing/ present and non-empty"
        fi
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 6: catalog/in-stock preserves self-canonical with ?page=2
log_info "Check 6: catalog/in-stock preserves self-canonical with ?page=2"
if ! fetch_url "${BASE_URL}/catalog/in-stock/?page=2" 200 "Catalog in-stock page=2" "/tmp/smoke_instock_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    canonical_count=$(grep -o 'rel="canonical"' "$FETCH_BODY_FILE" | wc -l | tr -d '[:space:]')
    expected_canonical="${BASE_URL}/catalog/in-stock/?page=2"
    
    if [ "$canonical_count" -eq 0 ]; then
        log_error "FAIL: Canonical link not found on /catalog/in-stock/?page=2"
        check_failed=1
    elif [ "$canonical_count" -ne 1 ]; then
        log_error "FAIL: Multiple canonical links found ($canonical_count) on /catalog/in-stock/?page=2"
        check_failed=1
    elif [ "$canonical" != "$expected_canonical" ]; then
        log_error "FAIL: catalog/in-stock should have self-canonical with ?page=2"
        log_error "Expected: ${expected_canonical}"
        log_error "Got: ${canonical}"
        check_failed=1
    else
        log_info "OK: catalog/in-stock has self-canonical: ${canonical}"
    fi
    
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 6b: /catalog/?series=shacman&category=samosvaly -> 301 to /catalog/series/shacman/samosvaly/
log_info "Check 6b: /catalog/?series=shacman&category=samosvaly returns 301 to clean URL"
if ! fetch_url "${BASE_URL}/catalog/?series=shacman&category=samosvaly" 301 "Catalog series+category redirect" "/tmp/smoke_catalog_sc_$$"; then
    check_failed=1
else
    loc_raw="$(grep -i '^Location:' "$FETCH_HEADERS_FILE" 2>/dev/null | head -n1)"
    loc="$(normalize_location "$loc_raw")"
    expected="${BASE_URL}/catalog/series/shacman/samosvaly/"
    if [ -z "$loc_raw" ]; then
        log_error "FAIL: 301 response missing Location header"
        check_failed=1
    elif [ "$loc" != "$expected" ]; then
        log_error "FAIL: Catalog series+category redirect Location mismatch"
        log_error "Expected: ${expected}"
        log_error "Got: ${loc}"
        check_failed=1
    else
        log_info "OK: Location ${loc}"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 6c: /catalog/?series=shacman&category=samosvaly&page=2 -> 301 to .../series/shacman/samosvaly/?page=2
log_info "Check 6c: /catalog/?series=shacman&category=samosvaly&page=2 returns 301 to clean URL with page=2"
if ! fetch_url "${BASE_URL}/catalog/?series=shacman&category=samosvaly&page=2" 301 "Catalog series+category page=2 redirect" "/tmp/smoke_catalog_sc_p2_$$"; then
    check_failed=1
else
    loc_raw="$(grep -i '^Location:' "$FETCH_HEADERS_FILE" 2>/dev/null | head -n1)"
    loc="$(normalize_location "$loc_raw")"
    expected2="${BASE_URL}/catalog/series/shacman/samosvaly/?page=2"
    if [ -z "$loc_raw" ]; then
        log_error "FAIL: 301 response missing Location header (page=2)"
        check_failed=1
    elif [ "$loc" != "$expected2" ]; then
        log_error "FAIL: Catalog series+category page=2 redirect Location mismatch"
        log_error "Expected: ${expected2}"
        log_error "Got: ${loc}"
        check_failed=1
    else
        log_info "OK: Location ${loc}"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 6d: Catalog SEO zone on clean URLs (series, category, series+category)
log_info "Check 6d: /catalog/series/shacman/ (clean URL) has catalog-seo-zone"
if fetch_url "${BASE_URL}/catalog/series/shacman/" 200 "Catalog series shacman" "/tmp/smoke_cat_series_$$" 2>/dev/null; then
    if ! grep -q 'id="catalog-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/series/shacman/ must contain id=catalog-seo-zone"
        check_failed=1
    else
        log_info "OK: Catalog series has catalog-seo-zone"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
else
    log_warn "Skipping catalog series SEO zone check (page returned non-200)"
fi
log_info "Check 6d: /catalog/category/samosvaly/ (clean URL) has catalog-seo-zone"
if fetch_url "${BASE_URL}/catalog/category/samosvaly/" 200 "Catalog category samosvaly" "/tmp/smoke_cat_cat_$$" 2>/dev/null; then
    if ! grep -q 'id="catalog-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/category/samosvaly/ must contain id=catalog-seo-zone"
        check_failed=1
    else
        log_info "OK: Catalog category has catalog-seo-zone"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
else
    log_warn "Skipping catalog category SEO zone check (page returned non-200)"
fi
log_info "Check 6d: /catalog/series/shacman/samosvaly/ (clean URL) has catalog-seo-zone"
if fetch_url "${BASE_URL}/catalog/series/shacman/samosvaly/" 200 "Catalog series+category" "/tmp/smoke_cat_sc_$$" 2>/dev/null; then
    if ! grep -q 'id="catalog-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/series/shacman/samosvaly/ must contain id=catalog-seo-zone"
        check_failed=1
    else
        log_info "OK: Catalog series+category has catalog-seo-zone"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
else
    log_warn "Skipping catalog series+category SEO zone check (page returned non-200)"
fi

# Check 6e: Catalog pages with ?utm_source=test have NO JSON-LD and canonical is clean
log_info "Check 6e: /catalog/series/shacman/?utm_source=test no JSON-LD, canonical clean"
if fetch_url "${BASE_URL}/catalog/series/shacman/?utm_source=test" 200 "Catalog series with utm" "/tmp/smoke_cat_series_utm_$$" 2>/dev/null; then
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/series/shacman/?utm_source=test must not contain application/ld+json"
        check_failed=1
    fi
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -n "$canonical" ] && ( echo "$canonical" | grep -q "utm_source" || echo "$canonical" | grep -q '?' ); then
        log_error "FAIL: /catalog/series/shacman/?utm_source=test canonical must be clean (got: ${canonical})"
        check_failed=1
    fi
    [ $check_failed -eq 0 ] && log_info "OK: No JSON-LD, canonical clean on catalog series with ?utm_source=test"
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi
log_info "Check 6e: /catalog/category/samosvaly/?utm_source=test no JSON-LD, canonical clean"
if fetch_url "${BASE_URL}/catalog/category/samosvaly/?utm_source=test" 200 "Catalog category with utm" "/tmp/smoke_cat_cat_utm_$$" 2>/dev/null; then
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/category/samosvaly/?utm_source=test must not contain application/ld+json"
        check_failed=1
    fi
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -n "$canonical" ] && ( echo "$canonical" | grep -q "utm_source" || echo "$canonical" | grep -q '?' ); then
        log_error "FAIL: /catalog/category/samosvaly/?utm_source=test canonical must be clean (got: ${canonical})"
        check_failed=1
    fi
    [ $check_failed -eq 0 ] && log_info "OK: No JSON-LD, canonical clean on catalog category with ?utm_source=test"
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi
log_info "Check 6e: /catalog/series/shacman/samosvaly/?utm_source=test no JSON-LD, canonical clean"
if fetch_url "${BASE_URL}/catalog/series/shacman/samosvaly/?utm_source=test" 200 "Catalog series+category with utm" "/tmp/smoke_cat_sc_utm_$$" 2>/dev/null; then
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /catalog/series/shacman/samosvaly/?utm_source=test must not contain application/ld+json"
        check_failed=1
    fi
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -n "$canonical" ] && ( echo "$canonical" | grep -q "utm_source" || echo "$canonical" | grep -q '?' ); then
        log_error "FAIL: /catalog/series/shacman/samosvaly/?utm_source=test canonical must be clean (got: ${canonical})"
        check_failed=1
    fi
    [ $check_failed -eq 0 ] && log_info "OK: No JSON-LD, canonical clean on catalog series+category with ?utm_source=test"
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 7: Product page with ?utm_source=test — 200, text/html, canonical clean (no utm), no Product/FAQPage/BreadcrumbList schema
if [ -z "${PRODUCT_SLUG:-}" ]; then
    log_info "Product slug not provided, skipping product utm check"
else
    log_info "Check 7: Product page /product/${PRODUCT_SLUG}/?utm_source=test (canonical clean, no schema)"
    if ! fetch_url "${BASE_URL}/product/${PRODUCT_SLUG}/?utm_source=test" 200 "Product page with utm_source" "/tmp/smoke_product_utm_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        canonical_count=$(grep -o 'rel="canonical"' "$FETCH_BODY_FILE" | wc -l | tr -d '[:space:]')
        expected_canonical="${BASE_URL}/product/${PRODUCT_SLUG}/"

        if [ "$canonical_count" -eq 0 ]; then
            log_error "FAIL: Canonical link not found on /product/${PRODUCT_SLUG}/?utm_source=test"
            check_failed=1
        elif [ "$canonical_count" -ne 1 ]; then
            log_error "FAIL: Multiple canonical links found ($canonical_count) on /product/${PRODUCT_SLUG}/?utm_source=test"
            check_failed=1
        elif echo "$canonical" | grep -q "utm_source\|utm_"; then
            log_error "FAIL: Canonical must not contain utm params: ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Canonical is clean: ${canonical}"
        fi

        if ! check_no_schema "$FETCH_BODY_FILE" "Product" "FAQPage" "BreadcrumbList"; then
            log_error "FAIL: /product/${PRODUCT_SLUG}/?utm_source=test must not contain page-level schema (Product, FAQPage, BreadcrumbList)"
            check_failed=1
        else
            log_info "OK: No Product/FAQPage/BreadcrumbList schema on URL with GET params"
        fi

        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi

    # Check 7b: Clean product URL must have Product schema
    log_info "Check 7b: Product page /product/${PRODUCT_SLUG}/ (clean URL) has Product schema"
    if ! fetch_url "${BASE_URL}/product/${PRODUCT_SLUG}/" 200 "Product page clean URL" "/tmp/smoke_product_clean_$$"; then
        check_failed=1
    else
        if ! check_has_schema "$FETCH_BODY_FILE" "Product"; then
            log_error "FAIL: /product/${PRODUCT_SLUG}/ (clean URL) must contain Product schema"
            check_failed=1
        else
            log_info "OK: Product schema present on clean URL"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
fi

# Check 8: One B3 hub (optional) — 200, canonical clean
if [ -n "${B3_HUB_PATH:-}" ]; then
    log_info "Check 8: B3 hub /${B3_HUB_PATH}/ returns 200, canonical clean"
    # Ensure path has no leading/trailing slash for URL construction
    path_trimmed="${B3_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "B3 hub ${path_trimmed}" "/tmp/smoke_b3_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on B3 hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: B3 hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: B3 hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: B3 hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "B3 hub path not provided, skipping Check 8"
fi

# Check 8b: Engine hub (optional) — 200, canonical clean
if [ -n "${ENGINE_HUB_PATH:-}" ]; then
    log_info "Check 8b: Engine hub /${ENGINE_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Engine hub ${path_trimmed}" "/tmp/smoke_engine_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on engine hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Engine hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Engine hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Engine hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Engine hub path not provided, skipping Check 8b"
fi

# Check 8c: Line hub (optional) — 200, canonical clean
if [ -n "${LINE_HUB_PATH:-}" ]; then
    log_info "Check 8c: Line hub /${LINE_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${LINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Line hub ${path_trimmed}" "/tmp/smoke_line_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on line hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Line hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Line hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Line hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Line hub path not provided, skipping Check 8c"
fi

# Check 8d: Single-product engine hub (optional) — expect 404
if [ -n "${SINGLE_ENGINE_404_PATH:-}" ]; then
    log_info "Check 8d: Single-product engine /${SINGLE_ENGINE_404_PATH}/ returns 404"
    path_trimmed="${SINGLE_ENGINE_404_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 404 "Single-product engine hub (expect 404)" "/tmp/smoke_single_engine_$$"; then
        check_failed=1
    else
        log_info "OK: Single-product engine hub returns 404 as expected"
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Single-engine 404 path not provided, skipping Check 8d"
fi

# Check 8e: Combo hub (optional) — 200, canonical clean
if [ -n "${COMBO_HUB_PATH:-}" ]; then
    log_info "Check 8e: Combo hub /${COMBO_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${COMBO_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Combo hub ${path_trimmed}" "/tmp/smoke_combo_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on combo hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Combo hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Combo hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Combo hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Combo hub path not provided, skipping Check 8e"
fi

# Check 8f: Engine+category hub (optional) — 200, canonical clean
if [ -n "${ENGINE_CATEGORY_HUB_PATH:-}" ]; then
    log_info "Check 8f: Engine+category hub /${ENGINE_CATEGORY_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${ENGINE_CATEGORY_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Engine+category hub ${path_trimmed}" "/tmp/smoke_engine_cat_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on engine+category hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Engine+category hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Engine+category hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Engine+category hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Engine+category hub path not provided, skipping Check 8f"
fi

# Check 8g: Line+engine hub (optional) — 200, canonical clean
if [ -n "${LINE_ENGINE_HUB_PATH:-}" ]; then
    log_info "Check 8g: Line+engine hub /${LINE_ENGINE_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${LINE_ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Line+engine hub ${path_trimmed}" "/tmp/smoke_line_engine_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on line+engine hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Line+engine hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Line+engine hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Line+engine hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Line+engine hub path not provided, skipping Check 8g"
fi

# Check 8h0a: MANDATORY — sitemap index must contain section shacman-category-engine and section URL must return 200/XML with URLs
log_info "Check 8h0a: Sitemap index must contain shacman-category-engine section"
if ! echo "$SITEMAP_XML" | grep -qE 'sitemap-shacman-category-engine\.xml'; then
    log_error "FAIL: sitemap index must include <loc>.../sitemap-shacman-category-engine.xml</loc> (section missing or wrong name)"
    check_failed=1
else
    log_info "OK: Sitemap index contains shacman-category-engine section"
fi
SECTION_CAT_ENGINE_URL="${BASE_URL%/}/sitemap-shacman-category-engine.xml"
section_body=""
section_http=""
if [ -n "$SECTION_CAT_ENGINE_URL" ]; then
    section_http=$(curl -sS -w "\n%{http_code}" -o "/tmp/smoke_section_cat_engine_$$.xml" --max-time 10 "$SECTION_CAT_ENGINE_URL" 2>/dev/null || echo "000")
    section_body=$(cat "/tmp/smoke_section_cat_engine_$$.xml" 2>/dev/null || true)
    rm -f "/tmp/smoke_section_cat_engine_$$.xml"
fi
section_code=$(echo "$section_http" | tail -n1)
if [ "$section_code" != "200" ]; then
    log_error "FAIL: GET ${SECTION_CAT_ENGINE_URL} must return 200 (got ${section_code})"
    check_failed=1
elif [ -z "$section_body" ] || ! echo "$section_body" | grep -qE '<urlset|<loc>'; then
    log_error "FAIL: sitemap-shacman-category-engine.xml must return XML with at least one <loc> or <urlset>"
    check_failed=1
else
    log_info "OK: sitemap-shacman-category-engine.xml returns 200 and contains URLs"
fi
# Extract first category+engine hub path from section for 8h0/8h0b/8h0c
CATEGORY_ENGINE_HUB_PATH="${CATEGORY_ENGINE_HUB_PATH:-}"
if [ -z "${CATEGORY_ENGINE_HUB_PATH:-}" ] && [ -n "$section_body" ]; then
    CATEGORY_ENGINE_HUB_PATH=$(echo "$section_body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E '/shacman/category/[^/]+/engine/[^/]+/?$' | head -n1 | sed -E 's|https?://[^/]+/||' | sed 's|/$||') || true
fi
if [ -z "${CATEGORY_ENGINE_HUB_PATH:-}" ] && [ -n "$section_body" ]; then
    CATEGORY_ENGINE_HUB_PATH=$(echo "$section_body" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E '/shacman/category/' | head -n1 | sed -E 's|https?://[^/]+/||' | sed 's|/$||') || true
fi

# Check 8h0: Category-first engine hub (new clean URL) — 200, SEO zone, canonical clean (required if section has URLs)
if [ -n "${CATEGORY_ENGINE_HUB_PATH:-}" ]; then
    log_info "Check 8h0: Category+engine hub /${CATEGORY_ENGINE_HUB_PATH}/ returns 200, SEO zone, canonical clean"
    path_trimmed="${CATEGORY_ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Category+engine hub ${path_trimmed}" "/tmp/smoke_cat_engine_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Category+engine hub canonical not found: ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Category+engine hub canonical should be clean: ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Category+engine hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Category+engine hub canonical clean: ${canonical}"
        fi
        if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
            log_error "FAIL: Category+engine hub must contain id=shacman-hub-seo-zone"
            check_failed=1
        else
            log_info "OK: Category+engine hub has shacman-hub-seo-zone"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    if [ $check_failed -eq 0 ] && [ -n "$section_body" ]; then
        log_warn "Category+engine section has no hub URLs yet (0 products combo); Check 8h0 skipped (section itself passed 8h0a)"
    else
        log_error "FAIL: Cannot run Check 8h0 — no category+engine hub path (section missing or empty)"
        check_failed=1
    fi
fi

# Check 8h0b: /shacman/category/<cat>/engine/<val>/?utm_source=test — no JSON-LD, canonical clean
if [ -n "${CATEGORY_ENGINE_HUB_PATH:-}" ]; then
    path_trimmed="${CATEGORY_ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    log_info "Check 8h0b: ${CATEGORY_ENGINE_HUB_PATH}/?utm_source=test no JSON-LD, canonical clean"
    if fetch_url "${BASE_URL}/${path_trimmed}/?utm_source=test" 200 "Category+engine hub with utm" "/tmp/smoke_cat_engine_utm_$$" 2>/dev/null; then
        if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
            log_error "FAIL: Category+engine hub ?utm_source=test must not contain application/ld+json"
            check_failed=1
        else
            log_info "OK: No JSON-LD on category+engine hub with ?utm_source=test"
        fi
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        if [ -n "$canonical" ] && ( echo "$canonical" | grep -q "utm_source\|?" ); then
            log_error "FAIL: Category+engine hub ?utm_source=test canonical must be clean: ${canonical}"
            check_failed=1
        else
            log_info "OK: Canonical clean on category+engine hub with utm"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
fi

# Check 8h0c: /shacman/category/<cat>/engine/<val>/?page=2 — noindex + self-canonical
if [ -n "${CATEGORY_ENGINE_HUB_PATH:-}" ]; then
    path_trimmed="${CATEGORY_ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    log_info "Check 8h0c: ${CATEGORY_ENGINE_HUB_PATH}/?page=2 noindex, self-canonical"
    if fetch_url "${BASE_URL}/${path_trimmed}/?page=2" 200 "Category+engine hub page=2" "/tmp/smoke_cat_engine_p2_$$" 2>/dev/null; then
        if ! check_robots "$FETCH_BODY_FILE" "noindex, follow"; then
            log_error "FAIL: Category+engine hub ?page=2 should have robots noindex, follow"
            check_failed=1
        else
            log_info "OK: noindex, follow on ?page=2"
        fi
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_p2="${BASE_URL}/${path_trimmed}/?page=2"
        if [ -n "$canonical" ] && [ "$canonical" != "$expected_p2" ]; then
            log_error "FAIL: Category+engine hub ?page=2 should have self-canonical (expected: ${expected_p2}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Self-canonical ?page=2"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
fi

# Check 8h: Category+formula hub (optional) — 200, canonical clean
if [ -n "${CATEGORY_FORMULA_HUB_PATH:-}" ]; then
    log_info "Check 8h: Category+formula hub /${CATEGORY_FORMULA_HUB_PATH}/ returns 200, canonical clean"
    path_trimmed="${CATEGORY_FORMULA_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Category+formula hub ${path_trimmed}" "/tmp/smoke_cat_formula_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on category+formula hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Category+formula hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Category+formula hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Category+formula hub canonical clean: ${canonical}"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
else
    log_info "Category+formula hub path not provided, skipping Check 8h"
fi

# Check 8i0: Category+line+formula hub (optional) — 200, canonical clean, SEO zone; ?utm_source= no schema; ?page=2 noindex + self-canonical
if [ -n "${CATEGORY_LINE_FORMULA_HUB_PATH:-}" ]; then
    log_info "Check 8i0: Category+line+formula hub /${CATEGORY_LINE_FORMULA_HUB_PATH}/ returns 200, canonical clean, SEO zone"
    path_trimmed="${CATEGORY_LINE_FORMULA_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    url="${BASE_URL}/${path_trimmed}/"
    if ! fetch_url "$url" 200 "Category+line+formula hub ${path_trimmed}" "/tmp/smoke_cat_line_formula_$$"; then
        check_failed=1
    else
        canonical=$(extract_canonical "$FETCH_BODY_FILE")
        expected_canonical="${BASE_URL}/${path_trimmed}/"
        if [ -z "$canonical" ]; then
            log_error "FAIL: Canonical link not found on category+line+formula hub ${url}"
            check_failed=1
        elif echo "$canonical" | grep -q "?"; then
            log_error "FAIL: Category+line+formula hub canonical should be clean (no query): ${canonical}"
            check_failed=1
        elif [ "$canonical" != "$expected_canonical" ]; then
            log_error "FAIL: Category+line+formula hub canonical mismatch (expected: ${expected_canonical}, got: ${canonical})"
            check_failed=1
        else
            log_info "OK: Category+line+formula hub canonical clean: ${canonical}"
        fi
        if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
            log_error "FAIL: Category+line+formula hub must contain SEO block (id=shacman-hub-seo-zone)"
            check_failed=1
        else
            log_info "OK: Category+line+formula hub has SEO zone"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    fi
    # 8i0b: ?utm_source= => no schema, canonical clean
    if [ -n "${CATEGORY_LINE_FORMULA_HUB_PATH:-}" ]; then
        path_trimmed="${CATEGORY_LINE_FORMULA_HUB_PATH#/}"
        path_trimmed="${path_trimmed%/}"
        log_info "Check 8i0b: ${CATEGORY_LINE_FORMULA_HUB_PATH}/?utm_source=test no JSON-LD, canonical clean"
        if fetch_url "${BASE_URL}/${path_trimmed}/?utm_source=test" 200 "Category+line+formula hub with utm" "/tmp/smoke_cat_line_formula_utm_$$" 2>/dev/null; then
            if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
                log_error "FAIL: Category+line+formula hub with ?utm_source= must not contain application/ld+json"
                check_failed=1
            else
                log_info "OK: No JSON-LD on category+line+formula hub with ?utm_source=test"
            fi
            canonical=$(extract_canonical "$FETCH_BODY_FILE")
            if [ -n "$canonical" ] && echo "$canonical" | grep -q "?"; then
                log_error "FAIL: Canonical on utm URL should be clean: ${canonical}"
                check_failed=1
            fi
            rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
        fi
    fi
    # 8i0c: ?page=2 => noindex + self-canonical
    if [ -n "${CATEGORY_LINE_FORMULA_HUB_PATH:-}" ]; then
        path_trimmed="${CATEGORY_LINE_FORMULA_HUB_PATH#/}"
        path_trimmed="${path_trimmed%/}"
        log_info "Check 8i0c: ${CATEGORY_LINE_FORMULA_HUB_PATH}/?page=2 noindex, self-canonical"
        if fetch_url "${BASE_URL}/${path_trimmed}/?page=2" 200 "Category+line+formula hub page=2" "/tmp/smoke_cat_line_formula_p2_$$" 2>/dev/null; then
            if ! grep -qE 'noindex.*follow|noindex,\s*follow' "$FETCH_BODY_FILE" 2>/dev/null; then
                log_error "FAIL: Category+line+formula hub ?page=2 must have noindex,follow"
                check_failed=1
            else
                log_info "OK: Category+line+formula hub ?page=2 has noindex,follow"
            fi
            canonical=$(extract_canonical "$FETCH_BODY_FILE")
            expected_canonical="${BASE_URL}/${path_trimmed}/?page=2"
            if [ -n "$canonical" ] && [ "$canonical" != "$expected_canonical" ]; then
                log_error "FAIL: Category+line+formula hub ?page=2 should be self-canonical (expected: ${expected_canonical}, got: ${canonical})"
                check_failed=1
            else
                log_info "OK: Category+line+formula hub ?page=2 self-canonical"
            fi
            rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
        fi
    fi
else
    log_info "Category+line+formula hub path not provided, skipping Check 8i0"
fi

# Check 8i1: Facet pages on clean URL have SEO block (id=shacman-hub-seo-zone)
# Formula facet (fixed path)
log_info "Check 8i1: Facet shacman/formula/8x4/ (clean URL) has SEO block"
if fetch_url "${BASE_URL}/shacman/formula/8x4/" 200 "Formula facet 8x4" "/tmp/smoke_facet_formula_$$" 2>/dev/null; then
    if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /shacman/formula/8x4/ must contain SEO block (id=shacman-hub-seo-zone)"
        check_failed=1
    else
        log_info "OK: Formula facet has SEO block"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
else
    log_warn "Skipping formula 8x4 SEO block check (page returned non-200)"
fi
# Engine facet (optional path) — SEO block on clean URL
if [ -n "${ENGINE_HUB_PATH:-}" ]; then
    log_info "Check 8i1: Facet ${ENGINE_HUB_PATH}/ (clean URL) has SEO block"
    path_trimmed="${ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    if fetch_url "${BASE_URL}/${path_trimmed}/" 200 "Engine facet" "/tmp/smoke_facet_engine_$$" 2>/dev/null; then
        if ! grep -q 'id="shacman-hub-seo-zone"' "$FETCH_BODY_FILE" 2>/dev/null; then
            log_error "FAIL: ${ENGINE_HUB_PATH}/ must contain SEO block (id=shacman-hub-seo-zone)"
            check_failed=1
        else
            log_info "OK: Engine facet has SEO block"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    else
        log_warn "Skipping engine facet SEO block check (page returned non-200)"
    fi
fi

# Check 8i2: Facet pages with ?utm_source=test have NO JSON-LD
log_info "Check 8i2: /shacman/formula/8x4/?utm_source=test has no JSON-LD"
if fetch_url "${BASE_URL}/shacman/formula/8x4/?utm_source=test" 200 "Formula facet with utm" "/tmp/smoke_facet_utm_$$" 2>/dev/null; then
    if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
        log_error "FAIL: /shacman/formula/8x4/?utm_source=test must not contain application/ld+json"
        check_failed=1
    else
        log_info "OK: No JSON-LD on formula facet with ?utm_source=test"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
else
    log_warn "Skipping formula utm check (page returned non-200)"
fi
if [ -n "${ENGINE_HUB_PATH:-}" ]; then
    path_trimmed="${ENGINE_HUB_PATH#/}"
    path_trimmed="${path_trimmed%/}"
    log_info "Check 8i2: ${ENGINE_HUB_PATH}/?utm_source=test has no JSON-LD"
    if fetch_url "${BASE_URL}/${path_trimmed}/?utm_source=test" 200 "Engine facet with utm" "/tmp/smoke_facet_eng_utm_$$" 2>/dev/null; then
        if grep -q 'application/ld+json' "$FETCH_BODY_FILE" 2>/dev/null; then
            log_error "FAIL: ${ENGINE_HUB_PATH}/?utm_source=test must not contain application/ld+json"
            check_failed=1
        else
            log_info "OK: No JSON-LD on engine facet with ?utm_source=test"
        fi
        rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
    else
        log_warn "Skipping engine facet utm check (page returned non-200)"
    fi
fi

# Check 8i: Any shacman hub with ?utm_source=test — clean canonical, NO schema
log_info "Check 8i: /shacman/?utm_source=test has clean canonical and no schema"
if ! fetch_url "${BASE_URL}/shacman/?utm_source=test" 200 "SHACMAN hub with utm" "/tmp/smoke_shacman_utm_$$"; then
    check_failed=1
else
    canonical=$(extract_canonical "$FETCH_BODY_FILE")
    if [ -z "$canonical" ]; then
        log_error "FAIL: Canonical link not found on /shacman/?utm_source=test"
        check_failed=1
    elif echo "$canonical" | grep -q "utm_source\|?"; then
        log_error "FAIL: /shacman/?utm_source=test canonical must be clean (no GET): ${canonical}"
        check_failed=1
    else
        log_info "OK: SHACMAN hub with utm has clean canonical: ${canonical}"
    fi
    if ! check_no_schema "$FETCH_BODY_FILE" "ItemList" "BreadcrumbList" "FAQPage"; then
        log_error "FAIL: /shacman/?utm_source=test must not contain page-level schema"
        check_failed=1
    else
        log_info "OK: No schema on SHACMAN hub URL with GET params"
    fi
    rm -f "$FETCH_HEADERS_FILE" "$FETCH_BODY_FILE"
fi

# Check 8j: All sitemap <loc> matching /shacman/engine/.+/in-stock/ must return 200 or 3xx (no 404)
log_info "Check 8j: Sitemap engine in-stock URLs must not return 404"
SITEMAP_FOR_8J="$(curl -fsSL "${BASE_URL%/}/sitemap.xml" 2>/dev/null || true)"
if [ -n "$SITEMAP_FOR_8J" ]; then
    if echo "$SITEMAP_FOR_8J" | grep -q '<sitemapindex'; then
        SUB_LOCS_8J=$(echo "$SITEMAP_FOR_8J" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -iE 'sitemap.*(shacman|hubs)' || true)
        for sub_url in $SUB_LOCS_8J; do
            SITEMAP_FOR_8J="$SITEMAP_FOR_8J
$(curl -fsSL "$sub_url" 2>/dev/null || true)"
        done
    fi
    ENGINE_IN_STOCK_URLS=$(echo "$SITEMAP_FOR_8J" | grep -oE '<loc>[^<]+</loc>' | sed 's/<loc>//;s/<\/loc>//g' | tr -d '\r' | grep -E '/shacman/engine/[^/]+/in-stock' || true)
    failed_engine_in_stock=""
    for loc_url in $ENGINE_IN_STOCK_URLS; do
        http_code=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$loc_url" 2>/dev/null || echo "000")
        if [ "$http_code" != "200" ] && [ "$http_code" != "301" ] && [ "$http_code" != "302" ]; then
            failed_engine_in_stock="${failed_engine_in_stock} ${loc_url}(${http_code})"
        fi
    done
    if [ -n "$failed_engine_in_stock" ]; then
        log_error "FAIL: Sitemap engine in-stock URLs must return 200/3xx, not 404:$failed_engine_in_stock"
        check_failed=1
    else
        engine_in_stock_count=$(echo "$ENGINE_IN_STOCK_URLS" | wc -w | tr -d '[:space:]')
        log_info "OK: All engine in-stock URLs in sitemap return 200/3xx (checked ${engine_in_stock_count:-0} URLs)"
    fi
else
    log_warn "Could not fetch sitemap for Check 8j, skipping"
fi

# Cleanup any remaining temp files
rm -f /tmp/smoke_*_$$_headers.txt /tmp/smoke_*_$$_body.txt 2>/dev/null || true

if [ $check_failed -eq 0 ]; then
    log_info "All SEO smoke checks passed!"
    exit 0
else
    log_error "Some SEO smoke checks failed (see errors above)"
    exit 1
fi
