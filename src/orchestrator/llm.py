"""
LLM interface - supports Ollama (local) and any OpenAI-compatible API.
Designed to work with whatever is available.
"""

from __future__ import annotations

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


async def _call_ollama(system: str, user: str, model: str) -> str:
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 4096},
            },
        )
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        return response.json()["message"]["content"]


async def _call_openai_compatible(system: str, user: str, model: str) -> str:
    headers = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(
            f"{OPENAI_API_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        )
        if response.status_code != 200:
            raise LLMError(f"API returned {response.status_code}: {response.text}")
        return response.json()["choices"][0]["message"]["content"]


async def generate(system: str, user: str, model: Optional[str] = None) -> str:
    """Generate a response. Tries Ollama → OpenAI-compatible → mock fallback."""
    model = model or LLM_MODEL

    if OLLAMA_URL:
        try:
            return await _call_ollama(system, user, model)
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

    if OPENAI_API_URL:
        try:
            return await _call_openai_compatible(system, user, model)
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

    from src.orchestrator.mock_llm import mock_generate
    return mock_generate(system, user)


async def generate_json(system: str, user: str, model: Optional[str] = None) -> dict:
    """Generate and parse JSON response from LLM."""
    raw = await generate(system, user, model)

    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e}\nRaw output:\n{raw[:500]}")
