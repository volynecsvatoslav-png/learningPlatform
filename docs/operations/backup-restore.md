# Backup/Restore Runbook

Резервная копия платформы = PostgreSQL (вся бизнес-логика) + MinIO/S3 (загруженные медиа) + `.env` (секреты, которые иначе не восстановить). Redis и приложение не содержат долгоживущих данных: сессии — временные, кэш — инвалидируется.

## Что должно быть в бэкапе

| Данные | Где | Как бэкапится |
| --- | --- | --- |
| БД (пользователи, вендоры, курсы, enrollments, устройства, сессии, аудит) | контейнер `postgres` | `pg_dump` |
| Медиа (изображения, аудио, видео) | bucket `learning-platform` в MinIO/S3 | `mc mirror` (MinIO) или snapshot bucket (S3) |
| Секреты | `.env` / секрет-менеджер | отдельно, вне репозитория |
| Offline license key pair | `OFFLINE_LICENSE_SIGNING_PRIVATE_KEY_B64` + `VITE_OFFLINE_LICENSE_PUBLIC_JWK` | в `.env`/секрет-менеджере |

`pg_dump` делает консистентный снимок на момент запуска; медиа-файлы снимаются отдельно. Медиа-объекты immutable (каждая загрузка — новый ключ), поэтому рассинхронизация моментов не ломает целостность: БД ссылается только на существующие ключи, либо отсутствующий объект проявится как 404 и легко обнаружится проверкой ниже.

## Ежедневный бэкап

```powershell
# PostgreSQL: plain dump (или --format=custom для pg_restore --jobs)
docker compose exec -T postgres pg_dump -U learning --format=custom --no-owner --file=/tmp/learning.dump learning
docker compose cp postgres:/tmp/learning.dump ".\backups\learning-$(Get-Date -Format yyyyMMdd-HHmmss).dump"

# MinIO: зеркало bucket (ключами из .env)
docker run --rm -e MC_HOST_local="http://minio-local:minio-local-secret@host.docker.internal:9000" minio/mc mc mirror --overwrite --remove local/learning-platform ".\backups\media"
```

Хранение снимков: минимум 14 суток, ротация внешними средствами (например, `Backblaze B2`, `rclone` к холодному хранилищу или задание в scheduler). Хотя бы одна копия — вне хоста.

## Проверка (restore drill, обязателен перед production и при приёмке)

Восстановление всегда проверяется в отдельном контейнере, не поверх живого `postgres`:

```powershell
docker run --rm -d --name learning-restore-check -e POSTGRES_DB=learning -e POSTGRES_USER=learning -e POSTGRES_PASSWORD=learning -p 127.0.0.1:5433:5432 postgres:17-alpine

# вернуть в контейнер
docker cp ".\backups\learning-latest.dump" learning-restore-check:/tmp/learning.dump
docker exec learning-restore-check pg_restore -U learning -d learning --no-owner --jobs=4 /tmp/learning.dump
docker exec learning-restore-check psql -U learning -d learning -c "select count(*) from accounts_user; select count(*) from learner_enrollment; select count(*) from learning_course;"

docker stop learning-restore-check && docker rm learning-restore-check
```

Проверка: счётчики ключевых таблиц не нулевые и совпадают с ожидаемым состоянием на дату снимка.

## Восстановление на рабочий стек

1. Остановите `api`/`worker`, чтобы не было пишущих подключений: `docker compose stop api worker`.
2. Восстановите дамп в текущую БД (заменив данные): `docker exec -i postgres pg_restore -U learning -d learning --clean --if-exists --no-owner < ".\backups\learning-latest.dump"` (вариант: `--create` на свежий cluster).
3. Восстановите медиа: `mc mirror --overwrite --remove ".\backups\media" local/learning-platform`.
4. Запустите стек: `docker compose up -d --wait`.
5. Санити-чек: `Invoke-WebRequest http://localhost:8000/health/`, вход владельца, открытие курса с видео.

## Что не бэкапится (и почему это ок)

- IndexedDB/OPFS на устройствах учеников — это per-device кэш; после очистки аккаунт восстанавливается по ссылке «Восстановить доступ» (устройство заново активируется через email).
- Redis — heartbeat/rate-limit счётчики и celery results; после потери лимиты просто отсчитываются заново.
- Локальные файлы `apps/web/dist`, `apps/api/staticfiles` — артефакты сборки, воспроизводятся из кода.
- Дамп содержит пароли в виде argon2-хешей и HMAC-хеши токенов доступа — храните дампы как секрет, с тем же уровнем доступа, что и `.env`.
