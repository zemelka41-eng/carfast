#!/bin/bash
# Deploy script for CARFST Django project
# Usage: ./deploy_carfst.sh /path/to/release.zip
#
# This script:
# 1. Validates the ZIP archive contains required files
# 2. Extracts the archive (preserving .env, .venv, media/, staticfiles/, logs/)
# 3. Applies migrations
# 4. Collects static files
# 5. Restarts gunicorn service
# 6. Reloads nginx

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration (adjust these to your server setup)
DEST_CODE_DIR="${DEST_CODE_DIR:-/home/carfst/app/cursor_work}"
DEST_BIN_DIR="${DEST_BIN_DIR:-/home/carfst/app/bin}"
WORK_DIR="${WORK_DIR:-${DEST_CODE_DIR}}"
PROJECT_DIR="${PROJECT_DIR:-${DEST_CODE_DIR}}"
VENV_PATH="${VENV_PATH:-${DEST_CODE_DIR}/.venv}"
GUNICORN_SERVICE_OVERRIDE="${GUNICORN_SERVICE:-}"
GUNICORN_SERVICE_DEFAULT="carfst-gunicorn"
GUNICORN_SERVICE="${GUNICORN_SERVICE_OVERRIDE:-$GUNICORN_SERVICE_DEFAULT}"
PYTHON_CMD="${PYTHON_CMD:-${VENV_PATH}/bin/python}"
MANAGE_PY="${MANAGE_PY:-${DEST_CODE_DIR}/manage.py}"
COLLECTSTATIC_CLEAR="${COLLECTSTATIC_CLEAR:-0}"
ENV_FILE="${ENV_FILE:-}"
SYSTEM_ENV_FILE="/etc/carfst/carfst.env"
RUN_AS_USER="${RUN_AS_USER:-carfst}"
NGINX_CONF_SRC="${NGINX_CONF_SRC:-${DEST_CODE_DIR}/deploy/nginx.carfst.ru.conf}"
NGINX_HTTP_CONF_SRC="${NGINX_HTTP_CONF_SRC:-${DEST_CODE_DIR}/deploy/nginx.http.conf}"
NGINX_CONF_DST="${NGINX_CONF_DST:-/etc/nginx/sites-available/carfst.ru.conf}"
NGINX_CONF_LINK="${NGINX_CONF_LINK:-/etc/nginx/sites-enabled/carfst.ru.conf}"
NGINX_HTTP_CONF_DST="${NGINX_HTTP_CONF_DST:-/etc/nginx/conf.d/carfst-http.conf}"
NGINX_SITES_ENABLED_DIR="${NGINX_SITES_ENABLED_DIR:-/etc/nginx/sites-enabled}"
NGINX_SITES_DISABLED_DIR="${NGINX_SITES_DISABLED_DIR:-/etc/nginx/sites-disabled}"
NGINX_LEGACY_SITE="${NGINX_LEGACY_SITE:-${NGINX_SITES_ENABLED_DIR}/carfst.ru}"
STATIC_ROOT="${STATIC_ROOT:-${DEST_CODE_DIR}/staticfiles}"
STATIC_PUBLISH_DST="${STATIC_PUBLISH_DST:-/var/www/carfst/staticfiles}"
NGINX_STATIC_ROOT="${NGINX_STATIC_ROOT:-${STATIC_PUBLISH_DST}}"
MEDIA_PUBLISH_DST="${MEDIA_PUBLISH_DST:-/var/www/carfst/media}"

# Required files to check in ZIP
REQUIRED_FILES=(
    "templates/catalog/_product_card.html"
    "static/css/styles.css"
    "deploy/deploy_carfst.sh"
    "bin/deploy_carfst.sh"
    "scripts/smoke_seo.sh"
    "catalog/migrations/0016_add_site_settings_fields.py"
    "catalog/migrations/0026_alter_seo_faq_fields.py"
    "deploy/nginx.carfst.ru.conf"
    "deploy/nginx.http.conf"
)

# Required migration patterns (at least one should match)
MIGRATION_PATTERNS=(
    "catalog/migrations/0016*.py"
    "catalog/migrations/0017*.py"
)

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

trap 'log_error "Deploy failed at line ${LINENO}: ${BASH_COMMAND}"; exit 1' ERR

ensure_runtime_ownership() {
    local code_dir="$DEST_CODE_DIR"
    local db_path="${DEST_CODE_DIR}/db.sqlite3"

    log_info "Ensuring runtime ownership for ${code_dir}"
    sudo chown "${RUN_AS_USER}:${RUN_AS_USER}" "$code_dir"
    sudo chmod 775 "$code_dir"

    if [ -f "$db_path" ]; then
        log_info "Ensuring ownership for SQLite DB: ${db_path}"
        sudo chown "${RUN_AS_USER}:${RUN_AS_USER}" "$db_path"
        sudo chmod 664 "$db_path"
    else
        log_warn "SQLite DB file not found (skipping file permission fix): ${db_path}"
    fi

    if ! sudo -u "${RUN_AS_USER}" -H test -w "$code_dir"; then
        log_error "User ${RUN_AS_USER} cannot write to ${code_dir} (SQLite WAL/SHM needs this)."
        exit 1
    fi
}

# Output first product slug (or empty). Always uses venv python (${PYTHON_CMD}); env via source.
# Callers should capture with tr -d '\r' to avoid CRLF. Used by product_smoke_check and SEO smoke.
get_product_slug() {
    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "${RUN_AS_USER}" -H bash -lc "set -a; [ -n \"${ENV_FILE_RESOLVED:-}\" ] && . \"${ENV_FILE_RESOLVED}\"; set +a; cd \"${DEST_CODE_DIR}\"; \"${PYTHON_CMD}\" - <<'PY'
import os, django
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\",\"carfst_site.settings\")
django.setup()
from catalog.models import Product
print(Product.objects.values_list(\"slug\", flat=True).first() or \"\")
PY"
    else
        "${PYTHON_CMD}" - <<'PY' "$DEST_CODE_DIR"
import os, sys, django
os.chdir(sys.argv[1])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carfst_site.settings")
django.setup()
from catalog.models import Product
print(Product.objects.values_list("slug", flat=True).first() or "")
PY
    fi
}

product_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_warn "curl not found; skipping product smoke check"
        return
    fi

    local slug
    slug="$(get_product_slug 2>/dev/null | tr -d '\r' || true)"

    if [ -z "${slug:-}" ]; then
        log_info "Product smoke check skipped (no products in DB)"
        return
    fi

    log_info "Product smoke check: /product/${slug}/"
    if ! curl -sS -o /dev/null -w "%{http_code}" "https://carfst.ru/product/${slug}/" | grep -Eq "^(200|404)$"; then
        log_error "Product smoke check failed for slug: ${slug}"
        exit 1
    fi
}

seo_in_stock_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl not found; cannot run SEO in-stock smoke checks"
        exit 1
    fi

    log_info "SEO in-stock smoke check: redirect availability -> /catalog/in-stock/"
    local headers status_line status_code location
    headers="$(curl -sI "https://carfst.ru/catalog/?availability=in_stock&utm_source=test")"
    status_line="$(printf "%s" "$headers" | awk 'NR==1{print;exit}')"
    status_code="$(printf "%s" "$status_line" | awk '{print $2}')"
    location="$(printf "%s" "$headers" | awk -F': ' 'tolower($1)=="location"{print $2}' | tr -d '\r')"
    if [ "$status_code" != "301" ] && [ "$status_code" != "302" ]; then
        log_error "Expected 301/302 for availability redirect (got: ${status_code:-<empty>})"
        log_error "Status line: ${status_line:-<empty>}"
        log_error "Location: ${location:-<empty>}"
        exit 1
    fi
    if ! echo "$location" | grep -q "/catalog/in-stock/"; then
        log_error "Expected Location to end with /catalog/in-stock/ (got: ${location:-<empty>})"
        log_error "Status line: ${status_line:-<empty>}"
        exit 1
    fi

    log_info "SEO in-stock smoke check: /catalog/in-stock/ returns 200"
    local stock_headers stock_status_line stock_status_code
    stock_headers="$(curl -sI "https://carfst.ru/catalog/in-stock/")"
    stock_status_line="$(printf "%s" "$stock_headers" | awk 'NR==1{print;exit}')"
    stock_status_code="$(printf "%s" "$stock_status_line" | awk '{print $2}')"
    if [ "$stock_status_code" != "200" ]; then
        log_error "Expected 200 for /catalog/in-stock/ (got: ${stock_status_code:-<empty>})"
        log_error "Status line: ${stock_status_line:-<empty>}"
        exit 1
    fi

    log_info "SEO in-stock smoke check: homepage has no availability=in_stock"
    if curl -sL "https://carfst.ru/" | grep -q "availability=in_stock"; then
        log_error "Homepage contains availability=in_stock links"
        exit 1
    fi

    log_info "OK: SEO in-stock smoke checks passed"
}

restart_gunicorn() {
    GUNICORN_SERVICE_SELECTED="$(detect_gunicorn_service)"
    GUNICORN_STATUS_BEFORE="$(systemctl is-active "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || echo "unknown")"
    local old_pid old_ts
    old_pid="$(systemctl show -p MainPID --value "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || true)"
    old_ts="$(systemctl show -p ActiveEnterTimestamp --value "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || true)"
    log_info "Gunicorn service selected: ${GUNICORN_SERVICE_SELECTED}"
    log_info "Gunicorn status before: ${GUNICORN_STATUS_BEFORE}"
    log_info "Gunicorn PID before: ${old_pid:-<empty>}"
    log_info "Gunicorn ActiveEnterTimestamp before: ${old_ts:-<empty>}"
    log_info "Restarting gunicorn service: ${GUNICORN_SERVICE_SELECTED}"

    if ! sudo systemctl restart "${GUNICORN_SERVICE_SELECTED}"; then
        log_warn "systemctl restart failed, trying start..."
        sudo systemctl start "${GUNICORN_SERVICE_SELECTED}" || {
            log_error "Failed to start gunicorn service"
            exit 1
        }
    fi

    local attempt new_pid new_ts active_state
    for attempt in $(seq 1 60); do
        active_state="$(systemctl show -p ActiveState --value "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || true)"
        new_pid="$(systemctl show -p MainPID --value "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || true)"
        new_ts="$(systemctl show -p ActiveEnterTimestamp --value "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || true)"
        if [ "${active_state}" = "active" ] && [ -n "${new_pid}" ]; then
            log_info "Gunicorn PID after: ${new_pid:-<empty>}"
            log_info "Gunicorn ActiveEnterTimestamp after: ${new_ts:-<empty>}"
            break
        fi
        sleep 1
    done

    if ! systemctl is-active --quiet "${GUNICORN_SERVICE_SELECTED}"; then
        log_error "Gunicorn service is not active after restart/start"
        systemctl status "${GUNICORN_SERVICE_SELECTED}" --no-pager || true
        exit 1
    fi

    if [ -n "${old_pid}" ] && [ -n "${new_pid}" ] && [ "${new_pid}" = "${old_pid}" ]; then
        log_error "Gunicorn did not restart (PID unchanged)"
        journalctl -u "${GUNICORN_SERVICE_SELECTED}" -n 200 --no-pager || true
        exit 1
    fi

    if [ -n "${old_ts}" ] && [ -n "${new_ts}" ] && [ "${new_ts}" = "${old_ts}" ]; then
        log_error "Gunicorn did not restart (ActiveEnterTimestamp unchanged)"
        journalctl -u "${GUNICORN_SERVICE_SELECTED}" -n 200 --no-pager || true
        exit 1
    fi

    wait_gunicorn_readiness || exit 1

    # Mandatory HTTP smoke right after restart: new code must respond
    deploy_http_smoke "${GUNICORN_SERVICE_SELECTED}" || exit 1
}

# Minimal HTTP smoke after gunicorn restart: /__version__/, /shacman/, /sitemap.xml. On failure: journalctl and exit 1.
deploy_http_smoke() {
    local gunicorn_service="${1:-carfst-gunicorn}"
    local base_url="https://${CANONICAL_HOST:-carfst.ru}"
    local code headers ct

    log_info "Deploy HTTP smoke: GET ${base_url}/__version__/"
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${base_url}/__version__/" 2>/dev/null || echo "000")"
    if [ "$code" != "200" ]; then
        log_error "Deploy smoke failed: GET ${base_url}/__version__/ returned HTTP ${code} (expected 200)"
        log_error "Last 200 lines of journalctl -u ${gunicorn_service}:"
        journalctl -u "${gunicorn_service}" -n 200 --no-pager 2>/dev/null || true
        exit 1
    fi
    log_info "OK: /__version__/ returned 200"

    log_info "Deploy HTTP smoke: GET ${base_url}/shacman/"
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${base_url}/shacman/" 2>/dev/null || echo "000")"
    if [ "$code" != "200" ]; then
        log_error "Deploy smoke failed: GET ${base_url}/shacman/ returned HTTP ${code} (expected 200)"
        log_info "Retrying with X-Carfast-Diag: 1 to capture diagnostic headers:"
        headers="$(curl -sSI --max-time 10 -H 'X-Carfast-Diag: 1' "${base_url}/shacman/" 2>/dev/null || true)"
        printf "%s" "$headers" | grep -i '^X-Diag-' || true
        log_error "Last 200 lines of journalctl -u ${gunicorn_service}:"
        journalctl -u "${gunicorn_service}" -n 200 --no-pager 2>/dev/null || true
        exit 1
    fi
    log_info "OK: /shacman/ returned 200"

    log_info "Deploy HTTP smoke: GET ${base_url}/sitemap.xml"
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "${base_url}/sitemap.xml" 2>/dev/null || echo "000")"
    if [ "$code" != "200" ]; then
        log_error "Deploy smoke failed: GET ${base_url}/sitemap.xml returned HTTP ${code} (expected 200)"
        log_error "Last 200 lines of journalctl -u ${gunicorn_service}:"
        journalctl -u "${gunicorn_service}" -n 200 --no-pager 2>/dev/null || true
        exit 1
    fi
    headers="$(curl -sSI --max-time 10 "${base_url}/sitemap.xml" 2>/dev/null || true)"
    ct="$(printf "%s" "$headers" | grep -i '^Content-Type:' | head -n1 || true)"
    if ! printf "%s" "$ct" | grep -qi 'xml'; then
        log_error "Deploy smoke failed: GET ${base_url}/sitemap.xml Content-Type does not contain xml: ${ct:-<empty>}"
        log_error "Last 200 lines of journalctl -u ${gunicorn_service}:"
        journalctl -u "${gunicorn_service}" -n 200 --no-pager 2>/dev/null || true
        exit 1
    fi
    log_info "OK: /sitemap.xml returned 200 and Content-Type contains xml"
}

wait_gunicorn_readiness() {
    local url="https://carfst.ru/__version__/"
    log_info "Waiting for gunicorn readiness: ${url}"
    local attempt out code body body_len
    for attempt in $(seq 1 20); do
        out="$(curl -sS --max-time 2 -o - -w '\n%{http_code}' "$url" 2>/dev/null || true)"
        code="$(printf "%s" "$out" | tail -n1 | tr -d '\r')"
        body="$(printf "%s" "$out" | sed '$d')"
        body_len="$(printf "%s" "$body" | wc -c | tr -d '[:space:]')"
        log_info "Readiness attempt ${attempt}/20: http=${code:-<empty>} len=${body_len:-0}"
        if [ "$code" = "200" ] && [ -n "$body" ]; then
            log_info "Gunicorn is responding"
            return 0
        fi
        sleep 1
    done
    log_error "Gunicorn readiness failed after 20 attempts: ${url}"
    return 1
}

version_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl not found; cannot run version smoke check"
        exit 1
    fi

    if [ ! -f "${DEST_CODE_DIR}/BUILD_ID" ]; then
        log_error "BUILD_ID not found at ${DEST_CODE_DIR}/BUILD_ID"
        exit 1
    fi

    local expected_build
    expected_build="$(cat "${DEST_CODE_DIR}/BUILD_ID" | tr -d '\r\n')"

    # Check via nginx (public URL)
    log_info "Version smoke check: BUILD_ID via nginx (https://carfst.ru/)"
    local nginx_headers nginx_build_id
    nginx_headers="$(curl -sSI --max-time 5 "https://carfst.ru/" 2>/dev/null || true)"
    nginx_build_id="$(printf "%s" "$nginx_headers" | grep -i "x-build-id:" | awk -F': ' '{print $2}' | tr -d '\r\n ' || true)"
    if [ -z "${nginx_build_id:-}" ]; then
        log_error "X-Build-ID header missing in nginx response"
        exit 1
    fi
    if [ "$expected_build" != "$nginx_build_id" ]; then
        log_error "Build id mismatch via nginx (expected: ${expected_build}, got: ${nginx_build_id})"
        exit 1
    fi
    log_info "OK: nginx X-Build-ID matches ${expected_build}"

    # Check directly via gunicorn (bypass nginx)
    log_info "Version smoke check: BUILD_ID via gunicorn (127.0.0.1:8001)"
    local gunicorn_port="8001"
    local gunicorn_headers gunicorn_build_id
    # Try to detect gunicorn port from service or use default
    if systemctl show "${GUNICORN_SERVICE_SELECTED:-carfst-gunicorn}" 2>/dev/null | grep -q "bind.*8001"; then
        gunicorn_port="8001"
    elif systemctl show "${GUNICORN_SERVICE_SELECTED:-carfst-gunicorn}" 2>/dev/null | grep -q "bind.*8000"; then
        gunicorn_port="8000"
    fi
    
    gunicorn_headers="$(curl -sSI --max-time 2 -H 'Host: carfst.ru' -H 'X-Forwarded-Proto: https' "http://127.0.0.1:${gunicorn_port}/" 2>/dev/null || true)"
    if [ -n "${gunicorn_headers:-}" ]; then
        gunicorn_build_id="$(printf "%s" "$gunicorn_headers" | grep -i "x-build-id:" | awk -F': ' '{print $2}' | tr -d '\r\n ' || true)"
        if [ -n "${gunicorn_build_id:-}" ]; then
            if [ "$expected_build" != "$gunicorn_build_id" ]; then
                log_error "Build id mismatch via gunicorn (expected: ${expected_build}, got: ${gunicorn_build_id})"
                log_error "Some gunicorn workers may still be running old code"
                exit 1
            fi
            log_info "OK: gunicorn X-Build-ID matches ${expected_build}"
        else
            log_warn "X-Build-ID header missing in gunicorn response (port ${gunicorn_port})"
        fi
    else
        log_warn "Could not connect to gunicorn directly (port ${gunicorn_port}), skipping direct check"
    fi

    # Also check /__version__/ endpoint for backward compatibility
    log_info "Version smoke check: BUILD_ID vs /__version__/"
    local response parsed raw_preview deployed_build
    response="$(curl -sS --max-time 2 "https://carfst.ru/__version__/" 2>/dev/null || true)"
    raw_preview="$(printf "%s" "$response" | head -c 200 | tr -d '\r\n')"
    if [ -z "${response:-}" ]; then
        log_error "Version smoke check failed: empty __version__ response"
        exit 1
    fi

    parsed="$(printf "%s" "$response" | sed -nE 's/.*"build_id"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' | head -n1)"
    if [ -z "${parsed:-}" ]; then
        parsed="$(printf "%s" "$response" | tr -d '\r\n' | head -c 200)"
        if printf "%s" "$parsed" | grep -q '[{}:]'; then
            log_error "Version smoke check failed: cannot parse build_id"
            log_error "Raw /__version__/ response: ${raw_preview:-<empty>}"
            exit 1
        fi
    fi

    deployed_build="$parsed"
    if [ "$expected_build" != "$deployed_build" ]; then
        log_error "Build id mismatch (expected: ${expected_build}, got: ${deployed_build})"
        log_error "Raw /__version__/ response: ${raw_preview:-<empty>}"
        exit 1
    fi

    log_info "OK: build id matches ${expected_build}"
}

# Mandatory: /shacman/ must return 200 (never optional; deploy fails on 404)
shacman_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl not found; cannot run SHACMAN hub smoke check"
        exit 1
    fi
    local base_url="https://${CANONICAL_HOST:-carfst.ru}"
    local shacman_url="${base_url}/shacman/"
    log_info "SHACMAN smoke: GET ${shacman_url} (must be 200)"
    local code
    code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 10 "$shacman_url" 2>/dev/null || echo "000")"
    if [ "$code" != "200" ]; then
        log_error "SHACMAN hub smoke failed: ${shacman_url} returned HTTP ${code} (expected 200)"
        exit 1
    fi
    log_info "OK: /shacman/ returned 200"
}

health_smoke_check() {
    if [ "${SKIP_HEALTH_SMOKE:-0}" = "1" ]; then
        log_warn "Health smoke skipped (SKIP_HEALTH_SMOKE=1)"
        return
    fi
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl not found; cannot run health smoke check"
        exit 1
    fi
    local base_url="${1:-https://${CANONICAL_HOST:-carfst.ru}}"
    local health_url="${base_url}/health/"
    local deep_url="${base_url}/health/?deep=1"
    local tmp_body
    tmp_body="$(mktemp)"
    trap "rm -f \"${tmp_body}\"" RETURN

    log_info "Health smoke: GET ${health_url} (default contract)"
    local code headers body
    headers="$(curl -sS -w "\n%{http_code}" --max-time 10 -D - -o "$tmp_body" "$health_url" 2>&1)"
    code="$(printf "%s" "$headers" | tail -n1)"
    body="$(cat "$tmp_body")"
    if [ "$code" != "200" ]; then
        log_error "Health smoke failed: ${health_url} returned HTTP ${code}"
        log_error "Headers (first 15 lines):"
        printf "%s" "$headers" | head -n 15 | while read -r line; do log_error "  $line"; done
        log_error "Body (first 20 lines):"
        printf "%s" "$body" | head -n 20 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    if ! printf "%s" "$headers" | head -n 20 | grep -qi "content-type:.*application/json"; then
        log_error "Health smoke failed: ${health_url} Content-Type is not application/json"
        printf "%s" "$headers" | head -n 15 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    local status reason
    status="$(printf "%s" "$body" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    o = d.get('checks', {}).get('orphaned_media', {})
    print(o.get('status', ''))
except Exception as e:
    print('PARSE_ERROR:', e, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null)" || {
        log_error "Health smoke failed: could not parse JSON from ${health_url}"
        log_error "Body (first 20 lines):"
        printf "%s" "$body" | head -n 20 | while read -r line; do log_error "  $line"; done
        exit 1
    }
    reason="$(printf "%s" "$body" | python3 -c "
import sys, json
d = json.load(sys.stdin)
o = d.get('checks', {}).get('orphaned_media', {})
det = o.get('detail') or {}
print(det.get('reason', ''))
" 2>/dev/null)"
    if [ "$status" != "skipped" ]; then
        log_error "Health smoke failed: orphaned_media.status expected 'skipped', got '${status}'"
        log_error "Body (first 30 lines):"
        printf "%s" "$body" | head -n 30 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    if [ -z "$(printf "%s" "$reason" | tr -d '\r\n ')" ]; then
        log_error "Health smoke failed: orphaned_media.detail.reason is empty"
        log_error "Body (first 30 lines):"
        printf "%s" "$body" | head -n 30 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    log_info "OK: default health contract (orphaned_media skipped, reason present)"

    log_info "Health smoke: GET ${deep_url} (deep contract)"
    headers="$(curl -sS -w "\n%{http_code}" --max-time 15 -D - -o "$tmp_body" "$deep_url" 2>&1)"
    code="$(printf "%s" "$headers" | tail -n1)"
    body="$(cat "$tmp_body")"
    if [ "$code" != "200" ] && [ "$code" != "503" ]; then
        log_error "Health smoke failed: ${deep_url} returned HTTP ${code}"
        log_error "Headers (first 15 lines):"
        printf "%s" "$headers" | head -n 15 | while read -r line; do log_error "  $line"; done
        log_error "Body (first 20 lines):"
        printf "%s" "$body" | head -n 20 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    if ! printf "%s" "$body" | python3 -c "
import sys, json
d = json.load(sys.stdin)
o = d.get('checks', {}).get('orphaned_media', {})
det = o.get('detail')
if det is None:
    print('MISSING_DETAIL', file=sys.stderr)
    sys.exit(1)
for k in ('cached', 'cache_age_seconds', 'missing_files', 'unreferenced_files'):
    if k not in det:
        print('MISSING_KEY:', k, file=sys.stderr)
        sys.exit(1)
" 2>/dev/null; then
        log_error "Health smoke failed: deep response orphaned_media.detail missing or missing required keys (cached, cache_age_seconds, missing_files, unreferenced_files)"
        log_error "Body (first 40 lines):"
        printf "%s" "$body" | head -n 40 | while read -r line; do log_error "  $line"; done
        exit 1
    fi
    log_info "OK: deep health contract (detail has cached, cache_age_seconds, missing_files, unreferenced_files)"
}

disable_legacy_sites_enabled() {
    if [ ! -e "$NGINX_LEGACY_SITE" ]; then
        return
    fi

    local ts
    ts="$(date +%Y%m%d%H%M%S)"
    sudo mkdir -p "$NGINX_SITES_DISABLED_DIR"
    local target="${NGINX_SITES_DISABLED_DIR}/carfst.ru.disabled.${ts}"

    if [ -L "$NGINX_LEGACY_SITE" ]; then
        log_info "Disabling legacy nginx link: ${NGINX_LEGACY_SITE} -> ${target}"
        sudo mv "$NGINX_LEGACY_SITE" "$target"
        return
    fi

    if [ -f "$NGINX_LEGACY_SITE" ]; then
        log_info "Disabling legacy nginx file: ${NGINX_LEGACY_SITE} -> ${target}"
        sudo mv "$NGINX_LEGACY_SITE" "$target"
        return
    fi

    log_warn "Legacy nginx path exists but is not a file/link: ${NGINX_LEGACY_SITE} (unlinking)"
    sudo rm -f "$NGINX_LEGACY_SITE"
}

assert_sites_enabled_clean() {
    local path
    local basename
    for path in "${NGINX_SITES_ENABLED_DIR}"/carfst.ru*; do
        if [ ! -e "$path" ]; then
            continue
        fi
        basename="$(basename "$path")"
        if [ "$basename" != "carfst.ru.conf" ]; then
            log_error "Unexpected nginx site in sites-enabled: ${path}"
            log_error "Only carfst.ru.conf is allowed in ${NGINX_SITES_ENABLED_DIR}"
            exit 1
        fi
    done
}

# Diagnostic: log state of conf.d and carfst-http.conf (before/after steps that touch nginx).
log_nginx_conf_d_state() {
    local label="${1:-conf.d}"
    local conf_d_dir
    local http_dst
    http_dst="${NGINX_HTTP_CONF_DST:-/etc/nginx/conf.d/carfst-http.conf}"
    conf_d_dir="$(dirname "$http_dst")"
    log_info "[nginx diag] ${label}: ls -la ${conf_d_dir}"
    sudo ls -la "$conf_d_dir" 2>/dev/null || true
    if sudo test -e "$http_dst" 2>/dev/null; then
        log_info "[nginx diag] ${label}: stat ${http_dst}"
        sudo stat "$http_dst" 2>/dev/null || true
        log_info "[nginx diag] ${label}: first 20 lines of ${http_dst}"
        sudo sed -n '1,20p' "$http_dst" 2>/dev/null || true
    else
        log_warn "[nginx diag] ${label}: ${http_dst} does not exist"
    fi
}

# Validate carfst-http.conf by content: limit_req_zone ... zone=admin_login:<NONZERO> ... and limit_req_status 429.
# NONZERO: 10m, 256k, 1g etc; not 0m, not empty. Returns 0 if valid.
validate_carfst_http_content() {
    local f="$1"
    local content
    content="$(sudo cat "$f" 2>/dev/null)" || return 1
    [ -n "$content" ] || return 1
    if printf '%s' "$content" | grep -qE 'zone=admin_login:0m|zone=admin_login:[[:space:]]|zone=admin_login:$'; then
        return 1
    fi
    if ! printf '%s' "$content" | grep -qE 'zone=admin_login:[1-9][0-9]*[mkg]'; then
        return 1
    fi
    if ! printf '%s' "$content" | grep -q 'limit_req_status 429'; then
        return 1
    fi
    return 0
}

# Ensure /etc/nginx/conf.d exists and carfst-http.conf exists and is valid (by content). Create/repair with fallback if not.
ensure_carfst_http_conf() {
    log_nginx_conf_d_state "ensure_carfst_http_conf START"
    local dst="${NGINX_HTTP_CONF_DST:-/etc/nginx/conf.d/carfst-http.conf}"
    local conf_d_dir
    conf_d_dir="$(dirname "$dst")"
    sudo mkdir -p "$conf_d_dir"
    if [ -f "$dst" ] 2>/dev/null || sudo test -f "$dst" 2>/dev/null; then
        if validate_carfst_http_content "$dst"; then
            log_info "carfst-http.conf present and valid: ${dst}"
            log_nginx_conf_d_state "ensure_carfst_http_conf END (valid)"
            return 0
        fi
        log_warn "carfst-http.conf invalid (zone size or limit_req_status); overwriting with fallback"
    else
        log_warn "carfst-http.conf missing; creating with fallback"
    fi
    sudo bash -c "cat > \"$dst\" << 'ENDOFFILE'
limit_req_zone \$binary_remote_addr zone=admin_login:10m rate=10r/m;
limit_req_status 429;
ENDOFFILE"
    sudo chmod 644 "$dst"
    if ! validate_carfst_http_content "$dst"; then
        log_error "carfst-http.conf fallback validation failed"
        return 1
    fi
    log_info "Created/updated ${dst} with valid fallback content"
    log_nginx_conf_d_state "ensure_carfst_http_conf END (repaired)"
}

publish_staticfiles() {
    log_nginx_conf_d_state "publish_staticfiles BEFORE"
    local src="${STATIC_ROOT}/"

    if [ ! -d "$src" ]; then
        log_error "Staticfiles directory not found: ${src}"
        exit 1
    fi

    log_info "Publishing staticfiles to nginx: ${STATIC_ROOT}/ -> ${NGINX_STATIC_ROOT}/"
    if ! command -v rsync >/dev/null 2>&1; then
        log_error "rsync is required but not found."
        exit 1
    fi

    sudo mkdir -p "$NGINX_STATIC_ROOT"
    sudo rsync -a --delete "$src" "${NGINX_STATIC_ROOT}/"
    sudo find "$NGINX_STATIC_ROOT" -type d -exec chmod 755 {} \;
    sudo find "$NGINX_STATIC_ROOT" -type f -exec chmod 644 {} \;

    log_info "Verifying nginx config and reloading nginx after static publish..."
    if ! sudo nginx -t; then
        log_error "nginx -t failed after publishing staticfiles"
        exit 1
    fi
    if ! sudo systemctl reload nginx; then
        log_error "systemctl reload nginx failed after publishing staticfiles"
        exit 1
    fi
    log_info "Nginx reloaded successfully"
    log_nginx_conf_d_state "publish_staticfiles AFTER"
}

ensure_media_alias() {
    local media_src="${DEST_CODE_DIR}/media"
    local publish_dir_root
    publish_dir_root="$(dirname "$MEDIA_PUBLISH_DST")"

    log_info "Ensuring media publish path: ${MEDIA_PUBLISH_DST} -> ${media_src}"
    sudo mkdir -p "$publish_dir_root"

    if [ ! -d "$media_src" ]; then
        log_warn "Media source directory missing, creating: ${media_src}"
        sudo mkdir -p "$media_src"
        sudo chown "${RUN_AS_USER}:${RUN_AS_USER}" "$media_src"
        sudo chmod 775 "$media_src"
    fi

    if [ -L "$MEDIA_PUBLISH_DST" ]; then
        local target
        target="$(readlink -f "$MEDIA_PUBLISH_DST" || true)"
        if [ "$target" != "$media_src" ]; then
            log_warn "Media symlink points to ${target:-<unknown>}, updating to ${media_src}"
            sudo ln -sfn "$media_src" "$MEDIA_PUBLISH_DST"
        else
            log_info "Media symlink already points to ${media_src}"
        fi
        return
    fi

    if [ -e "$MEDIA_PUBLISH_DST" ]; then
        if [ -d "$MEDIA_PUBLISH_DST" ]; then
            log_warn "Media publish path is a directory (not a symlink): ${MEDIA_PUBLISH_DST}"
            log_warn "Manual migration recommended to ${media_src}"
            return
        fi
        log_warn "Media publish path exists but is not a directory/symlink: ${MEDIA_PUBLISH_DST}"
        return
    fi

    log_info "Creating media symlink: ${MEDIA_PUBLISH_DST} -> ${media_src}"
    sudo ln -s "$media_src" "$MEDIA_PUBLISH_DST"
}

staticfiles_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_error "curl is required for staticfiles smoke check."
        exit 1
    fi

    local base_url="${1:-https://${CANONICAL_HOST:-carfst.ru}}"

    log_info "Staticfiles smoke check: ${base_url}/static/admin/css/base.css"
    if ! curl -fsSI "${base_url}/static/admin/css/base.css" >/dev/null; then
        log_error "Staticfiles smoke check failed: ${base_url}/static/admin/css/base.css"
        exit 1
    fi

    log_info "Staticfiles smoke check: ${base_url}/static/css/styles.css"
    if ! curl -fsSI "${base_url}/static/css/styles.css" >/dev/null; then
        log_error "Staticfiles smoke check failed: ${base_url}/static/css/styles.css"
        exit 1
    fi

    # Hero: always check direct v3 URL > 50KB; if homepage has hashed URL, check that too > 50KB
    log_info "Staticfiles smoke check: /static/img/hero/shacman_mein.v3.webp (content-length > 50KB)"
    local hero_headers content_length
    hero_headers="$(curl -sSI --max-time 10 "${base_url}/static/img/hero/shacman_mein.v3.webp" 2>/dev/null || true)"
    content_length="$(printf "%s" "$hero_headers" | grep -i '^content-length:' | awk '{print $2}' | tr -d '\r\n ')"

    if [ -z "${content_length:-}" ]; then
        log_error "Staticfiles smoke check failed: hero shacman_mein.v3.webp returned no content-length"
        exit 1
    fi

    if [ "${content_length:-0}" -lt 50000 ] 2>/dev/null; then
        log_error "Staticfiles smoke check failed: hero content-length ${content_length} < 50000"
        exit 1
    fi

    log_info "OK: hero shacman_mein.v3.webp content-length ${content_length} (> 50KB)"

    local homepage_html hashed_hero_url
    homepage_html="$(curl -sS --compressed --max-time 15 "${base_url}/" 2>/dev/null || true)"
    hashed_hero_url="$(printf "%s" "$homepage_html" | grep -oE '/static/img/hero/shacman_mein\.v3\.[a-f0-9]+\.webp' | head -n1)"

    if [ -n "${hashed_hero_url:-}" ]; then
        log_info "Staticfiles smoke check: hashed hero from homepage (content-length > 50KB)"
        hero_headers="$(curl -sSI --max-time 10 "${base_url}${hashed_hero_url}" 2>/dev/null || true)"
        content_length="$(printf "%s" "$hero_headers" | grep -i '^content-length:' | awk '{print $2}' | tr -d '\r\n ')"

        if [ -z "${content_length:-}" ]; then
            log_error "Staticfiles smoke check failed: hashed hero returned no content-length (URL: ${hashed_hero_url})"
            exit 1
        fi

        if [ "${content_length:-0}" -lt 50000 ] 2>/dev/null; then
            log_error "Staticfiles smoke check failed: hashed hero content-length ${content_length} < 50000 (stale?)"
            log_error "Hashed URL: ${hashed_hero_url}"
            exit 1
        fi

        log_info "OK: hashed hero content-length ${content_length} (> 50KB)"
    fi

    # Verify hero CSS (object-position) is in published hashed styles
    local css_dir="${STATIC_PUBLISH_DST:-/var/www/carfst/staticfiles}/css"
    local latest_css
    if [ -d "$css_dir" ]; then
        latest_css="$(ls -1 "${css_dir}"/styles.*.css 2>/dev/null | tail -n 1)"
        if [ -n "${latest_css:-}" ] && [ -f "$latest_css" ]; then
            if ! grep -q "hero--shacman" "$latest_css" 2>/dev/null; then
                log_error "Staticfiles smoke check: hero--shacman not found in $(basename "$latest_css")"
                exit 1
            fi
            if ! grep -qE 'object-position:[[:space:]]*50%[[:space:]]*(20|30|55)%' "$latest_css" 2>/dev/null; then
                log_warn "Hero object-position (50% 20%/30%/55%%) not found in $(basename "$latest_css"); check static/css/styles.css"
            else
                log_info "OK: hero--shacman and object-position present in $(basename "$latest_css")"
            fi
        fi
    fi
}

media_smoke_check() {
    if ! command -v curl >/dev/null 2>&1; then
        log_warn "curl not found; skipping media smoke check"
        return
    fi

    local env_file
    env_file="${ENV_FILE_RESOLVED:-/etc/carfst/carfst.env}"

    local media_url
    media_url="$(sudo -u "${RUN_AS_USER}" -H bash -lc "set -a; [ -f \"${env_file}\" ] && . \"${env_file}\"; set +a; cd \"${DEST_CODE_DIR}\"; \"${PYTHON_CMD}\" - <<'PY'
import os, django
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\",\"carfst_site.settings\")
django.setup()
from catalog.models import ProductImage
image = ProductImage.objects.first()
print(getattr(getattr(image, \"image\", None), \"url\", \"\") if image else \"\")
PY")"

    if [ -z "${media_url:-}" ]; then
        log_info "Media smoke check skipped (no ProductImage in DB)"
        return
    fi

    log_info "Media smoke check: ${media_url}"
    local code
    code="$(curl -sS -o /dev/null -w "%{http_code}" "https://carfst.ru${media_url}")"
    if [ "${code}" != "200" ]; then
        log_error "Media smoke check failed (${code}): https://carfst.ru${media_url}"
        exit 1
    fi
}

preflight_nginx_config() {
    local src_site="$1"
    local src_http="$2"

    if [ ! -f "$src_site" ]; then
        log_error "Nginx site config source not found: ${src_site}"
        exit 1
    fi
    if [ ! -f "$src_http" ]; then
        log_error "Nginx http config source not found: ${src_http}"
        exit 1
    fi

    if grep -q 'admin_login' "$src_http" 2>/dev/null; then
        if grep -qE 'zone=admin_login:0m|zone=admin_login:[[:space:]]|zone=admin_login:$' "$src_http" 2>/dev/null; then
            log_error "Preflight: nginx http config has zero/missing admin_login zone size"
            exit 1
        fi
        if ! grep -qE 'zone=admin_login:[1-9][0-9]*[mkg]' "$src_http" 2>/dev/null; then
            log_error "Preflight: nginx http config must have zone=admin_login:10m (or 256k, 1g)"
            exit 1
        fi
    fi

    log_info "Preflight nginx config (staged + nginx -t)"
    sudo mkdir -p "$(dirname "$NGINX_CONF_DST")" "$(dirname "$NGINX_CONF_LINK")" "$(dirname "$NGINX_HTTP_CONF_DST")"

    local staged_site="${NGINX_CONF_DST}.tmp"
    local staged_http="${NGINX_HTTP_CONF_DST}.tmp"
    local site_link_backup=""
    local http_backup=""
    local http_backup_type="none"

    if [ -e "$NGINX_CONF_LINK" ]; then
        site_link_backup="$(readlink -f "$NGINX_CONF_LINK" || true)"
    fi

    if [ -e "$NGINX_HTTP_CONF_DST" ]; then
        if [ -L "$NGINX_HTTP_CONF_DST" ]; then
            http_backup="$(readlink -f "$NGINX_HTTP_CONF_DST" || true)"
            http_backup_type="link"
        else
            http_backup="${NGINX_HTTP_CONF_DST}.pretest.$(date +%Y%m%d%H%M%S)"
            sudo cp "$NGINX_HTTP_CONF_DST" "$http_backup"
            http_backup_type="file"
        fi
    fi

    sudo cp "$src_site" "$staged_site"
    sudo cp "$src_http" "$staged_http"
    sudo chmod 644 "$staged_site" "$staged_http"

    sudo ln -sfn "$staged_site" "$NGINX_CONF_LINK"
    sudo ln -sfn "$staged_http" "$NGINX_HTTP_CONF_DST"

    if ! sudo nginx -t; then
        log_error "Nginx config preflight failed."
        if [ -n "$site_link_backup" ]; then
            sudo ln -sfn "$site_link_backup" "$NGINX_CONF_LINK"
        else
            sudo rm -f "$NGINX_CONF_LINK"
        fi
        if [ "$http_backup_type" = "link" ] && [ -n "$http_backup" ]; then
            sudo ln -sfn "$http_backup" "$NGINX_HTTP_CONF_DST"
        elif [ "$http_backup_type" = "file" ]; then
            sudo cp "$http_backup" "$NGINX_HTTP_CONF_DST"
            sudo rm -f "$http_backup"
        else
            sudo rm -f "$NGINX_HTTP_CONF_DST"
        fi
        sudo rm -f "$staged_site" "$staged_http"
        exit 1
    fi

    if [ -n "$site_link_backup" ] && [ -e "$site_link_backup" ]; then
        sudo ln -sfn "$site_link_backup" "$NGINX_CONF_LINK"
    else
        sudo rm -f "$NGINX_CONF_LINK"
    fi
    if [ "$http_backup_type" = "link" ] && [ -n "$http_backup" ] && [ -e "$http_backup" ]; then
        sudo ln -sfn "$http_backup" "$NGINX_HTTP_CONF_DST"
    elif [ "$http_backup_type" = "file" ] && [ -f "$http_backup" ]; then
        sudo cp "$http_backup" "$NGINX_HTTP_CONF_DST"
        sudo rm -f "$http_backup"
    else
        sudo rm -f "$NGINX_HTTP_CONF_DST"
    fi

    sudo rm -f "$staged_site" "$staged_http"
    log_info "Nginx config preflight passed"
}

install_nginx_config() {
    local src_site="$1"
    local src_http="$2"

    if [ ! -f "$src_site" ]; then
        log_error "Nginx site config source not found: ${src_site}"
        exit 1
    fi
    if [ ! -f "$src_http" ]; then
        log_error "Nginx http config source not found: ${src_http}"
        exit 1
    fi

    log_nginx_conf_d_state "install_nginx_config START"

    # Prevent "zero size shared memory zone admin_login": require non-zero zone size in repo config (10m/256k/1g etc)
    if grep -q 'admin_login' "$src_http" 2>/dev/null; then
        if grep -qE 'zone=admin_login:0m|zone=admin_login:[[:space:]]|zone=admin_login:$' "$src_http" 2>/dev/null; then
            log_error "Nginx http config has zero or missing size for admin_login zone (would cause 'zero size shared memory zone')"
            log_error "Fix deploy/nginx.http.conf: use zone=admin_login:10m"
            exit 1
        fi
        if ! grep -qE 'zone=admin_login:[1-9][0-9]*[mkg]' "$src_http" 2>/dev/null; then
            log_error "Nginx http config must have zone=admin_login:10m (or similar non-zero size: 256k, 1g)"
            exit 1
        fi
        log_info "Nginx http config: admin_login zone has non-zero size (OK)"
    fi

    local conf_d_dir
    conf_d_dir="$(dirname "$NGINX_HTTP_CONF_DST")"
    sudo mkdir -p "$(dirname "$NGINX_CONF_DST")" "$(dirname "$NGINX_CONF_LINK")" "$conf_d_dir"

    # Single source of truth for limit_req_zone admin_login: only deploy/nginx.http.conf -> carfst-http.conf.
    if [ -f "${conf_d_dir}/00-rate-limits.conf" ]; then
        if sudo grep -q 'admin_login' "${conf_d_dir}/00-rate-limits.conf" 2>/dev/null; then
            log_info "Removing legacy 00-rate-limits.conf (admin_login zone is only in carfst-http.conf)"
            sudo mv "${conf_d_dir}/00-rate-limits.conf" "${conf_d_dir}/00-rate-limits.conf.bak.$(date +%Y%m%d%H%M%S)" || true
        fi
    fi

    # --- carfst-http.conf: atomic write (never remove working file until nginx -t passes) ---
    # Write to .tmp in same dir (not included by include *.conf), validate, then mv over (no rm before mv).
    local tmp_http="${conf_d_dir}/.carfst-http.conf.tmp"
    local http_backup_file=""
    sudo cp "$src_http" "$tmp_http"
    sudo chmod 644 "$tmp_http"
    if ! validate_carfst_http_content "$tmp_http"; then
        log_error "New carfst-http content invalid (zone size or limit_req_status); aborting"
        sudo rm -f "$tmp_http"
        exit 1
    fi
    if [ -f "$NGINX_HTTP_CONF_DST" ] || sudo test -f "$NGINX_HTTP_CONF_DST" 2>/dev/null; then
        http_backup_file="${NGINX_HTTP_CONF_DST}.bak.$(date +%Y%m%d%H%M%S)"
        sudo cp "$NGINX_HTTP_CONF_DST" "$http_backup_file"
        log_info "Backed up existing http config to ${http_backup_file}"
    fi
    sudo mv -f "$tmp_http" "$NGINX_HTTP_CONF_DST"
    # carfst-http.conf now has new content; file was never removed (atomic overwrite).

    # --- site config: staged .tmp + symlink for nginx -t, then mv ---
    local tmp_site="${NGINX_CONF_DST}.tmp"
    local link_backup=""
    if [ -e "$NGINX_CONF_LINK" ]; then
        link_backup="$(readlink -f "$NGINX_CONF_LINK" 2>/dev/null || true)"
    fi
    sudo cp "$src_site" "$tmp_site"
    sudo chmod 644 "$tmp_site"
    sudo ln -sfn "$tmp_site" "$NGINX_CONF_LINK"

    log_info "Running nginx -t (site .tmp + carfst-http.conf already in place)"
    if ! sudo nginx -t 2>&1; then
        log_error "Nginx config test failed. Restoring site link and carfst-http.conf from backup."
        if [ -n "$link_backup" ] && [ -e "$link_backup" ]; then
            sudo ln -sfn "$link_backup" "$NGINX_CONF_LINK"
        else
            sudo rm -f "$NGINX_CONF_LINK"
        fi
        if [ -n "$http_backup_file" ] && [ -f "$http_backup_file" ]; then
            sudo cp "$http_backup_file" "$NGINX_HTTP_CONF_DST"
            sudo rm -f "$http_backup_file"
        fi
        sudo rm -f "$tmp_site"
        exit 1
    fi

    # nginx -t passed: finalize site (mv .tmp to dest, link to dest)
    if [ -f "$NGINX_CONF_DST" ]; then
        local site_bak="${NGINX_CONF_DST}.bak.$(date +%Y%m%d%H%M%S)"
        sudo cp "$NGINX_CONF_DST" "$site_bak"
        log_info "Nginx site config backup: ${site_bak}"
    fi
    sudo rm -f "$NGINX_CONF_LINK"
    sudo mv "$tmp_site" "$NGINX_CONF_DST"
    sudo ln -sfn "$NGINX_CONF_DST" "$NGINX_CONF_LINK"
    if [ -n "$http_backup_file" ] && [ -f "$http_backup_file" ]; then
        sudo rm -f "$http_backup_file"
    fi

    if ! validate_carfst_http_content "$NGINX_HTTP_CONF_DST"; then
        log_error "carfst-http.conf invalid after install; writing fallback"
        sudo bash -c "cat > \"$NGINX_HTTP_CONF_DST\" << 'ENDOFFILE'
limit_req_zone \$binary_remote_addr zone=admin_login:10m rate=10r/m;
limit_req_status 429;
ENDOFFILE"
        sudo chmod 644 "$NGINX_HTTP_CONF_DST"
    fi
    log_nginx_conf_d_state "install_nginx_config END"
    log_info "Nginx configs installed: ${NGINX_CONF_DST}, ${NGINX_HTTP_CONF_DST}"
}

detect_gunicorn_service() {
    if [ -n "${GUNICORN_SERVICE_OVERRIDE:-}" ]; then
        echo "${GUNICORN_SERVICE_OVERRIDE}"
        return
    fi

    if systemctl list-unit-files | grep -q '^carfst-gunicorn\.service'; then
        echo "carfst-gunicorn"
        return
    fi

    if systemctl list-unit-files | grep -q '^gunicorn_carfst\.service'; then
        echo "gunicorn_carfst"
        return
    fi

    log_error "Gunicorn unit not found. Available gunicorn units:"
    systemctl list-unit-files | grep -i gunicorn || true
    exit 1
}

resolve_env_file() {
    if [ -n "${ENV_FILE:-}" ]; then
        echo "$ENV_FILE"
        return
    fi
    if [ -f "$SYSTEM_ENV_FILE" ]; then
        echo "$SYSTEM_ENV_FILE"
        return
    fi
    if [ -f "${DEST_CODE_DIR}/.env" ]; then
        echo "${DEST_CODE_DIR}/.env"
        return
    fi
    echo ""
}

load_env_file() {
    if [ -n "${ENV_FILE_RESOLVED:-}" ]; then
        log_info "Loading environment variables from: $ENV_FILE_RESOLVED"
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE_RESOLVED"
        set +a
        log_info "Environment variables loaded (SECRET_KEY length logged, value hidden)"
    else
        log_warn "No env file found (ENV_FILE, /etc/carfst/carfst.env, .env)"
        log_warn "Relying on existing environment variables only."
    fi
}

assert_secret_key() {
    local key="${DJANGO_SECRET_KEY:-${SECRET_KEY:-}}"
    if [ -z "${key:-}" ]; then
        log_error "DJANGO_SECRET_KEY/SECRET_KEY is not set."
        log_error "Set ENV_FILE or create /etc/carfst/carfst.env with DJANGO_SECRET_KEY."
        exit 1
    fi
    if [ "$key" = "dev-secret-key" ]; then
        log_error "SECRET_KEY must not be default 'dev-secret-key'."
        log_error "Update /etc/carfst/carfst.env or ENV_FILE with a secure key."
        exit 1
    fi
    log_info "SECRET_KEY loaded (length: ${#key})"
}

run_manage() {
    local args="$*"
    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "$RUN_AS_USER" -H bash -lc "set -euo pipefail; \
            if [ -n \"${ENV_FILE_RESOLVED:-}\" ]; then set -a; . \"${ENV_FILE_RESOLVED}\"; set +a; fi; \
            cd \"${PROJECT_DIR}\"; \
            \"${PYTHON_CMD}\" \"${MANAGE_PY}\" ${args}"
    else
        "${PYTHON_CMD}" "${MANAGE_PY}" ${args}
    fi
}

assert_venv() {
    if [ ! -x "${PYTHON_CMD}" ]; then
        log_error "Venv python not found: ${PYTHON_CMD}"
        log_error "Create venv: python3 -m venv ${VENV_PATH}"
        log_error "Install deps: ${VENV_PATH}/bin/pip install -r ${PROJECT_DIR}/requirements.txt"
        exit 1
    fi
    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "$RUN_AS_USER" -H "${PYTHON_CMD}" -c "import django" || {
            log_error "Django not available in venv: ${PYTHON_CMD}"
            log_error "Install deps: ${VENV_PATH}/bin/pip install -r ${PROJECT_DIR}/requirements.txt"
            exit 1
        }
    else
        "${PYTHON_CMD}" -c "import django" || {
            log_error "Django not available in venv: ${PYTHON_CMD}"
            log_error "Install deps: ${VENV_PATH}/bin/pip install -r ${PROJECT_DIR}/requirements.txt"
            exit 1
        }
    fi
}

run_python_cmd() {
    local cmd="$1"
    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "${RUN_AS_USER}" -H "${PYTHON_CMD}" -c "${cmd}"
    else
        "${PYTHON_CMD}" -c "${cmd}"
    fi
}

install_dependencies_if_needed() {
    local req_file="${PROJECT_DIR}/requirements.txt"
    local hash_dir="${DEST_CODE_DIR}/.deploy"
    local hash_file="${hash_dir}/requirements.sha256"

    if [ ! -f "$req_file" ]; then
        log_warn "requirements.txt not found at ${req_file} (skipping dependency install)"
        return
    fi

    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "${RUN_AS_USER}" -H mkdir -p "${hash_dir}"
    else
        mkdir -p "${hash_dir}"
    fi

    local new_hash old_hash need_install
    if command -v sha256sum >/dev/null 2>&1; then
        new_hash="$(sha256sum "$req_file" | awk '{print $1}')"
    else
        new_hash="$("${PYTHON_CMD}" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$req_file")"
    fi

    old_hash=""
    if [ -f "$hash_file" ]; then
        old_hash="$(cat "$hash_file" | tr -d '\r\n')"
    fi

    need_install=0
    if [ "$new_hash" != "$old_hash" ]; then
        need_install=1
    fi

    if ! run_python_cmd "import docx, lxml" >/dev/null 2>&1; then
        need_install=1
    fi

    if [ "$need_install" -eq 1 ]; then
        log_info "Installing Python dependencies from requirements.txt..."
        if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
            sudo -u "${RUN_AS_USER}" -H "${PYTHON_CMD}" -m pip install -r "${req_file}"
        else
            "${PYTHON_CMD}" -m pip install -r "${req_file}"
        fi
        run_python_cmd "import docx, lxml; print('deps ok')"
        if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
            sudo -u "${RUN_AS_USER}" -H bash -lc "printf '%s' '${new_hash}' > '${hash_file}'"
        else
            printf '%s' "${new_hash}" > "${hash_file}"
        fi
    else
        log_info "Dependencies unchanged; skipping pip install"
    fi
}

# Check if ZIP file is provided
if [ $# -lt 1 ]; then
    log_error "Usage: $0 <path_to_zip_file>"
    exit 1
fi

ZIP_FILE="$1"

# Validate ZIP file exists
if [ ! -f "$ZIP_FILE" ]; then
    log_error "ZIP file not found: $ZIP_FILE"
    exit 1
fi

log_info "Starting deployment from: $ZIP_FILE"

# Validate ZIP contains required files
log_info "Validating ZIP archive..."
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

unzip -q "$ZIP_FILE" -d "$TEMP_DIR" || {
    log_error "Failed to extract ZIP file"
    exit 1
}

# Detect project root inside archive (support both "flat" zips and zips with a top-level folder)
log_info "Detecting project root inside archive..."
MANAGE_IN_ARCHIVE=$(find "$TEMP_DIR" -maxdepth 3 -name "manage.py" -type f | head -n 1 || true)
if [ -z "${MANAGE_IN_ARCHIVE:-}" ]; then
    log_error "manage.py not found inside ZIP archive"
    log_error "Make sure the archive contains the Django project root (where manage.py lives)."
    exit 1
fi
ARCHIVE_ROOT=$(dirname "$MANAGE_IN_ARCHIVE")
log_info "Archive project root detected: $ARCHIVE_ROOT"
NGINX_CONF_SRC_ARCHIVE="${ARCHIVE_ROOT}/deploy/nginx.carfst.ru.conf"
NGINX_HTTP_CONF_SRC_ARCHIVE="${ARCHIVE_ROOT}/deploy/nginx.http.conf"

# Early self-update + re-exec (source of truth entrypoint)
if [ -z "${DEPLOY_REEXEC:-}" ]; then
    NEW="${ARCHIVE_ROOT}/bin/deploy_carfst.sh"
    DST="/home/carfst/app/bin/deploy_carfst.sh"
    TMP="/home/carfst/app/bin/deploy_carfst.sh.new"
    if [ -f "$NEW" ]; then
        cp "$NEW" "$TMP"
        chmod +x "$TMP"
        if ! bash -n "$TMP"; then
            log_error "Syntax check failed for ${TMP}"
            exit 1
        fi
        if ! cmp -s "$TMP" "$DST"; then
            if [ -f "$DST" ]; then
                BACKUP="${DST}.bak.$(date +%Y%m%d%H%M%S)"
                cp "$DST" "$BACKUP"
                log_info "Deploy entrypoint backup saved: $BACKUP"
            fi
            mv "$TMP" "$DST"
            log_info "Re-executing updated deploy script: $DST"
            DEPLOY_REEXEC=1 exec "$DST" "$@"
        else
            rm -f "$TMP"
        fi
    else
        log_warn "Deploy entrypoint not found in archive: $NEW"
    fi
fi

# Check required files
MISSING_FILES=()
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "${ARCHIVE_ROOT}/${file}" ]; then
        MISSING_FILES+=("$file")
    fi
done

# Check migration files - CRITICAL: must have migration 0016 or later
MIGRATION_FOUND=false
MIGRATION_FILES=()
for pattern in "${MIGRATION_PATTERNS[@]}"; do
    for file in ${ARCHIVE_ROOT}/${pattern}; do
        if [ -f "$file" ]; then
            MIGRATION_FOUND=true
            MIGRATION_FILES+=("$(basename "$file")")
        fi
    done
done

# Log all migrations found in archive
log_info "Scanning migrations in archive..."
MIGRATION_DIR="${ARCHIVE_ROOT}/catalog/migrations"
if [ -d "$MIGRATION_DIR" ]; then
    ALL_MIGRATIONS=$(find "$MIGRATION_DIR" -name "*.py" -type f ! -name "__init__.py" | sort)
    if [ -n "$ALL_MIGRATIONS" ]; then
        log_info "Found migrations in archive:"
        while IFS= read -r mig_file; do
            log_info "  - $(basename "$mig_file")"
        done <<< "$ALL_MIGRATIONS"
    else
        log_warn "No migration files found in catalog/migrations/"
    fi
else
    log_warn "Migration directory not found: catalog/migrations/"
fi

# Validate required files
if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    log_error "Missing required files in ZIP:"
    for file in "${MISSING_FILES[@]}"; do
        log_error "  - $file"
    done
    exit 1
fi

# CRITICAL: Stop deployment if required migration is missing
if [ "$MIGRATION_FOUND" = false ]; then
    log_error "CRITICAL: Required migration not found in ZIP!"
    log_error "Expected migration: catalog/migrations/0016_add_site_settings_fields.py"
    log_error "Or later migration (0017+) that includes work_hours and map_embed fields"
    log_error ""
    log_error "Deployment stopped to prevent database errors."
    log_error "Please ensure the migration is included in the ZIP archive."
    exit 1
fi

log_info "ZIP validation passed"
log_info "Required migration found: ${MIGRATION_FILES[*]}"

# Ensure no legacy carfst.ru link is left in sites-enabled
disable_legacy_sites_enabled

# Preflight nginx config before touching the codebase
preflight_nginx_config "$NGINX_CONF_SRC_ARCHIVE" "$NGINX_HTTP_CONF_SRC_ARCHIVE"

# Validate archive contents (catch wrong/old template/CSS before touching the server)
log_info "Validating archive card template + CSS build marker..."
$PYTHON_CMD - <<'PY' "$ARCHIVE_ROOT"
import sys
from pathlib import Path

root = Path(sys.argv[1])

build_marker = "build: cards-eqheight-20251224"

css_path = root / "static" / "css" / "styles.css"
tpl_path = root / "templates" / "catalog" / "_product_card.html"

css = css_path.read_text(encoding="utf-8", errors="ignore")
if build_marker not in css:
    print(f"ERROR: Archive styles.css missing build marker '{build_marker}'", file=sys.stderr)
    print(f"ERROR: File: {css_path}", file=sys.stderr)
    sys.exit(1)

tpl = tpl_path.read_text(encoding="utf-8", errors="ignore")

def require_exactly_one(token: str):
    n = tpl.count(token)
    if n != 1:
        print("ERROR: Archive product card template looks wrong (duplicate/missing blocks).", file=sys.stderr)
        print(f"ERROR: Expected exactly 1 occurrence of '{token}', found {n}", file=sys.stderr)
        print(f"ERROR: File: {tpl_path}", file=sys.stderr)
        sys.exit(1)

require_exactly_one("product-card__body")
require_exactly_one("product-card__footer")
require_exactly_one("product-card__actions")

if "style=" in tpl:
    print("ERROR: Archive product card template contains inline styles (forbidden for stable heights).", file=sys.stderr)
    print(f"ERROR: File: {tpl_path}", file=sys.stderr)
    sys.exit(1)

print("OK: archive contains expected product card template + CSS build marker")
PY

# Change to project directory
cd "$PROJECT_DIR" || {
    log_error "Cannot access project directory: $PROJECT_DIR"
    exit 1
}

log_info "Updating project files from archive (rsync to code dir)..."
if ! command -v rsync >/dev/null 2>&1; then
    log_error "rsync is required but not found."
    log_error "Install rsync or update the deploy script."
    exit 1
fi

rsync -a \
    --exclude ".venv/" \
    --exclude "venv/" \
    --exclude "media/" \
    --exclude "logs/" \
    --exclude "staticfiles/" \
    --exclude "_incoming/" \
    --exclude ".env*" \
    --exclude "__pycache__/" \
    --exclude ".pytest_cache/" \
    --exclude ".git/" \
    --exclude ".idea/" \
    --exclude ".vscode/" \
    "${ARCHIVE_ROOT}/" "${DEST_CODE_DIR}/"

log_info "OK: updated files from ${ARCHIVE_ROOT} -> ${DEST_CODE_DIR}"

# Ensure migrations directory has correct ownership (critical for makemigrations)
log_info "Ensuring ownership for catalog/migrations directory..."
MIGRATIONS_DIR="${DEST_CODE_DIR}/catalog/migrations"
if [ -d "$MIGRATIONS_DIR" ]; then
    sudo chown -R "${RUN_AS_USER}:${RUN_AS_USER}" "$MIGRATIONS_DIR"
    sudo chmod -R u+w "$MIGRATIONS_DIR"
    log_info "✓ catalog/migrations ownership set to ${RUN_AS_USER}:${RUN_AS_USER}"
else
    log_warn "catalog/migrations directory not found: ${MIGRATIONS_DIR}"
fi

# Normalize scripts/ ownership and permissions (smoke and package scripts; avoid root:root after rsync)
log_info "Ensuring ownership and permissions for scripts directory..."
SCRIPTS_DIR="${DEST_CODE_DIR}/scripts"
if [ -d "$SCRIPTS_DIR" ]; then
    sudo chown -R "${RUN_AS_USER}:${RUN_AS_USER}" "$SCRIPTS_DIR"
    sudo find "$SCRIPTS_DIR" -type d -exec chmod 755 {} \;
    sudo find "$SCRIPTS_DIR" -type f -name "*.sh" -exec chmod 755 {} \;
    sudo find "$SCRIPTS_DIR" -type f ! -name "*.sh" -exec chmod 644 {} \;
    log_info "✓ scripts ownership set to ${RUN_AS_USER}:${RUN_AS_USER} (dirs 755, *.sh 755, other 644)"
else
    log_warn "scripts directory not found: ${SCRIPTS_DIR}"
fi

# Normalize source code directories ownership and permissions (avoid root:root after rsync)
# This ensures carfst user can write to __pycache__ and edit files if needed
log_info "Ensuring ownership and permissions for source code directories..."
CODE_DIRS=("catalog" "blog" "carfst_site" "templates" "docs")
for dir in "${CODE_DIRS[@]}"; do
    DIR_PATH="${DEST_CODE_DIR}/${dir}"
    if [ -d "$DIR_PATH" ]; then
        sudo chown -R "${RUN_AS_USER}:${RUN_AS_USER}" "$DIR_PATH"
        sudo find "$DIR_PATH" -type d -exec chmod 755 {} \;
        sudo find "$DIR_PATH" -type f -exec chmod 644 {} \;
        # Clean __pycache__ to avoid stale .pyc with wrong ownership
        sudo find "$DIR_PATH" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    fi
done
# Also fix manage.py ownership
if [ -f "${DEST_CODE_DIR}/manage.py" ]; then
    sudo chown "${RUN_AS_USER}:${RUN_AS_USER}" "${DEST_CODE_DIR}/manage.py"
    sudo chmod 644 "${DEST_CODE_DIR}/manage.py"
fi
log_info "✓ Source code directories ownership set to ${RUN_AS_USER}:${RUN_AS_USER} (dirs 755, files 644, __pycache__ cleaned)"

ensure_runtime_ownership

# Log working paths and ensure venv is usable
log_info "WORK_DIR: ${WORK_DIR}"
log_info "PROJECT_DIR: ${PROJECT_DIR}"
log_info "DEST_CODE_DIR: ${DEST_CODE_DIR}"
log_info "DEST_BIN_DIR: ${DEST_BIN_DIR}"
log_info "VENV_PATH: ${VENV_PATH}"
log_info "PYTHON_CMD: ${PYTHON_CMD}"
assert_venv

# Load environment variables (ENV_FILE > /etc/carfst/carfst.env > .env)
ENV_FILE_RESOLVED="$(resolve_env_file)"
if [ -n "${ENV_FILE_RESOLVED:-}" ]; then
    log_info "ENV file selected: $ENV_FILE_RESOLVED"
else
    log_warn "ENV file selected: <none>"
fi
load_env_file
assert_secret_key
if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
    log_info "manage.py will run as user: ${RUN_AS_USER} (sudo -u)"
else
    log_info "manage.py will run as current user: $(id -un)"
fi

install_dependencies_if_needed

# Apply migrations
log_info "Applying database migrations..."
if [ -f "$MANAGE_PY" ]; then
    run_manage "migrate --noinput" || {
        log_error "Migration failed!"
        exit 1
    }
    
    # Show applied migrations for catalog app (critical for debugging)
    log_info "Checking applied migrations for catalog app..."
    log_info "Recent catalog migrations status:"
    run_manage "showmigrations catalog" | tail -n 20 || {
        log_error "Could not show migrations status"
        exit 1
    }
    
    # Verify critical migration 0016 is applied
    if run_manage "showmigrations catalog" | grep -q "\[X\].*0016_add_site_settings_fields"; then
        log_info "✓ Migration 0016_add_site_settings_fields is applied"
    else
        log_error "CRITICAL: Migration 0016_add_site_settings_fields is NOT applied"
        log_error "This will cause errors if SiteSettings.work_hours or map_embed are accessed"
        exit 1
    fi

    # Verify DB schema for SiteSettings (catches missing columns early)
    log_info "Verifying SiteSettings DB columns (work_hours, map_embed)..."
    run_manage "shell -c \"from catalog.models import SiteSettings; SiteSettings.objects.values('work_hours','map_embed').first(); print('OK: SiteSettings columns exist')\"" || {
        log_error "SiteSettings column check failed! (migration 0016 may be missing)"
        exit 1
    }
else
    log_error "manage.py not found at $MANAGE_PY"
    exit 1
fi

# Collect static files
# Clear stale hashed hero v3 and manifest so collectstatic re-hashes (avoids serving old 38KB placeholder)
if [ -d "${STATIC_ROOT}" ]; then
    log_info "Clearing stale hashed hero v3 and manifest so collectstatic re-hashes..."
    if [ "$(id -u)" -eq 0 ] && [ -n "${RUN_AS_USER:-}" ]; then
        sudo -u "${RUN_AS_USER}" rm -f "${STATIC_ROOT}/img/hero/shacman_mein.v3."*.webp "${STATIC_ROOT}/staticfiles.json" 2>/dev/null || true
    else
        rm -f "${STATIC_ROOT}/img/hero/shacman_mein.v3."*.webp "${STATIC_ROOT}/staticfiles.json" 2>/dev/null || true
    fi
fi

log_info "Collecting static files..."
COLLECTSTATIC_ARGS=(--noinput)
if [ "${COLLECTSTATIC_CLEAR}" = "1" ]; then
    log_info "collectstatic --clear enabled (COLLECTSTATIC_CLEAR=1)"
    COLLECTSTATIC_ARGS+=(--clear)
fi

run_manage "collectstatic ${COLLECTSTATIC_ARGS[*]}" || {
    log_error "collectstatic failed!"
    exit 1
}

# Log + verify which CSS file is actually used (manifest) and that it contains product card selectors
log_info "Verifying compiled CSS (manifest) contains product card selectors..."
STATIC_ROOT_PATH="$($PYTHON_CMD - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "carfst_site.settings")
import django
django.setup()
from django.conf import settings
print(settings.STATIC_ROOT)
PY
)"

$PYTHON_CMD - <<'PY' "$STATIC_ROOT_PATH"
import json
import sys
from pathlib import Path

static_root = Path(sys.argv[1])
manifest_path = static_root / "staticfiles.json"
if not manifest_path.is_file():
    print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
    sys.exit(1)

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
css_key = "css/styles.css"
hashed = (manifest.get("paths") or {}).get(css_key)
if not hashed:
    print(f"ERROR: manifest has no entry for {css_key}", file=sys.stderr)
    sys.exit(1)

compiled_css = static_root / hashed
if not compiled_css.is_file():
    print(f"ERROR: compiled CSS not found: {compiled_css}", file=sys.stderr)
    sys.exit(1)

print(f"STATIC_ROOT: {static_root}")
print(f"Manifest: {css_key} -> {hashed}")

content = compiled_css.read_text(encoding="utf-8", errors="ignore")
required = [
    "build: cards-eqheight-20251224",
    "product-card__description",
    "product-card__badges",
    "product-card__actions",
]
missing = [s for s in required if s not in content]
if missing:
    print("ERROR: Static CSS not updated / wrong file served.", file=sys.stderr)
    print("ERROR: compiled (hashed) CSS is missing: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)

print("OK: compiled (hashed) CSS contains build marker + product card selectors")
print("CSS HEAD (hashed):")
for line in content.splitlines()[:3]:
    print(line)

# Also verify unhashed css/styles.css exists and contains the build marker (useful for quick curl checks).
unhashed_css = static_root / css_key
if unhashed_css.is_file():
    unhashed_content = unhashed_css.read_text(encoding="utf-8", errors="ignore")
    if "build: cards-eqheight-20251224" not in unhashed_content:
        print("ERROR: Static CSS not updated / wrong file served.", file=sys.stderr)
        print(f"ERROR: unhashed CSS missing build marker: {unhashed_css}", file=sys.stderr)
        sys.exit(1)
    print("OK: unhashed css/styles.css contains build marker")
    print("CSS HEAD (unhashed):")
    for line in unhashed_content.splitlines()[:3]:
        print(line)
else:
    print(f"WARN: unhashed css/styles.css not found (ok for Manifest, but curl check will differ): {unhashed_css}", file=sys.stderr)
PY

# Publish staticfiles to nginx alias and verify availability
publish_staticfiles

# Restart gunicorn so Django workers re-read staticfiles.json (hashed hero etc.)
log_info "Restarting gunicorn so workers pick up new staticfiles.json"
restart_gunicorn

# Run Django check (critical - stops deployment on errors)
# Note: DJANGO_SECRET_KEY must be loaded from env file
log_info "Running Django system check..."
if ! run_manage "check --deploy"; then
    log_error "Django system check failed!"
    log_error "Please fix the issues above before deploying."
    exit 1
fi
log_info "Django system check passed"

# Install nginx configs from repository (source of truth)
log_info "Installing nginx configs from repository"
install_nginx_config "$NGINX_CONF_SRC_ARCHIVE" "$NGINX_HTTP_CONF_SRC_ARCHIVE"

# Ensure nginx media alias points to MEDIA_ROOT
log_info "Ensuring nginx media alias points to MEDIA_ROOT"
ensure_media_alias

# Ensure sites-enabled is clean before reload
log_info "Validating nginx sites-enabled state"
assert_sites_enabled_clean

# Ensure carfst-http.conf exists and is valid (by content); create/repair with fallback if not
ensure_carfst_http_conf || exit 1

# Diagnostics before final nginx -t (conf.d, stat, first 20 lines)
log_nginx_conf_d_state "before final nginx -t"

# Reload nginx
log_info "Reloading nginx..."
if ! sudo nginx -t 2>&1; then
    log_error "nginx -t failed after installing configs; aborting (working config unchanged)"
    exit 1
fi
if ! sudo systemctl reload nginx; then
    log_error "systemctl reload nginx failed"
    exit 1
fi
log_info "Nginx reloaded successfully"

# Smoke: nginx -t must pass with current config (no broken symlinks / zero-size zones)
log_info "Smoke: nginx -t"
if ! sudo nginx -t 2>&1; then
    log_error "Smoke failed: nginx -t failed (check shared memory zones e.g. admin_login:10m)"
    exit 1
fi
log_info "OK: nginx -t passed"

# Verify exactly one limit_req_zone admin_login in effective config (no duplicates)
_admin_zone_count="$(sudo nginx -T 2>/dev/null | grep -c 'limit_req_zone.*admin_login' || echo 0)"
if [ "${_admin_zone_count:-0}" -ne 1 ]; then
    log_error "Expected exactly one limit_req_zone admin_login in nginx -T, got: ${_admin_zone_count}"
    exit 1
fi
log_info "OK: exactly one admin_login zone in nginx config"

# Final guarantee: carfst-http.conf exists and is valid
if ! validate_carfst_http_content "${NGINX_HTTP_CONF_DST:-/etc/nginx/conf.d/carfst-http.conf}"; then
    log_error "carfst-http.conf invalid after deploy; run ensure_carfst_http_conf or fix manually"
    exit 1
fi
log_info "OK: carfst-http.conf exists and valid"

log_info "Validating deployed build id"
version_smoke_check

# Mandatory: /shacman/ must return 200 (deploy fails on 404; not skippable)
shacman_smoke_check

# Health smoke: /health/ contract (orphaned_media skipped + deep detail keys)
log_info "Running health smoke check"
health_smoke_check "https://${CANONICAL_HOST:-carfst.ru}"

# SEO smoke: canonical/robots/schema (required unless SKIP_SEO_SMOKE=1)
if [ "${SKIP_SEO_SMOKE:-0}" = "1" ]; then
    log_warn "SEO smoke skipped (SKIP_SEO_SMOKE=1)"
else
    SEO_SCRIPT="${DEST_CODE_DIR}/scripts/smoke_seo.sh"
    if [ ! -f "${SEO_SCRIPT}" ]; then
        log_error "SEO smoke script not found: ${SEO_SCRIPT} (required for SEO invariants)"
        exit 1
    fi
    SEO_BASE_URL="https://${CANONICAL_HOST:-carfst.ru}"
    SEO_PRODUCT_SLUG="$(get_product_slug 2>/dev/null | tr -d '\r' || true)"
    log_info "Running SEO smoke tests (canonical/robots/schema)"
    if ! bash "${SEO_SCRIPT}" "${SEO_BASE_URL}" "${SEO_PRODUCT_SLUG:-}"; then
        log_error "SEO smoke tests failed (canonical/robots/schema)"
        exit 1
    fi
fi

log_info "Running SEO in-stock smoke checks"
seo_in_stock_smoke_check
log_info "Running staticfiles smoke check"
staticfiles_smoke_check
log_info "Running product smoke check"
product_smoke_check
log_info "Running media smoke check"
media_smoke_check

# Non-blocking CSP check (optional)
if command -v curl >/dev/null 2>&1; then
    log_info "Checking CSP header on https://carfst.ru/ (non-blocking)"
    if curl -sI https://carfst.ru/ | grep -qi "Content-Security-Policy"; then
        log_info "CSP header present on https://carfst.ru/"
    else
        log_warn "CSP header missing on https://carfst.ru/"
    fi
else
    log_warn "curl not found; skipping CSP header check"
fi

# Install updated deploy entrypoint safely (avoid self-overwrite)
if [ -z "${DEPLOY_REEXEC:-}" ]; then
    log_info "Installing deploy entrypoint into ${DEST_BIN_DIR}..."
    mkdir -p "${DEST_BIN_DIR}"
    DEPLOY_SRC="${ARCHIVE_ROOT}/bin/deploy_carfst.sh"
    DEPLOY_TMP="${DEST_BIN_DIR}/deploy_carfst.sh.new"
    DEPLOY_DST="${DEST_BIN_DIR}/deploy_carfst.sh"
    if [ -f "${DEPLOY_SRC}" ]; then
        cp "${DEPLOY_SRC}" "${DEPLOY_TMP}"
        if [ -f "${DEPLOY_DST}" ]; then
            BACKUP="${DEPLOY_DST}.bak.$(date +%Y%m%d%H%M%S)"
            cp "${DEPLOY_DST}" "${BACKUP}"
            log_info "Deploy entrypoint backup saved: ${BACKUP}"
        fi
        mv "${DEPLOY_TMP}" "${DEPLOY_DST}"
        chmod +x "${DEPLOY_DST}"
        log_info "OK: updated deploy entrypoint at ${DEPLOY_DST}"
    else
        log_warn "Deploy entrypoint not found in archive: ${DEPLOY_SRC}"
    fi
fi

log_info "Deployment completed successfully!"
log_info "Project directory: $PROJECT_DIR"
GUNICORN_STATUS_AFTER="$(systemctl is-active "${GUNICORN_SERVICE_SELECTED}" 2>/dev/null || echo "unknown")"
log_info "Gunicorn service: ${GUNICORN_SERVICE_SELECTED}"
log_info "Gunicorn final state: ${GUNICORN_STATUS_AFTER}"
