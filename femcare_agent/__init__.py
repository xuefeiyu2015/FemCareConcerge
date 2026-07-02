"""FemCare Concierge — ADK agent package (discovered by the web/api runtime).

ADK's `adk web` / `get_fast_api_app` scan for agent packages and load the
`root_agent` symbol. This package intentionally contains no new logic: it simply
re-exposes the exact agent tree defined in main.py.
"""

from . import agent  # noqa: F401  (ADK looks up agent.root_agent)
