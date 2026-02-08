# C1 — Инвентаризация и карта посадочных SHACMAN

## Команда для запуска (прод или копия БД)

```bash
# С env и venv на сервере
set -a; source /etc/carfst/carfst.env; set +a
cd /home/carfst/app/cursor_work
.venv/bin/python manage.py seo_audit_shacman --all --csv reports/shacman_inventory_$(date +%Y%m%d).csv
```

Локально (если есть копия БД с SHACMAN):

```bash
python manage.py seo_audit_shacman --all --csv reports/shacman_inventory_<DATE>.csv
```

## Выход команды (структура отчёта)

После запуска команда выводит в консоль и пишет CSV. Ниже — шаблон отчёта для подстановки реальных данных с проды.

---

### 1. Количество товаров SHACMAN

| Показатель | Значение |
|------------|----------|
| **Всего (public)** | *из вывода: Total SHACMAN* |
| **Active (is_active)** | *по CSV: count is_active=True* |
| **In-stock (total_qty > 0)** | *из вывода: In stock* |

*(На локальной копии без SHACMAN все значения могут быть 0.)*

---

### 2. Список категорий и количество товаров

Из секции **By category** вывода:

| Категория | Кол-во товаров |
|-----------|----------------|
| *(категория 1)* | *N* |
| *(категория 2)* | *M* |
| ... | ... |

---

### 3. Распределение по колёсным формулам (4x2, 6x4, 8x4 и т.д.)

Из секции **By wheel formula**:

| Формула | Кол-во |
|---------|--------|
| 4x2 | *N* |
| 6x4 | *M* |
| 8x4 | *K* |
| (no formula) | *...* |

---

### 4. Распределение по двигателям (WP13.550E501 и т.п.)

Из секции **By engine**:

| Двигатель | Кол-во |
|-----------|--------|
| WP13.550E501 | *N* |
| WP12 | *M* |
| (no engine) | *...* |

---

### 5. Распределение по линейкам/кабинам (X3000 / X5000 / X6000)

Поле `model_variant.line` в БД; в отчёте — секция **By line (model_variant.line)**.

| Line | Кол-во |
|------|--------|
| X3000 | *N* |
| X6000 | *M* |
| X5000 | *K* |
| (no line) | *...* |

В B3-хабах «линейка» реализована как **series** (slug от `model_variant.line`): URL вида `/shacman/series/<series_slug>/`, например `/shacman/series/x3000/`, `/shacman/series/x6000/`.

---

### 6. Топ дублей (duplicate_group) и рекомендации

Группа дубля: одинаковые **category_slug + model_code + wheel_formula + engine + year**. В CSV колонка `duplicate_group` — номер группы при count > 1.

Из секции **Duplicate / cannibalization**:

| Группа (cat \| code \| formula \| engine \| year) | Кол-во URL | Рекомендация |
|---------------------------------------------------|------------|--------------|
| *(пример: samosvaly \| SX... \| 6x4 \| WP12 \| 2023)* | 2–3 | Выбрать главный URL (in-stock, полный slug, цена, новее год); остальные — 301 на главный или canonical. |
| ... | ... | ... |

**Правила выбора главного URL (C5):**

1. Приоритет: in-stock > под заказ.  
2. Более полный slug (модель + формула + двигатель).  
3. Наличие цены и/или города.  
4. Более новый год.  
5. Действия с остальными: 301 на главный (если различия косметические), либо canonical на главный (если 301 рискован), либо оставить с уникальным контентом/FAQ (если разные комплектации).

---

## CSV

- **Путь по умолчанию:** `reports/shacman_inventory_YYYYMMDD.csv` (дата — день запуска).  
- **Явный путь:** `--csv reports/shacman_inventory_<DATE>.csv`.

**Колонки CSV:**  
`url`, `slug`, `category`, `category_slug`, `series_model`, `line`, `wheel_formula`, `engine`, `model_code`, `year`, `in_stock`, `availability`, `price`, `duplicate_group`, `product_id`, `is_active`.

Приложенный файл (после запуска на проде): `reports/shacman_inventory_<DATE>.csv`.
