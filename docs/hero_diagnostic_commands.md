# Hero главной (/): диагностика и приёмка (v3, cache-busting)

## A) Диагностика: есть ли hero в HTML

### Через nginx (с gzip)

```bash
curl -sS --compressed https://carfst.ru/ | grep -n -E 'hero--shacman|hero__bg-img|shacman_mein'
```

### С полным набором маркеров (v3)

```bash
curl -sS -H 'Accept-Encoding: gzip' --compressed https://carfst.ru/ \
  | grep -n -E 'hero-marker-20260203-v3|data-hero-bg|shacman_mein\.v3\.webp|hero--shacman|hero__bg-img|hero__overlay' | head -n 50
```

### Через gunicorn напрямую (на сервере)

```bash
curl -sS -H 'Host: carfst.ru' http://127.0.0.1:8001/ \
  | grep -n -E 'hero-marker-20260203-v3|data-hero-bg|shacman_mein\.v3\.webp|hero--shacman|hero__bg-img' | head -n 50
```

**Ожидание:** хотя бы одна строка с номером.

### Какой hero URL в HTML и какой у него размер (для диагностики)

Чтобы однозначно понять: проблема в старом hashed src или в overlay — выполните и пришлите вывод:

```bash
HOME_HTML="$(curl -sS --compressed https://carfst.ru/)"
HERO_SRC="$(printf '%s' "$HOME_HTML" | grep -oE 'src="[^"]*shacman_mein[^"]*\.webp"' | head -1)"
echo "HERO_SRC=$HERO_SRC"
# Извлечь URL без кавычек
HERO_URL="$(printf '%s' "$HERO_SRC" | sed -n 's/.*src="\([^"]*\)".*/\1/p')"
if [ -n "$HERO_URL" ]; then
  echo "Content-Length for $HERO_URL:"
  curl -sSI "https://carfst.ru${HERO_URL}" | grep -i content-length
fi
```

Если `HERO_SRC` — прямой `/static/img/hero/shacman_mein.v3.webp` и content-length > 50KB, а фото всё равно не видно, причина в overlay. Если URL hashed и content-length ~38KB — причина в старом manifest/файле.

### Проверка заголовка (что отдаёт view home)

```bash
curl -sSI https://carfst.ru/ | grep -i x-home-template
```

**Ожидание:** `X-Home-Template: templates/catalog/home.html`

---

## B) Статика: hashed hero не заглушка (content-length > 100KB)

При ManifestStaticFilesStorage в HTML подставляется hashed URL вида `/static/img/hero/shacman_mein.v3.<hash>.webp`. Проверять нужно именно его.

```bash
HASHED="$(curl -sS --compressed https://carfst.ru/ \
  | grep -oE '/static/img/hero/shacman_mein\.v3\.[a-f0-9]{12}\.webp' | head -1)"
echo "HASHED=$HASHED"
curl -sSI "https://carfst.ru${HASHED}?nocache=1" | egrep -i 'http/|content-length'
```

**Ожидание:** `content-length` > 100000 (сотни KB), hash в HTML не от старой заглушки (38KB).

Нехешированный путь (для проверки после сборки в static/):

```bash
curl -sSI https://carfst.ru/static/img/hero/shacman_mein.v3.webp | egrep -i 'content-length|cache-control'
```

---

## Загрузка исходника и сборка v3 (на сервере)

### Куда положить исходник

- **Путь:** `/home/carfst/app/cursor_work/static/img/hero/shacman_mein.webp`
- **Формат:** любой, что открывает Pillow (WebP, JPEG, PNG).
- **Права после загрузки:** `chown carfst:carfst`, `chmod 644`.

**Загрузка с локальной машины (scp):**

```bash
scp /path/to/your/shacman_photo.webp user@server:/home/carfst/app/cursor_work/static/img/hero/shacman_mein.webp
```

### Сборка v3 и публикация статики

Скрипт выводит `shacman_mein.v3.webp`. Проверка «похоже на заглушку» (яркость + энтропия); при необходимости `--force`.

**Первый деплой после перехода на v3:** на сервере один раз выполнить сборку, затем collectstatic.

### Принудительное пересоздание manifest и hashed hero (если HTML ссылается на старый 38KB)

Если в HTML уже есть hashed URL, но файл по нему отдаёт 38KB (manifest не обновился), на сервере:

```bash
cd /home/carfst/app/cursor_work
set -a; source /etc/carfst/carfst.env; set +a

# убедиться, что v3 собран из большого исходника
sudo -u carfst -E .venv/bin/python scripts/build_hero_v2.py
ls -lh static/img/hero/shacman_mein.v3.webp

# очистить STATIC_ROOT и собрать всю статику заново (новый manifest)
sudo -u carfst -E .venv/bin/python manage.py collectstatic --clear --noinput

# опубликовать в nginx
sudo rsync -a --delete /home/carfst/app/cursor_work/staticfiles/ /var/www/carfst/staticfiles/
sudo nginx -t && sudo systemctl reload nginx
```

Либо при деплое скрипт сам удаляет старые `shacman_mein.v3.*.webp` и `staticfiles.json` перед collectstatic, чтобы manifest пересобрался.

Обычная сборка без полной очистки:

```bash
cd /home/carfst/app/cursor_work
sudo -u carfst -E .venv/bin/python scripts/build_hero_v2.py
sudo -u carfst -E .venv/bin/python manage.py collectstatic --noinput
```

Проверка в STATIC_ROOT и по HTTP (hashed URL — см. раздел B выше):

```bash
ls -lh /home/carfst/app/cursor_work/staticfiles/img/hero/shacman_mein.v3.webp
```

---

## Проверка, что hero CSS (object-position) применился

После деплоя убедиться, что в отданном (хэшированном) CSS есть стили hero и новые `object-position`:

```bash
ls -1 /var/www/carfst/staticfiles/css/styles.*.css | tail -n 1
grep -n "hero--shacman" /var/www/carfst/staticfiles/css/styles.*.css | head
```

Ожидание: в выводе `grep` есть строки с `.hero--shacman` и `object-position: 50% 20%` (или `50%30%`, `50%55%` в медиа-запросах). Деплой-скрипт в `staticfiles_smoke_check` сам проверяет наличие `hero--shacman` и `object-position` в опубликованном CSS.

---

## Деплой: публикация статики в /var/www/carfst/staticfiles

В `bin/deploy_carfst.sh`:

- Используется `STATIC_ROOT` и `NGINX_STATIC_ROOT`; статика копируется так:
  `rsync -a --delete "$STATIC_ROOT/" "$NGINX_STATIC_ROOT/"`.
- После публикации выполняются `nginx -t` и `systemctl reload nginx`.
- Перед collectstatic удаляются старые hashed hero v3 и `staticfiles.json`, чтобы manifest пересобрался под актуальный v3.
- В smoke-проверке: из главной извлекается hashed hero URL, проверяется его `content-length > 100KB` (иначе — fallback на unhashed и > 50KB).

---

## Итоговые команды приёмки

```bash
# 1) Hero-разметка в HTML
curl -sS --compressed https://carfst.ru/ \
  | grep -n -E 'hero--shacman|hero__bg-img|hero__overlay|hero-marker-20260203-v3|shacman_mein\.v3' | head -n 80

# 2) Hashed hero URL и размер (ожидаемо > 100KB)
HASHED="$(curl -sS --compressed https://carfst.ru/ \
  | grep -oE '/static/img/hero/shacman_mein\.v3\.[a-f0-9]{12}\.webp' | head -1)"
curl -sSI "https://carfst.ru${HASHED}?nocache=1" | egrep -i 'http/|content-length'
```

**Ожидание:** фон в hero виден (не «чёрный блок»), HTML ссылается на новый hashed hero (не 38KB), текст читаем.

---

## Чеклист приёмки

- [ ] Команды выше: hero-маркер и классы в HTML; hashed hero `content-length` > 100000.
- [ ] В браузере на главной фон заметен, текст и кнопки читаемы (desktop и mobile).

---

## Смена фото в будущем (v4 и т.д.)

1. Положить новый исходник в `static/img/hero/shacman_mein.webp` (или другой путь и передать аргументом в скрипт).
2. Изменить в `scripts/build_hero_v2.py` выход на новое имя (например `shacman_mein.v4.webp`) или добавить параметр версии.
3. Обновить в `templates/catalog/home.html`: preload, `src`, `data-hero-bg` на новый файл.
4. Запустить скрипт сборки, `collectstatic`, задеплоить. Новое имя файла даёт cache-busting при `immutable` кэше.
