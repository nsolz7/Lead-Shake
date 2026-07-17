.PHONY: up down logs test seed backup

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

test:
	docker compose run --rm api pytest

seed:
	docker compose exec api python -m app.seed

backup:
	docker compose --profile maintenance run --rm backup
