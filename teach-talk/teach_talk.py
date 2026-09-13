"""Teach the talk lane — the conversation's first teacher factory (John, 2026-09-11, "a").

WHY THIS EXISTS. The nightly student improves only where something TEACHES it and something
GRADES it. The first student's exam read houses +2.8, objects +10.4, architect +0.0 — and the
conversation, the capability John most wants local (Maya runs local-first for exactly that
reason), had NEITHER. On the night of 2026-09-10 every one of ~60 vision-talk turns failed with
"no JSON object in the reply" and fell back to the canned line; nobody noticed until the
simulated ten-year-old read the signboard.

WHAT IT DOES, on the Overnight Solver's proven shape: deep cloud tags draft in volume, a
DETERMINISTIC checker decides what survives, and nothing unchecked becomes training data.
Rows that pass land in talk-sft.jsonl for the nightly set; rows that fail are kept with their
reason, because a rejected draft is evidence about the teacher, not rubbish.

WHAT IT DOES NOT DO. It never trains, never touches the world, never writes outside its own
folder, and never spends: the lane is the prepaid Ollama cloud (the 4090 stays free), and the
licence question is settled by doc 27's own law — Ollama disclaims ownership of outputs and
does not train on them, subject to the competing-service clause and a per-model weight-licence
check, which is why every row carries its teacher lineage.

THE CONTRACT IS NOT INVENTED HERE. src/web/vision_talk.py is imported and used to pick the next
question, exactly as the product does, and the system prompt and reply schema are the product's
own (src/web/v17_say_routes.py). What grades is what ships (BUILD-RULES E2).

    python teach_talk.py --selftest         prove every check trips on a known-bad input
    python teach_talk.py --once 12          draft and grade 12 turns, append the survivors
    python teach_talk.py --once 12 --model gpt-oss:120b-cloud
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                     # CEO_Attempt
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web import vision_talk        # noqa: E402  the REAL contract, not a copy

OLLAMA = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
# The house routing law: cloud first so the 4090 stays free; local only as the net at the end.
LADDER = [os.getenv("TEACH_TALK_MODEL", "gpt-oss:120b-cloud"), "qwen3.5:397b-cloud", "qwen3.8:27b"]
OUT_ROWS = HERE / "talk-sft.jsonl"
OUT_CALLS = HERE / "calls.jsonl"
OUT_REJECTS = HERE / "talk-rejected.jsonl"
OUT_PROMOTED = HERE / "promoted.jsonl"   # ids already rescued by a regrade, so it never doubles up
LOG = HERE / "teach-talk-log.txt"

# The product's own system prompt and schema (v17_say_routes.py). Copied deliberately and
# marked: if either changes there, this factory teaches the wrong shape, so the selftest
# asserts they still match what the product sends.
VISION_TALK_SYSTEM = (
    "You are a kind builder talking with an eight-year-old about the house he wants. "
    "Repeat back in one short sentence what you just heard, then ask exactly ONE "
    "question. The question is GIVEN to you below — rephrase it warmly, or ask it "
    "as-is. If no question is given, say the place sounds ready and that he can say "
    '"build it" whenever he likes. Two sentences max. No lists. Never invent a detail '
    "he did not say."
)
VISION_REPLY_SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}

# ─── the seed bank: how a ten-year-old actually opens, and what he adds next ────────────
# Drawn from the persona and from what Sam really typed on 2026-09-10 (live_trace), not
# invented prose: short, partial, one wish at a time, often a colour or a porch first.
OPENINGS = [
    "i want a house right here with a big porch",
    "build me a blue house on the empty lot",
    "can i have a small white cottage",
    "a red brick house like my grandmas",
    "i want a tall house with lots of windows",
    "make a yellow house near the garage",
    "i want a house with a swing on the porch",
    "a green house with a big front door",
]
FOLLOW_UPS = [
    "two floors", "three floors please", "white siding", "red brick walls",
    "shingles", "a metal roof", "a big porch", "a garage on the left",
    "a red flowerpot by the door", "a swing in the yard", "a flag by the path",
    "make the door red", "i want it blue", "a really big porch",
]

# ─── the deterministic checker ──────────────────────────────────────────────────────────
# Every rule below is a sentence from the product's own system prompt, turned into a test.
# A rule that cannot be checked mechanically is NOT in this list; taste is not graded here.

_SENT_SPLIT = re.compile(r"[.!?]+(?:\s|$)")
_WORD = re.compile(r"[a-z]+")
# House attributes a reply may only mention if the child said them or the given question asks.
_ATTRS = {
    "brick", "siding", "plaster", "stone", "wood", "shingle", "shingles", "metal", "flat",
    "tile", "tiles", "porch", "garage", "carport", "storey", "storeys", "story", "stories",
    "floor", "floors", "red", "white", "black", "blue", "green", "yellow", "brown", "grey",
    "gray", "beige", "tan", "cream", "orange", "purple", "pink", "swing", "flag", "bench",
    "tree", "fence", "mailbox", "path", "flowerpot", "pot", "colonial", "ranch", "modern",
    "cottage", "farmhouse", "georgian", "chimney", "dormer", "column", "columns", "balcony",
}
# Which words prove a reply asked about the topic the code chose.
_TOPIC_WORDS = {
    "storeys": {"floor", "floors", "storey", "storeys", "story", "stories", "tall", "high"},
    "wall": {"wall", "walls", "siding", "brick", "stone", "plaster", "wood", "colour", "color", "painted", "paint"},
    "roof": {"roof", "shingles", "shingle", "metal", "flat", "tile", "tiles", "top"},
    "porch": {"porch", "garage", "carport"},
    "yard": {"yard", "door", "flowerpot", "pot", "swing", "flag", "bench", "tree", "fence", "mailbox", "path", "garden"},
}
MAX_SENTENCES = 2
MAX_WORDS = 45                 # two sentences a ten-year-old will actually read


# Words a child and the order form use interchangeably. Folded to ONE token before any
# comparison, because a grader that matches letters instead of meaning throws away the
# better sentence: 2026-09-11's 60-turn batch lost both its failures to "three floors"
# answered as "a three-story house" — the order form's own field is literally "stories".
_SAME = {
    "storey": "floor", "story": "floor", "storie": "floor", "level": "floor",
    "colour": "color", "grey": "gray", "pillar": "column", "portico": "column",
    "carport": "garage", "flowerpot": "pot", "shingle": "roof", "tile": "roof",
}


def _fold(w: str) -> str:
    """Fold a plain plural, so "two floors" and "a two-floor house" are the same word here.

    2026-09-11, the factory's FIRST real batch: 2 of 12 replies were rejected and BOTH were the
    grader's fault, not the teacher's. The child said "two floors"; the model wrote "a two-floor
    house" — correct English and the better phrasing — and a literal word match called "floor" an
    invented detail AND decided nothing had been repeated back. Left overnight this would have
    quietly binned every reply that uses a compound adjective, i.e. the well-written ones. Both
    cases are selftest fixtures below now.
    """
    w = w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
    return _SAME.get(w, w)


_ATTRS_FOLDED = {_fold(a) for a in _ATTRS}
_TOPIC_FOLDED = {k: {_fold(w) for w in v} for k, v in _TOPIC_WORDS.items()}


def topic_of(question: str) -> str | None:
    """Which of vision_talk's five questions this is — by identity, never by guessing."""
    for key, q in vision_talk._QUESTIONS:
        if q == question:
            return key
    return None


def check(reply: str, *, said: str, latest: str, question: str | None) -> list[str]:
    """Every reason this reply must NOT be taught. Empty list = it may be taught."""
    bad: list[str] = []
    text = (reply or "").strip()
    if not text:
        return ["empty reply"]
    low = text.lower()

    if "\n" in text or re.search(r"(^|\s)[-*•]\s|\b\d\)\s", text):
        bad.append("is a list — the builder speaks in sentences")

    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        bad.append(f"{len(sentences)} sentences — two is the limit")
    words = _WORD.findall(low)
    if len(words) > MAX_WORDS:
        bad.append(f"{len(words)} words — too long for a ten-year-old")

    marks = text.count("?")
    if question and marks != 1:
        bad.append(f"{marks} question marks — exactly one question is asked")
    if not question and marks != 0:
        bad.append("asked a question when everything was already known")

    folded = {_fold(w) for w in words}
    if question:
        key = topic_of(question)
        if key and not (_TOPIC_FOLDED[key] & folded):
            bad.append(f"did not ask about {key} — the question given was not the question asked")

    # Repeat back what was just heard: share a real word with his latest line.
    heard = {_fold(w) for w in _WORD.findall(latest.lower()) if len(w) > 3}
    if heard and not (heard & folded):
        bad.append("never repeated back what he just said")

    # Invent nothing: an attribute may appear only if he said it, or the question asks it.
    allowed = {_fold(w) for w in _WORD.findall((said + " " + (question or "")).lower())}
    invented = sorted({w for w in words if _fold(w) in _ATTRS_FOLDED and _fold(w) not in allowed})
    if invented:
        bad.append("invented a detail he never said: " + ", ".join(invented))
    return bad


# ─── the teacher ────────────────────────────────────────────────────────────────────────

def ollama_chat(model: str, system: str, user: str, timeout: float = 60.0) -> tuple[dict, float]:
    # No "format" argument on purpose. Measured against John's live daemon on 2026-09-11:
    # gpt-oss:120b-cloud IGNORES it — the schema object and plain "json" both returned prose,
    # HTTP 200, done_reason "stop". That is exactly why the live talk lane failed ~60 turns in
    # one evening. A reply here is one string, so the product now takes the text (_ollama_text
    # in v17_say_routes.py) and this factory teaches the same shape.
    body = {"model": model, "stream": False, "options": {"temperature": 0.15},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        data = json.loads(fh.read().decode("utf-8"))
    return data, time.time() - t0


def user_prompt(said_lines: list[str], latest: str, question: str | None) -> str:
    """Byte-for-byte the shape v17_say_routes.py sends, so the student learns the real input."""
    user = f"What he has told you about the house so far: {'; '.join(said_lines)}\n\nHis latest line: {latest}\n\n"
    user += (f"Ask him this, in your own warm words: {question}" if question
             else "He has told you everything the builder needs. No question is needed.")
    return user


def one_turn(seed: int) -> dict:
    """Build one real conversational state with the product's own module, then draft a reply."""
    import random
    rnd = random.Random(seed)
    session = f"teach-{seed}"
    vision_talk.close(session)
    lines = [rnd.choice(OPENINGS)]
    v = vision_talk.open_vision(session, lines[0])
    for _ in range(rnd.randint(0, 3)):
        nxt = rnd.choice(FOLLOW_UPS)
        lines.append(nxt)
        vision_talk.add(session, nxt)
    question = vision_talk.next_question(v)
    latest = lines[-1]
    prompt = user_prompt(lines, latest, question)
    row = {"seed": seed, "said": "; ".join(lines), "latest": latest, "question": question,
           "topic": topic_of(question) if question else None, "prompt": prompt}
    errors = []
    for model in LADDER:
        try:
            data, secs = ollama_chat(model, VISION_TALK_SYSTEM, prompt)
            raw = ((data.get("message") or {}).get("content") or "").strip()
            reply, wrapped = raw, False
            if raw.startswith("{"):                      # a local model whose grammar still wraps it
                try:
                    inner = json.loads(raw).get("reply")
                    if isinstance(inner, str) and inner.strip():
                        reply, wrapped = inner.strip(), True
                except (ValueError, AttributeError):
                    pass
            row.update({"model": model, "seconds": round(secs, 2), "raw": raw[:2000],
                        "reply": reply, "arrived_wrapped": wrapped})
            row["rejected_for"] = check(reply, said=row["said"], latest=latest, question=question)
            return row
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append(f"{model}: {type(exc).__name__} {exc}")
    row.update({"model": None, "reply": "", "arrived_wrapped": False,
                "rejected_for": ["no model answered"], "backend_errors": errors})
    return row


def sft_row(row: dict) -> dict:
    """One teachable example, carrying its teacher lineage for the provenance filter."""
    return {
        "messages": [
            {"role": "system", "content": VISION_TALK_SYSTEM},
            {"role": "user", "content": row["prompt"]},
            {"role": "assistant", "content": row["reply"]},
        ],
        "origin": {"lane": "talk", "teacher": row.get("model"), "teacher_lineage": "ollama-cloud",
                   "checked_by": "teach_talk.check", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "seed": row["seed"], "topic": row.get("topic")},
    }


def append(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def regrade() -> int:
    """Re-judge everything an EARLIER, worse grader threw away, and rescue what is teachable now.

    A grader fix is not finished when the code changes: the rows it wrongly binned are still good
    teaching data sitting in a reject pile. Nothing is rewritten or deleted — rescued rows are
    appended to talk-sft.jsonl and their ids recorded in promoted.jsonl, so running this twice
    cannot duplicate a row and the reject file keeps its full history of what was refused and why.
    """
    if not OUT_REJECTS.exists():
        log("regrade: nothing has been rejected yet")
        return 0
    done = set()
    if OUT_PROMOTED.exists():
        for line in OUT_PROMOTED.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["seed"])
            except (ValueError, KeyError):
                continue
    promoted = looked = 0
    for line in OUT_REJECTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        looked += 1
        if row.get("seed") in done or not row.get("reply"):
            continue
        if check(row["reply"], said=row["said"], latest=row["latest"], question=row.get("question")):
            continue
        append(OUT_ROWS, sft_row(row))
        append(OUT_PROMOTED, {"seed": row["seed"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "was_rejected_for": row.get("rejected_for"), "topic": row.get("topic")})
        promoted += 1
        log(f"  rescued [{row.get('topic')}] once refused for: {(row.get('rejected_for') or ['?'])[0]}")
    log(f"=== regrade: {promoted} of {looked} earlier rejections are teachable under today's grader")
    return promoted


def run_once(n: int) -> int:
    kept = 0
    base = int(time.time())
    log(f"=== teach-talk: drafting {n} turns on {LADDER[0]} (cloud — the 4090 stays free)")
    for i in range(n):
        row = one_turn(base + i)
        append(OUT_CALLS, row)
        if row["rejected_for"]:
            append(OUT_REJECTS, row)
            log(f"  {i+1}/{n} REJECTED [{row.get('topic')}] {row['rejected_for'][0]}")
        else:
            append(OUT_ROWS, sft_row(row))
            kept += 1
            log(f"  {i+1}/{n} kept     [{row.get('topic')}] {row['reply'][:90]}")
    log(f"=== kept {kept} of {n} — survivors in {OUT_ROWS.name}, the rest with their reason in {OUT_REJECTS.name}")
    return kept


# ─── the gate's own proof: every check tripped on a known-bad input ─────────────────────

def selftest() -> int:
    said = "i want a house right here with a big porch; two floors"
    latest = "two floors"
    q_wall = dict(vision_talk._QUESTIONS)["wall"]
    qs_wall, qs_roof = q_wall, dict(vision_talk._QUESTIONS)["roof"]
    good = "Got it, two floors. What are the outside walls made of, and what colour?"
    cases = [
        ("a clean reply passes", good, q_wall, []),
        ("empty is refused", "   ", q_wall, ["empty reply"]),
        ("a list is refused", "Got it, two floors.\n- brick\n- siding", q_wall, ["is a list"]),
        ("three sentences refused", "Got it, two floors. Nice. What are the walls made of and what colour?", q_wall, ["sentences"]),
        ("no question refused", "Got it, two floors. The walls sound lovely.", q_wall, ["question marks"]),
        ("two questions refused", "Two floors? What are the walls made of and what colour?", q_wall, ["question marks"]),
        ("wrong topic refused", "Got it, two floors. What kind of roof would you like?", q_wall, ["did not ask about wall"]),
        ("no repeat-back refused", "Lovely choice. What are the outside walls made of, and what colour?", q_wall, ["never repeated back"]),
        ("invented detail refused", "Got it, two floors with a red brick chimney. What are the walls made of and what colour?",
         q_wall, ["invented a detail"]),
        ("a question when none was given is refused", "Sounds ready. Shall we build it?", None, ["asked a question"]),
        ("no question given, none asked, passes", "That sounds ready — say build it whenever you like, with two floors.", None, []),
    ]
    # THE FIRST BATCH'S TWO REJECTIONS (2026-09-11) — both were the grader's fault. A compound
    # adjective ("a two-floor house") must never read as an invented detail or as a failure to
    # repeat back what the child said. These are the real replies, verbatim.
    real = [
        ("a compound adjective is not an invented detail",
         "You\u2019d like a two\u2011floor house with a porch swing and a garage on the left. "
         "What material and color would you like for the outside walls\u2014perhaps white siding or red brick?",
         "i want a house with a swing on the porch; a garage on the left; two floors; two floors", "two floors", qs_wall),
        ("a storey is a floor is a level — the order form's own field is \"stories\"",
         "You\u2019d like a three\u2011story house with a big porch. What kind of roof would you like\u2014shingles, metal, or flat?",
         "i want a house right here with a big porch; three floors please", "three floors please", qs_roof),
        ("a compound adjective still counts as repeating him back",
         "You\u2019d like a blue three\u2011floor house with a big porch and a swing. "
         "What kind of roof would you like\u2014shingles, metal, or flat?",
         "i want a house with a swing on the porch; a big porch; i want it blue; three floors please",
         "three floors please", qs_roof),
    ]
    passed = failed = 0
    for name, reply, said_r, latest_r, question in real:
        got = check(reply, said=said_r, latest=latest_r, question=question)
        ok = not got
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f" -> {got}"))
    for name, reply, question, expect in cases:
        got = check(reply, said=said, latest=latest, question=question)
        ok = (not expect and not got) or (expect and any(any(e in g for g in got) for e in expect))
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL {name}: expected {expect}, got {got}")
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    # the contract itself must still match the product, or this factory teaches the wrong shape
    product = (ROOT / "src" / "web" / "v17_say_routes.py").read_text(encoding="utf-8", errors="ignore")
    for label, needle in (("system prompt", "You are a kind builder talking with an eight-year-old"),
                          ("two-sentence rule", "Two sentences max. No lists."),
                          ("plain-text path (no envelope the cloud tag can never fill)", "_ollama_text(model, VISION_TALK_SYSTEM")):
        ok = needle in product
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"  {'ok  ' if ok else 'FAIL'} the product still uses this {label}")
    print(f"\n  {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--once", type=int, default=0, help="draft and grade this many turns")
    ap.add_argument("--regrade", action="store_true", help="rescue rows an earlier, worse grader binned")
    ap.add_argument("--model", default=None)
    ns = ap.parse_args()
    if ns.model:
        LADDER[0] = ns.model
    if ns.selftest:
        return selftest()
    if ns.regrade:
        regrade()
        if ns.once <= 0:
            return 0
    if ns.once > 0:
        run_once(ns.once)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
