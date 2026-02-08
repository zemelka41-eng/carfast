# Отчёт: устранение 404 на /shacman/ и /shacman/?page=2

## 1. Список изменённых файлов

| Файл | Изменения |
|------|-----------|
| **catalog/views.py** | `_shacman_series()` — возвращает серию по slug без фильтра `.public()`; добавлена `_shacman_series_is_public(series)` для проверки индексируемости. Вьюхи `shacman_hub`, `shacman_in_stock`, `shacman_category`, `shacman_category_in_stock`: никогда не возвращают 404 при отсутствии/не-public серии; при пустом листинге или не-public серии — 200 + `meta_robots="noindex, follow"`. Для категорий: 404 только если `category_slug` не существует; при существующей категории без товаров — 200 + noindex. |
| **catalog/management/commands/url_resolve_diagnostic.py** | Добавлен шаг 4: вызов вьюхи через `RequestFactory().get("/shacman/")` и отлов `Http404` с выводом traceback. |
| **bin/deploy_carfst.sh** | Добавлена функция `shacman_smoke_check()`: GET `/shacman/` → ожидание HTTP 200; при не-200 — `exit 1`. Вызов `shacman_smoke_check` после `version_smoke_check` (без возможности пропуска). |
| **docs/SHACMAN_404_FIX_REPORT.md** | Этот отчёт. |

---

## 2. Причина 404 (и доказательство)

**Гипотеза:** 404 возникал из-за того, что серия SHACMAN не попадала в `Series.objects.public()` (например, серия скрыта/не публична в БД), и где-то в цепочке выполнялся код, приводящий к 404.

**Фактически в коде:** в `shacman_hub` и `shacman_in_stock` явного `raise Http404` или `get_object_or_404(Series...)` не было: при `series = _shacman_series()` равном `None` (когда SHACMAN не в `.public()`) использовался пустой `qs` и выставлялся `meta_robots = "noindex, follow"`. То есть по коду вьюхи сами по себе 404 не вызывали.

**Возможные источники 404 на проде:**

1. **Роутинг:** запрос мог не доходить до вьюхи SHACMAN (например, другой порядок `urlpatterns` на проде или префикс языка). Локально при `resolve("shacman/")` (без ведущего слеша) возможен Resolver404; при `resolve("/shacman/")` (с ведущим слешем) — совпадение с вьюхой. Диагностика: на сервере выполнить `python manage.py url_resolve_diagnostic` — см. раздел 3.
2. **Исключение внутри вьюхи/шаблона:** любое необработанное исключение в цепочке (вьюха, контекст, шаблон) могло приводить к 404, если где-то выше по стеку есть обработчик, превращающий его в 404. Диагностика: шаг 4 в `url_resolve_diagnostic` вызывает вьюху через `RequestFactory` и ловит `Http404` с traceback.
3. **Зависимость от `.public()`:** старый код использовал `_shacman_series() = Series.objects.public().filter(slug__iexact="shacman").first()`. Если SHACMAN не входил в `.public()`, `series` был `None` — 404 из этой строки не шёл, но любая другая зависимость от «обязательной» публичной серии могла дать 404 в другом месте.

**Внесённые изменения (устранение риска 404):**

- `_shacman_series()` больше не использует `.public()`: возвращается серия по `slug__iexact="shacman"` независимо от публичности.
- Добавлена `_shacman_series_is_public(series)`: по ней решается, показывать ли товары и индексировать ли страницу.
- Правило для `/shacman/` и `/shacman/in-stock/`: при отсутствии серии или при не-public серии всегда возвращается **200**, пустой листинг, `meta_robots="noindex, follow"`, без schema, canonical чистый. **Http404 не вызывается.**
- Для `/shacman/<category_slug>/`: 404 только при несуществующем `category_slug`; при существующей категории без товаров (или при не-public серии) — 200, пустой листинг, noindex.

---

## 3. Диагностика на сервере (manage.py shell / команда)

Выполнять на сервере с загруженным окружением (например: `set -a; source /etc/carfst/carfst.env; set +a`) и venv.

### 3.1. Команда диагностики (resolve + вызов вьюхи)

```bash
cd /home/carfst/app/cursor_work
set -a; source /etc/carfst/carfst.env; set +a
.venv/bin/python manage.py url_resolve_diagnostic
```

**Ожидаемый вывод (после фикса):**

- `resolve('shacman/') -> shacman_hub  url_name='shacman_hub'  kwargs={}`
- `reverse('shacman_hub') -> '/shacman/'`
- В списке urlpatterns первыми идут маршруты `'shacman/'`, `'shacman/in-stock/'`, ...
- Шаг 4: `view shacman_hub returned status_code=200` (без Http404 и без traceback).

**Если виден Http404:** в выводе будет блок «view raised Http404» и traceback — по нему можно определить место вызова `raise Http404` или `get_object_or_404`.

### 3.2. Ручная проверка в shell (resolve + RequestFactory)

```python
# В manage.py shell (с загруженным /etc/carfst/carfst.env):
from django.test import RequestFactory
from django.urls import resolve, Resolver404

# a) resolve
r = resolve("shacman/")
print(r.func.__name__, r.url_name)  # shacman_hub

# b) вызов вьюхи и отлов Http404
request = RequestFactory().get("/shacman/")
request.resolver_match = r
try:
    response = r.func(request)
    print("status_code", response.status_code)  # 200
except Exception as e:
    print("Exception", type(e).__name__, e)
```

---

## 4. Команды curl для проверки после деплоя

Базовый URL: `https://carfst.ru` (или подставить свой).

```bash
# 1) /shacman/ — обязательно 200
curl -sI "https://carfst.ru/shacman/"
# Ожидание: HTTP/2 200 (или HTTP/1.1 200)

# 2) /shacman/?page=2 — 200
curl -sI "https://carfst.ru/shacman/?page=2"
# Ожидание: HTTP/2 200

# 3) canonical на /shacman/ — без query
curl -s "https://carfst.ru/shacman/" | grep -o 'rel="canonical" href="[^"]*"'
# Ожидание: rel="canonical" href="https://carfst.ru/shacman/"
```

Деплой после правок при неуспешной проверке `/shacman/` (не 200) завершится с ошибкой за счёт `shacman_smoke_check()` в `bin/deploy_carfst.sh`.
