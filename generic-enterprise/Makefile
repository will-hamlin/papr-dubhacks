PY ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000

.PHONY: dev test install reset clean

$(BIN)/uvicorn: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@touch $@

install: $(BIN)/uvicorn

# Fake agent unless AGENT_URL is set (then PROXY_SHARED_SECRET is required).
dev: install
	PROXY_PUBLIC_URL=$${PROXY_PUBLIC_URL:-http://localhost:$(PORT)} \
	$(BIN)/uvicorn --factory proxy.app:create_app --reload --port $(PORT)

test: install
	$(BIN)/pytest -q

# Wipe runtime state: live spend, audit log, outbox. Data files are untouched.
reset:
	rm -rf var

clean: reset
	rm -rf $(VENV) .pytest_cache
