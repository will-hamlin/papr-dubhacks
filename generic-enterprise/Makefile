PY ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000
# Local-only default. Set a real PROXY_SHARED_SECRET (shared with the demo site and engine) anywhere else.
export PROXY_SHARED_SECRET ?= dev-only-secret
USER_ID ?= u_jordan

.PHONY: dev test install token reset clean

$(BIN)/uvicorn: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@touch $@

install: $(BIN)/uvicorn

# Stub engine unless ENGINE_URL is set; rule parser unless an Anthropic credential is set (see SPEC_PARSER).
dev: install
	$(BIN)/uvicorn --factory proxy.app:create_app --reload --port $(PORT)

test: install
	$(BIN)/pytest -q

# Print a signed auth object for USER_ID (what the demo site sends in "auth").
token: install
	@$(BIN)/python -m proxy.signing $(USER_ID)

# Wipe runtime state: spend counters and audit log. Data files are untouched.
reset:
	rm -rf var

clean: reset
	rm -rf $(VENV) .pytest_cache
