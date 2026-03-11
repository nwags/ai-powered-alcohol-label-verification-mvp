.PHONY: up down build rebuild logs shell test test-ocr test-health coverage

up:
	docker compose up

down:
	docker compose down

build:
	docker compose build

rebuild:
	docker compose down
	docker compose build --no-cache
	docker compose up

logs:
	docker compose logs -f web

shell:
	docker compose exec -w /app web sh

test:
	docker compose exec -w /app web sh -lc 'PYTHONPATH=/app python -m pytest -q'

test-ocr:
	docker compose exec -w /app web sh -lc 'PYTHONPATH=/app python -m pytest tests/test_ocr_service.py -vv -s'

test-health:
	docker compose exec -w /app web sh -lc 'PYTHONPATH=/app python -m pytest tests/test_health.py -vv -s'

coverage:
	docker compose exec -w /app web sh -lc 'mkdir -p runtime/coverage/html && PYTHONPATH=/app python -m pytest -q --cov=app --cov-report=term-missing --cov-report=html:runtime/coverage/html --cov-report=json:runtime/coverage/coverage.json'
