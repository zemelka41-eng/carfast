# DEPLOY (архивом) — Beget Cloud / Linux

Этот проект рассчитан на деплой через `gunicorn` (systemd) и **статику через WhiteNoise** (без обязательной ручной настройки nginx под `/static/`).
Production unit: `carfst-gunicorn.service` (можно переопределить через env `GUNICORN_SERVICE`).

Важно: при обновлении **не перетирайте** на сервере:
- `.env`
- `.venv` / `venv`
- `media/`
- `staticfiles/`
- `logs/`

## Единственный правильный путь деплоя

**Используйте автоматический скрипт деплоя** — это единственный рекомендуемый способ. Источник правды: `/home/carfst/app/bin/deploy_carfst.sh` (версионируется как `bin/deploy_carfst.sh`). Ручной деплой не рекомендуется, так как легко пропустить критичные шаги (миграции, collectstatic, проверки).

Источник правды для nginx-конфига: `deploy/nginx.carfst.ru.conf` (копируется в `/etc/nginx/sites-available/carfst.ru.conf`). Каталог `deployment/nginx/` считается историческим и не используется в актуальном деплое. Legacy-ссылка/файл `sites-enabled/carfst.ru` удаляется/переносится в `sites-disabled`, в `sites-enabled` должен оставаться только `carfst.ru.conf`. Деплой автоматически публикует статику из `staticfiles/` в `/var/www/carfst/staticfiles` (nginx alias), ручной rsync больше не нужен.

**Один источник правды для rate-limit (admin_login):** зона `limit_req_zone ... admin_login` задаётся только в `deploy/nginx.http.conf`, который деплой устанавливает в `/etc/nginx/conf.d/carfst-http.conf`. Файл `00-rate-limits.conf` в `conf.d` не используется; при деплое старый `00-rate-limits.conf` с `admin_login` удаляется (бэкапится), чтобы в системе была только одна зона.

### Подготовка архива

На локальной машине создайте ZIP-архив проекта:

```bash
# Из корня проекта (где manage.py)
python scripts/make_deploy_zip.py /path/to/carfst.zip
```

Скрипт автоматически исключает `.venv/`, `.env`, `media/`, `staticfiles/`, `logs/` и другие локальные файлы.

### Деплой на сервере

**Шаг 1:** Скопируйте архив на сервер (например, через `scp`):

```bash
scp carfst.zip user@server:/tmp/carfst.zip
```

**Шаг 2:** Убедитесь, что скрипт деплоя находится на сервере:

```bash
# Точка входа (source of truth): /home/carfst/app/bin/deploy_carfst.sh
# Код проекта находится в: /home/carfst/app/cursor_work
# В репозитории entrypoint хранится как bin/deploy_carfst.sh.
#
# Если скрипта нет, скопируйте оба файла из репозитория:
# - bin/deploy_carfst.sh    → /home/carfst/app/bin/deploy_carfst.sh
# - deploy/deploy_carfst.sh → /home/carfst/app/deploy/deploy_carfst.sh (обёртка)

# Проверка синтаксиса bash (перед запуском):
bash -n /home/carfst/app/bin/deploy_carfst.sh
# Проверка, что entrypoint содержит авто-обновление и re-exec:
grep -n "DEPLOY_REEXEC\\|Re-executing updated deploy script" /home/carfst/app/bin/deploy_carfst.sh

# Сделайте скрипт исполняемым
chmod +x /home/carfst/app/bin/deploy_carfst.sh
```

**Шаг 3:** Запустите деплой (единственный корректный путь):

```bash
/home/carfst/app/bin/deploy_carfst.sh /tmp/carfst.zip
# В логе деплоя должны быть строки:
# DEST_CODE_DIR: /home/carfst/app/cursor_work
# VENV_PATH: /home/carfst/app/cursor_work/.venv
# PYTHON_CMD: /home/carfst/app/cursor_work/.venv/bin/python

### Самообновление entrypoint
Скрипт `/home/carfst/app/bin/deploy_carfst.sh` сам обновляет себя из архива и **переисполняется** новым кодом
в начале деплоя. Это гарантирует, что изменения начинают работать в том же запуске.

Переменная `DEPLOY_REEXEC=1` защищает от рекурсии при повторном exec.
```

### Диагностика: какой CSS реально подключается на проде (Manifest/hashed)

В продакшене `{% static 'css/styles.css' %}` превращается в `/static/css/styles.<hash>.css`.
Проверяем какой именно файл подключён и есть ли в нём build-маркер.

```bash
CSS=$(curl -s https://carfst.ru/catalog/ | grep -Eo "/static/css/styles[^\"']+\\.css" | head -n 1); echo "$CSS"
curl -s "https://carfst.ru${CSS}" | head -n 5
curl -s "https://carfst.ru${CSS}" | grep -n "build: cards-eqheight"
```

Важно: `curl https://carfst.ru/static/css/styles.css` может показывать не тот файл, который реально использует браузер (из-за Manifest storage).

### Диагностика: применена ли миграция 0016 (SiteSettings.work_hours / map_embed)

```bash
python manage.py showmigrations catalog | grep 0016
```

### Форс-очистка статики при подозрении на «залипший» hashed CSS

```bash
COLLECTSTATIC_CLEAR=1 /home/carfst/app/bin/deploy_carfst.sh /tmp/carfst.zip
```

### Что делает скрипт деплоя

Скрипт выполняет следующие шаги **в строгом порядке**:

1. ✅ **Валидация ZIP-архива**
   - Проверяет наличие обязательных файлов (`_product_card.html`)
   - **КРИТИЧНО:** Проверяет наличие миграции `0016_add_site_settings_fields.py` (или более новой)
   - Логирует все найденные миграции
   - **Останавливает деплой**, если миграция не найдена

2. ✅ **Распаковка архива**
   - Сохраняет `.env`, `.venv`, `media/`, `staticfiles/`, `logs/` (не перезаписывает)

3. ✅ **Установка Python-зависимостей** (по необходимости)
   - Скрипт вычисляет SHA256 `requirements.txt` и сравнивает с файлом
     `${PROJECT_DIR}/.deploy/requirements.sha256`.
   - Если хэш изменился или не удаётся импортировать `docx`/`lxml`, выполняется:
     ```bash
     /home/carfst/app/cursor_work/.venv/bin/python -m pip install -r requirements.txt
     ```
   - После установки выполняется smoke-check:
     ```bash
     python -c "import docx, lxml; print('deps ok')"
     ```
   - Хэш сохраняется в `.deploy/requirements.sha256`.

4. ✅ **Применение миграций** (обязательно)
   ```bash
   python manage.py migrate --noinput
   ```
   - **Останавливает деплой** при ошибке миграций

5. ✅ **Сборка статики** (обязательно)
   ```bash
   python manage.py collectstatic --noinput
   ```
   - **Останавливает деплой** при ошибке collectstatic
   - (Опционально) `COLLECTSTATIC_CLEAR=1` добавляет `--clear` для принудительной очистки `STATIC_ROOT`

6. ✅ **Проверка Django** (обязательно)
   ```bash
   python manage.py check
   ```
   - **Останавливает деплой** при ошибках конфигурации

7. ✅ **Перезапуск gunicorn**
   ```bash
   sudo systemctl restart gunicorn_carfst
   ```

8. ✅ **Перезагрузка nginx**
   ```bash
   sudo systemctl reload nginx
   ```

### Настройка скрипта

Если ваш проект находится не в `/home/carfst/app`, настройте переменные окружения перед запуском:

```bash
export PROJECT_DIR=/var/www/carfst
export VENV_PATH=/var/www/carfst/.venv
export GUNICORN_SERVICE=gunicorn_carfst
/home/carfst/app/bin/deploy_carfst.sh /path/to/release.zip
```

Или отредактируйте переменные в начале скрипта `deploy/deploy_carfst.sh`.

### Настройка SECRET_KEY на сервере

**ВАЖНО:** Перед первым деплоем или при необходимости сменить ключ:

1. **Сгенерируйте безопасный SECRET_KEY:**
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
   
   Или используйте Django management команду:
   ```bash
   python manage.py shell -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

2. **Настройте переменные окружения для production:**
   
   **Рекомендуемый способ (production):** Используйте systemd `EnvironmentFile`:
   ```bash
   # Создайте файл конфигурации (например, /etc/carfst/carfst.env)
   sudo mkdir -p /etc/carfst
   sudo nano /etc/carfst/carfst.env
   
   # Добавьте строку с DJANGO_SECRET_KEY (замените на ваш сгенерированный ключ)
   DJANGO_SECRET_KEY=ваш-сгенерированный-ключ-минимум-50-символов
   DJANGO_DEBUG=False
   # ... другие переменные
   ```
   
   **Альтернативный способ (development):** Используйте `.env` в корне проекта:
   ```bash
   # Путь к .env файлу (должен совпадать с PROJECT_DIR в deploy скрипте)
   ENV_FILE="/home/carfst/app/.env"
   
   # Добавьте строку с DJANGO_SECRET_KEY
   echo "DJANGO_SECRET_KEY=ваш-сгенерированный-ключ-минимум-50-символов" >> "$ENV_FILE"
   ```
   
   **Важно:** 
   - В production приложение работает БЕЗ `.env` файла, используя переменные окружения из systemd `EnvironmentFile`
   - `.env` файл используется только в development (DEBUG=True) или если явно указан через `ENV_FILE`
   - Не используйте ключи короче 50 символов. Валидатор в `settings.py` строго проверяет длину и уникальность символов в production.

3. **Настройте systemd service для загрузки переменных окружения:**
   
   В файле `/etc/systemd/system/gunicorn_carfst.service` должна быть строка:
   ```ini
   EnvironmentFile=/etc/carfst/carfst.env
   ```
   
   Или если используете `.env` в корне проекта:
   ```ini
   EnvironmentFile=/home/carfst/app/.env
   ```
   
   Если её нет, добавьте после `[Service]`:
   ```ini
   [Service]
   EnvironmentFile=/etc/carfst/carfst.env
   ...
   ```
   
   Затем перезагрузите systemd и перезапустите сервис:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart gunicorn_carfst
   ```

4. **Проверка, что ключ загружен и валиден:**
   
   ```bash
   # Проверка статуса сервиса
   sudo systemctl status gunicorn_carfst
   # Должен быть статус "active (running)" без ошибок
   
   # Проверка через Django check --deploy (критично для production)
   cd /home/carfst/app
   source .venv/bin/activate
   # Переменные окружения загружаются автоматически из EnvironmentFile
   python manage.py check --deploy
   # Ожидаемый результат: "System check identified no issues (0 silenced)."
   # Без предупреждений security.W009 (SECRET_KEY)
   ```
   
   Если `check --deploy` выдает ошибку `SECRET_KEY validation failed`, проверьте:
   - Длина ключа минимум 50 символов
   - Ключ содержит минимум 5 уникальных символов
   - Ключ не начинается с `django-insecure-`
   - Ключ не равен `dev-secret-key`
   - Переменная `DJANGO_SECRET_KEY` установлена в `EnvironmentFile`

5. **Deploy скрипт (ENV загрузка и запуск, единый источник):**
   
   Скрипт `deploy_carfst.sh` загружает переменные окружения в таком порядке:
   1. `ENV_FILE` (если явно задан)
   2. `/etc/carfst/carfst.env` (production по умолчанию)
   3. `.env` в корне проекта (dev)
   
   Примеры запуска:
   ```bash
   # Production: использовать /etc/carfst/carfst.env
   sudo /home/carfst/app/bin/deploy_carfst.sh /tmp/carfst.zip

   # Явно указать env файл (например, другой путь)
   sudo ENV_FILE=/etc/carfst/carfst.env /home/carfst/app/bin/deploy_carfst.sh /tmp/carfst.zip
   ```
   Скрипт сам повторно подгружает ENV при запуске `manage.py` (в том числе при `sudo -u carfst`).

## Настройка уведомлений (SMTP/Telegram)

**ВНИМАНИЕ:** НЕ коммитить токены и chat_id в репозиторий. Задавать только в `/etc/carfst/carfst.env`.

Переменные окружения (добавлять в `/etc/carfst/carfst.env`):

- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` или `EMAIL_USE_SSL`
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
- `LEADS_NOTIFY_EMAIL_TO` (список адресов через запятую)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `LEADS_NOTIFY_ENABLE` (по умолчанию `True`)
- `LEADS_NOTIFY_TIMEOUT` (таймаут HTTP в секундах, по умолчанию `3`)

Пример (с плейсхолдерами):

```bash
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=notify@example.com
EMAIL_HOST_PASSWORD=super-secret
DEFAULT_FROM_EMAIL=CARFAST <notify@example.com>
LEADS_NOTIFY_EMAIL_TO=info@carfst.ru
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID
LEADS_NOTIFY_ENABLE=True
LEADS_NOTIFY_TIMEOUT=3
```

### Как получить Telegram chat_id

1. Напишите боту `/start` в Telegram.
2. Вызовите `getUpdates`:
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
   ```
3. Найдите в ответе `chat.id` и используйте его как `TELEGRAM_CHAT_ID`.

### Применение env и перезапуск

```bash
sudo nano /etc/carfst/carfst.env
sudo systemctl restart gunicorn_carfst
```

### Smoke-тест формы через curl (CSRF)

```bash
# Контакты
curl -s -c /tmp/carfst_cookies.txt https://carfst.ru/contacts/ > /dev/null
CSRF=$(grep csrftoken /tmp/carfst_cookies.txt | tail -n 1 | awk '{print $7}')
curl -s -o /dev/null -w "%{http_code}\n" \
  -b /tmp/carfst_cookies.txt \
  -e "https://carfst.ru/contacts/" \
  -H "Referer: https://carfst.ru/contacts/" \
  -d "csrfmiddlewaretoken=$CSRF&name=Test&phone=+79990000000&city=Vladivostok&message=Test&consent=on" \
  https://carfst.ru/contacts/

# Lead
curl -s -c /tmp/carfst_cookies.txt https://carfst.ru/lead/ > /dev/null
CSRF=$(grep csrftoken /tmp/carfst_cookies.txt | tail -n 1 | awk '{print $7}')
curl -s -o /dev/null -w "%{http_code}\n" \
  -b /tmp/carfst_cookies.txt \
  -e "https://carfst.ru/lead/" \
  -H "Referer: https://carfst.ru/lead/" \
  -d "csrfmiddlewaretoken=$CSRF&name=Test&phone=+79990000000&email=test@example.com&message=Test" \
  https://carfst.ru/lead/
```

**Примечание:** В production (когда `DJANGO_DEBUG=False`) приложение **не запустится**, если:
- `DJANGO_SECRET_KEY` не установлен в переменных окружения (systemd `EnvironmentFile`)
- Значение начинается с `django-insecure-`
- Значение равно `dev-secret-key`
- Длина ключа меньше 50 символов
- Ключ содержит меньше 5 уникальных символов

При ошибке запуска проверьте логи:
```bash
sudo journalctl -u gunicorn_carfst -n 50
```

**Требования к SECRET_KEY в production:**
- Минимум 50 символов (строгая проверка в `settings.py`)
- Минимум 5 уникальных символов
- Не начинается с `django-insecure-`
- Не равен `dev-secret-key`

**Источники конфигурации (в порядке приоритета):**
1. **Production:** Переменные окружения из systemd `EnvironmentFile` (например, `/etc/carfst/carfst.env`)
2. **Development:** `.env` файл в корне проекта (только если `DEBUG=True` или явно указан через `ENV_FILE`)
3. **Fallback:** Значения по умолчанию в `settings.py` (только для development)

### Настройка ADMIN_URL (опционально)

По умолчанию админка доступна по пути `/admin/`. Чтобы изменить путь (например, на `/staff/`):

1. Добавьте в `.env`:
   ```bash
   echo "ADMIN_URL=staff/" >> /home/carfst/app/.env
   ```

2. Перезапустите gunicorn:
   ```bash
   sudo systemctl restart gunicorn_carfst
   ```

3. Обновите конфигурацию nginx (если используется rate-limiting для admin):
   ```nginx
   # Пример rate-limiting для admin в nginx
   limit_req_zone $binary_remote_addr zone=admin_limit:10m rate=5r/m;
   
   location ~ ^/(admin|staff)/login {
       limit_req zone=admin_limit burst=3 nodelay;
       # ... остальная конфигурация
   }
   ```

### Rate-limiting админ-логина через nginx

Зона `admin_login` управляется **только** из репозитория: `deploy/nginx.http.conf` → `/etc/nginx/conf.d/carfst-http.conf`. Не создавайте вручную `00-rate-limits.conf` или другие файлы в `conf.d` с `limit_req_zone admin_login` (деплой при установке удаляет/бэкапит такой файл, чтобы зона была одна).

В `deploy/nginx.http.conf` задано:

```nginx
limit_req_zone $binary_remote_addr zone=admin_login:10m rate=10r/m;
```

Использование зоны — в `deploy/nginx.carfst.ru.conf` (location админ-логина):

```nginx
limit_req zone=admin_login burst=3 nodelay;
```

Это ограничивает попытки входа в админку (10 запросов в минуту с одного IP, burst 3).

### Проверка после деплоя

После успешного деплоя выполните следующие проверки:

```bash
# 1. Проверка Django security (критично - не должно быть ошибок)
python manage.py check --deploy
# Ожидаемый результат: "System check identified no issues (0 silenced)."
# Без предупреждений security.W009 (SECRET_KEY)

# 1.1. Проверка gunicorn unit (production по умолчанию)
systemctl is-active carfst-gunicorn
# Ожидаемый результат: active
# Если используете другой unit, задайте env GUNICORN_SERVICE и проверьте его:
# systemctl is-active "$GUNICORN_SERVICE"

# 2. Проверка миграций (не должно быть незавершенных миграций)
python manage.py makemigrations --check --dry-run
# Ожидаемый результат: "No changes detected"
# Если вывод содержит "Migrations for ...", создайте миграции (python manage.py makemigrations),
# добавьте созданные файлы catalog/migrations/0031_*.py в репозиторий и примените migrate на проде.

# 3. Проверка версии (должно вернуть JSON с build_id)
curl -sS https://carfst.ru/__version__/
# Ожидаемый результат: {"build_id": "..."}

# 4. Проверка canonical (главная)
curl -I https://carfst.ru/
# Ожидаемый результат: 200 OK

# 4.1. Проверка default server (неизвестный Host/IP не должен попадать в Django)
# Ожидаемый результат: 444 (или 301 на canonical) и отсутствие X-Request-ID
curl -I -k https://109.69.16.149/  # замените на актуальный IP
curl -I http://109.69.16.149/     # замените на актуальный IP

# 5. Проверка robots.txt (формат и содержимое)
curl -sS https://carfst.ru/robots.txt
# Ожидаемый результат: многострочный формат, Disallow: /admin/, Disallow: /adminlogin/, Disallow: /staff/, Disallow: /lead/, Sitemap: https://carfst.ru/sitemap.xml
curl -I -sS https://carfst.ru/robots.txt
# Ожидаемый результат: Content-Type: text/plain; charset=utf-8 (или аналогично)
# 5.1. Диагностика источника robots.txt (Django vs nginx static)
# Если есть X-Request-ID и Permissions-Policy, значит ответ идет из Django.
curl -I -sS https://carfst.ru/robots.txt | grep -iE "X-Request-ID|Permissions-Policy|X-Frame-Options"

# 6. Проверка sitemap.xml (валидность и доступность)
curl -I https://carfst.ru/sitemap.xml
# Ожидаемый результат: 200 OK, Content-Type: application/xml
curl -sS https://carfst.ru/sitemap.xml | head -n 20
# Ожидаемый результат: валидный XML с ссылками на продукты, категории, статические страницы
# 6.1. Убедиться, что sitemap не имеет X-Robots-Tag: noindex
curl -I -sS https://carfst.ru/sitemap.xml | grep -i "X-Robots-Tag"

# 7. Проверка X-Robots-Tag для админки (должен быть noindex, nofollow)
curl -I https://carfst.ru/admin/ | grep -i "X-Robots-Tag"
# Ожидаемый результат: X-Robots-Tag: noindex, nofollow

# 7.1. Проверка X-Robots-Tag для /adminlogin/ (если используется)
curl -I https://carfst.ru/adminlogin/ 2>/dev/null | grep -i "X-Robots-Tag" || echo "OK: /adminlogin/ закрыт в robots.txt"

# 8. Проверка /admin/ доступен только по ADMIN_URL (по умолчанию /admin/)
curl -I https://carfst.ru/admin/
# Ожидаемый результат: 302 Redirect на /admin/login/ (или 200 если залогинен)

# 8.1. Проверка Security Headers (Permissions-Policy, X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
curl -I https://carfst.ru/ | grep -iE "Permissions-Policy|X-Content-Type-Options|X-Frame-Options|Referrer-Policy"
# Ожидаемый результат:
# - Permissions-Policy: присутствует с ограничительной политикой
# - X-Content-Type-Options: nosniff
# - X-Frame-Options: DENY
# - Referrer-Policy: strict-origin-when-cross-origin (или из settings)

# 8.2. Проверка HSTS header (только в production, если SECURE_HSTS_SECONDS > 0)
curl -I https://carfst.ru/ | grep -i "Strict-Transport-Security"
# Ожидаемый результат: Strict-Transport-Security: max-age=31536000; includeSubDomains (в production)

# 8.3. Проверка CSP Report-Only (если включен через CSP_REPORT_ONLY=1)
curl -I https://carfst.ru/ | grep -i "Content-Security-Policy-Report-Only"
# Ожидаемый результат: Content-Security-Policy-Report-Only: <policy> (если CSP_REPORT_ONLY=1 в env)

# 8.4. Проверка Cache-Control для админки (должен быть no-store)
curl -I https://carfst.ru/admin/ | grep -i "Cache-Control"
# Ожидаемый результат: Cache-Control: no-store, no-cache, must-revalidate, private

# 8.5. Проверка meta robots в админке (должен быть noindex, nofollow в HTML)
curl -sS https://carfst.ru/admin/ | grep -i "meta.*robots"
# Ожидаемый результат: <meta name="robots" content="noindex, nofollow">

# 9. Проверка отсутствия артефактов "#####" на главной (критично)
curl -sS https://carfst.ru/ | grep -nE '#####|\{#|Inline SVG placeholder' || echo "OK: артефакты не найдены"
# Ожидаемый результат: OK: артефакты не найдены

# 10. Проверка отсутствия артефактов в каталоге
curl -sS https://carfst.ru/catalog/ | grep -nE '#####|\{#|Inline SVG placeholder' || echo "OK: артефакты не найдены"
# Ожидаемый результат: OK: артефакты не найдены

# 11. Проверка отсутствия артефактов на странице контактов
curl -sS https://carfst.ru/contacts/ | grep -nE '#####|\{#|Inline SVG placeholder' || echo "OK: артефакты не найдены"
# Ожидаемый результат: OK: артефакты не найдены

# 12. Проверка DRF docs доступны только для staff (в production)
# В DEBUG=False должен быть 403 для неавторизованных или redirect на login
curl -I https://carfst.ru/api/docs/
# Ожидаемый результат: 302 Redirect на /admin/login/ (для неавторизованных) или 403 Forbidden

# 13. Проверка статики (должно быть 200 OK)
curl -I https://carfst.ru/static/admin/css/base.css

# 14. Проверка health endpoint
curl -sS https://carfst.ru/health/
# Ожидаемый результат: JSON с status: "ok"
```

### Типовые проблемы

**500 ошибка на страницах товара (`OperationalError: no such column: catalog_sitesettings.work_hours`)**
- Причина: миграция `0016_add_site_settings_fields.py` не применена
- Решение: скрипт деплоя автоматически применяет миграции. Если ошибка осталась, проверьте логи деплоя

**Превью товаров "вытягиваются" по высоте в листингах**
- Причина: старый CSS или шаблон не попал в архив
- Решение: убедитесь, что `static/css/styles.css` и `templates/catalog/_product_card.html` включены в архив
 - Диагностика: проверьте, что на `/catalog/` подключён `/static/css/styles.<hash>.css` и он содержит `build: cards-eqheight-20251224` (см. блок “Диагностика” выше)

**"Голый" `/admin/login` (без стилей)**
- Причина: не выполнен `collectstatic`
- Решение: скрипт деплоя автоматически собирает статику. Если проблема осталась, проверьте права на `STATIC_ROOT`

### Важно

- **НЕ используйте ручной деплой** — легко пропустить критичные шаги
- **Всегда проверяйте логи** скрипта деплоя на наличие ошибок
- **Убедитесь, что архив содержит миграции** — скрипт проверит это автоматически


