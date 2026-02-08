# Краткая сводка изменений для SEO-аудита

## Изменённые файлы

1. **catalog/views.py**
   - Добавлена функция `_build_breadcrumb_schema()` (строки 525-549)
   - Обновлены `catalog_series()`, `catalog_category()`, `catalog_series_category()` для добавления BreadcrumbList JSON-LD
   - Обновлена `_seo_context()` для добавления default og:image

2. **blog/views.py**
   - Добавлен импорт `json`
   - Обновлена `blog_detail()` для добавления BlogPosting JSON-LD с полем `mainEntityOfPage`

3. **tests/test_technical_seo.py**
   - Добавлены тесты для sitemap (9 новых тестов)
   - Добавлены тесты для BreadcrumbList (4 теста)
   - Добавлены тесты для BlogPosting (2 теста)
   - Добавлены тесты для og:image/twitter (3 теста)
   - Добавлены тесты для BUILD_ID (2 теста)

## Ключевые улучшения

### Sitemap.xml
- ✅ Исключён `/catalog/` из sitemap
- ✅ Исключены все URL с querystring (`?page=`, `&page=`, и т.д.)
- ✅ Добавлены тесты для валидации

### Structured data (JSON-LD)
- ✅ BreadcrumbList на catalog landing pages с абсолютными URL
- ✅ BlogPosting с полем `mainEntityOfPage`
- ✅ Добавлены тесты для валидации структуры

### Open Graph / Twitter
- ✅ Default og:image для всех страниц
- ✅ Twitter Card автоматически использует og:image
- ✅ Добавлены тесты для проверки на разных типах страниц

### Диагностика билда
- ✅ X-Build-ID header на всех ответах (включая редиректы)
- ✅ BUILD_ID согласован между header, endpoint и функцией
- ✅ Добавлены тесты для проверки

## Команды для быстрой проверки

```bash
# Запуск всех тестов
pytest tests/test_technical_seo.py tests/test_build_id_header.py -v

# Проверка sitemap
curl -s http://localhost:8000/sitemap.xml | grep -E "(catalog/|\?)" || echo "OK"

# Проверка BreadcrumbList
curl -s http://localhost:8000/catalog/series/shacman/ | grep "BreadcrumbList"

# Проверка BUILD_ID
curl -sI http://localhost:8000/ | grep "X-Build-ID"
```

## SEO-инварианты сохранены

✅ `/catalog/` — noindex, follow, не в sitemap
✅ Landing pages (page=1) — index, follow
✅ Пагинация (page>1) — noindex, follow + self-canonical
✅ Лишние GET-параметры — noindex, follow
✅ Формулировка «CARFAST — официальный дилер SHACMAN» не убрана

## Оптимизация стилей для inline-изображений в блоге

### static/css/styles.css
- ✅ Добавлены стили для `.blog-inline-image` с адаптивным размером
- ✅ Мобильные: картинка в пределах контейнера, без горизонтального скролла
- ✅ Десктоп: ограничение ширины до 900px, центрирование, отступы 2rem
- ✅ Стили для `figcaption` с адаптивным размером шрифта
- ✅ Совместимость с Bootstrap `.img-fluid` сохранена
- ✅ Не затрагивает картинки в каталоге/товарах (только `.blog-inline-image`)
