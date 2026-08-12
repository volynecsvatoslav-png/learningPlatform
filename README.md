# Learning Platform

Фундамент лёгкой многовендорной обучающей платформы. Реализован объём итерации 1.1: Django backoffice, tenant-модель, вход и восстановление пароля, React skeleton и локальная инфраструктура.

## Требования

- Docker Desktop с Compose v2;
- свободные порты `5173`, `8000`, `8025`, `9000`, `9001`, `5432`, `6379`.

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
docker compose run --rm api sh -c "ruff check . && ruff format --check . && mypy accounts vendors config && python manage.py makemigrations --check --dry-run && pytest"
docker compose run --rm frontend sh -c "npm run lint && npm run typecheck && npm run test && npm run build"
```

## Ограничения итерации 1.1

- Курсы, медиа, ученики, access links, PWA и offline-механизм относятся к следующим итерациям и отсутствуют.
- MinIO и Celery worker подняты как фундамент; прикладные media-задачи появятся в итерации 1.2.
- Rate limits, полный CSP/CORS hardening, production deployment и MFA относятся к итерации 1.5. MFA обязательно перед реальными продажами.
- Локальные примеры секретов нельзя использовать в production.
