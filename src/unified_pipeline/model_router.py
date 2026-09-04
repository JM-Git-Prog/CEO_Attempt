"""The model router for the Living Room chat — ONE place that decides which
Ollama model answers John, by the house law and nothing else.

John, 2026-09-03: "update the model router in the chat … auto, but let me
override with a word."

The house law (ollama-connector: pick-a-model): the 4090 is the scarce
resource and the Ollama Pro plan is prepaid, so TALKING and PLANNING go to
cloud tags and the card stays free for ComfyUI / Hunyuan3D / the mesh engine.
The chat used to answer on ``llama3.1`` — a local 8B on the very card that was
painting his props — because ``ConversationEngine()`` never chose a model and
``generate()`` fell back to the LLM_MODEL default.

Three things live here:
  * ``garage()``   — what is actually installed (GET /api/tags), cached briefly,
                     split into cloud tags (``:cloud`` / ``-cloud``, 0 bytes on
                     disk) and local ones. Never a hard-coded list of models.
  * ``pick()``     — the first model of the TALK lane that is installed; the lane
                     is data (``V17_TALK_LANE``), cloud first, local last.
  * ``override()`` — ``use <model>: <sentence>`` in front of a message forces one
                     model for that sentence; ``models`` lists the garage.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Cloud first (prepaid, off the card), local last. Order = preference. A tag that
# is not installed is skipped, so this list can name models John may add later.
DEFAULT_TALK_LANE = (
    "gpt-oss:120b-cloud,"
    "deepseek-v4-flash:cloud,"
    "qwen3.5:397b-cloud,"
    "glm-5.2:cloud,"
    "gpt-oss:20b,"
    "llama3.1:latest"
)

_OVERRIDE = re.compile(r"^\s*use\s+([A-Za-z0-9][\w.\-/:]{0,80})\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_MODELS_CMD = re.compile(r"^\s*(models|which models|list models|what models)\b", re.IGNORECASE)


def is_cloud(name: str) -> bool:
    n = name.lower()
    return n.endswith(":cloud") or n.endswith("-cloud")


@dataclass
class Garage:
    cloud: list[str] = field(default_factory=list)
    local: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""

    @property
    def all(self) -> list[str]:
        return self.cloud + self.local


_cache = Garage()
_TTL = 60.0


async def garage(force: bool = False) -> Garage:
    """John's installed models, as Ollama reports them right now (cached 60 s)."""
    global _cache
    if not force and _cache.fetched_at and time.time() - _cache.fetched_at < _TTL:
        return _cache
    g = Garage(fetched_at=time.time())
    try:
        async with httpx.AsyncClient(timeout=5.0) as cl:
            r = await cl.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            for m in r.json().get("models", []):
                name = str(m.get("name", ""))
                if not name:
                    continue
                (g.cloud if is_cloud(name) else g.local).append(name)
    except Exception as exc:  # the chat must still answer when Ollama's list is unreachable
        g.error = f"{type(exc).__name__}: {exc}"
        if _cache.all:
            g.cloud, g.local = _cache.cloud, _cache.local
    _cache = g
    return g


def talk_lane() -> list[str]:
    raw = os.getenv("V17_TALK_LANE", DEFAULT_TALK_LANE)
    return [t.strip() for t in raw.split(",") if t.strip()]


def _installed(name: str, names: list[str]) -> str | None:
    """Match 'gpt-oss:20b' to 'gpt-oss:20b' or 'gpt-oss:20b-…'; 'llama3.1' to 'llama3.1:latest'."""
    low = name.lower()
    for n in names:
        nl = n.lower()
        if nl == low or nl == low + ":latest" or (":" not in low and nl.split(":")[0] == low):
            return n
    return None


async def pick(kind: str = "talk") -> str:
    """The cheapest installed model for the job. Only 'talk' exists today; the
    vision and mesh lanes stay where they are (stage handlers), on purpose."""
    g = await garage()
    for want in talk_lane():
        hit = _installed(want, g.all)
        if hit:
            return hit
    return os.getenv("LLM_MODEL", "llama3.1")


def override(text: str) -> tuple[str | None, str]:
    """'use gpt-oss:120b-cloud: make it warmer' -> ('gpt-oss:120b-cloud', 'make it warmer')."""
    m = _OVERRIDE.match(text or "")
    if not m:
        return None, text
    return m.group(1), m.group(2).strip()


def is_models_command(text: str) -> bool:
    return bool(_MODELS_CMD.match(text or ""))


async def resolve_override(name: str) -> str | None:
    """A forced model must be installed; the caller tells John when it is not."""
    g = await garage()
    return _installed(name, g.all)


async def models_sentence() -> str:
    """The garage in one breath, for the 'models' command."""
    g = await garage(force=True)
    lane = [m for m in (_installed(w, g.all) for w in talk_lane()) if m]
    parts = []
    if g.cloud:
        parts.append("Cloud, prepaid — the 4090 stays free: " + ", ".join(g.cloud) + ".")
    if g.local:
        parts.append("On the 4090: " + ", ".join(g.local) + ".")
    parts.append("To talk with you I use, in order: " + (" → ".join(lane) or "(none of the lane is installed)") + ".")
    parts.append('Put "use <model>:" in front of a sentence to force one, just for that sentence.')
    if g.error:
        parts.append(f"(Ollama's list was unreachable just now — {g.error}; this is the last one I saw.)")
    return " ".join(parts)
