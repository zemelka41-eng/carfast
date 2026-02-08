# Задача C: максимальное SEO-покрытие SHACMAN — отчёт

## Что было сделано (по пунктам C1–C6)

### C1 — Инвентаризация и карта посадочных

- **Команда:** `python manage.py seo_audit_shacman --all --csv reports/shacman_inventory_<DATE>.csv`
- В команду добавлены: распределение по **line** (model_variant.line), по **wheel_formula**, по **engine**; в CSV добавлена колонка **line**; исправлена опечатка `category_name` → `category`.
- **Отчёт:** `docs/SHACMAN_SEO_C1_INVENTORY.md` — структура отчёта, шаблоны таблиц (всего/in-stock/active, по категориям, по формулам, по двигателям, по линейкам, топ дублей), правила выбора главного URL и путь к CSV.
- **CSV:** по умолчанию `reports/shacman_inventory_YYYYMMDD.csv` (на проде — после запуска команды с `--all`).

### C2 — Посадочные страницы (хабы)

- **Отчёт:** `docs/SHACMAN_SEO_C2_HUBS.md` — таблица всех URL: обязательные хабы (/shacman/, in-stock, category, category in-stock), B3 (formula, engine, series/line), ограничения (≥2 товара, до 20 на тип), правила page/canonical/schema.
- Линейка (X3000/X6000 и т.д.) реализована как **series** (URL `/shacman/series/<series_slug>/`), не отдельный префикс `/shacman/line/`.

### C3 — Контент и мета для хабов

- **Отчёт:** `docs/SHACMAN_SEO_C3_HUB_CONTENT.md` — требования (Title 70–90, Description 140–180, H1, Intro 800–1500 слов, FAQ 5–8), редактирование через **ShacmanHubSEO**, шаблоны автогенерации и демонстрация на 3 хабах (brand, category, formula).
- Блоки перелинковки (категории, «В наличии», популярные модели) уже в шаблоне `shacman_hub.html`.

### C4 — Карточки товара SHACMAN

- **Отчёт:** `docs/SHACMAN_SEO_C4_PRODUCT_CARD.md` — пример «идеальной» карточки на товаре **sedelnyj-tyagach-shacman-sx418853381-4x2-wp13550e501**: Title/Description/H1, описание, FAQ, перелинковка, Schema.org Product+Offer, alt изображений.
- В **product_detail** добавлены ссылки на B3-хабы: **SHACMAN {formula}** и **SHACMAN двигатель {engine}** (только если формула/двигатель входят в `_shacman_allowed_clusters()`).

### C5 — Дубли (duplicate_group)

- **Отчёт:** `docs/SHACMAN_SEO_C5_DUPLICATES.md` — правила выбора главного URL (in-stock, полный slug, цена, год), действия (301 / canonical / оставить), шаблон таблицы топ-20 дублей для подстановки с проды и план внедрения.

### C6 — Sitemap и тесты

- **Sitemap:** B3-хабы уже в `ShacmanHubSitemap`; новых изменений в sitemap не вносилось.
- **Smoke:** `scripts/smoke_seo.sh` уже принимает **B3_HUB_PATH** (3-й аргумент) и проверяет 200 + canonical без query.
- **Django-тесты:** добавлены/расширены:
  - `tests/test_shacman_hub.py`: `test_shacman_hub_no_schema`, `test_shacman_formula_hub_200_canonical_clean`;
  - `tests/test_schema_org.py`: `test_product_clean_url_has_product_schema`, `test_product_url_with_get_has_no_schema`.
- **Отчёт:** `docs/SHACMAN_SEO_C6_SITEMAP_TESTS.md` — список файлов, команды проверки на проде, примечание про Python 3.14.

---

## Список изменённых файлов

| Файл | Изменения |
|------|-----------|
| **catalog/management/commands/seo_audit_shacman.py** | Колонка `line`, секции By line / By wheel formula / By engine; исправление `category_name` → `category`; fieldnames CSV с `line`. |
| **catalog/views.py** | В `product_detail`: добавлены ссылки на B3-хабы formula и engine в `seo_hub_links` (при наличии в allowed clusters). |
| **tests/test_shacman_hub.py** | Тесты: no schema на хабах, B3 formula hub 200 + canonical. |
| **tests/test_schema_org.py** | Тесты: Product schema на чистом URL продукта, отсутствие schema на URL с GET. |
| **docs/SHACMAN_SEO_C1_INVENTORY.md** | Новый: структура инвентаризации, команда, шаблоны таблиц, CSV. |
| **docs/SHACMAN_SEO_C2_HUBS.md** | Новый: таблица всех хабов, ограничения, типы URL. |
| **docs/SHACMAN_SEO_C3_HUB_CONTENT.md** | Новый: контент хабов, шаблоны, 3 примера. |
| **docs/SHACMAN_SEO_C4_PRODUCT_CARD.md** | Новый: идеальная карточка, пример slug, schema/перелинковка. |
| **docs/SHACMAN_SEO_C5_DUPLICATES.md** | Новый: стратегия дублей, таблица топ-20, план. |
| **docs/SHACMAN_SEO_C6_SITEMAP_TESTS.md** | Новый: sitemap B3, smoke B3_HUB_PATH, тесты. |
| **docs/SHACMAN_SEO_TASK_C_REPORT.md** | Этот отчёт. |

**Миграции:** нет (новых миграций не создавалось).

---

## Команды для проверки на проде

```bash
# 1) Инвентаризация SHACMAN (запустить с env и venv)
set -a; source /etc/carfst/carfst.env; set +a
cd /home/carfst/app/cursor_work
.venv/bin/python manage.py seo_audit_shacman --all --csv reports/shacman_inventory_$(date +%Y%m%d).csv

# 2) /shacman/ и B3-хаб
curl -sI "https://carfst.ru/shacman/"
curl -s "https://carfst.ru/shacman/" | grep -o 'rel="canonical" href="[^"]*"'
curl -sI "https://carfst.ru/shacman/formula/6x4/"
curl -s "https://carfst.ru/shacman/formula/6x4/" | grep -o 'rel="canonical" href="[^"]*"'

# 3) Карточка товара: schema на чистом URL, нет на URL с GET
SLUG="sedelnyj-tyagach-shacman-sx418853381-4x2-wp13550e501"  # или другой SHACMAN slug
curl -s "https://carfst.ru/product/${SLUG}/" | grep -o '"@type"[[:space:]]*:[[:space:]]*"Product"'
curl -s "https://carfst.ru/product/${SLUG}/?utm_source=test" | grep -o '"@type"[[:space:]]*:[[:space:]]*"Product"'
# Первый — должна быть строка; второй — пусто.

# 4) Smoke (с опциональным B3)
./scripts/smoke_seo.sh https://carfst.ru "${PRODUCT_SLUG:-}" shacman/formula/6x4

# 5) Диагностика URL
.venv/bin/python manage.py url_resolve_diagnostic
```

---

## Риски и что может сломаться

1. **product_detail:** вызов `_shacman_allowed_clusters()` при каждом запросе карточки SHACMAN — дополнительный запрос к БД. При высокой нагрузке можно закэшировать результат на короткое время.
2. **seo_audit_shacman:** добавлено поле `line` в строку — старые скрипты, парсящие CSV по фиксированному списку колонок, нужно обновить.
3. **Тесты:** на окружении с Python 3.14 возможен сбой из-за несовместимости Django test client (`AttributeError: 'super' object has no attribute 'dicts'`). На проде с Python 3.11/3.12 тесты должны проходить.

**Как откатиться**

- **Вьюха product_detail:** убрать блок с `_shacman_allowed_clusters()` и добавлением ссылок formula/engine в `seo_hub_links` (оставить только ссылки на /shacman/, category, in-stock).
- **seo_audit_shacman:** вернуть использование `category_name` в by_cat и убрать секции By line / By wheel formula / By engine и колонку `line` из CSV при необходимости.
- **Тесты:** новые тесты можно закомментировать или пропускать по маркеру, если на CI используется Python 3.14.

---

## Пути к CSV и docs

- **CSV (после запуска на проде):** `reports/shacman_inventory_YYYYMMDD.csv`
- **Документы:**
  - `docs/SHACMAN_SEO_C1_INVENTORY.md`
  - `docs/SHACMAN_SEO_C2_HUBS.md`
  - `docs/SHACMAN_SEO_C3_HUB_CONTENT.md`
  - `docs/SHACMAN_SEO_C4_PRODUCT_CARD.md`
  - `docs/SHACMAN_SEO_C5_DUPLICATES.md`
  - `docs/SHACMAN_SEO_C6_SITEMAP_TESTS.md`
  - `docs/SHACMAN_SEO_TASK_C_REPORT.md` (этот отчёт)
