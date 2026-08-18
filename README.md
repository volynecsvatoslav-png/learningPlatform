# Learning Platform

Лёгкая многовендорная обучающая платформа. Реализованы итерации 1.1–1.5: platform backoffice, отдельный vendor cabinet, выдача доступов без оплаты, learner cabinet с привязкой доступа к одному устройству (перенос и восстановление), зашифрованные offline-пакеты для установленной PWA, публикации и приватные медиа в MinIO, hardening (CSP/CSRF/CORS/rate limits, редактирование секретов из логов), полный E2E suite, backup/restore runbook и deployment guide.

## Требования

- Docker Desktop с Compose v2;
- свободные локальные порты `5173`, `8000`, `8025`, `9000`, `9001`.

## Запуск

Проект поднимается из чистого checkout одной командой:

```powershell
docker compose up --build
```

Compose использует безопасные локальные значения по умолчанию. Чтобы изменить их, скопируйте `.env.example` в `.env` до запуска; production-секреты в репозиторий не добавляйте.

После первого запуска создайте platform admin в отдельном терминале:

```powershell
docker compose exec api python manage.py createsuperuser
```

Сервисы:

- frontend: <http://localhost:5173>;
- vendor cabinet: <http://localhost:5173/vendor/>;
- learner cabinet: <http://localhost:5173/app/> или ссылка из email;
- backoffice только для superuser: <http://localhost:8000/backoffice/>;
- healthcheck API: <http://localhost:8000/health/>;
- Mailpit: <http://localhost:8025>;
- MinIO console: <http://localhost:9001>.

Миграции применяются контейнером API автоматически. Bucket MinIO создаётся приватным сервисом `minio-init`.

### Передача медиа

`MEDIA_TRANSFER_MODE=proxy` используется по умолчанию в DEBUG и безопасен для туннелей: браузер отправляет multipart в Django, а просмотр идёт через same-origin URL с поддержкой Range. Для production по умолчанию используется `presigned`, где браузер загружает файл напрямую в S3/MinIO. Режим можно явно задать как `proxy` или `presigned`.

Для внешнего туннеля укажите только его конкретный домен, не wildcard:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,example-tunnel.example
VITE_ALLOWED_HOSTS=localhost,127.0.0.1,example-tunnel.example
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:5173,https://example-tunnel.example
```

### Статический HTTPS-туннель

Для удалённого просмотра используется `https://learningplatform.ru.tuna.am`. Туннель должен направляться только на локальный `http://127.0.0.1:5173`: API и медиа остаются same-origin и проходят через Vite proxy по `/api`; порты API, PostgreSQL, Mailpit и MinIO наружу не публикуются. Укажите домен в `PUBLIC_APP_URL`, `VITE_ALLOWED_HOSTS`, `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS` без wildcard. `TRUSTED_PROXY_CIDRS` должен содержать только immediate proxy между клиентом и Django; Vite добавляет доверенную цепочку `X-Forwarded-For`. После изменения домена переотправьте ученику ссылку доступа, чтобы новая ссылка содержала актуальный публичный адрес.

В DEBUG оставьте `OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64` и `VITE_OFFLINE_LICENSE_PUBLIC_JWK` пустыми — Compose подставит development-пару. При `DJANGO_DEBUG=false` обязательно задайте собственные согласованные private PKCS8 PEM (base64) и public P-256 JWK.

## Кабинет вендора

1. Создайте platform admin и через `/backoffice/` создайте Vendor, подтверждённого пользователя и VendorMember с ролью `owner` или `editor`.
2. Войдите на `/vendor/` по email и паролю. Обычный owner/editor получает только vendor API и не имеет доступа к Django admin.
3. Создайте курс, модуль, урок и Markdown content unit. Публикация доступна только после опубликованного урока с валидным контентом.
4. Для image/audio/video используйте библиотеку медиа. В proxy mode кнопка «Загрузить новый файл» отправляет multipart через Django и показывает прогресс; в presigned mode сохраняется прямая загрузка через presigned POST. Asset можно прикрепить только после статуса `ready`.
5. Owner откройте блок «Ученики», выберите опубликованный курс, укажите email и выдайте доступ. Editor не видит и не может изменять members/enrollments.

## Кабинет ученика

1. После выдачи доступа письмо появляется в Mailpit: <http://localhost:8025>. Ссылка имеет не менее 256 бит случайности; в БД хранится только HMAC-хеш.
2. Откройте персональную ссылку `/app/#access=<token>`. Приложение создаёт на устройстве ECDSA P-256 ключ (IndexedDB `lms-device`), подписывает challenge и активирует устройство. Fragment удаляется до первого API-запроса и не попадает в серверные access logs.
3. Markdown, image, audio и video открываются через learner-scoped URL с `Cache-Control: private, no-store` и `Accept-Ranges: bytes`. В proxy mode URL остаётся same-origin; в presigned mode используется короткий signed URL. `object_key` в frontend не передаётся.
4. Нажмите «Отметить урок завершённым». Прогресс сохраняется на сервере.
5. Откройте ту же ссылку во втором browser context. Появится запрос «Перенести вход на это устройство»; после подтверждения `generation` доступа увеличивается, старое устройство получает `SESSION_REPLACED`, показывает «Сессия завершена» и выходит.
6. Приложение держит доступ на устройстве: heartbeat каждые 10 секунд, после удаления/замены приложения ссылка «Восстановить доступ» отправляет на почту `/app/#recovery=<token>`; восстановление подписывается тем же device key, ротирует доступ и активирует устройство заново.
7. Learner-сессия живёт `LEARNER_SESSION_AGE` (по умолчанию 30 дней); vendor/backoffice-сессия сохраняет общий восьмичасовой `SESSION_COOKIE_AGE`.

## Курсы и медиа

1. Войдите в `http://localhost:8000/backoffice/` как platform admin, создайте вендора, подтверждённого owner/editor и `VendorMember`.
2. В разделе «Обучение» создайте курс со статусом `draft`, затем модули, уроки и content units. Позиции автоматически остаются плотными.
3. В разделе «Media assets» нажмите «Загрузить медиа». Браузер получает короткую presigned POST policy, отправляет файл напрямую в приватный MinIO, а worker проверяет размер, SHA-256, magic bytes и ffprobe-метаданные. Используйте PNG/JPEG/WebP, MP3/M4A/AAC/OGG или MP4 (H.264 + AAC).
4. После статуса `ready` привяжите изображение, аудио или видео к content unit. Text unit должен содержать Markdown без raw HTML.
5. Отметьте хотя бы один урок опубликованным и используйте действие «Опубликовать выбранные курсы». Оно создаёт неизменяемый `CourseRevision`, увеличивает `offline_revision` и оставляет draft-дерево независимым.
6. Ссылка «Открыть опубликованную версию» в карточке курса показывает только сохранённый snapshot.

MinIO bucket не имеет anonymous policy. Не передавайте `object_key` во frontend: получить короткий URL просмотра можно только через авторизованный `GET /api/v1/media/{asset_id}/stream-url` текущего tenant. В итерации 1.2 это доступ backoffice; проверка learner Enrollment появится только в 1.3.

## Проверка tenant isolation

1. Войдите в `/backoffice/` как platform admin. Owner/editor должны быть перенаправлены на `/backoffice/login/`.
2. Создайте двух пользователей с разными email, паролем не короче 15 символов, `is_staff` и заполненным `email_verified_at`.
3. Создайте два вендора и по одному `VendorMember` с ролью `owner`, каждый для своего пользователя.
4. Выйдите и по очереди войдите каждым владельцем. Владелец видит только своего вендора, его участников и связанных пользователей.
5. Скопируйте URL объекта второго вендора и откройте из первой сессии: объект не должен отображаться.

## Проверка восстановления пароля

1. На странице входа выберите восстановление пароля и укажите email владельца.
2. Откройте письмо в Mailpit, перейдите по ссылке и задайте новый пароль не короче 15 символов.
3. Повторный переход по той же ссылке должен показать, что ссылка недействительна.
4. Для неизвестного email форма показывает тот же результат, но письмо не отправляет.

## Автоматические проверки

```powershell
docker compose run --rm api sh -c "ruff check . && ruff format --check . && mypy accounts vendors learning media_assets learner vendor_api config && python manage.py makemigrations --check --dry-run && pytest"
docker compose run --rm frontend sh -c "npm run lint && npm run typecheck && npm run test && npm run build"
```

Dependency audit: `pip-audit --requirement requirements.lock` и `npm audit --audit-level=high` должны быть чистыми; оба запускаются в CI вместе с backend/frontend job'ами.

E2E полностью создаёт курс и доступ через vendor cabinet и проверяет активацию устройства,
перенос доступа, завершение сессии, восстановление по email-ссылке и поведение после полной
очистки данных сайта (повторная активация = перенос). Второй конфиг
(`npm run test:e2e:pwa`) гоняет офлайн-сценарии против production-сборки приложения.
Запускайте на чистых volumes; bootstrap-команда намеренно откажется работать без `DEBUG`,
явного флага или на базе с другими данными:

```powershell
docker compose down --volumes --remove-orphans
docker compose up --build --detach --wait
docker compose exec -e E2E_BOOTSTRAP_ENABLED=true -e E2E_OWNER_EMAIL=owner.e2e@example.com -e E2E_OWNER_PASSWORD="unusual e2e password 48371" -e E2E_VENDOR_NAME="E2E Vendor" -e E2E_VENDOR_SLUG=e2e-vendor api python manage.py bootstrap_e2e_owner
docker run --rm -it --network host -v "${PWD}:/work" -w /work -e E2E_OWNER_EMAIL=owner.e2e@example.com -e E2E_OWNER_PASSWORD="unusual e2e password 48371" -e E2E_VENDOR_NAME="E2E Vendor" -e E2E_BASE_URL=http://localhost:5173 -e E2E_MAILPIT_URL=http://localhost:8025 mcr.microsoft.com/playwright:v1.55.0-noble sh -lc "npm ci && npx --no-install playwright test"
docker run --rm -it --network host -v "${PWD}:/work" -w /work mcr.microsoft.com/playwright:v1.55.0-noble sh -lc "npm ci && npx --no-install playwright test --config=playwright.pwa.config.ts"
```

## Безопасность

- **CSP**: страницы собираются с `script-src 'self' 'wasm-unsafe-eval'` (hash-wasm) и без `unsafe-inline`; API отдаёт `default-src 'none'; frame-ancestors 'none'`, backoffice — `frame-ancestors 'none'`. Заголовки выставляются Vite (dev/preview) и Django (API).
- **Cookies**: `__Host-sessionid`/`__Host-csrftoken` при `DJANGO_SECURE_COOKIES=true`, `HttpOnly`, `SameSite=Lax`.
- **CORS**: по умолчанию заголовки не отдаются вовсе; включаются только для origins из `DJANGO_CORS_ALLOWED_ORIGINS`. Preflight от чужих origins — 403.
- **Secrets в логах**: gunicorn access-формат без Referer/User-Agent; `RedactSecretsFilter` заменяет `[REDACTED]` в сообщениях S3-подписей, Bearer-токенов, access/recovery/reset-токенов и паролей. Токены доступа живут только во fragment URL и не попадают в access logs.
- **Referrer**: приложение переключается на `no-referrer`, пока токен виден в URL; глобально `strict-origin-when-cross-origin`.
- **Rate limits** (Redis-бэкенд, считаются на IP и/или email):

| Эндпоинт | Лимит | Период |
| --- | --- | --- |
| Vendor login / password-reset | 10 на IP+email | 15 мин |
| Recovery request | 5 на IP; 3 на hash(email) | 1 час |
| Access inspect/exchange | 20 на IP | 1 мин |
| Heartbeat | 1 | 5 сек |
| Медиа stream-url/content | 120 на активную сессию | 1 мин |

Все значения переопределяются через `*_RATE_LIMIT`/`*_RATE_WINDOW_SECONDS` переменные (см. `compose.yaml`).

- **Остальное**: HSTS (1 год, включая subdomains) при `DJANGO_DEBUG=false`, nosniff, `X-Frame-Options: DENY`, CSRF-token обязателен для всех POST, ORM без raw SQL, UUID primary keys, tenant-фильтры на сервере, offline-лицензии подписаны EC P-256.

### Документация

- `docs/operations/backup-restore.md` — pg_dump/MinIO mirror и проверяемый restore drill;
- `docs/deployment.md` — production compose + nginx (TLS, HSTS, проксирование медиа и API);
- `docs/manual-testing-android-ios.md` — ручной чек-лист PWA на реальных устройствах;
- `docs/adr/0001-single-device-learner-access.md` — решение о привязке доступа к устройству.

## Ограничения

- Офлайн-пакеты работают только внутри установленной PWA: AES-GCM chunks хранятся в OPFS/IndexedDB и требуют действующую offline license (`OFFLINE_LICENSE_TTL_HOURS`, по умолчанию 24 часа; без сети через сутки курсы требуют подключения). Это не абсолютная DRM-защита.
- После первого открытия `/app/` обновите страницу один раз, чтобы Service Worker начал контролировать приложение. Интерфейс покажет «Офлайн-функции готовы» после активации.
- В локальном Docker Service Worker включён через `VITE_ENABLE_SERVICE_WORKER=true`; для production используется стандартный `import.meta.env.PROD`.
- Learner session использует серверную Django session cookie; доступ привязан к устройству: вторая активация по той же ссылке требует подтверждения переноса и завершает сессию первого устройства (`SESSION_REPLACED`). `device_id`, User-Agent и IP не используются как фактор блокировки; очистка данных сайта приводит к повторной активации как переносу (критерий 17).
- E2E bootstrap доступен только при `DEBUG=true` и `E2E_BOOTSTRAP_ENABLED=true`; используйте его только на одноразовой чистой базе.
- Rate limits считаются per-instance: при нескольких репликах Django окна пересчитываются каждой нодой независимо.
- MFA для владельцев относится к итерации 1.6 и обязательна перед реальными продажами.
- Локальные примеры секретов нельзя использовать в production.
