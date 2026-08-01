"""Live trace middleware — streams all V16 API requests, responses, and errors to a log file.

Append-only JSONL at output/live_trace.jsonl. Each entry has:
- timestamp, method, path, status, elapsed_ms, request_body (truncated), response_body (truncated), error

Usage: Add the middleware to the FastAPI app via `install_live_trace(app)`.
Read the trace with: `python -m src.web.live_trace` (tails the file).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import StreamingResponse

TRACE_PATH = Path(os.getenv("TRACE_PATH", "output/live_trace.jsonl"))
MAX_BODY = 2000  # truncate bodies to keep entries readable


def _truncate(text: str, limit: int = MAX_BODY) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _write_entry(entry: dict) -> None:
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")


class LiveTraceMiddleware(BaseHTTPMiddleware):
    """Logs every request/response to a JSONL file for live observability."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.time()
        path = request.url.path
        method = request.method
        query = str(request.url.query) if request.url.query else ""

        # Read request body (only for POST/PUT)
        request_body = ""
        if method in ("POST", "PUT", "PATCH"):
            try:
                raw = await request.body()
                request_body = _truncate(raw.decode("utf-8", errors="replace"))
            except Exception:
                request_body = "<unreadable>"

        entry = {
            "ts": time.strftime("%H:%M:%S"),
            "method": method,
            "path": path,
            "query": query,
            "request_body": request_body,
            "status": 0,
            "elapsed_ms": 0,
            "response_body": "",
            "error": "",
        }

        try:
            response = await call_next(request)
            elapsed = (time.time() - start) * 1000
            entry["status"] = response.status_code
            entry["elapsed_ms"] = round(elapsed, 1)

            # Capture response body for JSON responses (not streaming/files)
            content_type = response.headers.get("content-type", "")
            if "json" in content_type and not isinstance(response, StreamingResponse):
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
                entry["response_body"] = _truncate(body_bytes.decode("utf-8", errors="replace"))
                # Rebuild response since we consumed the iterator
                response = Response(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            elif "event-stream" in content_type:
                entry["response_body"] = "<SSE stream>"
            elif "octet" in content_type or "image" in content_type or "gltf" in content_type:
                entry["response_body"] = f"<binary {content_type}>"

            _write_entry(entry)
            return response

        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            entry["elapsed_ms"] = round(elapsed, 1)
            entry["status"] = 500
            entry["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}"
            _write_entry(entry)
            raise


def install_live_trace(app: FastAPI) -> None:
    """Install the live trace middleware on the FastAPI app."""
    app.add_middleware(LiveTraceMiddleware)
    print(f"[live_trace] Writing to {TRACE_PATH.resolve()}")


# --- CLI tail mode ---
if __name__ == "__main__":
    """Tail the trace file for live watching."""
    path = TRACE_PATH
    if not path.exists():
        print(f"Waiting for {path}...")
        while not path.exists():
            time.sleep(0.5)

    print(f"=== Tailing {path} ===\n")
    with path.open("r", encoding="utf-8") as f:
        # Seek to end
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                try:
                    entry = json.loads(line)
                    status = entry.get("status", "?")
                    symbol = "✓" if 200 <= status < 400 else "✗" if status >= 400 else "→"
                    elapsed = entry.get("elapsed_ms", 0)
                    print(f"  {entry['ts']} {symbol} {entry['method']:4s} {entry['path']}"
                          f"  [{status}] {elapsed:.0f}ms")
                    if entry.get("request_body"):
                        print(f"           req: {entry['request_body'][:120]}")
                    if entry.get("response_body") and entry["response_body"] not in ("<SSE stream>",):
                        print(f"           res: {entry['response_body'][:200]}")
                    if entry.get("error"):
                        print(f"           ERR: {entry['error'][:200]}")
                    print()
                except json.JSONDecodeError:
                    print(line.strip())
            else:
                time.sleep(0.3)
