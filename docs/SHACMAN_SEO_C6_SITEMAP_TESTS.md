# C6 — Sitemap и тесты SHACMAN

## Sitemap (B3-хабы)

Новые хабы B3 (formula, engine, series и их in-stock варианты) уже включены в **ShacmanHubSitemap** (`catalog/sitemaps.py`):

- `/shacman/`, `/shacman/in-stock/`
- `/shacman/series/<series_slug>/`, `/shacman/series/<series_slug>/in-stock/`
- `/shacman/formula/<formula>/`, `/shacman/formula/<formula>/in-stock/`
- `/shacman/engine/<engine_slug>/`, `/shacman/engine/<engine_slug>/in-stock/`
- `/shacman/<category_slug>/`, `/shacman/<category_slug>/in-stock/`

В sitemap попадают **только чистые URL** (без `?page=...` и без GET-параметров). `lastmod` по возможности из `updated_at` товаров в сегменте.

---

## Smoke-скрипт (B3_HUB_PATH)

`scripts/smoke_seo.sh` уже поддерживает опциональный третий аргумент **B3_HUB_PATH**:

```bash
./scripts/smoke_seo.sh [BASE_URL] [PRODUCT_SLUG] [B3_HUB_PATH]
```

- **B3_HUB_PATH** — путь к одному B3-хабу без ведущего/конечного слеша, например `shacman/formula/6x4` или `shacman/engine/wp13550e501`.
- Проверка: GET `/<B3_HUB_PATH>/` → HTTP 200, canonical без query.

Пример (проверка одного formula-хаба):

```bash
./scripts/smoke_seo.sh https://carfst.ru "" shacman/formula/6x4
```

При деплое можно передавать B3_HUB_PATH из окружения или не передавать (тогда проверка 8 пропускается).

---

## Django-тесты (добавлены/обновлены)

### Файлы тестов

| Файл | Изменения |
|------|-----------|
| **tests/test_shacman_hub.py** | Добавлены: `test_shacman_hub_no_schema` (на хабах нет Product/BreadcrumbList/FAQPage), `test_shacman_formula_hub_200_canonical_clean` (B3 formula 200 + canonical без query). |
| **tests/test_schema_org.py** | Добавлены: `test_product_clean_url_has_product_schema`, `test_product_url_with_get_has_no_schema` (на URL с GET нет Product/FAQPage/BreadcrumbList). |

### Что проверяют тесты

1. **robots/canonical/pagination для хабов** — уже покрыто: `test_shacman_hub_page1_redirect`, `test_shacman_hub_page2_noindex_self_canonical`, `test_shacman_hub_canonical_clean`.
2. **Отсутствие schema на хабах** — `test_shacman_hub_no_schema`.
3. **Отсутствие schema на URL с GET** — `test_product_url_with_get_has_no_schema`.
4. **Наличие Product schema на чистом product_detail** — `test_product_clean_url_has_product_schema`.
5. **Один B3-хаб (formula)** — `test_shacman_formula_hub_200_canonical_clean`.

**Примечание:** локально тесты могут падать с `AttributeError: 'super' object has no attribute 'dicts'` при использовании Python 3.14 и Django test client (известная несовместимость). На проде (Python 3.11/3.12) тесты должны проходить.

---

## Команды проверки на проде

```bash
# 1) Sitemap: наличие /shacman/ и B3-URL без параметров
curl -s "https://carfst.ru/sitemap.xml" | grep -E "/shacman/|formula|engine|series"
# Ожидание: строки с <loc>https://carfst.ru/shacman/...</loc>, без ? в URL

# 2) Smoke (все проверки, включая опциональный B3)
./scripts/smoke_seo.sh https://carfst.ru <product_slug> shacman/formula/6x4

# 3) Один B3-хаб: 200 + canonical
curl -sI "https://carfst.ru/shacman/formula/6x4/"
curl -s "https://carfst.ru/shacman/formula/6x4/" | grep -o 'rel="canonical" href="[^"]*"'
# Ожидание: 200, canonical = https://carfst.ru/shacman/formula/6x4/

# 4) Управление (диагностика разрешения URL)
python manage.py url_resolve_diagnostic
```

---

## Миграции

Новых миграций для C6 нет (sitemap и smoke уже были доработаны ранее).
