# Технический SEO-аудит carfst.ru — Финальный отчёт

## Выполненные задачи

### 1) Sitemap.xml ✅

**Реализовано:**
- Sitemap включает только indexable URL
- Исключён `/catalog/` (не включён в StaticViewSitemap)
- Исключены все URL с querystring (включая `?page=`)
- Lastmod проставлен для products, blog posts, series/categories

**Тесты добавлены:**
- `test_sitemap_xml_ok_and_no_get_catalog_links` - проверяет отсутствие `/catalog/?`
- `test_sitemap_xml_no_page_params` - проверяет отсутствие `?page=` и `&page=`
- `test_sitemap_xml_contains_series_landing` - проверяет наличие `/catalog/series/shacman/`
- `test_sitemap_excludes_catalog_root` - проверяет отсутствие `/catalog/` как standalone URL
- `test_sitemap_excludes_querystring_urls` - проверяет отсутствие любых querystring параметров

### 2) Structured data (JSON-LD) ✅

**BreadcrumbList:**
- Добавлен на catalog landing pages (series/category/series_category)
- Schema ровно одна на странице
- Все URL абсолютные (через `request.build_absolute_uri()`)
- Добавляется только для indexable страниц (page=1 или без page, без лишних GET-параметров)

**BlogPosting:**
- Добавлен на страницах постов блога
- Поля: `headline`, `description`, `url`, `mainEntityOfPage`, `datePublished`, `dateModified`, `author`, `publisher`, `image` (если есть)

**Тесты добавлены:**
- `test_catalog_series_has_breadcrumb_schema` - проверяет BreadcrumbList для series landing
- `test_catalog_category_has_breadcrumb_schema` - проверяет BreadcrumbList для category landing
- `test_catalog_series_category_has_breadcrumb_schema` - проверяет BreadcrumbList для series+category landing
- `test_breadcrumb_urls_are_absolute` - проверяет, что все breadcrumb URLs абсолютные
- `test_blog_post_has_blogposting_schema` - проверяет наличие BlogPosting
- `test_blogposting_has_required_fields` - проверяет все обязательные поля включая `mainEntityOfPage`

### 3) Open Graph / Twitter ✅

**Реализовано:**
- Default `og:image` для всех страниц (`/static/img/logo-h128.webp`)
- `twitter:card=summary_large_image` (уже было)
- `twitter:image` автоматически использует `og:image`

**Тесты добавлены:**
- `test_pages_have_default_og_image` - проверяет наличие og:image на главной
- `test_og_image_on_different_page_types` - проверяет og:image на разных типах страниц (home, static, catalog landing, product)
- `test_twitter_card_present` - проверяет наличие twitter:card

### 4) Диагностика билда ✅

**Реализовано:**
- `/__version__/` endpoint возвращает `{"build_id": "<value>"}`
- `X-Build-ID` header ставится на все ответы (включая редиректы)
- BUILD_ID согласован между header, endpoint и функцией `get_build_id()`

**Тесты добавлены:**
- `test_build_id_header_on_redirects` - проверяет X-Build-ID на редиректах
- `test_build_id_matches_version_endpoint` - проверяет согласованность BUILD_ID между header, endpoint и функцией

## Изменённые файлы

1. **catalog/views.py**
   - Добавлена функция `_build_breadcrumb_schema()` для генерации BreadcrumbList JSON-LD
   - Обновлены `catalog_series()`, `catalog_category()`, `catalog_series_category()` для добавления BreadcrumbList
   - Обновлена `_seo_context()` для добавления default og:image

2. **blog/views.py**
   - Добавлен импорт `json`
   - Обновлена `blog_detail()` для добавления BlogPosting JSON-LD с полем `mainEntityOfPage`

3. **tests/test_technical_seo.py**
   - Добавлены тесты для sitemap (отсутствие `/catalog/`, `?page=`, querystring)
   - Добавлены тесты для BreadcrumbList на catalog landing pages
   - Добавлены тесты для валидации абсолютных URL в breadcrumbs
   - Добавлены тесты для BlogPosting с проверкой всех обязательных полей
   - Добавлены тесты для og:image на разных типах страниц
   - Добавлены тесты для twitter:card
   - Добавлены тесты для BUILD_ID на редиректах и согласованности

## Ключевые diff-фрагменты

### BreadcrumbList для catalog landing pages

```python
# catalog/views.py
def _build_breadcrumb_schema(request, items: list[dict]) -> dict:
    """Build BreadcrumbList JSON-LD schema with absolute URLs."""
    breadcrumb_items = []
    for position, item in enumerate(items, start=1):
        breadcrumb_items.append({
            "@type": "ListItem",
            "position": position,
            "name": item["name"],
            "item": request.build_absolute_uri(item["url"]),  # Абсолютный URL
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumb_items,
    }

# В catalog_series(), catalog_category(), catalog_series_category():
breadcrumb_schema = None
if not page_num and not extra_keys:  # Только для indexable страниц
    breadcrumb_items = [
        {"name": "Главная", "url": reverse("catalog:home")},
        {"name": series.name, "url": reverse("catalog:catalog_series", kwargs={"slug": series.slug})},
    ]
    breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
    if breadcrumb_schema:
        context["page_schema_payload"] = json.dumps([breadcrumb_schema], ensure_ascii=False)[1:-1]
```

### BlogPosting с mainEntityOfPage

```python
# blog/views.py
blogposting_schema = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": post.title,
    "description": post.excerpt,
    "url": canonical,
    "mainEntityOfPage": {  # Добавлено
        "@type": "WebPage",
        "@id": canonical,
    },
    "datePublished": post.published_at.isoformat() if post.published_at else None,
    "dateModified": post.updated_at.isoformat(),
    "author": {
        "@type": "Organization",
        "@id": "https://carfst.ru/#organization",
        "name": "CARFAST",
    },
    "publisher": {
        "@type": "Organization",
        "@id": "https://carfst.ru/#organization",
        "name": "CARFAST",
    },
}
```

### Default og:image

```python
# catalog/views.py в _seo_context()
# Default og:image if none set (brand asset)
if not context.get("og_image"):
    from django.contrib.staticfiles.storage import staticfiles_storage
    default_og_image = request.build_absolute_uri(staticfiles_storage.url("img/logo-h128.webp"))
    context["og_image"] = default_og_image
```

## Команды для проверки

### Локальная проверка

```bash
# Запуск всех SEO тестов
python -m pytest tests/test_technical_seo.py -v
python -m pytest tests/test_build_id_header.py -v

# Проверка sitemap.xml
curl -s http://localhost:8000/sitemap.xml | grep -E "(catalog/|page=|\?)" | head -20
curl -s http://localhost:8000/sitemap.xml | grep -c "https://carfst.ru/catalog/"
curl -s http://localhost:8000/sitemap.xml | grep "catalog/series/shacman/"

# Проверка отсутствия /catalog/ в sitemap
curl -s http://localhost:8000/sitemap.xml | grep -c '<loc>.*catalog/</loc>'

# Проверка отсутствия querystring в sitemap
curl -s http://localhost:8000/sitemap.xml | grep -E '\?|&' || echo "OK: no querystring found"

# Проверка BreadcrumbList на landing page
curl -s http://localhost:8000/catalog/series/shacman/ | grep -A 15 "BreadcrumbList"

# Проверка абсолютных URL в breadcrumbs
curl -s http://localhost:8000/catalog/series/shacman/ | grep -o '"item":"[^"]*"' | grep -v "http" && echo "ERROR: relative URL found" || echo "OK: all URLs absolute"

# Проверка BlogPosting на blog post (замените <post-slug> на реальный)
curl -s http://localhost:8000/blog/<post-slug>/ | grep -A 20 "BlogPosting"
curl -s http://localhost:8000/blog/<post-slug>/ | grep "mainEntityOfPage"

# Проверка og:image на разных страницах
curl -s http://localhost:8000/ | grep "og:image"
curl -s http://localhost:8000/parts/ | grep "og:image"
curl -s http://localhost:8000/catalog/series/shacman/ | grep "og:image"

# Проверка twitter:card
curl -s http://localhost:8000/ | grep "twitter:card"

# Проверка BUILD_ID
curl -sI http://localhost:8000/ | grep "X-Build-ID"
curl -s http://localhost:8000/__version__/ | python -m json.tool
curl -sI http://localhost:8000/catalog/?series=shacman | grep "X-Build-ID"  # Редирект

# Проверка SEO-инвариантов каталога (не должны быть нарушены)
curl -sI http://localhost:8000/catalog/
curl -s http://localhost:8000/catalog/ | grep "robots"
curl -s http://localhost:8000/catalog/series/shacman/?page=2 | grep "robots"
curl -s http://localhost:8000/catalog/series/shacman/?utm_source=test | grep "robots"
```

### PROD проверка

```bash
# Проверка sitemap.xml
curl -sI https://carfst.ru/sitemap.xml
curl -s https://carfst.ru/sitemap.xml | grep -E "(catalog/|page=|\?)" | head -20
curl -s https://carfst.ru/sitemap.xml | grep -c "https://carfst.ru/catalog/"
curl -s https://carfst.ru/sitemap.xml | grep "catalog/series/shacman/"

# Проверка отсутствия /catalog/ в sitemap
curl -s https://carfst.ru/sitemap.xml | grep -c '<loc>.*catalog/</loc>'

# Проверка отсутствия querystring в sitemap
curl -s https://carfst.ru/sitemap.xml | grep -E '\?|&' || echo "OK: no querystring found"

# Проверка BreadcrumbList на landing page
curl -s https://carfst.ru/catalog/series/shacman/ | grep -A 15 "BreadcrumbList"

# Проверка абсолютных URL в breadcrumbs
curl -s https://carfst.ru/catalog/series/shacman/ | grep -o '"item":"[^"]*"' | grep -v "https" && echo "ERROR: relative URL found" || echo "OK: all URLs absolute"

# Проверка BlogPosting на blog post (замените <post-slug> на реальный)
curl -s https://carfst.ru/blog/<post-slug>/ | grep -A 20 "BlogPosting"
curl -s https://carfst.ru/blog/<post-slug>/ | grep "mainEntityOfPage"

# Проверка og:image на разных страницах
curl -s https://carfst.ru/ | grep "og:image"
curl -s https://carfst.ru/parts/ | grep "og:image"
curl -s https://carfst.ru/catalog/series/shacman/ | grep "og:image"

# Проверка twitter:card
curl -s https://carfst.ru/ | grep "twitter:card"

# Проверка BUILD_ID
curl -sI https://carfst.ru/ | grep "X-Build-ID"
curl -s https://carfst.ru/__version__/ | python -m json.tool
curl -sI https://carfst.ru/catalog/?series=shacman | grep "X-Build-ID"  # Редирект

# Проверка SEO-инвариантов каталога (не должны быть нарушены)
curl -sI https://carfst.ru/catalog/
curl -s https://carfst.ru/catalog/ | grep "robots"
curl -s https://carfst.ru/catalog/series/shacman/?page=2 | grep "robots"
curl -s https://carfst.ru/catalog/series/shacman/?utm_source=test | grep "robots"
```

## Критерии приёмки

✅ Все тесты проходят: `pytest -q`
✅ `curl -sI https://carfst.ru/sitemap.xml` отдаёт 200 и корректный Content-Type
✅ sitemap.xml не содержит `/catalog/` и не содержит `?page=` или любые querystring параметры
✅ На страницах присутствует нужная JSON-LD разметка:
   - BreadcrumbList на catalog landing pages (только одна schema, абсолютные URL)
   - BlogPosting на blog posts (со всеми обязательными полями включая mainEntityOfPage)
✅ SEO-инварианты каталога сохранены:
   - `/catalog/` — noindex, follow, не в sitemap
   - Landing pages (page=1) — index, follow
   - Пагинация (page>1) — noindex, follow + self-canonical
   - Лишние GET-параметры — noindex, follow
✅ og:image/twitter:image присутствует на всех страницах
✅ X-Build-ID header присутствует на всех ответах (включая редиректы)
✅ BUILD_ID согласован между header, `/__version__/` и функцией `get_build_id()`

## Примечания

- Все изменения обратно совместимы
- SEO-инварианты каталога не нарушены
- Существующие тесты не сломаны
- Добавлены новые тесты для проверки всех новых функций
- BreadcrumbList добавляется только для indexable страниц (page=1 или без page, без лишних GET-параметров)
- Все breadcrumb URLs абсолютные через `request.build_absolute_uri()`
- BlogPosting включает `mainEntityOfPage` для лучшей индексации
