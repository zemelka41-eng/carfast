# carfst_site

Django 5.1-ready bilingual catalog (RU/EN) with DRF API, XLSX import, and health checks. Includes admin tooling, sitemap/robots templates, and request logging with upload validation.

## Stack
- Python 3.11–3.14, Django 5.1, DRF, django-filter, drf-spectacular
- PostgreSQL in production; SQLite fallback for local development
- Swagger UI at `/api/docs/` and OpenAPI schema at `/api/schema/`
- Health endpoint `GET /health/` (HTTP 503 on degraded) and CLI `python manage.py healthcheck`
- Logging to `logs/` (`django.log` + `errors.log`), guarded uploads via `UploadValidationMiddleware`

## Quick start
1) `python -m venv .venv && .venv\Scripts\activate` (or `source .venv/bin/activate`)
2) `pip install -r requirements.txt`
3) `cp .env.example .env` and set `SECRET_KEY`, DB credentials (`DATABASE_URL` or `DB_*`), `DEFAULT_FROM_EMAIL`; add Telegram/WhatsApp keys if used
4) `python manage.py migrate`
5) Optional demo content: `python manage.py loaddata fixtures/initial_data.json`
6) Run dev server: `python manage.py runserver --settings carfst_site.settings_test` → http://127.0.0.1:8000/ (`/en/` for English)
7) Verify: `python manage.py healthcheck`

## Environment keys (common)
- `SECRET_KEY` (required), `DEBUG` (default false)
- `DATABASE_URL` or `DB_*` (falls back to SQLite if empty)
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_DOMAIN`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WHATSAPP_NUMBER`
- Upload guards: `MAX_IMAGE_SIZE` (10 MB default), `FILE_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_MEMORY_SIZE`
- Allowed media types: `MEDIA_ALLOWED_IMAGE_EXTENSIONS`, `MEDIA_ALLOWED_IMAGE_MIME_TYPES`
- `LOG_DIR` (defaults to `BASE_DIR/logs`)

## Useful commands
- Import products: `python manage.py import_products data/sample_products.xlsx [media_dir]`  
  Columns: `sku`, `slug`, `series`, `category`, `model_name_*`, `short_description_*`, `price`, `availability`, `image` (first image attached when available)
- Seed sample objects: `python manage.py seed_data`
- Seed SHACMAN: `python manage.py seed_shacman`
- Seed cities: `python manage.py seed_cities`
- Collect static assets: `python manage.py collectstatic --noinput` (outputs to `staticfiles/`)
- Tests: `pytest` (preferred) or `python manage.py test`
- OpenAPI schema: `/api/schema/`; Swagger UI: `/api/docs/`

## API and pages
- Public pages: `/`, `/catalog/`, `/product/<slug>/`, `/about/`, `/service/`, `/parts/`, `/contacts/`, `/news/`, `/lead/`
- REST: `GET /api/products/` (filters: `series`, `category`, `power_min`, `power_max`, `price_min`, `price_max`, `q`), `GET /api/products/<slug>/`, `POST /api/leads/`
- Sitemaps and robots: templates live under `templates/`

## Deployment notes
- Set `DEBUG=0`, configure hosts/CSRF origins, and use PostgreSQL
- Keep `MEDIA_ROOT` and `logs/` on persistent storage; do not commit media
- Run `python manage.py migrate` and `python manage.py collectstatic --noinput` before restarting the app server
- Monitor readiness with `/health/` (returns 503 when checks fail)
- Compat layer for <5.1 stays imported; remove `carfst_site.compat` after 5.1 is verified (see `docs/upgrade_django_5_1.md`)

## Сборка архива для деплоя

Windows (PowerShell):

```powershell
python scripts\make_deploy_zip.py "C:\Users\VLAD\Desktop\carfst.zip"
```

Если путь не передан — архив создаётся как `../carfst.zip` относительно корня проекта (где `manage.py`).

После загрузки/распаковки архива на сервере выполните:

- `python manage.py migrate`
- `python manage.py collectstatic --noinput`
- перезапустите `gunicorn`

## Orphaned media
- Просмотр: `python manage.py cleanup_orphaned_media --dry-run`
- Очистка: `python manage.py cleanup_orphaned_media --delete --path-prefix media/products`
- В `/health/` по умолчанию скан не выполняется; deep-скан: `?deep=1` или `HEALTH_ORPHANED_MEDIA=1`; TTL кеша: `HEALTH_ORPHANED_MEDIA_TTL_SECONDS` (по умолчанию 600).
- Подробнее: [MEDIA_CLEANUP.md](MEDIA_CLEANUP.md)

## Docs
- Upgrade guidance: `docs/upgrade_django_5_1.md`
