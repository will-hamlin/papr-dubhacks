PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000
# Local-only default. Set a real PROXY_SHARED_SECRET (shared with MS) anywhere else.
export PROXY_SHARED_SECRET ?= dev-only-secret
# Bearer token the employee dashboard sends (paste it into the dashboard's Connection settings).
export PROXY_API_TOKEN ?= dev-only-token
USER_ID ?= u_jordan

export MAIN_SERVICE_URL ?= http://127.0.0.1:8001

.PHONY: dev dev-linked test install token reset clean

$(BIN)/uvicorn: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	@touch $@

install: $(BIN)/uvicorn

# Run MS separately on the same host; both authorization outcomes are handed off to it.
dev: install
	$(BIN)/uvicorn --factory proxy.app:create_app --reload --host 127.0.0.1 --port $(PORT)

dev-linked: dev

test: install
	$(BIN)/pytest -q

# Print a signed auth object for USER_ID (what the demo site sends in "auth").
token: install
	@$(BIN)/python -m proxy.signing $(USER_ID)

# Reset legacy spend, audit and pending handoffs. Preserve account credentials, policies and account spend.
reset:
	rm -f var/spend.json var/audit.jsonl var/outbox.sqlite3

clean: reset
	rm -rf $(VENV) .pytest_cache
