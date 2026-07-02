"""Root agent definition for the web runtime.

We reuse `build_root_agent()` from main.py so there is a SINGLE source of truth
for the multi-agent tree. That means the web server automatically inherits:

  * the Router → Cycle Expert / Safety Guard delegation (multi-agent),
  * the skills tools + the local MCP toolset (McpToolset over stdio),
  * the security callbacks — PII redaction (before_model) and the medical
    disclaimer (after_model).

Nothing here is web-specific; the terminal app (main.py) is untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root (where main.py lives) is importable when ADK loads
# this package from an arbitrary working directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from main import build_root_agent  # noqa: E402

# ADK's agent loader looks for this exact symbol.
root_agent = build_root_agent()
