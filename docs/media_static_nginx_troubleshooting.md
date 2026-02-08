# Раздача /media/ и /static/ через Nginx (CARFST)

Чеклист диагностики и исправления 404/403 для картинок и статики.

---

## 1. Воспроизведение проблемы

Возьмите 1–2 URL «битых» картинок (с фронта или админки), например:
- `/media/products/2024/01/photo.jpg`
- или из админки: полный URL к ImageField

На сервере выполните:

```bash
# Подставьте реальный путь к файлу вместо /media/.../file.jpg
URL="/media/products/2024/01/example.jpg"

curl -I "https://carfst.ru${URL}"
curl -I "https://www.carfst.ru${URL}"
curl -I "http://127.0.0.1${URL}" -H "Host: carfst.ru"
```

Зафиксируйте: **код ответа**, **Content-Type**, **Server**, наличие **редиректов** (Location).

---

## 2. Логи Nginx

```bash
sudo tail -n 200 /var/log/nginx/error.log
sudo tail -n 200 /var/log/nginx/access.log | grep -E "(/media/|/static/|jpg|jpeg|png|webp|gif)"
```

По error.log смотрите «open() failed», «Permission denied», «No such file». По access.log — коды ответов (404, 403) для запросов к media/static.

---

## 3. Конфиг Nginx

Активный сервер-блок и включённые конфиги:

```bash
ls -la /etc/nginx/sites-enabled/
cat /etc/nginx/sites-enabled/carfst.ru.conf
```

Проверьте:

- **location /media/** — должен использовать **alias** (не root), путь должен **заканчиваться на /**:
  - `alias /var/www/carfst/media/;`
  - при необходимости: `try_files $uri =404;`
- **location /static/** — аналогично:
  - `alias /var/www/carfst/staticfiles/;`
  - при необходимости: `try_files $uri =404;`

При **root** путь к файлу считается иначе (root + uri), часто это даёт 404. Для раздачи с диска нужен именно **alias** с завершающим `/`.

В репозитории шаблон: `deploy/nginx.carfst.ru.conf`. После правок:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 4. Файлы на диске и права

Для конкретной «битой» картинки по URI определите ожидаемый путь:

- Nginx: `alias /var/www/carfst/media/` + URI `/media/products/...` → файл:  
  `/var/www/carfst/media/products/...`  
  (часть `/media/` в URI заменяется на alias).

Проверка:

```bash
# Пример: URI /media/products/2024/01/photo.jpg
FILE="/var/www/carfst/media/products/2024/01/photo.jpg"

ls -la "$FILE"
namei -l "$FILE"
```

Убедитесь:

- Файл существует.
- Все каталоги в пути доступны на чтение пользователю, от которого работает Nginx (часто `www-data`): `x` на каталогах, права на файл не запрещают чтение.

Если **/var/www/carfst/media** — симлинк на каталог проекта (например `/home/carfst/app/cursor_work/media`), проверьте и сам симлинк, и целевой каталог:

```bash
ls -la /var/www/carfst/media
readlink -f /var/www/carfst/media
```

---

## 5. Django: MEDIA_ROOT и раздача

Проверьте настройки (на сервере, в окружении приложения):

```bash
cd /home/carfst/app/cursor_work
set -a; source /etc/carfst/carfst.env; set +a
.venv/bin/python -c "
from django.conf import settings
print('MEDIA_URL:', settings.MEDIA_URL)
print('MEDIA_ROOT:', settings.MEDIA_ROOT)
print('STATIC_URL:', settings.STATIC_URL)
print('STATIC_ROOT:', settings.STATIC_ROOT)
"
```

- **MEDIA_ROOT** должен совпадать с тем каталогом, на который указывает Nginx (напрямую или через симлинк). Деплой создаёт симлинк: `/var/www/carfst/media` → `MEDIA_ROOT` (например `/home/carfst/app/cursor_work/media`).
- Для статики: после `collectstatic` файлы лежат в **STATIC_ROOT**; Nginx раздаёт каталог, указанный в `alias /var/www/carfst/staticfiles/` (должен совпадать с тем, куда собирается статика, или быть симлинком/копией).

---

## 6. Внести правку и применить

После изменения конфига Nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Повторите:

```bash
curl -I "https://carfst.ru${URL}"
```

Проверьте в браузере, что картинка открывается (200, корректный Content-Type, нет 404/403 в access.log).

---

## 7. HTTPS, редиректы, www

Убедитесь, что и для **carfst.ru**, и для **www.carfst.ru** раздача `/media/` и `/static/` одна и та же:

- Обычно www редиректит на apex (carfst.ru), запросы к статике/медиа идут уже на carfst.ru.
- На основном сервере `server_name carfst.ru` блоки `location /media/` и `location /static/` должны отдавать файлы с диска (alias), а не проксировать на backend для этих путей.

---

## Критерий готовности

- Проблемные URL картинок возвращают **200**.
- Заголовок **Content-Type** корректный (image/jpeg, image/png и т.д.).
- Файл реально читается Nginx с диска (alias указывает на существующий путь с нужными правами).
- В логах Nginx нет 404/403 по этим URL после исправления.

---

## Если curl до продакшена не доходит

Проверка на самом сервере:

```bash
sudo systemctl status nginx --no-pager
sudo nginx -t
sudo ss -lntp | egrep ':(80|443)\s'
# Локально без внешнего DNS:
curl -kI https://127.0.0.1 -H "Host: carfst.ru"
```

Если сервис слушает 80/443 и `nginx -t` успешен, а снаружи сайт недоступен — смотреть файрвол, DNS, балансировщик.
