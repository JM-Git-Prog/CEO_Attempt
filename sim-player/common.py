"""sim-player/common.py — the shared floor under the Sam Loop (decision 23 + John's "C", 2026-09-10).

Paths, the sim namespace, one Ollama call, one capture writer, one logger. stdlib only, so the
loop runs on John's plain Python. Every model call goes through `ollama_chat()` and is written to a
`calls.jsonl` by `capture()` — the capture law: prompt rendered, model, options, latency, digest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # CEO_Attempt/sim-player
ROOT = HERE.parent                                     # CEO_Attempt
RUNS = Path(os.getenv("SAM_RUNS", str(HERE / "sim-runs")))

OLLAMA = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
SIM_LIVING_ROOM = os.getenv("SAM_LIVING_ROOM", "http://127.0.0.1:8001")     # the loop's own instance, never John's :8000
# 2026-09-11, John: "Give the sim its own Pick Board". Sam answers walls and judges props on
# HIS board (sim_board.py, :8294, its own stations and its own preferences.jsonl), never on
# John's :8194 — a robot's pick in John's taste ledger is a corrupted training set, and the
# rule that a robot never acts as John is the same rule that governs me.
SIM_PICK_PORT = int(os.getenv("SAM_PICK_PORT", "8294"))
PICKBOARD = os.getenv("PICKBOARD", f"http://127.0.0.1:{SIM_PICK_PORT}")
BUILDER = os.getenv("NEIGHBOURHOOD_BUILDER", "http://127.0.0.1:8196")
WORLDS = Path(os.getenv("CEO3D_WORLDS", r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\worlds"))
GAP_LEDGER = Path(os.getenv("CAPABILITY_GAPS", r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\tools\capability-gaps.jsonl"))
GAP_ROUTER = Path(os.getenv("GAP_ROUTER", r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\tools\gap-router\gap-router.mjs"))
PERSONA = Path(os.getenv("SAM_PERSONA", r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\briefings\END-USER-PROMPT-ten-year-old-first-visit-2026-09-10.md"))

HOME_SLUG = "mr-johns-neighborhood"                    # read, never written
SIM_SLUG = os.getenv("SAM_WORLD", "sim-neighborhood")  # Sam's copy; reset every round
SIM_PREFIX = "sim-"                                    # every Sam session id starts with this (decision 23)

# The house routing law: cheapest rung that passes the gate, cloud first so the 4090 stays free.
# A LADDER, not a tag — the garage listing is stale and `ask_lane` proves each rung live before a
# job commits to it. Evidence from the first real night (2026-09-10):
#   gpt-oss:120b-cloud    ANSWERED every call — proven live, so it is the net at the end of each ladder
#   qwen3-coder:480b-cloud HTTP 410 on all 36 mechanic calls (retired) — kept last, never first again
# 2026-09-14, John: "sam can use cloud lanes, any of them ... to train himself faster and better
# and more accurate." Every ladder below is CLOUD from top to bottom, with a local tag only as the
# last net. Every rung was censused live that morning; the two known-retired tags stay last.
#
# This is not only about speed. The 4090 is the thing that BLOCKED Sam: the loop refuses to start a
# round while the card holds more than 8 GB, and the old friend rung (qwen3.8:27b, 17.7 GB) put it
# over that line by itself — so every round Sam played made the next round wait five minutes for
# Sam. Cloud ladders end that, and the eyes become the only local model in a round.
LANES = {
    # 2026-09-14, John: "you dont need to use only gptOSS we have super advanced models available
    # through ollamma use them." The frontier tags lead each ladder now and gpt-oss:120b-cloud is
    # demoted to the net at the end — it keeps that place because it is the ONE tag proven live
    # across several nights, and a ladder needs a rung that has never failed. Every tag below was
    # censused live this morning. ask_lane still proves each one before a job commits to it.
    #
    # ONLY :cloud AND -cloud TAGS. Corrected 2026-09-14, hours after I wrote the bare ones in.
    # The garage census lists two kinds of cloud tag and they are NOT the same door:
    #   "kimi-k3:cloud"  goes through the local daemon, which is signed in  -> works
    #   "glm-5.3"        goes direct to https://ollama.com/api/chat with no key -> HTTP 401
    # I put glm-5.3, minimax-m3, deepseek-v4-pro:0813, nemotron-3-ultra and mistral-large-3:675b on
    # these ladders because the census advertised them, and every one of them 401s. That is the
    # verified-backend law catching me doing exactly what it exists to prevent: reading a listing
    # instead of proving a rung. Both tags I actually tested - kimi-k3:cloud and qwen3.5:397b-cloud -
    # answered in seconds. Every rung below is one of those two kinds.
    "sam":      [os.getenv("SAM_MODEL", "kimi-k3:cloud"), "qwen3.5:397b-cloud", "glm-5.2:cloud",
                 "deepseek-v4-flash:cloud", "gpt-oss:120b-cloud", "gpt-oss:20b"],
    # The judge reasons over a whole transcript and has to be right about what actually happened,
    # so it gets the biggest thinkers on the plan.
    "judge":    [os.getenv("SAM_JUDGE_MODEL", "qwen3.5:397b-cloud"), "kimi-k3:cloud",
                 "glm-5.2:cloud", "deepseek-v4-flash:cloud", "gpt-oss:120b-cloud", "gemma4:26b"],
    # The mechanic writes real patches into real files, so a code-trained tag leads.
    "mechanic": [os.getenv("SAM_MECHANIC_MODEL", "kimi-k2.7-code:cloud"), "kimi-k3:cloud",
                 "glm-5.2:cloud", "gpt-oss:120b-cloud", "qwen3.5:397b-cloud",
                 "qwen3-coder:480b-cloud"],
    # Maya, Sam's friend. PAUSED by John on 2026-09-14 ("sams friend can be paused until further
    # notice") — see FRIEND_PAUSED below, which is what actually silences her. The ladder is kept,
    # and moved to cloud, so turning her back on is one environment variable and no code change.
    "friend":   [os.getenv("SAM_FRIEND_MODEL", "gpt-oss:120b-cloud"), "glm-5.2:cloud", "gpt-oss:20b"],
    # Sam's EYES (2026-09-11). A prop wall is four PNGs; a chooser who cannot see them is rolling a
    # die, and a die's answer in a preferences file teaches a style model that taste is random.
    #
    # CLOUD FIRST, as of 2026-09-14 — and this is a correction I owe the ledger. I read the garage
    # census, saw no tag advertising vision, and wrote in this file that seeing had to cost the 4090.
    # John said "send the cloud models pictures if you need to", so I sent one: kimi-k3:cloud named
    # the building in the picture in 2.1 s and the card was never touched. The census was stale, and
    # the verified-backend law exists precisely because it always is — PROVE the rung, never read
    # about it. The local vision models stay as the rungs below, which is where they belong.
    "eyes":     [os.getenv("SAM_EYES_MODEL", "kimi-k3:cloud"), "qwen3.5:397b-cloud",
                 "qwen3-vl:8b", "qwen2.5vl:7b", "minicpm-v:latest", "ibm/granite3.3-vision:2b"],
}

# Maya is off until John says otherwise. furnish.Friend with ask=None goes quiet by design — it
# returns "" and reports its model as "quiet" — so pausing her costs the loop nothing and breaks
# nothing. To bring her back: set SAM_FRIEND=on.
FRIEND_PAUSED = os.getenv("SAM_FRIEND", "paused").strip().lower() not in ("on", "1", "yes", "true")


class Backend(Exception):
    """A transport/backend failure (HTTP error, timeout, empty body) — never a task failure."""


class Truncated(Backend):
    """The model ran out of budget mid-answer (done_reason="length"). NOT the model's fault and not
    the transport's: the cap was too small. The caller retries with a bigger one before giving up.
    Proven 2026-09-10 on the first real night: every one of Sam's failures was eval_count == the cap."""


class TagGone(Backend):
    """This tag is retired or unauthorised (HTTP 410/401/404). The lane ladder falls through to the
    next rung — the verified backend law: the garage listing is stale, a tag must be proven live."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str, *, file: Path | None = None) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if file:
        try:
            with open(file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, object]:
    """One JSON request. Returns (status, parsed-or-text). Raises Backend on transport failure."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:                      # URLError, timeout, ConnectionReset
        raise Backend(f"{method} {url}: {type(e).__name__}: {e}") from e
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def ollama_tags() -> list[str]:
    try:
        st, data = http_json("GET", OLLAMA + "/api/tags", timeout=8)
    except Backend:
        return []
    if st != 200 or not isinstance(data, dict):
        return []
    return [m.get("name") for m in data.get("models", []) if isinstance(m, dict)]


def pick_lane(kind: str, available: list[str] | None = None) -> str:
    """The first lane tag that exists in the garage. Cloud tags are always 'available' (the daemon pulls them);
    a local tag must be listed. Falls back to the first lane so a missing census never blocks.
    NOTE: listed is not live — `ask_lane` is what proves a tag before a job commits to it."""
    lanes = LANES[kind]
    have = available if available is not None else ollama_tags()
    for tag in lanes:
        if tag.endswith("-cloud") or tag.endswith(":cloud") or tag in have or not have:
            return tag
    return lanes[0]


# The verified backend law (route-a-job): THE GARAGE LISTING IS STALE. A tag it advertises can be
# retired — qwen3-coder:480b-cloud answered HTTP 410 on all 36 of the mechanic's calls on the first
# real night, so the mechanic never proposed a single patch. A lane is proven by one cheap call
# before a job commits to it, a dead tag falls through to the next rung, and the winner is recorded
# so the same ladder is never walked twice in a run.
_lane_winner: dict[str, str] = {}
_lane_dead: set[str] = set()


def ask_lane(kind: str, system: str, messages: list[dict], *, schema: dict | None = None,
             lanes: list[str] | None = None, ledger: Path | None = None, **kw) -> dict:
    """Ask the cheapest rung of `kind` that is actually alive. Falls through a retired/unauthorised
    tag (TagGone) to the next; raises the last Backend when every rung is dead. Truncated is NOT a
    ladder failure — it belongs to the caller, who knows how big its answer should be."""
    # `lanes` is a LADDER: a list of model tags, cheapest first. Handing it the whole
    # {lane: [tags]} table iterates the table's KEYS, so the LANE'S OWN NAME goes to Ollama as a
    # model name. That is what happened on 2026-09-14 to both lanes added that day, at once:
    #     ollama curious: HTTP 404 — {'error': "model 'curious' not found"}
    #     ollama coach:   HTTP 404 — {'error': "model 'coach' not found"}
    # Ten nights played, not one question asked, no lesson learned, and the batch report said only
    # "no model answered". Accept either shape, and refuse a ladder that is not model tags rather
    # than discovering it one 404 at a time.
    if isinstance(lanes, dict):
        lanes = lanes.get(kind)
    ladder = list(lanes or LANES[kind])
    if not ladder or any(not isinstance(t, str) or not t.strip() for t in ladder):
        raise Backend(f"lane {kind}: that is not a ladder of model tags — {ladder!r}")
    winner = _lane_winner.get(kind)
    if winner:
        ladder = [winner] + [t for t in ladder if t != winner]
    last: Exception | None = None
    for tag in ladder:
        if tag in _lane_dead:
            continue
        try:
            out = ollama_chat(tag, system, messages, schema=schema, **kw)
        except TagGone as e:
            _lane_dead.add(tag)
            last = e
            log(f"lane {kind}: {tag} is gone ({e}) — falling through to the next rung")
            if ledger:
                capture(ledger, {"at": now_iso(), "lane": kind, "tag": tag, "result": "gone", "why": str(e)[:200]})
            continue
        if _lane_winner.get(kind) != tag:
            _lane_winner[kind] = tag
            log(f"lane {kind}: {tag} answered — recorded as this run's winner")
            if ledger:
                capture(ledger, {"at": now_iso(), "lane": kind, "tag": tag, "result": "winner"})
        return out
    raise Backend(f"lane {kind}: every rung is dead ({', '.join(ladder)}) — last: {last}")


# THE CLOUD TAGS IGNORE `format`. Proven 2026-09-14: the judge's exact schema and payload sent to
# gpt-oss:120b-cloud came back as markdown prose with bolded verdicts — no JSON at all — while the
# same shape on a local tag obeys the schema exactly. Grammar-constrained decoding happens in the
# local runner; a `:cloud` tag is proxied and the constraint is dropped on the way. Nothing warns
# you: HTTP 200, done_reason "stop", a perfectly good answer in the wrong shape.
#
# That one fact is why the judge has read `unparseable` on EVERY round since 2026-09-10 — the night
# the judge lane was moved to a cloud tag. Nothing scored a single night for four days.
#
# So a schema is a REQUEST, never a guarantee, and the parse has to survive prose. Three steps, in
# order of how much they assume: the whole reply is JSON; a fenced ```json block; the first balanced
# object in the text. Only if all three fail does the caller hear "unparseable" — and by then it is
# true.
_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.S)


def extract_json(text: str):
    """The first JSON object in `text`, however it is wrapped. None when there isn't one."""
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for body in _FENCE.findall(text):
        try:
            return json.loads(body.strip())
        except ValueError:
            continue
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\" and in_str:
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


# Numeric bounds in a `format` schema stall Ollama's local grammar compiler - proven 2026-09-14 on
# qwen3-vl:8b, where the identical call answered in 2.3 s without them and had not returned after
# 60 s with them. It cost the eyes lane its whole ladder for three days, misdiagnosed as "every rung
# is dead". Ollama never enforced these keywords, so nothing is lost by dropping them, and every
# caller already has to range-check the number itself. Stripped here, at the one door every model
# call goes through, so the next schema anyone writes cannot lose a lane the same way.
_BOUNDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")

# Appended to the system prompt on the one retry after a cloud tag answered in prose.
JSON_ONLY = ("\n\nAnswer with a single raw JSON object and NOTHING else: no prose, no explanation, "
             "no markdown fences, no bullet points. The first character of your reply must be '{' "
             "and the last must be '}'.")


def grammar_safe(node):
    """A copy of `node` with numeric bounds removed at every depth. Never mutates the original."""
    if isinstance(node, dict):
        return {k: grammar_safe(v) for k, v in node.items() if k not in _BOUNDS}
    if isinstance(node, list):
        return [grammar_safe(v) for v in node]
    return node


def ollama_chat(model: str, system: str, messages: list[dict], *, schema: dict | None = None,
                temperature: float = 0.4, num_predict: int = 700, timeout: float = 120.0,
                capture_to: Path | None = None, purpose: str = "", think: bool | None = False,
                _retried_as_json: bool = False) -> dict:
    """POST /api/chat, no streaming. With `schema`, the reply is parsed as JSON (format=schema).
    Returns {"text": str, "json": obj|None, "latency_s": float, "model": model}.

    think=False by default: a reasoning model (gpt-oss) otherwise spends num_predict on hidden
    thinking and returns an EMPTY answer at done_reason="length" — the architect bench hit this on
    2026-09-07 and the Sam Loop hit it on every round of its first night. A model that cannot switch
    thinking off answers HTTP 400; we retry once letting it think, exactly as the bench does.

    Raises TagGone (410/401/404 — fall through to the next rung), Truncated (ran out of budget —
    retry bigger), or Backend (everything else). None of the three is ever a verdict on the task."""
    body = {
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": system}] + messages,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if schema:
        body["format"] = grammar_safe(schema)
    if think is not None:
        body["think"] = think
    t0 = time.monotonic()
    st, data = http_json("POST", OLLAMA + "/api/chat", body, timeout=timeout)
    if st == 400 and "think" in body and "think" in str(data).lower():
        body.pop("think")                                   # this model cannot switch thinking off: let it
        st, data = http_json("POST", OLLAMA + "/api/chat", body, timeout=timeout)
    latency = round(time.monotonic() - t0, 2)
    if st in (401, 404, 410):
        raise TagGone(f"ollama {model}: HTTP {st} — the tag is retired or unauthorised: {str(data)[:160]}")
    if st != 200 or not isinstance(data, dict):
        raise Backend(f"ollama {model}: HTTP {st}: {str(data)[:200]}")
    done = data.get("done_reason")
    text = str((data.get("message") or {}).get("content") or "").strip()
    if not text:
        if done == "length":
            raise Truncated(f"ollama {model}: spent all {num_predict} tokens before answering (done_reason=length)")
        raise Backend(f"ollama {model}: empty reply (done_reason={done!r})")
    parsed = None
    if schema:
        parsed = extract_json(text)
        if parsed is None:
            if done == "length":
                raise Truncated(f"ollama {model}: the answer was cut off at {num_predict} tokens: {text[-80:]!r}")
            # A cloud tag that ignored the schema and answered in prose. One more try, this time
            # SAYING the shape out loud in the prompt, because that is all a cloud tag listens to.
            if not _retried_as_json:
                log(f"ollama {model}: answered outside the schema — asking again in words")
                return ollama_chat(model, system + JSON_ONLY, messages, schema=schema,
                                   temperature=temperature, num_predict=num_predict, timeout=timeout,
                                   capture_to=capture_to, purpose=purpose, think=think,
                                   _retried_as_json=True)
    out = {"text": text, "json": parsed, "latency_s": latency, "model": model, "done_reason": done,
           "eval_count": data.get("eval_count"), "prompt_eval_count": data.get("prompt_eval_count")}
    if capture_to:
        capture(capture_to, {
            "at": now_iso(), "purpose": purpose, "model": model, "options": body["options"],
            "schema": bool(schema), "done_reason": done, "think": body.get("think"),
            "prompt_sha": hashlib.sha1(json.dumps(body["messages"], sort_keys=True).encode()).hexdigest()[:12],
            "prompt_rendered": body["messages"], "reply": text[:4000], "parsed_ok": parsed is not None if schema else None,
            "latency_s": latency, "eval_count": out["eval_count"], "prompt_eval_count": out["prompt_eval_count"],
        })
    return out


def capture(path: Path, row: dict) -> None:
    """Append-only, one JSON object per line. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def persona_text() -> str:
    """Sam's system prompt: the briefing file, verbatim, from its '---' line on. A short built-in
    stand-in if the file is missing (logged), so the loop never silently plays a different Sam."""
    try:
        text = PERSONA.read_text(encoding="utf-8")
        if "\n---\n" in text:
            text = text.split("\n---\n", 1)[1]
        return text.strip()
    except OSError:
        log(f"persona file missing at {PERSONA} — using the built-in short Sam")
        return ("You are Sam, ten years old, first time in this app: a chat on the left, a 3D neighborhood on the right. "
                "Whatever you type on the left should show up on the right. One wish per message, under fifteen words, kid words only. "
                "Say what you see, say what you want, say 'nothing happened' when nothing changed.")


def new_session_id() -> str:
    return SIM_PREFIX + hashlib.sha1(f"{time.time_ns()}".encode()).hexdigest()[:12]


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
