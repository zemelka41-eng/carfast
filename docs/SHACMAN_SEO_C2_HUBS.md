# C2 — Посадочные страницы (хабы) SHACMAN

## Ограничения (без «взрыва» URL)

- Хаб создаётся только если **≥ 2 товаров** в выборке.  
- Максимум **20 значений** на каждый тип (formula / engine / series).  
- Сортировка по частоте (по убыванию количества товаров).  
- Для всех хабов: **page=1** — index; **page>1** — noindex, follow, self-canonical; **canonical** только по `request.path`; **Schema.org на хабах не выводится**.

---

## Таблица создаваемых URL

### Обязательные хабы (уже есть)

| URL | Фильтр | Условие появления |
|-----|--------|-------------------|
| `/shacman/` | series=SHACMAN | Всегда (200 даже без серии; noindex если серия не public). |
| `/shacman/in-stock/` | series=SHACMAN, total_qty>0 | Всегда. |
| `/shacman/<category_slug>/` | series=SHACMAN, category.slug | Категория из БД (есть товары SHACMAN в этой категории). 404 только если slug категории не существует. |
| `/shacman/<category_slug>/in-stock/` | + total_qty>0 | То же + в наличии. |

### B3-хабы (расширенные, по порогам)

**Формула (колёсная формула):**

| URL | Фильтр | Условие |
|-----|--------|--------|
| `/shacman/formula/4x2/` | wheel_formula нормализован 4x2 | ≥2 товаров, до 20 формул. |
| `/shacman/formula/6x4/` | 6x4 | Аналогично. |
| `/shacman/formula/8x4/` | 8x4 | Аналогично. |
| `/shacman/formula/<formula>/in-stock/` | + total_qty>0 | Только если есть в наличии по этой формуле. |

**Двигатель:**

| URL | Фильтр | Условие |
|-----|--------|--------|
| `/shacman/engine/<engine_slug>/` | engine_model → slugify (напр. wp13550e501) | ≥2 товаров, до 20 двигателей. |
| `/shacman/engine/<engine_slug>/in-stock/` | + total_qty>0 | Только если есть в наличии по этому двигателю. |

**Линейка (line = series в URL):**

В проекте «линейка» — это `model_variant.line` (X3000, X6000, X5000 и т.д.). URL идут как **series** (не отдельный префикс `/shacman/line/`):

| URL | Фильтр | Условие |
|-----|--------|--------|
| `/shacman/series/<series_slug>/` | model_variant.line → slugify (x3000, x6000, …) | ≥2 товаров, до 20 линеек. |
| `/shacman/series/<series_slug>/in-stock/` | + total_qty>0 | Только если есть в наличии по этой линейке. |

---

## Итоговая сводка типов URL

| Тип | Пример URL | Лимит значений |
|-----|------------|----------------|
| hub | `/shacman/` | 1 |
| in_stock | `/shacman/in-stock/` | 1 |
| category | `/shacman/samosvaly/`, `/shacman/sedelnye-tyagachi/` | по числу категорий с SHACMAN |
| category_in_stock | `/shacman/samosvaly/in-stock/` | то же |
| formula | `/shacman/formula/4x2/`, `6x4`, `8x4` | до 20 |
| formula_in_stock | `/shacman/formula/6x4/in-stock/` | по наличию |
| engine | `/shacman/engine/wp13550e501/` | до 20 |
| engine_in_stock | `/shacman/engine/wp13550e501/in-stock/` | по наличию |
| series (line) | `/shacman/series/x3000/`, `/shacman/series/x6000/` | до 20 |
| series_in_stock | `/shacman/series/x3000/in-stock/` | по наличию |

Все перечисленные URL (только чистые, без `?page=...`) попадают в sitemap через `ShacmanHubSitemap`.
