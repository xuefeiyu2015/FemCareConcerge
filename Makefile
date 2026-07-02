# FemCare Concierge — developer experience (DX) commands.
# Usage: `make install`, `make run`, `make clean`, `make distclean`.

PYTHON ?= python3
VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help install run clean distclean

help:
	@echo "FemCare Concierge — available commands:"
	@echo "  make install    Check python3, create $(VENV) if missing, install requirements"
	@echo "  make run        Verify GOOGLE_API_KEY, then launch the Web Dev-UI + MCP server"
	@echo "  make clean      Wipe caches + reset user_data.json to cold start (keeps $(VENV))"
	@echo "  make distclean  Everything in clean, plus remove $(VENV)"

install:
	@command -v $(PYTHON) >/dev/null 2>&1 || { echo "❌ python3 not found. Please install Python 3."; exit 1; }
	@test -d $(VENV) || { echo "🐍 Creating virtual environment in $(VENV)..."; $(PYTHON) -m venv $(VENV); }
	@echo "📦 Installing dependencies from requirements.txt..."
	@$(PIP) install --upgrade pip >/dev/null
	@$(PIP) install -r requirements.txt
	@echo "✅ Install complete. Add your key to .env, then run 'make run'."

run:
	@test -d $(VENV) || { echo "❌ No $(VENV) found. Run 'make install' first."; exit 1; }
	@if [ -n "$$GOOGLE_API_KEY" ] || grep -qsE '^GOOGLE_API_KEY=.+' .env; then \
		echo "🌸 Starting FemCare web runtime → http://localhost:8000/dev-ui/  (app: femcare_agent)"; \
		echo "   (the local MCP server is spawned automatically by the agent)"; \
		$(PY) app.py; \
	else \
		echo "⚠️  GOOGLE_API_KEY is not set — the live agent needs it."; \
		echo "   1) cp .env.example .env"; \
		echo "   2) Add:  GOOGLE_API_KEY=your_key   (get one at https://aistudio.google.com/apikey)"; \
		echo "   3) Re-run:  make run"; \
		exit 1; \
	fi

clean:
	@echo "🧹 Removing Python caches..."
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@echo "🔄 Resetting user_data.json to a cold-start state (backup → user_data.json.bak)..."
	@if [ -f user_data.json ]; then cp user_data.json user_data.json.bak; fi
	@$(PYTHON) -c "import json, os; f='user_data.json'; d=json.load(open(f)) if os.path.exists(f) else {'profile': {}}; d['period_history']=[]; json.dump(d, open(f,'w'), indent=2, ensure_ascii=False)"
	@echo "✅ Clean done. $(VENV) kept for fast re-testing of the Cold Start flow."

distclean: clean
	@echo "🗑  Removing $(VENV) for a full workspace wipe..."
	@rm -rf $(VENV)
	@echo "✅ Distclean complete."
