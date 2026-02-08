# Сводка исправления: поиск изображений без привязки к slug

## Проблема

Команда `move_images_to_content` не находила изображения на PROD, так как использовала жёсткую привязку к `slug` статьи в начале имени файла:
- Slug статьи: `shacman-x3000-8x4-komplektaciya`
- Реальные имена файлов: `x3000-8x4-komplektaciya_2.png`, `x3000-8x4-komplektaciya_3.png`, `x3000-8x4-komplektaciya_4.png`
- Префикс `shacman-` отсутствует в именах файлов

## Исправления

### 1. Убрана привязка к slug в паттерне поиска

**Было:**
```python
pattern = re.compile(
    rf"^{re.escape(slug)}_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$",
    re.IGNORECASE,
)
match = pattern.match(basename)
```

**Стало:**
```python
pattern = re.compile(
    r"_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$",
    re.IGNORECASE,
)
match = pattern.search(basename)  # search вместо match для поиска в любом месте
```

**Изменения:**
- Убрана привязка к `slug` в начале паттерна
- Используется `pattern.search()` вместо `pattern.match()` для поиска паттерна в любом месте имени файла
- Паттерн ищет `_2`, `_3` или `_4` перед расширением, независимо от префикса

### 2. Обновлены сообщения об ошибках

**Было:**
```
Expected 3 images matching pattern 'shacman-x3000-8x4-komplektaciya_{2|3|4}(_*)?.(png|jpg|jpeg|webp)'
```

**Стало:**
```
Expected 3 images matching pattern 'any_prefix_{2|3|4}(_*)?.(png|jpg|jpeg|webp)'
Expected pattern: any prefix + _{2|3|4} + optional suffix + extension
Pattern examples:
  - x3000-8x4-komplektaciya_2.png
  - anything_2_720.webp
  - prefix_3.jpg
  - name_4.jpeg
```

### 3. Обновлены тесты

**Добавлено в `test_move_images_finds_png_files`:**
- Явная проверка случая, когда префикс имени файла (`x3000-8x4-komplektaciya`) отличается от slug статьи (`shacman-x3000-8x4-komplektaciya`)
- Проверка количества figure элементов после миграции
- Проверка идемпотентности (повторный запуск не дублирует)

**Обновлён `test_move_images_shows_diagnostic_info_when_not_found`:**
- Проверка нового сообщения об ошибке (без упоминания slug в паттерне)

### 4. Обновлена документация

**`BLOG_IMAGE_MIGRATION.md`:**
- Указано, что префикс имени файла может отличаться от slug статьи
- Добавлен пример для PROD (slug `shacman-x3000-8x4-komplektaciya`, файлы `x3000-8x4-komplektaciya_*.png`)
- Обновлены примеры паттернов в разделе диагностики

## Изменённые файлы

1. **`blog/management/commands/move_images_to_content.py`**
   - Убрана привязка к `slug` в паттерне поиска
   - Используется `pattern.search()` вместо `pattern.match()`
   - Обновлены сообщения об ошибках

2. **`tests/test_blog_image_migration.py`**
   - Обновлён `test_move_images_finds_png_files` с проверкой случая несовпадения префикса
   - Обновлён `test_move_images_shows_diagnostic_info_when_not_found` для нового формата сообщений

3. **`BLOG_IMAGE_MIGRATION.md`**
   - Добавлено пояснение о независимости префикса от slug
   - Добавлен пример для PROD
   - Обновлены примеры паттернов

## Использование на PROD

```bash
# SSH на сервер
ssh user@carfst.ru
cd /opt/carfst
source venv/bin/activate  # если используется

# 1. Проверка (dry-run)
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya --dry-run

# Команда найдёт файлы:
# - x3000-8x4-komplektaciya_2.png
# - x3000-8x4-komplektaciya_3.png
# - x3000-8x4-komplektaciya_4.png
# несмотря на то, что префикс отличается от slug

# 2. Выполнение
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya

# 3. Проверка результата
curl -sL https://carfst.ru/blog/shacman-x3000-8x4-komplektaciya/ | grep -c 'class="blog-inline-image"'
# Должно быть 3
```

## Проверки после выполнения

### a) content_html содержит 3 figure элементы

```bash
curl -sL https://carfst.ru/blog/shacman-x3000-8x4-komplektaciya/ | grep -c 'class="blog-inline-image"'
```

Должно быть ровно 3.

### b) Изображения удалены из галереи

```bash
# Проверка через Django shell
python manage.py shell
>>> from blog.models import BlogPost, BlogPostImage
>>> post = BlogPost.objects.get(slug='shacman-x3000-8x4-komplektaciya')
>>> post.images.filter(image__name__contains='_2').exists()  # False
>>> post.images.filter(image__name__contains='_3').exists()  # False
>>> post.images.filter(image__name__contains='_4').exists()  # False
```

### c) Повторный запуск безопасен (idempotency)

```bash
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya --dry-run
# Покажет: "All images already in content_html. Nothing to do (idempotent)."
```

## Тесты

```bash
# Запуск всех тестов миграции
pytest tests/test_blog_image_migration.py -v

# Быстрая проверка
pytest tests/test_blog_image_migration.py -q

# Все тесты проекта
pytest -q
```

Все тесты должны проходить.

## Технические детали

### Паттерн поиска

**Новый паттерн:** `_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$`

**Что он находит:**
- Любое имя файла, заканчивающееся на `_2`, `_3` или `_4` (с опциональным суффиксом типа `_720`) и расширением `png`, `jpg`, `jpeg` или `webp`
- Регистр не важен (case-insensitive)

**Примеры:**
- ✅ `x3000-8x4-komplektaciya_2.png` (найдёт)
- ✅ `anything_2_720.webp` (найдёт)
- ✅ `prefix_3.jpg` (найдёт)
- ✅ `name_4.jpeg` (найдёт)
- ❌ `image_1.png` (не найдёт, нет `_2`, `_3` или `_4`)
- ❌ `x3000-8x4-komplektaciya_2.gif` (не найдёт, неподдерживаемое расширение)

### Преимущества нового подхода

1. **Гибкость**: Работает с любыми префиксами имён файлов
2. **Устойчивость**: Не зависит от совпадения slug статьи и имени файла
3. **Простота**: Простой паттерн, легко понять и поддерживать
4. **Безопасность**: Сохранены все проверки безопасности (idempotency, транзакции, dry-run)
