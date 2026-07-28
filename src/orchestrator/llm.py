"""
LLM interface - supports Ollama (local) and any OpenAI-compatible API.
Designed to work with whatever is available.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import httpx

from src.orchestrator.net_guard import checked_url

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# 16384 was hardcoded and it does not work on this machine: a cold request at
# that size times out entirely, while the identical request at 4096 answers in
# under a second (check_ollama, 2026-07-27). A bigger KV cache also competes
# with training for the same card. 8192 is the compromise - still well above
# the plan prompt plus schema - and it is now tunable without a code edit.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))


class LLMError(Exception):
    pass


async def _call_ollama(
    system: str, user: str, model: str, *, json_mode: bool = False
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": 0.15 if json_mode else 0.7,
            "num_predict": 8192,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    if json_mode:
        payload["format"] = "json"
    endpoint = checked_url("OLLAMA_URL", "http://localhost:11434")
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(f"{endpoint}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        body = response.json()
        content = (body.get("message") or {}).get("content") or ""
        if not content.strip():
            # Ollama answers 200 with an EMPTY message more often than it
            # errors: measured 2026-07-26, 55% of calls. That is not an
            # exception, so it slipped through as "the model returned invalid
            # JSON" and the real reason was never recorded. Ollama's own
            # counters say why - done_reason "length" means the output cap or
            # context ran out; a prompt_eval_count at the context ceiling
            # means the prompt itself did not fit.
            # Ollama also answers 200 with an {"error": ...} payload for things
            # like "model requires more system memory" - there is no completion
            # in that body at all, which is why every counter below reads None.
            # Show the error field first, then the raw body, so the reason is
            # never a guess again.
            raise LLMError(
                "Ollama returned 200 with an EMPTY message. "
                f"error={body.get('error')!r} "
                f"done_reason={body.get('done_reason')!r} "
                f"prompt_eval_count={body.get('prompt_eval_count')} "
                f"eval_count={body.get('eval_count')} "
                f"num_ctx={payload['options']['num_ctx']} "
                f"num_predict={payload['options']['num_predict']} "
                f"total_duration_ms={round((body.get('total_duration') or 0) / 1e6)} "
                f"body={json.dumps(body)[:400]}"
            )
        return content


async def _call_openai_compatible(
    system: str, user: str, model: str, *, json_mode: bool = False
) -> str:
    headers = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.15 if json_mode else 0.7,
        "max_tokens": 8192,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    endpoint = checked_url("OPENAI_API_URL")
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(
            f"{endpoint}/v1/chat/completions", headers=headers, json=payload
        )
        if response.status_code != 200:
            raise LLMError(f"API returned {response.status_code}: {response.text}")
        return response.json()["choices"][0]["message"]["content"]


async def generate(
    system: str,
    user: str,
    model: Optional[str] = None,
    *,
    json_mode: bool = False,
) -> str:
    """Generate a response, preferring local Ollama and retaining mock fallback."""
    # Fresh lookup, not the frozen LLM_MODEL constant above - a caller that
    # flips os.environ["LLM_MODEL"] per-call (plan_bench.py's lane loop)
    # needs this fallback to see the current value, not whatever it was
    # the first time this module got imported in the process.
    model = model or os.getenv("LLM_MODEL", "llama3.1")

    # Every backend failure used to be swallowed with a bare `pass` and
    # answered with mock_generate(). The caller then saw an unparseable
    # response and reported "LLM returned invalid JSON" - so an ollama
    # timeout, a 500, or a refused connection all showed up as a JSON
    # problem, and the real cause was thrown away. Measured 2026-07-26: 50
    # of 50 "bad JSON" failures were actually EMPTY mock responses standing
    # in for a backend error nobody ever saw.
    failures: list[str] = []
    if OLLAMA_URL:
        try:
            return await _call_ollama(system, user, model, json_mode=json_mode)
        except (httpx.HTTPError, LLMError) as exc:
            failures.append(f"ollama({model}): {type(exc).__name__}: {exc}")
    if OPENAI_API_URL:
        try:
            return await _call_openai_compatible(
                system, user, model, json_mode=json_mode
            )
        except (httpx.HTTPError, LLMError) as exc:
            failures.append(f"openai-compatible({model}): {type(exc).__name__}: {exc}")

    if failures and os.getenv("ALLOW_MOCK_LLM", "") != "1":
        # A configured backend failed. Say so, loudly, instead of quietly
        # substituting fake output into a measurement run.
        raise LLMError("all configured LLM backends failed -> " + " | ".join(failures))

    if not failures and os.getenv("ALLOW_MOCK_LLM", "") != "1":
        # No backends configured at all — refuse to silently mock
        raise LLMError(
            "No LLM backends configured (OLLAMA_URL and OPENAI_API_URL both empty). "
            "Set ALLOW_MOCK_LLM=1 to use the deterministic diner fallback."
        )

    from src.orchestrator.mock_llm import mock_generate
    return mock_generate(system, user)


def _repair_json_text(text: str) -> str:
    """Fix the malformed-JSON defects that are unambiguous, and only those.

    Local models routinely emit JSON that is correct except for punctuation,
    and the whole generation - a minute of GPU time - was being thrown away
    for it. Measured 2026-07-26: "Expecting ',' delimiter" was the single
    biggest remaining failure once the schema faults were fixed.

    Four repairs, each with exactly one possible interpretation:
      - strip // and /* */ comments (never legal in JSON)
      - drop trailing commas before } or ]
      - insert a missing comma after a closing } or ] that is immediately
        followed by another value (the observed defect)
      - close containers left open by a truncated response

    Everything happens outside string literals, so no repair can alter the
    model's actual content. Anything ambiguous - a missing colon, a missing
    quote mid-key - is deliberately left alone to fail loudly.
    """
    out: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue

        if char == ",":
            following = index + 1
            while following < length and text[following].isspace():
                following += 1
            if following < length and text[following] in "}]":
                index += 1  # trailing comma
                continue

        if char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()
            # a value directly after a closed container needs a comma between
            following = index + 1
            while following < length and text[following].isspace():
                following += 1
            if following < length and text[following] in '{["' and stack:
                out.append(char)
                out.append(",")
                index += 1
                continue

        out.append(char)
        index += 1

    repaired = "".join(out)
    if in_string:
        repaired += '"'
    while stack:
        repaired += "]" if stack.pop() == "[" else "}"
    return repaired


def _log_bad_json(raw: str, error: Exception, repaired_ok: bool) -> None:
    """Keep the raw text of anything we could not parse, so the next defect
    is diagnosed from evidence instead of guessed at."""
    try:
        from pathlib import Path

        folder = Path(__file__).resolve().parent.parent.parent / "bench" / "bad-json"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        tag = "repaired" if repaired_ok else "unparseable"
        (folder / f"{tag}-{stamp}-{abs(hash(raw)) % 10000:04d}.txt").write_text(
            f"error: {error}\n{'-' * 60}\n{raw}", encoding="utf-8")
    except Exception:
        pass  # diagnostics must never break generation


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        sliced = cleaned[start : end + 1] if start >= 0 and end > start else cleaned
        try:
            value = json.loads(sliced)
        except json.JSONDecodeError:
            try:
                value = json.loads(_repair_json_text(sliced))
            except json.JSONDecodeError:
                _log_bad_json(raw, first_error, repaired_ok=False)
                raise first_error
            _log_bad_json(raw, first_error, repaired_ok=True)
    if not isinstance(value, dict):
        raise LLMError("LLM JSON response must be an object")
    return value


async def generate_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    *,
    timeout_seconds: float | None = None,
) -> dict:
    """Generate JSON with one repair retry and an optional total deadline."""

    async def run_attempts() -> dict:
        raw = ""
        parse_error: json.JSONDecodeError | None = None
        for attempt in range(2):
            retry_note = ""
            if attempt:
                retry_note = (
                    "\n\nYour previous response was malformed or incomplete. "
                    "Return the complete object as compact valid JSON only."
                )
            raw = await generate(system, user + retry_note, model, json_mode=True)
            try:
                return _parse_json(raw)
            except json.JSONDecodeError as exc:
                parse_error = exc
        raise LLMError(
            f"LLM returned invalid JSON after retry: {parse_error}\nRaw output:\n{raw[:500]}"
        )

    if timeout_seconds is None:
        return await run_attempts()
    try:
        async with asyncio.timeout(max(0.1, float(timeout_seconds))):
            return await run_attempts()
    except TimeoutError:
        # Do NOT silently substitute mock data — the user's actual prompt matters.
        # If the LLM times out, raise so the pipeline reports a clear failure.
        if os.getenv("ALLOW_MOCK_LLM", "") == "1":
            from src.orchestrator.mock_llm import mock_generate
            print(f"[LLM] Timeout after {timeout_seconds}s — using deterministic fallback (ALLOW_MOCK_LLM=1)")
            return _parse_json(mock_generate(system, user))
        raise LLMError(
            f"LLM timed out after {timeout_seconds}s. "
            f"Check that Ollama is running and the model is loaded. "
            f"Retry or increase LLM_TIMEOUT."
        )


async def generate_vision_json(
    system: str,
    user: str,
    image_paths: list[str | os.PathLike[str]],
    model: Optional[str] = None,
) -> dict:
    """Generate strict JSON from one or more images using local Ollama vision."""
    import base64
    from pathlib import Path

    vision_model = model or os.getenv("VISION_MODEL", "qwen2.5vl:7b")
    images = [base64.b64encode(Path(path).read_bytes()).decode("ascii") for path in image_paths]
    raw = ""
    last_error: json.JSONDecodeError | None = None
    for attempt in range(2):
        prompt = user
        if attempt:
            prompt += "\nYour prior response was malformed. Return one complete compact JSON object only."
        payload = {
            "model": vision_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt, "images": images},
            ],
            "stream": False,
            "format": "json",
            # was a hardcoded 24576 - even larger than the 16384 that times out
            # cold on this card. Same tunable, same reason.
            "options": {"temperature": 0.1, "num_predict": 8192,
                        "num_ctx": OLLAMA_NUM_CTX},
        }
        endpoint = checked_url("OLLAMA_URL", "http://localhost:11434")
        async with httpx.AsyncClient(timeout=max(LLM_TIMEOUT, 300)) as client:
            response = await client.post(f"{endpoint}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Vision model returned {response.status_code}: {response.text[:500]}")
        raw = response.json()["message"]["content"]
        try:
            return _parse_json(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise LLMError(f"Vision model returned invalid JSON: {last_error}\n{raw[:500]}")
