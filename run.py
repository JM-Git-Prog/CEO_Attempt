"""Run The Living Room web server. Usage: python run.py   (V17_PORT=8001 python run.py for a second instance)"""
import os

import uvicorn

if __name__ == "__main__":
    # reload MUST stay False. With reload=True, any edit under src/ triggers a
    # StatReload graceful shutdown that WEDGES on open SSE streams
    # (GET /api/v2/session/{id}/stream never close), leaving the port listening
    # but the server unreachable. See wiki ops/v2-server-8000. To pick up code
    # changes, restart the server manually.
    # V17_PORT (2026-09-10): the Sam Loop runs its own instance on :8001 so its
    # restarts never touch John's :8000. Default unchanged.
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=int(os.getenv("V17_PORT", "8000")),
        reload=False,
    )
