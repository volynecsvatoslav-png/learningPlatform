# Learning Platform

Лёгкая многовендорная обучающая платформа. Реализованы итерации 1.1–1.3: platform backoffice, отдельный vendor cabinet, выдача доступов без оплаты, learner cabinet с одноустройственной серверной сессией, публикации и приватные медиа в MinIO.

## Требования

- Docker Desktop с Compose v2;
- свободные порты `5173`, `8000`, `8025`, `9000`, `9001`, `5432`.

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

## Кабинет вендора

1. Создайте platform admin и через `/backoffice/` создайте Vendor, подтверждённого пользователя и VendorMember с ролью `owner` или `editor`.
2. Войдите на `/vendor/` по email и паролю. Обычный owner/editor получает только vendor API и не имеет доступа к Django admin.
3. Создайте курс, модуль, урок и Markdown content unit. Публикация доступна только после опубликованного урока с валидным контентом.
4. Для image/audio/video используйте библиотеку медиа. В proxy mode кнопка «Загрузить новый файл» отправляет multipart через Django и показывает прогресс; в presigned mode сохраняется прямая загрузка через presigned POST. Asset можно прикрепить только после статуса `ready`.
5. Owner откройте блок «Ученики», выберите опубликованный курс, укажите email и выдайте доступ. Editor не видит и не может изменять members/enrollments.

## Кабинет ученика

1. После выдачи доступа письмо появляется в Mailpit: <http://localhost:8025>. Ссылка имеет не менее 256 бит случайности; в БД хранится только HMAC-хеш.
2. Откройте ссылку в `/app/access/<token>`, подтвердите вход и просматривайте только выданный опубликованный snapshot курса.
3. Markdown, image, audio и video открываются через learner-scoped URL с `Cache-Control: private, no-store` и `Accept-Ranges: bytes`. В proxy mode URL остаётся same-origin; в presigned mode используется короткий signed URL. `object_key` в frontend не передаётся.
4. Нажмите «Отметить урок завершённым». Прогресс сохраняется на сервере.
5. Откройте ту же ссылку во втором browser context. Первая сессия при следующем API-запросе получает `SESSION_REVOKED` и показывает «Сессия открыта на другом устройстве»; второй context продолжает работать.

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

E2E полностью создаёт курс и доступ через vendor cabinet. Запускайте его на чистых volumes;
bootstrap-команда намеренно откажется работать без `DEBUG`, явного флага или на базе с другими
данными:

```powershell
docker compose down --volumes --remove-orphans
docker compose up --build --detach --wait
docker compose exec -e E2E_BOOTSTRAP_ENABLED=true -e E2E_OWNER_EMAIL=owner.e2e@example.com -e E2E_OWNER_PASSWORD="unusual e2e password 48371" -e E2E_VENDOR_NAME="E2E Vendor" -e E2E_VENDOR_SLUG=e2e-vendor api python manage.py bootstrap_e2e_owner
docker run --rm -it --network host -v "${PWD}:/work" -w /work -e E2E_OWNER_EMAIL=owner.e2e@example.com -e E2E_OWNER_PASSWORD="unusual e2e password 48371" -e E2E_VENDOR_NAME="E2E Vendor" -e E2E_BASE_URL=http://localhost:5173 -e E2E_MAILPIT_URL=http://localhost:8025 mcr.microsoft.com/playwright:v1.55.0-noble sh -lc "npm ci && npx --no-install playwright test"
```

## Ограничения

- PWA manifest и базовый service worker подготовлены, но скачивание курса и полноценный offline-режим не реализованы.
- Learner session использует серверную Django session cookie; `device_id`, User-Agent и IP не используются как фактор блокировки.
- E2E bootstrap доступен только при `DEBUG=true` и `E2E_BOOTSTRAP_ENABLED=true`; используйте его только на одноразовой чистой базе.
- Rate limits, полный CSP/CORS hardening, production deployment и MFA относятся к итерации 1.5. MFA обязательно перед реальными продажами.
- Локальные примеры секретов нельзя использовать в production.
