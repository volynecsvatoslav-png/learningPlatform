# Learning Platform

Лёгкая многовендорная обучающая платформа. Реализованы итерации 1.1 и 1.2: tenant-backoffice, вход и восстановление пароля, курсы, публикации и приватные медиа в MinIO.

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
- backoffice: <http://localhost:8000/backoffice/>;
- healthcheck API: <http://localhost:8000/health/>;
- Mailpit: <http://localhost:8025>;
- MinIO console: <http://localhost:9001>.

Миграции применяются контейнером API автоматически. Bucket MinIO создаётся приватным сервисом `minio-init`.

## Курсы и медиа

1. Войдите в `http://localhost:5173/backoffice/` как platform admin, создайте вендора, подтверждённого owner/editor и `VendorMember`.
2. В разделе «Обучение» создайте курс со статусом `draft`, затем модули, уроки и content units. Позиции автоматически остаются плотными.
3. В разделе «Media assets» нажмите «Загрузить медиа». Браузер получает короткую presigned POST policy, отправляет файл напрямую в приватный MinIO, а worker проверяет размер, SHA-256, magic bytes и ffprobe-метаданные. Используйте PNG/JPEG/WebP, MP3/M4A/AAC/OGG или MP4 (H.264 + AAC).
4. После статуса `ready` привяжите изображение, аудио или видео к content unit. Text unit должен содержать Markdown без raw HTML.
5. Отметьте хотя бы один урок опубликованным и используйте действие «Опубликовать выбранные курсы». Оно создаёт неизменяемый `CourseRevision`, увеличивает `offline_revision` и оставляет draft-дерево независимым.
6. Ссылка «Открыть опубликованную версию» в карточке курса показывает только сохранённый snapshot.

MinIO bucket не имеет anonymous policy. Не передавайте `object_key` во frontend: получить короткий URL просмотра можно только через авторизованный `GET /api/v1/media/{asset_id}/stream-url` текущего tenant. В итерации 1.2 это доступ backoffice; проверка learner Enrollment появится только в 1.3.

## Проверка tenant isolation

1. Войдите в `/backoffice/` как platform admin.
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
docker compose run --rm api sh -c "ruff check . && ruff format --check . && mypy accounts vendors learning media_assets config && python manage.py makemigrations --check --dry-run && pytest"
docker compose run --rm frontend sh -c "npm run lint && npm run typecheck && npm run test && npm run build"
```

## Ограничения

- Ученики, access links, Enrollment, PWA и offline-механизм относятся к итерациям 1.3-1.4 и отсутствуют.
- Admin preview отображает опубликованный снимок, но learner-facing course API появится в итерации 1.3.
- Rate limits, полный CSP/CORS hardening, production deployment и MFA относятся к итерации 1.5. MFA обязательно перед реальными продажами.
- Локальные примеры секретов нельзя использовать в production.
