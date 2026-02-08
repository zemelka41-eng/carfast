## Deploy на Beget VPS (carfst.ru / www.carfst.ru)

Ниже — «рецепт», чтобы развернуть проект на чистом VPS с `gunicorn + nginx`.

### 0) Подготовка домена

- **DNS**: A-запись для `carfst.ru` на IP VPS.
- **DNS**: `www` либо A-запись на IP VPS, либо CNAME на `carfst.ru`.

### 1) Пакеты и базовые зависимости

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-dev nginx certbot python3-certbot-nginx git curl
```

Если используете Postgres:

```bash
sudo apt install -y postgresql postgresql-contrib libpq-dev
```

### 2) Директория проекта и пользователь

Рекомендуемый путь:

- **код/venv**: `/var/www/carfst`
- **пользователь nginx/gunicorn**: `www-data`

```bash
sudo adduser --disabled-password --gecos "" carfst
sudo mkdir -p /var/www/carfst
sudo chown -R carfst:www-data /var/www/carfst
```

### 3) Получить код, создать venv, установить зависимости

```bash
sudo -iu carfst
cd /var/www/carfst
# Скопируйте сюда проект (git clone / rsync / scp)

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 4) Создать `.env`

Проект читает переменные окружения из файла `.env` в корне.

Создайте `/var/www/carfst/.env`:

```bash
nano /var/www/carfst/.env
```

Минимально необходимые переменные для продакшна:

```env
DEBUG=0
SECRET_KEY=CHANGE_ME_TO_RANDOM
ALLOWED_HOSTS=carfst.ru,www.carfst.ru
CSRF_TRUSTED_ORIGINS=https://carfst.ru,https://www.carfst.ru

# Вариант 1: Postgres (рекомендуется)
DATABASE_URL=postgres://carfst_user:carfst_pass@127.0.0.1:5432/carfst_db

# Статика/медиа под nginx
STATIC_ROOT=/var/www/carfst/staticfiles
MEDIA_ROOT=/var/www/carfst/media

# HTTPS редирект (можно включать после настройки SSL)
SSL_REDIRECT=1

# При необходимости
LOG_LEVEL=INFO
```

Сгенерировать `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5) Postgres (если используете)

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE carfst_db;
CREATE USER carfst_user WITH PASSWORD 'carfst_pass';
GRANT ALL PRIVILEGES ON DATABASE carfst_db TO carfst_user;
\q
```

### 6) Миграции и статика

```bash
source /var/www/carfst/.venv/bin/activate
cd /var/www/carfst
python manage.py migrate
python manage.py collectstatic --noinput
```

### 7) gunicorn через systemd

- Возьмите шаблон: `deploy/gunicorn.service`
- Проверьте пути (`WorkingDirectory`, `EnvironmentFile`, `ExecStart`) и пользователя.

```bash
sudo cp /var/www/carfst/deploy/gunicorn.service /etc/systemd/system/gunicorn_carfst.service
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn_carfst
sudo systemctl status gunicorn_carfst
```

### 8) nginx reverse proxy + статика

- Возьмите шаблон: `deploy/nginx.carfst.ru.conf`

```bash
sudo mkdir -p /var/www/letsencrypt
sudo cp /var/www/carfst/deploy/nginx.carfst.ru.conf /etc/nginx/sites-available/carfst.ru.conf
sudo ln -sf /etc/nginx/sites-available/carfst.ru.conf /etc/nginx/sites-enabled/carfst.ru.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 9) SSL (certbot) для `carfst.ru` и `www.carfst.ru`

```bash
sudo certbot --nginx -d carfst.ru -d www.carfst.ru
sudo certbot renew --dry-run
```

### 10) Команды для обновления релиза

```bash
cd /var/www/carfst
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart gunicorn_carfst
sudo nginx -t && sudo systemctl reload nginx
```
