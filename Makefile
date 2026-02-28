build:
	docker compose build
up:
	docker compose up
down:
	docker compose down --remove-orphans
up-bg:  # bg stands for background
	docker compose up -d

makemigrations:
	docker compose run --rm api python manage.py makemigrations
migrate:
	docker compose run --rm api python manage.py migrate

restart-api:
	docker compose restart api

pytest: export API_ENV_FILE := config/test.env
pytest:
	docker compose run --rm api python -m pytest

pytest-search: export API_ENV_FILE := config/test.env
pytest-search:
	docker compose run --rm api python -m pytest apps/search/tests/ -v

coverage: export API_ENV_FILE := config/test.env
coverage:
	docker compose run --rm api python -m pytest --cov=apps --cov=config --cov-report=term-missing --cov-fail-under=50
shell:
	docker compose run --rm api python manage.py shell_plus
bash:
	docker compose run --rm api bash

# Meilisearch: create indexes and sync from DB (run after first deploy or when index_not_found)
setup-search-indexes:
	docker compose run --rm api python manage.py setup_search_indexes
sync-search-index:
	@echo "Usage: make sync-search-index INDEX=item-parts (or item-images, scribes, hands, graphs)"
	docker compose run --rm api python manage.py sync_search_index $(INDEX)
sync-all-search-indexes:
	docker compose run --rm api python manage.py sync_all_search_indexes

clean:
	uvx ruff check --fix .
celery_status:
	docker compose run --rm api celery -A config inspect active
