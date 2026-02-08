## Django 5.1 Upgrade Guide

This project now runs on Django 4.2–5.1 with Python 3.14 support. Use this guide to move existing deployments forward safely and to remove legacy shims once 5.1 is verified.

### Prerequisites and backups
- Ensure Python 3.11+ (tested up to 3.14) and pip are available.
- Back up the database and `media/` before touching production.
- Keep a maintenance window for applying migrations and collecting static files.

### Dependencies to update
- Key pins in `requirements.txt`: `Django>=4.2,<5.2`, `djangorestframework>=3.15,<3.16`, `django-filter>=24.3,<25.0`, `pillow>=10.4,<12.0`, `openpyxl>=3.1.5,<3.2`, `werkzeug>=3.1,<3.2`.
- Upgrade in place: `pip install -r requirements.txt --upgrade`.
- Rebuild Docker images if you deploy with Compose.

### Compatibility layer (legacy only)
- `carfst_site.compat.apply_compat_if_needed()` runs early in `settings.py` (and via `carfst_site.patches` for legacy imports).
- On Django <5.1 it patches `BaseContext.__copy__` to keep template rendering working on Python 3.14.
- On Django ≥5.1 the compat layer is skipped (with a single warning when imported) but does nothing else. After verifying 5.1 in production, remove the compat import and module to drop the shim.

### Settings, middleware, and logging
- New env keys: `LOG_DIR` (default `BASE_DIR/logs`), `MAX_IMAGE_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_MEMORY_SIZE`. The log directory is created at startup.
- `ErrorLoggingMiddleware` adds an `X-Request-ID` header and writes 5xx/unhandled errors to `logs/errors.log`. Keep log rotation in place.
- Static/media: `STATIC_ROOT` and `MEDIA_ROOT` are unchanged; ensure `collectstatic` is run after upgrading.
- REST defaults now include `drf_spectacular` schema at `/api/schema/` and Swagger UI at `/api/docs/`.

### Health checks
- Endpoint: `GET /health/` returns JSON with `status`, `errors`, `warnings`, and check details. Any status other than `ok` responds with HTTP 503.
- CLI: `python manage.py healthcheck` prints warnings and exits non-zero if checks fail.
- Checks performed: database connectivity, unapplied migrations, `MEDIA_ROOT` presence, `STATIC_ROOT` existence and non-empty, duplicate slugs for Series/Category/Product, and orphaned media files (`ProductImage` references vs files on disk).

### Data model and validation changes
- Slug/sku strictness: Series, Category, and Product now validate slugs for URL-safe content and uniqueness (case-insensitive). Product enforces unique SKU as well.
- Availability choices are limited to `IN_STOCK` or `ON_REQUEST`.
- JSON fields default to empty dict/list; invalid types raise validation errors.
- ProductImage enforces unique `(product, order)` with a constraint and `clean()` check.
- A post-migrate signal guarantees `SiteSettings` with `pk=1` exists; keep it in place for clean deployments.

### Import pipeline expectations
- Management command: `python manage.py import_products <xlsx_path> [media_dir]` delegates to `catalog.importers.run_import`.
- Required/expected columns (case-sensitive): `sku`, `slug`, `series`, `category`, `model_name_ru`, `model_name_en`, `short_description_ru`, `short_description_en`, `price`, `availability`, `image`.
- `availability` defaults to `IN_STOCK` if empty/invalid. Slugs are normalized with `slugify`; SKU is mandatory.
- If `media_dir` is provided and the file exists, the first image is attached with `order=0`; missing files are logged as warnings.
- Calling the command with `data/sample_products.xlsx` will auto-create a demo file if it is missing.

### Migrations and rollout steps
1) Install updated requirements.
2) Run `python manage.py migrate`.
3) Run `python manage.py collectstatic --noinput` (if serving static files locally).
4) Restart application processes (gunicorn/celery/asgi) and clear old bytecode if needed.
5) Run `python manage.py healthcheck` and verify `GET /health/` returns `status: "ok"`.
6) Smoke-test the admin, sitemap (`/sitemap.xml`), Swagger UI (`/api/docs/`), and a sample XLSX import.

### Testing
- Preferred: `pytest` from the repo root (uses Django settings).
- Built-in: `python manage.py test` as a fallback.
- Focus regression checks: product CRUD/admin validation, sitemap responses, importer command against `data/sample_products.xlsx`, and healthcheck command behavior.

### Removing legacy shims after 5.1 is stable
- Delete the compat import from `carfst_site/settings.py` (and any remaining `carfst_site.patches` imports), then remove `carfst_site/compat/`.
- Re-run the full test suite and the healthcheck command.
