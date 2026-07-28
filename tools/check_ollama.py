"""Ask Ollama directly, outside the pipeline, and print exactly what it says.

Every generation is currently failing with an HTTP 200 whose body contains no
completion at all - done_reason, eval_count and total_duration are all absent,
which a real Ollama completion never omits. That means the body is something
else entirely, and the pipeline can only report "empty". This talks to Ollama
with no wrapper in the way and prints the verbatim response.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("LLM_MODEL", "llama3.1")


def get(path: str):
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}{path}", timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:800]
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def post(path: str, payload: dict, timeout: int = 120):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:800]
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print(f"OLLAMA_URL = {OLLAMA_URL}")
    print(f"LLM_MODEL  = {MODEL}\n")

    status, body = get("/api/tags")
    print(f"[installed models]  HTTP {status}")
    if isinstance(body, dict):
        names = [m.get("name") for m in body.get("models", [])]
        print("  " + (", ".join(names) if names else "(none installed)"))
        if MODEL not in names and not any((n or "").startswith(MODEL) for n in names):
            print(f"  *** {MODEL} IS NOT IN THIS LIST - that alone would explain the failures")
    else:
        print(f"  {body}")

    status, body = get("/api/ps")
    print(f"\n[loaded right now]  HTTP {status}")
    if isinstance(body, dict):
        loaded = body.get("models", [])
        if not loaded:
            print("  (nothing loaded)")
        for m in loaded:
            size_gb = (m.get("size") or 0) / 1e9
            vram_gb = (m.get("size_vram") or 0) / 1e9
            print(f"  {m.get('name')}  size={size_gb:.1f}GB  vram={vram_gb:.1f}GB "
                  f"expires={m.get('expires_at')}")
    else:
        print(f"  {body}")

    print("\n[tiny chat request - the exact shape the pipeline sends]")
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": 'Reply with only {"ok":true}'}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.15, "num_predict": 8192, "num_ctx": 16384},
    }
    status, body = post("/api/chat", payload)
    print(f"  HTTP {status}")
    print(f"  {json.dumps(body)[:900] if isinstance(body, dict) else body}")

    if isinstance(body, dict):
        content = (body.get("message") or {}).get("content") or ""
        if body.get("error"):
            print(f"\n  >>> OLLAMA REPORTED AN ERROR: {body['error']}")
        elif not content.strip():
            print("\n  >>> 200 with no content and no error field.")
        else:
            print(f"\n  >>> got content OK: {content[:120]}")

    print("\n[same request with a SMALL context - 4096]")
    payload["options"] = {"temperature": 0.15, "num_predict": 512, "num_ctx": 4096}
    status, small = post("/api/chat", payload)
    small_ok = isinstance(small, dict) and ((small.get("message") or {}).get("content") or "").strip()
    print(f"  HTTP {status}  ok={bool(small_ok)}")
    if not small_ok:
        print(f"  {small if not isinstance(small, dict) else small.get('error')}")

    # A cold big-context request differs from a warm small one in TWO ways -
    # size AND load state - so "4096 worked, 16384 did not" does not by itself
    # prove the context size is at fault. Now that the model is warm, retry the
    # big context. If it succeeds warm, the real cost is the cold load; if it
    # still fails, the context size genuinely is the problem.
    print("\n[big context AGAIN, now that the model is warm - controls for cold-load time]")
    payload["options"] = {"temperature": 0.15, "num_predict": 512, "num_ctx": 16384}
    status, big = post("/api/chat", payload)
    big_ok = isinstance(big, dict) and ((big.get("message") or {}).get("content") or "").strip()
    print(f"  HTTP {status}  ok={bool(big_ok)}")
    if isinstance(big, dict):
        print(f"  load_duration_ms={round((big.get('load_duration') or 0)/1e6)} "
              f"total_duration_ms={round((big.get('total_duration') or 0)/1e6)}")

    print("\n  >>> VERDICT:")
    if small_ok and big_ok:
        print("      16384 works once the model is WARM. The failure is cold-load")
        print("      time, not the context size - keep the model resident.")
    elif small_ok and not big_ok:
        print("      4096 works, 16384 fails even warm. The CONTEXT SIZE is the")
        print("      cause - OLLAMA_NUM_CTX is now the knob (default 8192).")
    elif not small_ok:
        print("      even 4096 fails - this is not about context size at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
