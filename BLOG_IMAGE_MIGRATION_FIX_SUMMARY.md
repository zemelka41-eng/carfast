# Сводка исправлений команды move_images_to_content

## Проблема

Команда не находила изображения на PROD, так как использовала жёсткий паттерн поиска `*_2_720`, в то время как реальные файлы имеют формат `*_2.png`, `*_3.png`, `*_4.png`.

## Исправления

### 1. Гибкий поиск изображений

**Было:**
```python
if "x3000-8x4-komplektaciya_2_720" in filename:
    images_to_move[2] = img
```

**Стало:**
```python
pattern = re.compile(
    rf"^{re.escape(slug)}_(2|3|4)(?:_[^.]*)?\.(png|jpe?g|webp)$",
    re.IGNORECASE,
)
basename = os.path.basename(img.image.name)
match = pattern.match(basename)
if match:
    image_num = int(match.group(1))
    if image_num in [2, 3, 4]:
        images_to_move[image_num] = img
```

**Поддерживаемые форматы:**
- `{slug}_2.png`
- `{slug}_2_720.webp`
- `{slug}_3.jpg`
- `{slug}_4.jpeg`
- И т.д. (регистр не важен)

### 2. Улучшенная диагностика

**Добавлено:**
- Список всех файлов в галерее при ошибке поиска
- Примеры ожидаемых паттернов
- Информация о найденных изображениях

**Пример вывода при ошибке:**
```
Expected 3 images matching pattern 'shacman-x3000-8x4-komplektaciya_{2|3|4}(_*)?.(png|jpg|jpeg|webp)', found 0: []. Missing: [2, 3, 4].

Images found in gallery:
  - other-image.jpg
  - x3000-8x4-komplektaciya_1.png
  - cover.jpg

Expected pattern examples:
  - shacman-x3000-8x4-komplektaciya_2.png
  - shacman-x3000-8x4-komplektaciya_2_720.webp
  - shacman-x3000-8x4-komplektaciya_3.jpg
  - shacman-x3000-8x4-komplektaciya_4.jpeg
```

### 3. Обновлённые тесты

Добавлены тесты для:
- ✅ Поиск изображений с `.png` расширением (без `_720`)
- ✅ Поддержка разных расширений (png, jpg, jpeg, webp)
- ✅ Поддержка разных суффиксов (`_2.png`, `_2_720.webp`)
- ✅ Диагностика при отсутствии изображений
- ✅ Проверка количества figure элементов после миграции

## Изменённые файлы

1. **`blog/management/commands/move_images_to_content.py`**
   - Исправлен поиск изображений (гибкий regex паттерн)
   - Добавлена диагностика (список файлов в галерее)
   - Использование `os.path.basename()` для получения имени файла

2. **`tests/test_blog_image_migration.py`**
   - Добавлен тест `test_move_images_finds_png_files` (без `_720`)
   - Добавлен тест `test_move_images_supports_different_extensions`
   - Добавлен тест `test_move_images_shows_diagnostic_info_when_not_found`
   - Обновлены существующие тесты для использования `.png` формата
   - Добавлена проверка количества figure элементов

3. **`BLOG_IMAGE_MIGRATION.md`**
   - Добавлены примеры поддерживаемых форматов файлов
   - Добавлены команды для PROD
   - Добавлен раздел диагностики проблем

## Использование на PROD

```bash
# SSH на сервер
ssh user@carfst.ru
cd /opt/carfst
source venv/bin/activate  # если используется

# 1. Проверка (dry-run)
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya --dry-run

# 2. Выполнение
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya

# 3. Проверка результата
curl -sL https://carfst.ru/blog/shacman-x3000-8x4-komplektaciya/ | grep -c 'class="blog-inline-image"'
# Должно быть 3
```

## Проверки после выполнения

### a) content_html содержит 3 figure элементы

```bash
# Проверка в базе данных или через curl
curl -sL https://carfst.ru/blog/shacman-x3000-8x4-komplektaciya/ | grep -c 'class="blog-inline-image"'
```

Должно быть ровно 3.

### b) Изображения удалены из галереи

```bash
# Проверка через Django shell или admin
python manage.py shell
>>> from blog.models import BlogPost, BlogPostImage
>>> post = BlogPost.objects.get(slug='shacman-x3000-8x4-komplektaciya')
>>> post.images.filter(image__name__contains='_2').exists()  # False
>>> post.images.filter(image__name__contains='_3').exists()  # False
>>> post.images.filter(image__name__contains='_4').exists()  # False
```

### c) Повторный запуск не меняет ничего (idempotency)

```bash
python manage.py move_images_to_content shacman-x3000-8x4-komplektaciya --dry-run
```

Должно показать: "All images already in content_html. Nothing to do (idempotent)."

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
