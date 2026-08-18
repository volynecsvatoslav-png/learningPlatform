# Production deployment guide

Производственная установка: один Docker-хост, Traefik/nginx как reverse proxy с TLS, внутренние сервисы без публичных портов. Пример без реальных секретов — все значения заменить в своём `.env`.

## Требования

- Docker Engine + Compose v2 на хосте;
- домен `app.example.com`, A-запись на хост, сертификаты (например, Let's Encrypt);
- свободные ресурсы: 2 vCPU, 4 GB RAM, ~50 GB диск (зависит от объёма медиа).

## `.env` для production

```dotenv
# Обязательные секреты (сгенерировать свои, примеры в репозитории не использовать)
DJANGO_SECRET_KEY=заменить-на-длинный-случайный
ACCESS_TOKEN_PEPPER=заменить
SESSION_TOKEN_PEPPER=заменить
OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64=заменить  # PKCS8 PEM (base64), EC P-256
VITE_OFFLINE_LICENSE_PUBLIC_JWK={"kty":"EC","crv":"P-256","x":"...","y":"..."}  # пара к приватному ключу
POSTGRES_PASSWORD=заменить
MINIO_KMS_SECRET_KEY=заменить  # формат: имя-ключа:32-байта-base64
S3_ACCESS_KEY_ID=заменить
S3_SECRET_ACCESS_KEY=заменить

# Домены и отключение dev-режима
PUBLIC_APP_URL=https://app.example.com
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=app.example.com,api
VITE_ALLOWED_HOSTS=app.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.example.com
DJANGO_CORS_ALLOWED_ORIGINS=https://app.example.com
DJANGO_SECURE_COOKIES=true
DJANGO_SECURE_SSL_REDIRECT=true
TRUSTED_PROXY_CIDRS=10.0.0.0/8  # только реальные proxy между клиентом и Django
```

При `DJANGO_DEBUG=false` все dev-значения по умолчанию заменяются безопасными: HSTS 1 год (включая subdomains/preload), `__Host-csrftoken`/`__Host-sessionid`, secure cookies, `SameSite=Lax`, nosniff, `Referrer-Policy: strict-origin-when-cross-origin`, development offline-ключи запрещены. Если часть запросов идёт не через reverse proxy, выключите `DJANGO_SECURE_SSL_REDIRECT` и переложите редирект на nginx.

Ключи `DJANGO_SECRET_KEY`, pepper-ы и offline private key должны быть одинаковыми между рестартами и нодами (пептинг HMAC токенов доступа и подпись offline-лицензий не восстановимы иначе).

## Production compose

Включите тот же `compose.yaml`, что и в разработке, но с production `.env`:

```powershell
docker compose up --build --detach --wait
```

Отличия от dev-конфигурации достигаются только переменными окружения:

- `api`/`worker` — те же образы; gunicorn уже настроен на `--workers=2 --threads=4`, access log без Referer/User-Agent;
- фронтенд — статическая сборка + Vite dev-server не используется. **В production не публикуйте порт 5173**: статику отдаёт nginx, `/api` проксирует Django (см. ниже);
- MinIO, PostgreSQL и Redis при необходимости вынесите на отдельные хосты, заменив `S3_ENDPOINT_URL`, `DATABASE_URL`, `REDIS_URL` в `.env`/compose override;
- `MEDIA_TRANSFER_MODE` оставьте `proxy` (медиа идут через same-origin nginx → Django), если не настроен presigned-путь до внешнего S3.

## nginx (основной конфиг)

```nginx
server {
    listen 80;
    server_name app.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.example.com;

    ssl_certificate     /etc/letsencrypt/live/app.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem;

    # HSTS — после того как TLS стабилен хотя бы неделю
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;

    client_max_body_size 6g;  # до MEDIA_VIDEO_MAX_BYTES

    # Статика PWA (SPA: /, /vendor/, /app/)
    root /srv/learning/apps/web/dist;
    location / {
        try_files $uri /index.html;
        expires 1h;
    }
    location /assets/ { try_files $uri =404; expires 1y; add_header Cache-Control "public, immutable"; }
    location = /manifest.webmanifest { expires 1h; }
    location = /sw.js { expires 0; add_header Cache-Control "no-store"; }

    # API, backoffice, медиа и health
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port 443;
        proxy_http_version 1.1;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_buffering off;         # для streaming-медиа (proxy mode)
        proxy_read_timeout 600s;
    }
    location /backoffice/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto https; }
    location /health/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
    location /static/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_cache_valid 200 1h; }
}
```

CSP-заголовки (включая `default-src 'none'` на API) уже отдаёт Django, а страницы собираются с CSP от Vite. Дополнительно в nginx ничего настраивать не нужно; `frame-ancestors 'none'` защищает от clickjacking.

### ВАЖНО: редирект для ссылок восстановления

`Referrer-Policy` уже выставляется приложением (`no-referrer`, пока токен в URL). Не добавляйте в nginx `Referrer-Policy: no-referrer` глобально — политика должна оставаться динамической. Ничего не логируйте со стороны nginx для путей с query/fragment: fragment в HTTP не уходит, а query параметров доступа нет — приложение передаёт токены во fragment `#access=...`/`#recovery=...`.

## Проверки после развёртывания

1. `curl -I https://app.example.com/health/` — ожидаем `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, CSP c `default-src 'none'`, `X-Frame-Options: DENY`.
2. `curl -I https://app.example.com/` — CSP страницы без `unsafe-inline`, `Referrer-Policy: strict-origin-when-cross-origin`.
3. Пройти E2E из чистого checkout против production-окружения (см. README) или ручной чек-лист.
4. Проверить restore drill из `docs/operations/backup-restore.md`.
5. `pip-audit --requirement requirements.lock` и `npm audit --audit-level=high` — должны быть чистыми (запускаются в CI).

## Операционные заметки

- Лимиты по умолчанию (recovery 5/3 в час, access 20/мин, heartbeat ≤1/5с, media 120/мин/сессия, vendor login 10/15 мин) подходят для single-host прототипа; при нескольких фронтенд-нодах каждый Django-инстанс считает отдельно.
- Отладка: `docker compose logs api` — access/error логи без токенов и User-Agent.
- Ротация offline-ключей ломает все скачанные офлайн-курсы (лицензии перестают проверяться) — ротация только вместе с новой ревизией курсов и перескачиванием пакетов.
