build:
	docker compose build
up:
	docker compose up
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
shell:
	docker compose run --rm api python manage.py shell_plus
bash:
	docker compose run --rm api bash
update_index:
	docker compose run --rm api python manage.py update_index
clear_index:
	docker compose run --rm api python manage.py clear_index --noinput
rebuild_index: clear_index update_index
clean:
	uvx ruff check --fix .
celery_status:
	docker compose run --rm api celery -A config inspect active
