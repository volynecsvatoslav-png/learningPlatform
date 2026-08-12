.PHONY: up down logs check test

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs --follow

check:
	docker compose run --rm api sh -c "ruff check . && ruff format --check . && mypy accounts vendors config && python manage.py makemigrations --check --dry-run"
	docker compose run --rm frontend sh -c "npm run lint && npm run typecheck && npm run test && npm run build"

test:
	docker compose run --rm api pytest
