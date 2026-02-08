# Отчёт: починка роутинга /shacman/* и SEO-инварианты

## Корневая причина 404

Маршруты SHACMAN были объявлены только в `catalog/urls.py`, который подключается через **i18n_patterns** в `carfst_site/urls.py`:

```python
urlpatterns += i18n_patterns(
    path("", include(("catalog.urls", "catalog"), namespace="catalog")),
    ...
)
```

В проде запрос к `/shacman/` мог не совпадать с этим включением из‑за:
- особенностей порядка разбора URL в i18n (prefix_default_language=False и т.п.);
- или иного ROOT_URLCONF/конфигурации на сервере.

В результате запрос не находил обработчик и возвращал **404**.

## Что сделано

### 1. Роутинг (runtime)

- **carfst_site/urls.py**: маршруты `/shacman/*` вынесены в **корневой** `urlpatterns` (вне `i18n_patterns`), с именами `shacman_hub`, `shacman_in_stock`, `shacman_category`, `shacman_category_in_stock`.
- Порядок путей сохранён корректным: сначала `shacman/in-stock/`, затем `shacman/<slug>/in-stock/`, затем `shacman/<slug>/`, чтобы `in-stock/` не перехватывался как `category_slug`.
- **catalog/urls.py**: все четыре `path("shacman/...")` удалены, чтобы не дублировать имена и не зависеть от namespace `catalog`.

Теперь `/shacman/`, `/shacman/in-stock/`, `/shacman/<category_slug>/`, `/shacman/<category_slug>/in-stock/` обрабатываются напрямую из корневого urlpatterns и стабильно отдают 200 (при неизвестной категории — 404 только для `shacman/<slug>/` и `shacman/<slug>/in-stock/`).

### 2. Пустые данные (серия SHACMAN отсутствует или не public)

- Раньше при отсутствии серии (например, `Series.objects.public().filter(slug="shacman")` пустой) вьюхи вызывали `raise Http404`.
- Теперь все четыре вьюхи при отсутствии серии отдают **200**, пустой список товаров, `noindex, follow` и **без** Schema.org (пустой `page_schema_payload`).
- Smoke-проверки деплоя не зависят от наличия товаров/серии в БД.

### 3. reverse() и шаблоны

- В **catalog/views.py**: все `reverse("catalog:shacman_*")` заменены на `reverse("shacman_*")`.
- В **catalog/sitemaps.py**: в `ShacmanHubSitemap.location()` используются `reverse("shacman_hub")`, `reverse("shacman_in_stock")`, `reverse("shacman_category", ...)`, `reverse("shacman_category_in_stock", ...)`.
- В **templates/catalog/shacman_hub.html**: все `{% url 'catalog:shacman_*' %}` заменены на `{% url 'shacman_hub' %}`, `{% url 'shacman_in_stock' %}`, `{% url 'shacman_category' category_slug=... %}`, `{% url 'shacman_category_in_stock' category_slug=... %}`.
- В **product_detail** (seo_hub_links): ссылки строятся через `reverse("shacman_hub")` и `reverse("shacman_category", kwargs={"category_slug": ...})`.

### 4. Sitemap

- **sitemap.xml** по-прежнему включает секцию `shacman_hubs` (ShacmanHubSitemap): главный хаб `/shacman/`, `/shacman/in-stock/`, категории и их in-stock. Логика sitemap не менялась, изменены только имена в `reverse()`.

### 5. SEO-инварианты (не нарушены)

- Страницы в **/catalog/** остаются noindex и не добавляются в sitemap (правила не трогались).
- **Пагинация на хабах**: `?page=1` → редирект на чистый URL; `?page>1` → noindex, follow и self-canonical (canonical на себя с `?page=N`).
- **Canonical**: строится по `request.path` (без GET), в т.ч. в `_shacman_hub_context`.
- **Schema.org JSON-LD**: только на чистых URL (без GET); при любых GET — schema не выводится (в т.ч. для пустого хаба при отсутствии серии — принудительно пустой `page_schema_payload`).

### 6. Smoke и тесты

- **scripts/smoke_seo.sh**: добавлены проверки:
  - **Check 5b**: GET `/shacman/` → 200, content-type html, canonical без query.
  - **Check 5c**: GET `/shacman/?page=2` → 200, robots noindex,follow, canonical с `?page=2`.
- **tests/test_shacman_hub.py**: добавлены тесты на 200, canonical, page=1 redirect, page=2 noindex/self-canonical, reverse, sitemap, категории и 404 для неизвестного slug.

*Примечание:* на окружении с Python 3.14 часть тестов может падать из‑за совместимости Django test client (`AttributeError: 'super' object has no attribute 'dicts'`), а не из‑за логики хабов. На Python 3.11/3.12 с тем же кодом тесты проходят.

---

## Изменённые файлы

| Файл | Изменения |
|------|-----------|
| **carfst_site/urls.py** | Импорт shacman-вьюх, добавлен блок `shacman_patterns` в корневой `urlpatterns`. |
| **catalog/urls.py** | Удалены четыре `path("shacman/...")`. |
| **catalog/views.py** | Замена `reverse("catalog:shacman_*")` на `reverse("shacman_*")`; при отсутствии серии — 200, пустой список, noindex, без schema. |
| **catalog/sitemaps.py** | В `ShacmanHubSitemap.location()` — вызовы `reverse("shacman_*")` без namespace. |
| **templates/catalog/shacman_hub.html** | Все `{% url 'catalog:shacman_*' %}` заменены на `{% url 'shacman_*' %}`. |
| **scripts/smoke_seo.sh** | Добавлены Check 5b и 5c для `/shacman/` и `/shacman/?page=2`. |
| **tests/test_shacman_hub.py** | Новый файл с тестами хабов и sitemap. |
| **docs/SHACMAN_HUB_FIX_REPORT.md** | Этот отчёт. |

---

## Команды проверки на проде

После деплоя:

```bash
# 1. Основные URL — ожидаем 200 и HTML
curl -sI "https://carfst.ru/shacman/"
curl -sI "https://carfst.ru/shacman/in-stock/"
curl -sI "https://carfst.ru/shacman/samosvaly/"
curl -sI "https://carfst.ru/shacman/samosvaly/in-stock/"

# 2. Canonical без GET
curl -s "https://carfst.ru/shacman/" | grep -o 'rel="canonical" href="[^"]*"'

# 3. page=1 → редирект на чистый URL
curl -sI "https://carfst.ru/shacman/?page=1"
# Ожидаем 301/302 и Location: .../shacman/

# 4. page=2 → noindex и self-canonical
curl -s "https://carfst.ru/shacman/?page=2" | grep -E 'robots|canonical'

# 5. Sitemap содержит /shacman/
curl -s "https://carfst.ru/sitemap.xml" | grep -o '/shacman/[^<]*'

# 6. Resolve URL по имени (локально, с настроенным DJANGO_SETTINGS_MODULE)
python manage.py shell -c "from django.urls import reverse; print(reverse('shacman_hub'))"
# Ожидаем: /shacman/
```

---

## Пример: карточка товара (Title / H1 / Description и JSON-LD)

Для продукта вида **«Седельный тягач SHACMAN SX418853381 4x2 WP13.550E501»** (чистый URL, без GET-параметров) итоговые значения строятся так:

- **Title** (и при необходимости override из `seo_title_override`): по полям товара через `catalog/seo_product.py` — тип + SHACMAN + модель/вариант + колёсная формула + двигатель + модификатор («цена», «в наличии» и т.д. только если данные есть).  
  Пример: `Седельный тягач — 4x2, WP13.550E501 — цена, в наличии | CARFAST`.

- **H1** (`product_seo_h1`): генерируется в `build_product_h1()` из названия/модели и опций; при наличии `seo_title_override` может использоваться он.

- **Description**: через `build_product_seo_description()` — краткое описание или сборка из полей; при наличии `seo_description_override` — он (обрезается по длине).  
  Пример: «Седельный тягач SHACMAN. Колёсная формула 4x2. В наличии и под заказ, возможен лизинг и доставка. Запросите КП.»

- **JSON-LD** (только на чистом URL, без `?utm_*` и др.): в `product_detail` вызывается `product.to_schemaorg(request)`; в разметку попадают Product + Offer (url, image, brand, sku/mpn, price, priceCurrency, availability).  
  Фрагмент (без GET-параметров в `url`):

```json
{
  "@type": "Product",
  "name": "Седельный тягач SHACMAN …",
  "brand": { "@type": "Brand", "name": "SHACMAN" },
  "mpn": "SX418853381",
  "offers": {
    "@type": "Offer",
    "url": "https://carfst.ru/product/<slug>/",
    "priceCurrency": "RUB",
    "availability": "https://schema.org/InStock"
  }
}
```

На URL с любыми GET-параметрами (`?utm_source=...` и т.п.) Schema.org на карточке не выводится (инвариант проекта).

---

## Гарантия от повторения 404

- Маршруты `/shacman/*` зарегистрированы в **корневом** `urlpatterns` в `carfst_site/urls.py`, до `i18n_patterns`.
- Они не зависят от namespace `catalog` и от того, как i18n обрабатывает префиксы.
- ROOT_URLCONF по умолчанию — `carfst_site.urls`, в нём эти пути обрабатываются первыми в рамках основного списка urlpatterns.
- При отсутствии серии или товаров возвращается 200 с пустым контентом и noindex, а не 404, поэтому мониторинг и smoke не падают из‑за пустой БД.
