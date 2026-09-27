install:
	python -m pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .

format-check:
	ruff format --check .

db-upgrade:
	hl db upgrade

run-api:
	uvicorn hiringleads.api.main:app --host 0.0.0.0 --port 8000

run-worker:
	python -m hiringleads.worker

compose:
	docker compose up --build
