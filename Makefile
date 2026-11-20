PY ?= .venv/bin/python
BIN = $(dir $(PY))

.PHONY: install lint type test check demo dashboard serve docker clean

install:
	python3.11 -m venv .venv
	.venv/bin/pip install -q -e ".[dev]"

lint:
	$(BIN)ruff check .
	$(BIN)ruff format --check .

type:
	$(BIN)mypy

test:
	$(BIN)pytest -q

check: lint type test

demo:  ## end-to-end SYNTHETIC simulation with a fake WhatsApp API server
	$(PY) -m speed_to_lead demo

dashboard:  ## anonymised dashboard from REAL data only -> site/index.html
	$(PY) -m speed_to_lead dashboard --out site/index.html --json site/metrics.json

serve:
	$(PY) -m speed_to_lead serve --port 8000

docker:
	docker build -t speed-to-lead .

clean:
	rm -rf demo_output .pytest_cache .mypy_cache .ruff_cache
