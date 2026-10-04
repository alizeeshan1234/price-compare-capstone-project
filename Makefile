.PHONY: install run dev test seed demo docker

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

run:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	.venv/bin/uvicorn app.main:app --reload --port 8000

test:
	.venv/bin/pytest -q

seed:
	.venv/bin/python scripts/seed_demo.py

demo: seed
	MOCK_SCRAPER=1 CHECK_INTERVAL_MINUTES=1 .venv/bin/uvicorn app.main:app --port 8000

docker:
	docker compose up --build
