# Orphaned media: просмотр и очистка

В health-проверке и в логах могут появляться предупреждения об orphaned media: файлы в `MEDIA_ROOT`, на которые нет ссылок в БД, или наоборот — записи в БД, указывающие на отсутствующие файлы.

## Проверка в /health/

По умолчанию **скан orphaned media в `/health/` не выполняется** (чтобы не нагружать эндпоинт при частых проверках мониторинга). В ответе check `orphaned_media` будет в статусе `skipped` с причиной.

**Включение deep-скана** (полный список missing/unreferenced):

- **Query-параметр:** `GET /health/?deep=1`
- **Переменная окружения:** `HEALTH_ORPHANED_MEDIA=1`

В deep-режиме результат скана **кешируется** (Django cache или in-process fallback). Повторные вызовы в пределах TTL возвращают кеш без повторного сканирования. В `detail` добавляются поля:

- `cached`: `true` / `false`
- `cache_age_seconds`: возраст кеша в секундах

**TTL кеша:** настройка `HEALTH_ORPHANED_MEDIA_TTL_SECONDS` (по умолчанию 600 секунд = 10 минут).

## Как посмотреть отчёт (ничего не удаляется)

```bash
python manage.py cleanup_orphaned_media --dry-run
```

По умолчанию вывод ограничен (до 50 путей в списке). Полные счётчики всегда показываются. Ограничить вывод в консоли:

```bash
python manage.py cleanup_orphaned_media --dry-run --limit 10
```

Только подпапка (например, только товарные фото):

```bash
python manage.py cleanup_orphaned_media --dry-run --path-prefix media/products
```

или

```bash
python manage.py cleanup_orphaned_media --dry-run --path-prefix products
```

## Как удалить только unreferenced-файлы

**Удаляются только файлы на диске, на которые нет ссылок в БД.** Записи в БД и файлы, на которые они ссылаются, не трогаются.

Рекомендуется сначала выполнить dry-run и проверить список:

```bash
python manage.py cleanup_orphaned_media --dry-run --path-prefix media/products
python manage.py cleanup_orphaned_media --delete --path-prefix media/products
```

Удаление только внутри `MEDIA_ROOT`; пути проверяются на path traversal.

## На сервере (под пользователем приложения)

```bash
sudo -u carfst -H bash -lc '
  set -a; source /etc/carfst/carfst.env; set +a
  cd /home/carfst/app/cursor_work
  /home/carfst/app/cursor_work/.venv/bin/python manage.py cleanup_orphaned_media --dry-run
'
```

Для реального удаления добавьте `--delete` и при необходимости `--path-prefix media/products`.

## Учитываемые модели

- **catalog**: `Category.cover_image`, `Series.logo`, `ProductImage.image`
- **blog** (если установлен): `BlogPost.cover_image`, `BlogPostImage.image`

Очистка **не** запускается автоматически при деплое — только ручной вызов команды.
