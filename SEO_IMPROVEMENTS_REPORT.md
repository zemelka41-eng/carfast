# Отчёт о SEO-доработках сайта carfst.ru

## Выполненные задачи

### A) Sitemap.xml

✅ **Проверено и подтверждено:**
- Sitemap содержит ТОЛЬКО indexable URL
- Исключён `/catalog/` (не включён в StaticViewSitemap)
- Исключены `?page=` параметры (все location() методы возвращают чистые URL)
- Исключены параметризованные URL (только landing pages через SeriesSitemap, CategorySitemap, SeriesCategorySitemap)

**Включено в sitemap:**
- Главная страница (`catalog:home`)
- Статические страницы (parts, service, used, contacts, etc.)
- Blog list + blog posts
- Product pages (через ProductSitemap)
- Indexable landing pages каталога:
  - `/catalog/series/<series>/` (через SeriesSitemap)
  - `/catalog/category/<category>/` (через CategorySitemap)
  - `/catalog/series/<series>/<category>/` (через SeriesCategorySitemap)

**Lastmod проставлен:**
- Products: `updated_at`
- Blog posts: `updated_at`
- Series/Categories: `latest_product` (Max products__updated_at)

**Тесты добавлены:**
- `test_sitemap_xml_no_page_params` - проверяет отсутствие `?page=` в sitemap
- `test_sitemap_xml_contains_series_landing` - проверяет наличие `/catalog/series/shacman/` в sitemap
- Существующий тест `test_sitemap_xml_ok_and_no_get_catalog_links` проверяет отсутствие `/catalog/?`

### B) Structured data (JSON-LD)

✅ **Site-wide:**
- Organization уже присутствует в `base.html` (не изменено)

✅ **Catalog landing pages:**
- Добавлен BreadcrumbList для:
  - `/catalog/series/<series>/` - Главная → Series
  - `/catalog/category/<category>/` - Главная → Category
  - `/catalog/series/<series>/<category>/` - Главная → Series → Category
- BreadcrumbList добавляется только для indexable страниц (page=1 или без page, без лишних GET-параметров)

✅ **Product page:**
- Product + Offer уже присутствует через `product.to_schemaorg()` (не изменено)
- BreadcrumbList уже присутствует (не изменено)

✅ **Blog posts:**
- Добавлен BlogPosting JSON-LD с полями:
  - `headline` - заголовок поста
  - `description` - excerpt
  - `datePublished` - дата публикации
  - `dateModified` - дата обновления
  - `author` - Organization (CARFAST)
  - `publisher` - Organization (CARFAST)
  - `image` - cover_image если есть

**Тесты добавлены:**
- `test_catalog_series_has_breadcrumb_schema` - проверяет BreadcrumbList для series landing
- `test_catalog_category_has_breadcrumb_schema` - проверяет BreadcrumbList для category landing
- `test_catalog_series_category_has_breadcrumb_schema` - проверяет BreadcrumbList для series+category landing
- `test_blog_post_has_blogposting_schema` - проверяет BlogPosting для blog posts

### C) Метаданные

✅ **Проверена уникальность:**
- `<title>` и `<meta name="description">` для ключевых страниц (home, parts, service, used, contacts, blog)
- Все страницы имеют уникальные title и description

✅ **og:image/twitter:image:**
- Добавлен default og:image (`img/logo-h128.webp`) для всех страниц, где не указан явно
- Twitter Card автоматически использует og:image

**Тесты добавлены:**
- `test_key_pages_have_unique_titles` - проверяет уникальность title
- `test_key_pages_have_unique_descriptions` - проверяет уникальность description
- `test_pages_have_default_og_image` - проверяет наличие og:image по умолчанию

## Изменённые файлы

1. **catalog/views.py**
   - Добавлена функция `_build_breadcrumb_schema()` для генерации BreadcrumbList JSON-LD
   - Обновлены `catalog_series()`, `catalog_category()`, `catalog_series_category()` для добавления BreadcrumbList
   - Обновлена `_seo_context()` для добавления default og:image

2. **blog/views.py**
   - Добавлен импорт `json`
   - Обновлена `blog_detail()` для добавления BlogPosting JSON-LD

3. **tests/test_technical_seo.py**
   - Добавлены тесты для sitemap (отсутствие `?page=`, наличие series landing)
   - Добавлены тесты для BreadcrumbList на catalog landing pages
   - Добавлены тесты для BlogPosting на blog posts
   - Добавлены тесты для уникальности метаданных
   - Добавлены тесты для default og:image

## Ключевые diff-фрагменты

### Добавление BreadcrumbList для catalog landing pages

```python
# catalog/views.py
def _build_breadcrumb_schema(request, items: list[dict]) -> dict:
    """Build BreadcrumbList JSON-LD schema."""
    breadcrumb_items = []
    for position, item in enumerate(items, start=1):
        breadcrumb_items.append({
            "@type": "ListItem",
            "position": position,
            "name": item["name"],
            "item": request.build_absolute_uri(item["url"]),
        })
    
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumb_items,
    }

# В catalog_series(), catalog_category(), catalog_series_category():
breadcrumb_schema = None
if not page_num and not extra_keys:
    breadcrumb_items = [
        {"name": "Главная", "url": reverse("catalog:home")},
        {"name": series.name, "url": reverse("catalog:catalog_series", kwargs={"slug": series.slug})},
    ]
    breadcrumb_schema = _build_breadcrumb_schema(request, breadcrumb_items)
    if breadcrumb_schema:
        context["page_schema_payload"] = json.dumps([breadcrumb_schema], ensure_ascii=False)[1:-1]
```

### Добавление BlogPosting для blog posts

```python
# blog/views.py
blogposting_schema = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": post.title,
    "description": post.excerpt,
    "url": canonical,
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
if og_image:
    blogposting_schema["image"] = request.build_absolute_uri(og_image)

schema_json = json.dumps([blogposting_schema], ensure_ascii=False)
context["page_schema_payload"] = schema_json[1:-1].strip()
```

### Добавление default og:image

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

# Проверка sitemap.xml
curl -s http://localhost:8000/sitemap.xml | grep -E "(catalog/|page=)" | head -20

# Проверка наличия BreadcrumbList на landing page
curl -s http://localhost:8000/catalog/series/shacman/ | grep -A 10 "BreadcrumbList"

# Проверка наличия BlogPosting на blog post
curl -s http://localhost:8000/blog/<post-slug>/ | grep -A 10 "BlogPosting"

# Проверка og:image на главной
curl -s http://localhost:8000/ | grep "og:image"
```

### PROD проверка

```bash
# Проверка sitemap.xml
curl -sI https://carfst.ru/sitemap.xml
curl -s https://carfst.ru/sitemap.xml | grep -E "(catalog/|page=)" | head -20

# Проверка отсутствия /catalog/ в sitemap
curl -s https://carfst.ru/sitemap.xml | grep -c "https://carfst.ru/catalog/"

# Проверка наличия series landing в sitemap
curl -s https://carfst.ru/sitemap.xml | grep "catalog/series/shacman/"

# Проверка BreadcrumbList на landing page
curl -s https://carfst.ru/catalog/series/shacman/ | grep -A 10 "BreadcrumbList"

# Проверка BlogPosting на blog post (замените <post-slug> на реальный)
curl -s https://carfst.ru/blog/<post-slug>/ | grep -A 10 "BlogPosting"

# Проверка og:image на главной
curl -s https://carfst.ru/ | grep "og:image"

# Проверка SEO-инвариантов каталога (не должны быть нарушены)
curl -sI https://carfst.ru/catalog/
curl -s https://carfst.ru/catalog/ | grep "robots"
curl -s https://carfst.ru/catalog/series/shacman/?page=2 | grep "robots"
curl -s https://carfst.ru/catalog/series/shacman/?utm_source=test | grep "robots"
```

## Критерии приёмки

✅ Все тесты проходят (pytest)
✅ `curl -sI https://carfst.ru/sitemap.xml` отдаёт 200 и корректный Content-Type
✅ sitemap.xml не содержит `/catalog/` и не содержит `?page=`
✅ На страницах присутствует нужная JSON-LD разметка:
   - BreadcrumbList на catalog landing pages
   - BlogPosting на blog posts
   - Organization на всех страницах (уже было)
✅ SEO-инварианты каталога сохранены:
   - `/catalog/` — noindex, follow
   - Landing pages (page=1) — index, follow
   - Пагинация (page>1) — noindex, follow + self-canonical
   - Лишние GET-параметры — noindex, follow
✅ Формулировка «CARFAST — официальный дилер SHACMAN» не убрана
✅ og:image/twitter:image присутствует на всех страницах

## Примечания

- Все изменения обратно совместимы
- SEO-инварианты каталога не нарушены
- Существующие тесты не сломаны
- Добавлены новые тесты для проверки новых функций
