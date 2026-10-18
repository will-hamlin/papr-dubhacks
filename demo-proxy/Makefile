PY ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000
# Local-only default. Set a real PROXY_SHARED_SECRET (shared with the demo site and engine) anywhere else.
export PROXY_SHARED_SECRET ?= dev-only-secret
# Bearer token the employee dashboard sends (paste it into the dashboard's Connection settings).
export PROXY_API_TOKEN ?= dev-only-token
USER_ID ?= u_jordan

# Linked stack: agent-purchase-verifier on :8001 (scripts/run_pbapo.py).
export ENGINE_URL ?=
export ENGINE_KIND ?= auto
export VP_AGENT_KEY ?= vpk_pbapo_dev_only
export VP_PROXY_MODE ?= supervised

.PHONY: dev dev-linked test install token reset clean

$(BIN)/uvicorn: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@touch $@

install: $(BIN)/uvicorn

# Stub engine unless ENGINE_URL is set; rule parser unless an Anthropic credential is set (see SPEC_PARSER).
dev: install
	$(BIN)/uvicorn --factory proxy.app:create_app --reload --port $(PORT)

# Forward accepted orders to the verified-purchase Agent API bridge on :8001.
dev-linked: install
	ENGINE_URL=http://127.0.0.1:8001 ENGINE_KIND=agent_v1 \
	VP_AGENT_KEY=$(VP_AGENT_KEY) VP_PROXY_MODE=$(VP_PROXY_MODE) \
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
