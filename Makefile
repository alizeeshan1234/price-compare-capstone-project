.PHONY: install dev run demo test eval alerts docker

install:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

dev:
	.venv/bin/uvicorn app.main:app --reload --port 8000

run:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

demo:
	MOCK_STORES=1 .venv/bin/uvicorn app.main:app --port 8000

test:
	.venv/bin/pytest -q

eval:
	.venv/bin/python -m evaluation.evaluate

alerts:
	.venv/bin/python -m app.alerts

docker:
	docker compose up --build
