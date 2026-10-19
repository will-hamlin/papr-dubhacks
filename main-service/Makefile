PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8001
export PROXY_SHARED_SECRET ?= dev-only-secret
export SPEC_PARSER ?= rules
export ENGINE_URL ?=
export ENGINE_KIND ?= auto
export VP_AGENT_KEY ?= vpk_pbapo_dev_only
export VP_PROXY_MODE ?= supervised

.PHONY: install dev dev-linked test

$(BIN)/uvicorn: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@touch $@

install: $(BIN)/uvicorn

dev: install
	$(BIN)/uvicorn --factory main_service.app:create_app --host 127.0.0.1 --port $(PORT) --workers 1

dev-linked: install
	ENGINE_URL=$${ENGINE_URL:-http://127.0.0.1:8002} ENGINE_KIND=agent_v1 \
	$(BIN)/uvicorn --factory main_service.app:create_app --host 127.0.0.1 --port $(PORT) --workers 1

test: install
	$(BIN)/pytest -c ../pytest.ini tests -q
