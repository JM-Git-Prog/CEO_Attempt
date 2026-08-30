"""Run The Living Room web server. Usage: python run.py"""
import uvicorn

if __name__ == "__main__":
    # reload MUST stay False. With reload=True, any edit under src/ triggers a
    # StatReload graceful shutdown that WEDGES on open SSE streams
    # (GET /api/v2/session/{id}/stream never close), leaving the port listening
    # but the server unreachable. See wiki ops/v2-server-8000. To pick up code
    # changes, restart the server manually.
    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
