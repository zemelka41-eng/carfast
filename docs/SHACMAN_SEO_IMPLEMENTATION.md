# SHACMAN SEO: реализация (B1–B6)

## 1. Краткий итог

- **Задача A:** Маршруты `/shacman/*` вынесены в начало корневого `urlpatterns` (вне i18n). `resolve('/shacman/')` → `shacman_hub`. Smoke: `/shacman/` 200 + canonical чистый; `/shacman/?page=2` noindex, follow + self-canonical.
- **B1:** Команда `seo_audit_shacman --all`, CSV в `reports/shacman_inventory_YYYYMMDD.csv`, колонки url, slug, category, series_model, wheel_formula, engine, model_code, year, in_stock, availability, price, duplicate_group.
- **B2:** Модель `ShacmanHubSEO` (type + optional key), админка, уникальные Title/H1/Description и SEO-текст (900–1500 слов), FAQ, «также ищут», перелинковка на хабах. Schema на хабах не выводится.
- **B3:** Хабы `/shacman/series/<series_slug>/`, `/shacman/formula/<formula>/`, `/shacman/engine/<engine_slug>/` и варианты `.../in-stock/` по данным инвентаря (≥2 товара, лимит ~60 страниц).
- **B4:** Карточки товара: override из 0027 или авто Title/Description/H1/первый абзац; alt изображений «{тип} SHACMAN {серия} {формула} {код}»; блок ссылок на хабы и «Похожие».
- **B5:** Product+Offer JSON-LD только на чистом URL карточки; на URL с GET schema не выводится. Smoke: на чистом URL schema есть, на `?utm_source=test` — нет.
- **B6:** Все чистые URL `/shacman/*` (включая B3) в sitemap, lastmod по возможности из updated_at.

---

## 2. Перечень хабов (URL → фильтр → примечание)

| URL | Фильтр | Кол-во товаров (пример) |
|-----|--------|-------------------------|
| `/shacman/` | series=SHACMAN | все публичные SHACMAN |
| `/shacman/in-stock/` | series=SHACMAN, total_qty>0 | в наличии |
| `/shacman/<category_slug>/` | series=SHACMAN, category.slug | по категории (samosvaly, sedelnye-tyagachi и т.д.) |
| `/shacman/<category_slug>/in-stock/` | + total_qty>0 | категория, в наличии |
| `/shacman/series/<series_slug>/` | model_variant.line → slug | ≥2 товара, до 20 серий |
| `/shacman/series/<series_slug>/in-stock/` | + total_qty>0 | только если есть в наличии |
| `/shacman/formula/<formula>/` | wheel_formula нормализован (4x2/6x4/8x4) | ≥2 товара, до 20 формул |
| `/shacman/formula/<formula>/in-stock/` | + total_qty>0 | только если есть в наличии |
| `/shacman/engine/<engine_slug>/` | engine_model → slug | ≥2 товара, до 20 двигателей |
| `/shacman/engine/<engine_slug>/in-stock/` | + total_qty>0 | только если есть в наличии |

Хабы B3 создаются только для кластеров с **≥2 товарами**; по каждому типу (series/formula/engine) берётся до **20** значений; суммарно новых страниц B3 — до ~60 (серии×2 + формулы×2 + двигатели×2 с учётом in-stock).

---

## 3. Логика slug для series / formula / engine

- **series_slug:** из `model_variant.line` — `slugify(line)` (латиница/цифры, нижний регистр). Пример: линия «X3000» → `x3000`.
- **formula:** нормализация `wheel_formula` в один из видов `4x2`, `6x4`, `8x4` (символ `×` заменяется на `x`). В URL передаётся строка без слешей, например `6x4`.
- **engine_slug:** из `engine_model` — `slugify(engine_model)`. Пример: «WP13.550E501» → `wp13550e501` (зависит от реализации slugify).

Функции: `_shacman_normalize_formula()` (views), `_shacman_allowed_clusters()` (views) — возвращает списки допустимых series_slugs, formulas, engine_slugs по БД.

---

## 4. Шаблоны Title/Description (карточка товара)

Логика в `catalog/seo_product.py` и во вьюхе `product_detail`. При заполненных полях миграции 0027 (`seo_title_override`, `seo_description_override`) используются они.

**Авто-шаблон:**

- **Title:** `{model_name_ru} — {wheel_formula}, {engine/опции} — {модификатор: цена, в наличии / цена под заказ} | CARFAST`. Длина до 255 символов.
- **Description:** краткое описание или сборка из полей + «В наличии и под заказ, возможен лизинг и доставка. Запросите КП.» До 160 символов.
- **H1:** чистое имя модели (`build_product_h1`).
- **Первый абзац:** серия + формула + код + двигатель + лизинг/доставка/КП (`build_product_first_block` или override).

**Примеры (условные):**

1. **Седельный тягач 4x2, WP13.550E501 (SX418853381):**  
   Title: `Седельный тягач — 4x2, WP13.550E501 — цена, в наличии | CARFAST`  
   Description: «Седельный тягач SHACMAN. Колёсная формула 4x2. В наличии и под заказ, возможен лизинг и доставка. Запросите КП.»

2. **Самосвал 6x4, WP12:**  
   Title: `Самосвал — 6x4, WP12 — в наличии | CARFAST`  
   Description: по полям товара + «В наличии и под заказ…».

3. **С переопределением:**  
   Если заданы `seo_title_override` / `seo_description_override` — выводятся они (с обрезкой по длине).

**Alt изображений:** `{тип} SHACMAN {серия} {формула} {код}` (например: «Седельный тягач SHACMAN X3000 4x2 SX418853381»).

---

## 5. Редактирование контента хабов в админке

- **Модель:** `ShacmanHubSEO` (каталог → раздел SHACMAN SEO).
- **Поля:** тип хаба (hub, in_stock, category, series, formula, engine), опциональный ключ (category_slug, series_slug, formula, engine_slug), `title`, `description`, `seo_text` (HTML/текст 900–1500 слов), `faq` (JSON или текст), «также ищут».
- Одна запись может соответствовать конкретному хабу (например category=in_stock, key=пусто для `/shacman/in-stock/`). Во вьюхах ищется запись по `hub_type` + `key`; при отсутствии используются дефолтные заголовки и текст-заглушка.
- Контент хабов (в т.ч. B3) можно вынести в отдельные записи по типу (series/formula/engine) и ключу, чтобы редактировать Title/H1/Description и блоки текста/FAQ без деплоя.

---

## 6. Команды проверки после деплоя (curl)

Базовый URL: `https://carfst.ru` (или свой BASE_URL).

```bash
# 1) /shacman/ — 200, canonical чистый
curl -sI "https://carfst.ru/shacman/"
curl -s "https://carfst.ru/shacman/" | grep -o 'rel="canonical" href="[^"]*"'
# Ожидание: HTTP 200, canonical = https://carfst.ru/shacman/

# 2) /shacman/?page=1 — редирект на чистый URL
curl -sI "https://carfst.ru/shacman/?page=1"
# Ожидание: 301/302, Location заканчивается на /shacman/

# 3) /shacman/?page=2 — noindex, self-canonical
curl -s "https://carfst.ru/shacman/?page=2" | grep -E 'robots|canonical'
# Ожидание: noindex, follow; canonical с ?page=2

# 4) Один хаб B3 (подставить реальный путь из sitemap/инвентаря)
curl -sI "https://carfst.ru/shacman/formula/6x4/"
curl -s "https://carfst.ru/shacman/formula/6x4/" | grep -o 'rel="canonical" href="[^"]*"'
# Ожидание: 200, canonical = https://carfst.ru/shacman/formula/6x4/

# 5) Карточка SHACMAN — schema на чистом URL есть, на URL с utm — нет
SLUG="shacman-samosval-..."   # подставить реальный slug
curl -s "https://carfst.ru/product/${SLUG}/" | grep -o '"@type"[[:space:]]*:[[:space:]]*"Product"'
# Должна быть строка с Product
curl -s "https://carfst.ru/product/${SLUG}/?utm_source=test" | grep -o '"@type"[[:space:]]*:[[:space:]]*"Product"'
# Не должно быть (пустой вывод или отсутствие Product в body)
```

**Диагностика URL на сервере:**

```bash
set -a; source /etc/carfst/carfst.env; set +a
python manage.py url_resolve_diagnostic
```

Ожидаемо: `resolve('shacman/')` → имя вьюхи (shacman_hub); в urlpatterns первыми идут маршруты `shacman/`.

---

## 7. Smoke-тесты (регрессия деплоя)

Скрипт: `scripts/smoke_seo.sh [BASE_URL] [PRODUCT_SLUG] [B3_HUB_PATH]`

- **Проверка 5b:** `GET /shacman/` → 200, text/html, canonical чистый (без query).
- **Проверка 5c:** `GET /shacman/?page=2` → 200, robots noindex, follow, canonical self `.../shacman/?page=2`.
- **Проверка 7:** При переданном `PRODUCT_SLUG`: `GET /product/<slug>/?utm_source=test` → 200, canonical чистый, **отсутствие** schema (Product/FAQPage/BreadcrumbList) в body.
- **Проверка 7b:** При переданном `PRODUCT_SLUG`: `GET /product/<slug>/` (чистый URL) → 200, в body присутствует JSON-LD с `"@type":"Product"`.
- **Проверка 8:** При переданном `B3_HUB_PATH` (например `shacman/formula/6x4`): `GET /<B3_HUB_PATH>/` → 200, canonical чистый (без query).

Деплой должен вызывать smoke после выката; при падении любой проверки деплой считается неуспешным.

---

## 8. Изменённые/добавленные файлы

| Путь | Изменения |
|------|-----------|
| **carfst_site/urls.py** | Маршруты SHACMAN в начале urlpatterns; добавлены B3 (series/formula/engine + in-stock). |
| **catalog/urls.py** | Удалены дублирующие shacman path. |
| **catalog/views.py** | shacman_hub, shacman_in_stock, shacman_category*, интеграция ShacmanHubSEO; B3 вьюхи и _shacman_allowed_clusters, _shacman_normalize_formula; product_detail: seo_hub_links, related_products, schema только без GET. |
| **catalog/models.py** | Модель ShacmanHubSEO. |
| **catalog/admin.py** | Регистрация ShacmanHubSEO. |
| **catalog/migrations/0028_add_shacman_hub_seo.py** | Миграция для ShacmanHubSEO. |
| **catalog/sitemaps.py** | ShacmanHubSitemap: hub, in_stock, series/formula/engine (+ in_stock), category (+ in_stock); lastmod по данным. |
| **catalog/seo_product.py** | Title/Description/H1/first_block, build_product_image_alt для SHACMAN. |
| **templates/catalog/shacman_hub.html** | SEO-текст, FAQ, «также ищут», ссылки на категории и топ-товары. |
| **scripts/smoke_seo.sh** | Проверки 5b, 5c, 7 (product utm), 7b (product clean URL — schema есть), 8 (B3 hub 200 + canonical). |
| **docs/SHACMAN_SEO_IMPLEMENTATION.md** | Этот документ. |

Старый отчёт: `docs/SHACMAN_SEO_REPORT.md` заменён данным документом.
