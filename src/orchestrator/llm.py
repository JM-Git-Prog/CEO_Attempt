"""
LLM interface - supports Ollama (local) and any OpenAI-compatible API.
Designed to work with whatever is available.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))


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
            "num_ctx": 16384,
        },
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        return response.json()["message"]["content"]


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
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(
            f"{OPENAI_API_URL}/v1/chat/completions", headers=headers, json=payload
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
    model = model or LLM_MODEL
    if OLLAMA_URL:
        try:
            return await _call_ollama(system, user, model, json_mode=json_mode)
        except (httpx.HTTPError, LLMError):
            pass
    if OPENAI_API_URL:
        try:
            return await _call_openai_compatible(
                system, user, model, json_mode=json_mode
            )
        except (httpx.HTTPError, LLMError):
            pass
    from src.orchestrator.mock_llm import mock_generate
    return mock_generate(system, user)


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
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
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
        from src.orchestrator.mock_llm import mock_generate

        print(f"[LLM] Timeout after {timeout_seconds}s — using deterministic fallback")
        return _parse_json(mock_generate(system, user))


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
            "options": {"temperature": 0.1, "num_predict": 8192, "num_ctx": 24576},
        }
        async with httpx.AsyncClient(timeout=max(LLM_TIMEOUT, 300)) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Vision model returned {response.status_code}: {response.text[:500]}")
        raw = response.json()["message"]["content"]
        try:
            return _parse_json(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise LLMError(f"Vision model returned invalid JSON: {last_error}\n{raw[:500]}")
