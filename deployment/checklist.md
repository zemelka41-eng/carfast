# Чеклист деплоя CARFST (Beget VPS)

1. DNS: A/AAAA на сервер, CNAME www → @.
2. Пакеты: `apt update && apt install -y python3.11-venv postgresql nginx certbot python3-certbot-nginx git`.
3. Пользователь/путь: `/opt/carfst`, права www-data.
4. Клонировать репо, `python -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`.
5. Заполнить `.env` из `.env.example`.
6. База: создать БД/пользователя, `python manage.py migrate`, `python manage.py createsuperuser`.
7. Статика: `python manage.py collectstatic --noinput`.
8. Gunicorn unit: скопировать `deployment/systemd/gunicorn_carfst.service` в `/etc/systemd/system/`, `systemctl daemon-reload && systemctl enable --now gunicorn_carfst`.
9. Nginx: файл `deployment/nginx/carfst/carfst.conf` в `/etc/nginx/sites-available/carfst`, симлинк в sites-enabled, `nginx -t && systemctl reload nginx`.
10. HTTPS: `certbot --nginx -d carfst.ru -d www.carfst.ru`.
11. Проверка: `curl -I https://www.carfst.ru/ru/`, `python manage.py check --deploy`.
12. Бэкапы: `deployment/backup_pg.sh` + cron.
# Чеклист развёртывания на Beget VPS (VPS Town)

## Предварительные требования

- [ ] Доступ к VPS серверу (SSH)
- [ ] Домен настроен и указывает на IP сервера (A-запись для carfst.ru и www.carfst.ru)
- [ ] Права sudo на сервере

## Шаг 1: Подготовка сервера

```bash
# Обновление системы
sudo apt update
sudo apt upgrade -y

# Установка необходимых пакетов
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib nginx git curl \
    build-essential libpq-dev libjpeg-dev zlib1g-dev
```

## Шаг 2: Создание базы данных PostgreSQL

```bash
# Переключение на пользователя postgres
sudo -u postgres psql

# В консоли PostgreSQL выполните:
CREATE DATABASE carfst_db;
CREATE USER carfst_user WITH PASSWORD 'your-secure-password-here';
ALTER ROLE carfst_user SET client_encoding TO 'utf8';
ALTER ROLE carfst_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE carfst_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE carfst_db TO carfst_user;
\q
```

**Важно**: Сохраните пароль базы данных, он понадобится для `.env` файла.

## Шаг 3: Клонирование проекта

```bash
# Создание директории для проектов
sudo mkdir -p /var/www
cd /var/www

# Клонирование репозитория (замените на ваш URL)
sudo git clone <your-repository-url> carfst
sudo chown -R $USER:$USER /var/www/carfst
cd carfst
```

## Шаг 4: Настройка виртуального окружения

```bash
# Создание виртуального окружения
python3.11 -m venv venv

# Активация
source venv/bin/activate

# Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt
```

## Шаг 5: Настройка переменных окружения

```bash
# Копирование примера
cp .env.example .env

# Редактирование .env
nano .env
```

Заполните все необходимые значения:
- `SECRET_KEY` - сгенерируйте через: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `DEBUG=False`
- `ALLOWED_HOSTS=carfst.ru,www.carfst.ru`
- Данные базы данных
- Настройки email
- Telegram токены (опционально)

## Шаг 6: Применение миграций и создание суперпользователя

```bash
# Активация venv (если ещё не активирован)
source venv/bin/activate

# Применение миграций
python manage.py migrate

# Создание суперпользователя
python manage.py createsuperuser

# Загрузка seed данных (опционально)
python manage.py loaddata data/fixtures/seed_data.json
```

## Шаг 7: Сбор статических файлов

```bash
# Создание директории для статики
mkdir -p staticfiles

# Сбор статики
python manage.py collectstatic --noinput
```

## Шаг 8: Настройка Gunicorn

```bash
# Создание директории для логов
sudo mkdir -p /var/log/gunicorn
sudo chown www-data:www-data /var/log/gunicorn

# Копирование systemd unit файла
sudo cp deployment/systemd/gunicorn_carfst.service /etc/systemd/system/

# Редактирование файла (проверьте пути!)
sudo nano /etc/systemd/system/gunicorn_carfst.service

# Убедитесь, что пути соответствуют:
# - WorkingDirectory=/var/www/carfst
# - ExecStart=/var/www/carfst/venv/bin/gunicorn
# - User и Group (обычно www-data)

# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable gunicorn_carfst

# Запуск сервиса
sudo systemctl start gunicorn_carfst

# Проверка статуса
sudo systemctl status gunicorn_carfst
```

## Шаг 9: Настройка Nginx

```bash
# Копирование конфига
sudo cp deployment/nginx/carfst /etc/nginx/sites-available/

# Создание симлинка
sudo ln -s /etc/nginx/sites-available/carfst /etc/nginx/sites-enabled/

# Удаление дефолтного конфига (опционально)
sudo rm /etc/nginx/sites-enabled/default

# Редактирование конфига (проверьте пути и домены!)
sudo nano /etc/nginx/sites-available/carfst

# Проверка конфигурации
sudo nginx -t

# Перезагрузка Nginx
sudo systemctl reload nginx
```

## Шаг 10: Настройка SSL (Let's Encrypt)

```bash
# Установка Certbot
sudo apt install -y certbot python3-certbot-nginx

# Получение сертификата
sudo certbot --nginx -d carfst.ru -d www.carfst.ru

# Следование инструкциям Certbot:
# - Введите email
# - Согласитесь с условиями
# - Выберите redirect HTTP to HTTPS

# Проверка автообновления
sudo certbot renew --dry-run
```

## Шаг 11: Настройка прав доступа

```bash
# Установка правильных прав
sudo chown -R www-data:www-data /var/www/carfst
sudo chmod -R 755 /var/www/carfst
sudo chmod -R 775 /var/www/carfst/media
sudo chmod -R 775 /var/www/carfst/logs
```

## Шаг 12: Настройка бэкапов

```bash
# Создание скрипта бэкапа
sudo nano /usr/local/bin/backup_carfst.sh
```

Содержимое скрипта:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/carfst"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Бэкап базы данных
sudo -u postgres pg_dump carfst_db > $BACKUP_DIR/db_$DATE.sql

# Бэкап медиа файлов
tar -czf $BACKUP_DIR/media_$DATE.tar.gz /var/www/carfst/media

# Удаление старых бэкапов (старше 30 дней)
find $BACKUP_DIR -type f -mtime +30 -delete

echo "Backup completed: $DATE"
```

```bash
# Делаем скрипт исполняемым
sudo chmod +x /usr/local/bin/backup_carfst.sh

# Настройка cron (ежедневно в 2:00)
sudo crontab -e
# Добавьте строку:
0 2 * * * /usr/local/bin/backup_carfst.sh >> /var/log/carfst_backup.log 2>&1
```

## Шаг 13: Финальная проверка

- [ ] Проверьте доступность сайта: https://www.carfst.ru
- [ ] Проверьте админ-панель: https://www.carfst.ru/admin
- [ ] Проверьте API: https://www.carfst.ru/api/products/
- [ ] Проверьте статические файлы (CSS, JS загружаются)
- [ ] Проверьте медиа файлы (изображения отображаются)
- [ ] Проверьте SSL сертификат (зелёный замочек в браузере)
- [ ] Проверьте редирект с HTTP на HTTPS
- [ ] Проверьте логи: `sudo journalctl -u gunicorn_carfst -f`
- [ ] Проверьте логи Nginx: `sudo tail -f /var/log/nginx/carfst_error.log`

## Шаг 14: Настройка мониторинга (опционально)

```bash
# Установка fail2ban для защиты от брутфорса
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## Полезные команды

### Перезапуск сервисов

```bash
# Gunicorn
sudo systemctl restart gunicorn_carfst

# Nginx
sudo systemctl restart nginx

# PostgreSQL
sudo systemctl restart postgresql
```

### Просмотр логов

```bash
# Gunicorn
sudo journalctl -u gunicorn_carfst -f

# Nginx
sudo tail -f /var/log/nginx/carfst_error.log
sudo tail -f /var/log/nginx/carfst_access.log

# Django
tail -f /var/www/carfst/logs/django.log
```

### Обновление кода

```bash
cd /var/www/carfst
source venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart gunicorn_carfst
```

## Решение проблем

### 502 Bad Gateway

- Проверьте, запущен ли Gunicorn: `sudo systemctl status gunicorn_carfst`
- Проверьте логи: `sudo journalctl -u gunicorn_carfst -n 50`
- Проверьте, что порт 8000 не занят: `sudo netstat -tlnp | grep 8000`

### Статические файлы не загружаются

- Проверьте права: `ls -la /var/www/carfst/staticfiles`
- Проверьте конфиг Nginx: `sudo nginx -t`
- Убедитесь, что выполнили `collectstatic`

### Ошибки базы данных

- Проверьте подключение: `sudo -u postgres psql -U carfst_user -d carfst_db`
- Проверьте `.env` файл (правильные данные БД)
- Проверьте права пользователя БД

### SSL сертификат не работает

- Проверьте DNS записи (A-запись для домена)
- Проверьте, что порт 80 открыт для Let's Encrypt
- Проверьте логи Certbot: `sudo certbot certificates`

## Контрольный список перед релизом

- [ ] `DEBUG=False` в `.env`
- [ ] `SECRET_KEY` изменён на уникальный
- [ ] `ALLOWED_HOSTS` содержит все домены
- [ ] SSL сертификат установлен и работает
- [ ] Бэкапы настроены и работают
- [ ] Логирование настроено
- [ ] Мониторинг настроен (опционально)
- [ ] Тесты пройдены
- [ ] Документация обновлена

