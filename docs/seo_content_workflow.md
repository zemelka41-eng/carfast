# SEO Content Workflow для carfst.ru

Руководство по заполнению и управлению SEO-контентом на всех индексируемых посадочных страницах.

## Индексируемые страницы (требуют SEO-контента)

### 1. Каталожные страницы

**CatalogLandingSEO** — управляемый SEO-контент для каталожных лендингов:
- `/catalog/in-stock/` — главная точка входа "Каталог" из меню
- Админка: `/admin/catalog/cataloglandingseo/`
- Поля: `meta_title`, `meta_description`, `seo_intro_html`, `seo_body_html`, `faq_items`
- Seed: `python manage.py seed_catalog_in_stock_seo_content --dry-run`

**ShacmanHubSEO** — SEO-контент для SHACMAN хабов:
- `/shacman/` (main)
- `/shacman/in-stock/`
- `/shacman/<category>/` (например, `/shacman/samosvaly/`)
- `/shacman/<category>/in-stock/`
- `/shacman/formula/<formula>/` (фасеты, например `/shacman/formula/8x4/`)
- `/shacman/engine/<engine>/`
- `/shacman/line/<line>/`
- Админка: `/admin/catalog/shacmanhubseo/`
- Поля: `meta_title`, `meta_description`, `seo_intro_html`, `seo_body_html`, `seo_text`, `faq`
- Seed: `python manage.py seed_shacman_seo --scope=hubs --dry-run`

**Series (бренды)** — SEO для витрин брендов:
- `/catalog/series/<slug>/` (например, `/catalog/series/shacman/`)
- Админка: `/admin/catalog/series/`
- Поля: `seo_description`, `seo_intro_html`, `seo_body_html`, `seo_faq`

**Category (категории)** — SEO для витрин категорий:
- `/catalog/category/<slug>/` (например, `/catalog/category/samosvaly/`)
- Админка: `/admin/catalog/category/`
- Поля: `seo_description`, `seo_intro_html`, `seo_body_html`, `seo_faq`

**SeriesCategorySEO** — SEO для комбинированных страниц бренд+категория:
- `/catalog/series/<series>/<category>/` (например, `/catalog/series/shacman/samosvaly/`)
- Админка: `/admin/catalog/seriescategoryseo/`
- Поля: `seo_description`, `seo_intro_html`, `seo_body_html`, `seo_faq`

### 2. Статические информационные страницы

**StaticPageSEO** — SEO для info-страниц:
- `/leasing/`
- `/used/`
- `/service/`
- `/parts/`
- `/payment-delivery/`
- Админка: `/admin/catalog/staticpageseo/`
- Поля: `meta_title`, `meta_description`, `seo_intro_html`, `seo_body_html`, `faq_items`
- Seed: `python manage.py seed_static_seo_content --dry-run`

### 3. Товарные страницы (Product)

Для каждого товара:
- `/product/<slug>/`
- Админка: `/admin/catalog/product/`
- Критичные поля: `description_ru`, фото (`ProductImage`), `meta_title`, `meta_description`
- **SEO override поля** (для расширенного SEO-контента):
  - `seo_title_override` — переопределение meta title
  - `seo_description_override` — intro-текст для карточки
  - `seo_text_override` — body-текст для карточки
  - `seo_faq_override` — FAQ в формате `вопрос|ответ`
- **Дубли**: используй `canonical_product` для мягкой каноникализации или `redirect_to_url` для жёстких 301-редиректов.
- **Seed**: `python manage.py seed_seo_content_full --include-products` (опционально)
- **Audit**: `python manage.py seo_content_audit --include-products`

---

## Рекомендуемые длины контента

- **Intro**: не менее 600 символов (1–3 абзаца)
- **Body**: не менее 2500 символов (развёрнутый блок с подзаголовками h2/h3)
- **FAQ**: не менее 6 вопросов (формат: `Вопрос?|Ответ.` по одному на строку)

Длины intro/body считаются **после strip_tags** (одинаково в аудите и в seed). Команда `seed_seo_content_full` при необходимости дополняет body контекстными блоками до порога (`--min-body`, по умолчанию 2500).

---

## Запуск seed-команд

Все seed-команды поддерживают `--dry-run` для предпросмотра без изменения базы:

```bash
# === РЕКОМЕНДУЕМАЯ КОМАНДА ДЛЯ ЗАПОЛНЕНИЯ ВСЕХ SEO-ПОЛЕЙ ===
# Создаёт отсутствующие записи и заполняет пустые поля черновиками (≥600/2500/6)
python manage.py seed_seo_content_full --dry-run   # предпросмотр
python manage.py seed_seo_content_full             # создать/обновить

# Заполняет:
# - CatalogLandingSEO (/catalog/in-stock/)
# - StaticPageSEO (leasing, used, service, parts, payment-delivery)
# - Category (samosvaly, sedelnye-tyagachi, avtobetonosmesiteli)
# - Series (shacman)
# - SeriesCategorySEO (shacman + categories)
# - ShacmanHubSEO (26 hub pages)
# Генерирует: meta_title, seo_intro_html, seo_body_html, faq_items/faq

# === С ТОВАРАМИ (опционально, может быть медленно) ===
python manage.py seed_seo_content_full --include-products --dry-run
python manage.py seed_seo_content_full --include-products

# Заполняет для товаров:
# - seo_title_override
# - seo_description_override (intro)
# - seo_text_override (body, НЕ дублирует "Описание/Характеристики/Комплектация")
# - seo_faq_override

# === ОТДЕЛЬНЫЕ КОМАНДЫ (если нужна точечная заливка) ===

# Посмотреть шаблон без заливки
python manage.py seed_catalog_in_stock_seo_content --dry-run

# Создать пустую запись (заполнять в админке)
python manage.py seed_catalog_in_stock_seo_content

# Статические страницы (leasing, used, service, parts, payment-delivery)
python manage.py seed_static_seo_content --dry-run
python manage.py seed_static_seo_content

# SHACMAN хабы (создаёт записи для всех типов хабов)
python manage.py seed_shacman_seo --scope=hubs --dry-run
python manage.py seed_shacman_seo --scope=hubs
```

**ВАЖНО:** Seed для товаров (`--include-products`) генерирует **контекстные блоки** без дублирования структуры карточки. Заголовки типа "Почему стоит выбрать", "Преимущества модели", "Финансирование и доставка" — не пересекаются с основными блоками карточки "Описание/Характеристики/Комплектация".

---

## SEO Content Audit

Проверка заполненности SEO-полей на всех индексируемых страницах:

```bash
# Таблица (по умолчанию)
python manage.py seo_content_audit

# Показать только проблемные записи (без --show-ok)
python manage.py seo_content_audit --format=table

# CSV для экспорта
python manage.py seo_content_audit --format=csv > seo_audit.csv

# JSON для автоматизации
python manage.py seo_content_audit --format=json > seo_audit.json

# Кастомные пороги
python manage.py seo_content_audit --min-intro=800 --min-body=3000 --min-faq=8

# С абсолютными ссылками на админку (для удобства в продакшн)
python manage.py seo_content_audit --base-url=https://carfst.ru

# Без статистики по товарам (если модель Product изменена)
python manage.py seo_content_audit --no-product-stats

# С ДЕТАЛЬНЫМ аудитом товаров (проверка seo_*_override полей на каждом товаре)
python manage.py seo_content_audit --include-products --base-url=https://carfst.ru
```

**Отчёт показывает:**
- Статус каждого поля: OK / Missing / Too short / N/A
- Длину intro/body (в символах, после `strip_tags`) и количество FAQ
- Ссылку на админку для редактирования

**ВАЖНО:** Аудит с `--include-products` может быть медленным на больших каталогах (проверяет SEO-поля каждого публичного товара). Используй для детального анализа.

---

## Генерация черновиков в админке

Для всех SEO-моделей доступен admin action **"Generate draft SEO content (safe: no overwrite)"**:

1. В админке открой список записей (например, `/admin/catalog/seriescategoryseo/`)
2. Выбери записи с пустыми полями
3. В выпадающем меню Actions выбери "Generate draft SEO content"
4. Нажми "Go"

**Безопасность:**
- Черновики генерируются **только для пустых полей**
- Заполненный контент **не перетирается**
- Шаблон учитывает контекст: бренд, категорию, формулу, двигатель
- Ссылки — **чистые URL без utm**

**Результат:**
- Intro: 1–3 абзаца (600+ символов)
- Body: развёрнутый блок с подзаголовками (2500+ символов)
- FAQ: 6 вопросов в формате `вопрос|ответ`

После генерации **отредактируй черновики вручную** в админке, добавив специфику.

---

## Работа с дублями товаров (canonical_product vs redirect_to_url)

**Проблема:** Несколько товаров с разными slug, но одинаковым содержанием (дубли).

### Когда использовать `canonical_product`

**Мягкая каноникализация** — товар остаётся доступен по своему URL, но указывает канонический вариант:
- Страница отдаёт HTTP 200
- Добавляется `<link rel="canonical" href="..." />` на основную страницу
- Робот индексирует только основной товар
- Пользователь видит контент дубля (полезно для внутренних ссылок)

**Пример:** Товар A (slug: `shacman-x3000-8x4-dump`) — основной, товар B (slug: `shacman-x3000-8x4-dump-2024`) — дубль с canonical на A.

```python
# В админке для товара B
canonical_product = товар A (выбрать из списка)
```

### Когда использовать `redirect_to_url`

**Жёсткий редирект** — товар перенаправляет на другой URL (301 Moved Permanently):
- Страница отдаёт HTTP 301
- Пользователь мгновенно перенаправляется
- Используй для устаревших или ошибочных URL

**Пример:** Товар был переименован, старый slug больше не актуален.

```python
# В админке для товара B
redirect_to_url = /product/shacman-x3000-8x4-dump/
```

**Правило выбора:**
- Если дубль может быть полезен (разные комплектации, год) → `canonical_product`
- Если дубль — ошибка или устарел → `redirect_to_url`

---

## Автопроверки (smoke tests)

### scripts/smoke_seo.sh

Быстрая проверка ключевых SEO-правил:

```bash
./scripts/smoke_seo.sh https://carfst.ru
```

**Проверяет:**
- `/catalog/` — **noindex, follow** (критический инвариант)
- `/catalog/?utm_source=test` — canonical clean, schema отсутствует
- URL с GET-параметрами не отдают `application/ld+json`
- Canonical URL остаются чистыми (без utm)
- Пагинация: page=1 → canonical без page, page>1 → self-canonical
- SEO-зоны присутствуют и не пустые:
  - `/catalog/in-stock/` → `id="catalog-in-stock-seo-zone"`
  - `/leasing/` → `id="static-seo-zone"`
  - `/catalog/series/shacman/` → `id="catalog-seo-zone"`

### scripts/check_indexables_from_sitemap.sh

Проверка всех URL из sitemap.xml:

```bash
./scripts/check_indexables_from_sitemap.sh https://carfst.ru
```

**Проверяет:**
- HTTP 200/3xx
- Отсутствие `noindex`
- Canonical = self (или page=N для пагинации)
- **Наличие соответствующей SEO-зоны** (id) на каждом индексируемом URL
- **Непустая SEO-зона** (минимум один `<p>` тег)

---

## SEO-инварианты (НЕЛЬЗЯ ЛОМАТЬ!)

1. `/catalog/` **всегда noindex** и не попадает в sitemap
2. Страницы с GET-параметрами (utm/gclid и т.п.) **не отдают JSON-LD schema**
3. Canonical URL **всегда чистый** (path-only, без GET)
4. Пагинация:
   - `page=1` → индексируется, canonical без page
   - `page>1` → noindex, follow, self-canonical с page
5. Schema разрешена **только на clean URL без GET**

---

## Правила schema_allowed (JSON-LD)

### Когда schema разрешена

Schema.org JSON-LD (Product, FAQPage, BlogPosting, BreadcrumbList) выводится **только** когда:
- URL **не содержит GET-параметров** (utm, gclid, fbclid, page > 1 и др.)
- Страница является **индексируемой** (clean URL)

### Реализация

В `catalog/context_processors.py`:
```python
schema_allowed = not has_get_params  # True только когда request.GET пустой
```

В шаблонах (`base.html`):
```django
{% if request and not request.GET %}
<script type="application/ld+json">
[Organization, WebSite{% if page_schema_payload and schema_allowed %}, {{ page_schema_payload|safe }}{% endif %}]
</script>
{% endif %}
```

### Тестирование

```bash
# URL с GET параметрами НЕ должен содержать FAQPage/Product schema
curl -s "https://carfst.ru/product/some-slug/?utm_source=test" | grep -o "FAQPage"
# Должен быть пустой результат

# Clean URL ДОЛЖЕН содержать schema
curl -s "https://carfst.ru/product/some-slug/" | grep -o "FAQPage"
# Должен вернуть "FAQPage"
```

Автотесты: `catalog/tests_seo.py`

---

## Чеклист перед деплоем

- [ ] `python manage.py seo_content_audit` — нет критичных Missing/Too short
- [ ] Все SEO-зоны заполнены (intro ≥600, body ≥2500, faq ≥6)
- [ ] Дубли товаров обработаны (`canonical_product` или `redirect_to_url`)
- [ ] `./scripts/smoke_seo.sh` — все тесты зелёные
- [ ] `./scripts/check_indexables_from_sitemap.sh` — все URL проходят (после публикации на продакшн)
- [ ] CSS build markers присутствуют (проверка в `scripts/package.py`)
- [ ] Sitemap не содержит `/catalog/` и URL с GET-параметрами

---

## Полезные ссылки

- Админка: `https://carfst.ru/admin/`
- Sitemap: `https://carfst.ru/sitemap.xml`
- Robots.txt: `https://carfst.ru/robots.txt`
- SEO гайды: `/docs/SHACMAN_SEO_*.md`
- Инвентаризация: `/docs/SHACMAN_SEO_C1_INVENTORY.md`
- Дубли: `/docs/SEO_NEXT_STEP_DUPLICATES.md`

---

**Вопросы?** Проверь `/docs/` или запусти `seo_content_audit` для диагностики.
