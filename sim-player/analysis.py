"""sim-player/analysis.py — the Sam Loop's analysis pass.

One round (a folder with transcript.jsonl) in; a scored, filed, reported round out: (1) deterministic
counts, never from a model; (2) per-wish verdicts — deterministic first (got/cant_yet/nothing from the
transcript's own shape), everything left "undecided" goes to a judge model ONCE per round as a draft
label ("draft:<model>"), never a silent default — a judge that fails leaves those wishes "unjudged"
with the reason recorded; (3) defects — what broke, deterministically; (4) capability gaps — one
append-only ledger line per wish the app couldn't meet, per-round dedup only, never cross-run; (5)
REPORT.md for the round plus a rolling SAM-LOOP-REPORT.md for the last 7 rounds. stdlib only.

CLI:
    python analysis.py --round <dir> [--no-judge] [--ledger <path>]
    python analysis.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402  (path must be set up first)

SLOW_SECONDS = 240
WISH_VERDICTS = ("got", "other", "nothing", "cant_yet")
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turn": {"type": "integer"},
                    "verdict": {"type": "string", "enum": list(WISH_VERDICTS)},
                    "evidence": {"type": "string"},
                },
                "required": ["turn", "verdict", "evidence"],
            },
        },
    },
    "required": ["verdicts"],
}
JUDGE_SYSTEM = (
    "You are grading one play session of 'The Living Room', a home-building app a ten-year-old (Sam) "
    "plays by chat. undecided_wishes lists wishes the deterministic scorer could not resolve; you get "
    "a compact transcript and the final row too. For each undecided wish return exactly one verdict: "
    "'got' (actually built/placed), 'cant_yet' (the app said it can't do this yet), 'nothing' (session "
    "ended before anything happened for it), or 'other' (no clean fit for the other three). Use only "
    "the transcript given. One entry per requested turn, with a short evidence quote or paraphrase."
)
STOPWORDS = {
    "want", "wants", "wanted", "the", "a", "an", "in", "on", "at", "with", "for", "right", "here",
    "my", "i", "to", "and", "some", "just", "really", "please", "can", "get", "got", "make", "put",
    "it", "is", "of", "be", "like", "one", "that", "this",
}

def _parse_t(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def _content_words(text: str | None) -> set:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}

def _shares_word(phrase, wish_text: str) -> bool:
    wa, wb = _content_words(str(phrase)), _content_words(wish_text)
    if not wb:            # wish has no meaningful words to compare against — can't rule it out
        return True
    return bool(wa & wb)

def _infer_target(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("house", "home", "porch", "roof", "door", "garage", "window")):
        return "house"
    if any(w in t for w in ("yard", "tree", "dog", "pool", "fence", "mailbox", "driveway", "street")):
        return "grounds"
    if any(w in t for w in ("room", "kitchen", "bed", "inside")):
        return "room"
    return "unknown"

def _changes_seen(rows: list[dict]) -> int:
    seen_done = set()
    n = 0
    for r in rows:
        wv_b, wv_a = r.get("world_version_before"), r.get("world_version_after")
        changed = wv_b is not None and wv_a is not None and wv_a > wv_b
        if not changed:
            order = r.get("order")
            if order and order.get("stage") == "done" and order.get("id") not in seen_done:
                seen_done.add(order.get("id"))
                changed = True
        if changed:
            n += 1
    return n

def _questions_answered(rows: list[dict]) -> int:
    n, prev = 0, None
    for r in rows:
        if prev is not None:
            if (prev.get("response") or {}).get("question") and r.get("wish") is False:
                n += 1
        prev = r
    return n

def _wall_counts(rows: list[dict]) -> tuple[int, int]:
    posted, picked = set(), set()
    for r in rows:
        w = r.get("wall")
        if w and w.get("station"):
            posted.add(w["station"])
            if w.get("picked") is not None:
                picked.add(w["station"])
    return len(posted), len(picked)

def _card_counts(rows: list[dict]) -> tuple[int, int]:
    """Top-level row `card` = {id, name, decision} — the pick, not the plan-gate card."""
    shown, built = set(), 0
    for r in rows:
        c = r.get("card")
        if c and c.get("id"):
            shown.add(c["id"])
        if c and c.get("decision") == "build":
            built += 1
    return len(shown), built

def _http_counts(rows: list[dict]) -> tuple[int, int, int]:
    errors = fives = excs = 0
    for r in rows:
        status, err = r.get("http_status"), r.get("error")
        if (status is not None and status >= 400) or err is not None:
            errors += 1
        if status is not None and status >= 500:
            fives += 1
        if err is not None and status is None:
            excs += 1
    return errors, fives, excs

def _build_completions(rows: list[dict]) -> list[dict]:
    """For each row where a card was decided 'build', the seconds to the first later row where the
    order reaches 'done' or the world version moves. Rows must already be turn-ordered."""
    out = []
    for i, r in enumerate(rows):
        card = r.get("card")
        if not card or card.get("decision") != "build":
            continue
        t0 = _parse_t(r.get("t"))
        if t0 is None:
            continue
        for later in rows[i + 1:]:
            order = later.get("order") or {}
            wv_b, wv_a = later.get("world_version_before"), later.get("world_version_after")
            moved = wv_b is not None and wv_a is not None and wv_a > wv_b
            if order.get("stage") == "done" or moved:
                t1 = _parse_t(later.get("t"))
                if t1 is not None:
                    out.append({"turn": r.get("turn"), "card_id": card.get("id"),
                                "seconds": (t1 - t0).total_seconds(), "done_turn": later.get("turn")})
                break
    return out

def _counts(rows: list[dict], final_row: dict, completions: list[dict]) -> dict:
    walls_posted, walls_picked = _wall_counts(rows)
    cards_shown, cards_built = _card_counts(rows)
    http_errors, http_5xx, exceptions = _http_counts(rows)
    seconds = [round(c["seconds"], 1) for c in completions]
    return {
        "turns": len(rows),
        "wishes": sum(1 for r in rows if r.get("wish") is True),
        "changes_seen": _changes_seen(rows),
        "nothing_streak_max": max((r.get("streak_nothing") or 0) for r in rows) if rows else 0,
        "questions_asked": sum(1 for r in rows if (r.get("response") or {}).get("question")),
        "questions_answered": _questions_answered(rows),
        "walls_posted": walls_posted, "walls_picked": walls_picked,
        "cards_shown": cards_shown, "cards_built": cards_built,
        "http_errors": http_errors, "http_5xx": http_5xx, "exceptions": exceptions,
        "seconds_build_to_house": seconds, "slow": sum(1 for s in seconds if s > SLOW_SECONDS),
        "reason_ended": final_row.get("reason_ended"),
        "world_versions": {"start": final_row.get("world_version_start"),
                            "end": final_row.get("world_version_end")},
    }

def _defects(rows: list[dict], completions: list[dict]) -> list[dict]:
    out, wall_seen = [], {}
    for r in rows:
        status, err, turn = r.get("http_status"), r.get("error"), r.get("turn")
        resp = r.get("response") or {}
        route = (r.get("request") or {}).get("route") or "/api/v17/say"
        excerpt = json.dumps(r.get("response"), ensure_ascii=False)[:600] if r.get("response") is not None else "null"

        if status is not None and status >= 500:
            out.append({"kind": "http_5xx", "turn": turn, "detail": f"HTTP {status}", "route": route, "excerpt": excerpt})
        elif status is not None and 400 <= status < 500:
            if status == 404 and err and "gone" in str(err).lower():
                out.append({"kind": "order_lost", "turn": turn, "detail": str(err), "route": route, "excerpt": excerpt})
            else:
                out.append({"kind": "http_4xx", "turn": turn, "detail": f"HTTP {status}", "route": route, "excerpt": excerpt})

        if err is not None and status is None:
            out.append({"kind": "exception", "turn": turn, "detail": str(err), "route": route, "excerpt": excerpt})

        rcard = resp.get("card")  # the plan-gate card lives inside the response, not the top-level pick
        if rcard and (not rcard.get("plan") or not rcard.get("summary")):
            out.append({"kind": "no_card_plan", "turn": turn, "detail": f"card {rcard.get('id')} missing plan/summary",
                        "route": route, "excerpt": excerpt})

        kind = resp.get("kind")
        if kind == "vision" and not resp.get("reply"):
            out.append({"kind": "bad_reply", "turn": turn, "detail": "empty vision reply", "route": route, "excerpt": excerpt})
        if kind == "unknown" and not resp.get("clarify"):
            out.append({"kind": "bad_reply", "turn": turn, "detail": "unknown with no clarify", "route": route, "excerpt": excerpt})

        wall = r.get("wall")
        if wall and wall.get("station"):
            st = wall["station"]
            entry = wall_seen.setdefault(st, {"first_turn": turn, "picked": False, "route": route, "excerpt": excerpt})
            if wall.get("picked") is not None:
                entry["picked"] = True

    for st, info in wall_seen.items():
        if not info["picked"]:
            out.append({"kind": "wall_unanswered", "turn": info["first_turn"], "detail": f"wall {st} never answered",
                        "route": info["route"], "excerpt": info["excerpt"]})

    for c in completions:
        if c["seconds"] > SLOW_SECONDS:
            out.append({"kind": "slow", "turn": c["turn"],
                        "detail": f"{c['seconds']:.0f}s from build decision to house (card {c['card_id']})",
                        "route": "/api/v17/say", "excerpt": ""})

    out.sort(key=lambda d: d["turn"] if d["turn"] is not None else -1)
    return out

def _deterministic_verdict(wish: dict, window: list[dict], next_row: dict | None, reason_ended, last_wish_turns: set):
    """`window` is the rows strictly between this wish and Sam's NEXT wish (or end of round, for the
    last wish) — the "got" check is bounded to it so an unrelated later build never gets credited to
    an earlier, different wish. `next_row` (the very next transcript row, wish-window or not) is
    still used for the cant_yet check, matching the app's immediate reply."""
    wish_before = wish.get("world_version_before")
    wish_text = wish.get("i_type") or ""

    if wish_before is not None:
        for r in window:
            wv_a, wv_b = r.get("world_version_after"), r.get("world_version_before")
            if wv_a is None or wv_a <= wish_before:
                continue
            order, card = r.get("order") or {}, r.get("card") or {}
            if order.get("stage") == "done":
                return "got", f"order {order.get('id')} done at world version {wv_a}"
            if card.get("decision") == "build" and wv_b is not None and wv_a > wv_b:
                return "got", f"card {card.get('id')} built, world version {wv_a}"

    for r in [wish, next_row]:
        if r is None:
            continue
        resp = r.get("response") or {}
        # V17's receipt.needs is one string ("three storeys (the workshop can't do that yet)"); gaps_filed is a list
        needs = (resp.get("receipt") or {}).get("needs")
        phrases = ([needs] if isinstance(needs, str) and needs.strip() else list(needs or [])) + [str(g) for g in (resp.get("gaps_filed") or [])]
        for phrase in phrases:
            if _shares_word(str(phrase), wish_text):
                wish["_phrase"] = str(phrase)
                return "cant_yet", "the app said it can't make that yet: " + str(phrase)
        if resp.get("kind") == "gap":
            wish["_phrase"] = wish_text
            return "cant_yet", "the app answered that it can't make that yet (kind=gap)"

    if reason_ended == "streak" and wish.get("turn") in last_wish_turns:
        return "nothing", "session ended on a nothing-happened streak"

    return None, None

def _wishes(rows: list[dict], final_row: dict) -> tuple[list[dict], list[dict]]:
    wish_rows = [r for r in rows if r.get("wish") is True]
    last_wish_turns = {r["turn"] for r in wish_rows[-3:]}
    reason_ended = final_row.get("reason_ended")

    results, undecided = [], []
    for i, w in enumerate(wish_rows):
        wt = w.get("turn", -1)
        hi = wish_rows[i + 1].get("turn") if i + 1 < len(wish_rows) else None
        window = [r for r in rows if r.get("turn", -1) > wt and (hi is None or r.get("turn", -1) < hi)]
        next_row = next((r for r in rows if r.get("turn", -1) > wt), None)
        verdict, evidence = _deterministic_verdict(w, window, next_row, reason_ended, last_wish_turns)
        entry = {"turn": w.get("turn"), "text": w.get("i_type") or "", "verdict": verdict,
                  "evidence": evidence, "judge": "deterministic", "phrase": w.get("_phrase") or (w.get("i_type") or "")}
        if verdict is None:
            undecided.append(entry)
        results.append(entry)
    return results, undecided

def _compact_transcript(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        resp = r.get("response") or {}
        top_card, wall, order = r.get("card") or {}, r.get("wall") or {}, r.get("order") or {}
        out.append({
            "turn": r.get("turn"), "i_see": r.get("i_see"), "i_type": r.get("i_type"),
            "response_kind": resp.get("kind"), "receipt": resp.get("receipt"), "question": resp.get("question"),
            "card_name": top_card.get("name") or (resp.get("card") or {}).get("name"),
            "wall_picked": wall.get("picked"), "order_stage": order.get("stage"),
            "world_version": r.get("world_version_after"),
        })
    return out

def _call_judge(ask_fn, schema) -> tuple[dict | None, str | None]:
    fail_kind = "backend"
    for _ in range(3):
        try:
            result = ask_fn(JUDGE_SYSTEM, [], schema)
        except common.Backend:
            fail_kind = "backend"
            continue
        parsed = result.get("json") if isinstance(result, dict) else None
        if isinstance(parsed, dict) and isinstance(parsed.get("verdicts"), list):
            return parsed, None
        fail_kind = "unparseable"
    return None, fail_kind

def _run_judge(ask_fn, model: str, undecided: list[dict], rows: list[dict], final_row: dict) -> str:
    """Mutates each undecided entry in place with its final verdict/evidence/judge label."""
    payload = {"undecided_wishes": [{"turn": e["turn"], "text": e["text"]} for e in undecided],
               "transcript": _compact_transcript(rows), "final": final_row}
    messages = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    bound = lambda system, _msgs, schema: ask_fn(system, messages, schema)  # noqa: E731
    parsed, fail_kind = _call_judge(bound, JUDGE_SCHEMA)

    if parsed is None:
        for e in undecided:
            e["verdict"], e["evidence"], e["judge"] = "unjudged", f"judge {fail_kind}", "unjudged"
        return fail_kind

    by_turn = {}
    for v in parsed.get("verdicts", []):
        if isinstance(v, dict) and v.get("verdict") in WISH_VERDICTS:
            by_turn[v.get("turn")] = (v["verdict"], v.get("evidence") or "")

    label = f"draft:{model}"
    for e in undecided:
        if e["turn"] in by_turn:
            e["verdict"], e["evidence"] = by_turn[e["turn"]]
            e["judge"] = label
        else:
            e["verdict"], e["evidence"], e["judge"] = "unjudged", "judge did not return a verdict for this wish", "unjudged"
    return "ok"

def _file_gaps(wishes: list[dict], rows_by_turn: dict, round_id: str, ledger: Path) -> list[str]:
    seen, filed = set(), []
    for w in wishes:
        if w["verdict"] not in ("cant_yet", "nothing"):
            continue
        row = rows_by_turn.get(w["turn"], {})
        session = row.get("session") or (row.get("request") or {}).get("session") or "unknown-session"
        wish_text = w["text"]
        # the phrase is what the app itself called unbuildable when it said so; otherwise the wish as typed
        phrase = w.get("phrase") or wish_text
        gid = hashlib.sha1(f"sim-user{wish_text}{phrase}".encode("utf-8")).hexdigest()[:12]
        if gid in seen:
            filed.append(gid)
            continue
        seen.add(gid)
        row_obj = {
            "id": gid, "at": common.now_iso(), "source": "sim-user", "session": session,
            "request": wish_text, "phrase": phrase, "model": None,
            "context": {"target": _infer_target(wish_text), "world": common.SIM_SLUG,
                        "round": round_id, "loop": "sam-loop", "verdict": w["verdict"]},
            "status": "new",
        }
        common.capture(ledger, row_obj)  # append-only, creates the file if missing — never read-modify-write
        filed.append(gid)
    return filed

def _headline(round_id, wishes: list[dict], defects: list[dict]) -> str:
    total = len(wishes)
    got = sum(1 for w in wishes if w["verdict"] == "got")
    cant = sum(1 for w in wishes if w["verdict"] == "cant_yet")
    nowhere = total - got - cant
    ndef = len(defects)
    return (f"Round {round_id}: Sam made {total} wishes, got {got}, the app said can't-yet to {cant}, "
            f"{nowhere} went nowhere; {ndef} {'defect' if ndef == 1 else 'defects'}.")

def _md_cell(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")

def _report_md(analysis: dict, final_row: dict) -> str:
    lines = [_headline(analysis["round"], analysis["wishes"], analysis["defects"]), "",
             "| Turn | Wish | Verdict | Evidence |", "|---|---|---|---|"]
    for w in analysis["wishes"]:
        lines.append(f"| {w['turn']} | {_md_cell(w['text'])} | {w['verdict']} | {_md_cell(w['evidence'])} |")

    lines += ["", "## What went wrong"]
    if analysis["defects"]:
        for d in analysis["defects"]:
            lines.append(f"- turn {d['turn']} — {d['kind']}: {d['detail']} ({d['route']})")
    else:
        lines.append("- none")

    lines += ["", "## Sam's own words at the end"]
    didnt_get = final_row.get("didnt_get") or []
    if didnt_get:
        lines += [f"- {phrase}" for phrase in didnt_get]
    else:
        lines.append("- (nothing left unsaid)")

    lines += ["", "## Counts"]
    lines += [f"- {k}: {v}" for k, v in analysis["counts"].items()]
    return "\n".join(lines) + "\n"

def _rolling_report(runs_dir: Path) -> None:
    """Rewritten from the analysis.json files on disk every time — the loop owns this file, so a
    read-then-rewrite here (unlike the ledger) is fine."""
    entries = []
    for p in sorted(runs_dir.glob("*/analysis.json")):
        try:
            entries.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    entries.sort(key=lambda d: d.get("at") or "")   # stable sort: dir-name order breaks any tie
    last7 = entries[-7:]

    lines = ["# Sam Loop — rolling report", "",
              f"_last updated {common.now_iso()} · {len(last7)} of {len(entries)} rounds shown_",
              "", "## Recent rounds"]
    lines += [f"- {_headline(d.get('round'), d.get('wishes', []), d.get('defects', []))}" for d in last7]

    tally = Counter()
    for d in last7:
        for w in d.get("wishes", []):
            if w.get("verdict") in ("nothing", "cant_yet"):
                tally[(w.get("text") or "").strip().lower()] += 1

    lines += ["", "## Most wanted, never got"]
    if tally:
        lines += [f"- {text} — {n}" for text, n in tally.most_common(10)]
    else:
        lines.append("- (nothing outstanding)")

    (runs_dir / "SAM-LOOP-REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

def analyze(round_dir: Path, *, ask=None, ledger: Path | None = None, judge_model: str | None = None,
            no_judge: bool = False) -> dict:
    round_dir = Path(round_dir)
    ledger = Path(ledger) if ledger else common.GAP_LEDGER

    all_rows = common.read_jsonl(round_dir / "transcript.jsonl")
    rows = sorted((r for r in all_rows if "turn" in r), key=lambda r: r["turn"])
    final_row = next((r for r in all_rows if r.get("final")), {})
    rows_by_turn = {r["turn"]: r for r in rows}

    completions = _build_completions(rows)
    counts = _counts(rows, final_row, completions)
    wishes, undecided = _wishes(rows, final_row)

    judge_status, used_model = "skipped", None
    if no_judge:
        for e in undecided:
            e["verdict"], e["evidence"], e["judge"] = "unjudged", "judge skipped (--no-judge)", "unjudged"
    elif undecided:
        used_model = judge_model or common.pick_lane("judge")   # a label for the report; ask_lane picks the live rung
        ask_fn = ask or (lambda system, messages, schema:
                          common.ask_lane("judge", system, messages, schema=schema,
                                          lanes=[judge_model] if judge_model else None,
                                          num_predict=2500, temperature=0.2, timeout=240,
                                          ledger=round_dir.parent / "lane-ledger.jsonl",
                                          capture_to=round_dir / "calls.jsonl", purpose="judge"))
        judge_status = _run_judge(ask_fn, used_model, undecided, rows, final_row)

    defects = _defects(rows, completions)
    gaps_filed = _file_gaps(wishes, rows_by_turn, round_dir.name, ledger)

    analysis = {
        "round": round_dir.name, "at": common.now_iso(), "counts": counts,
        "wishes": wishes, "defects": defects, "gaps_filed": gaps_filed,
        "judge_model": used_model, "judge_status": judge_status,
    }
    (round_dir / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    (round_dir / "REPORT.md").write_text(_report_md(analysis, final_row), encoding="utf-8")
    _rolling_report(round_dir.parent)
    return analysis

# One JSONL round, sequenced so every wish's "got" window (rows up to Sam's NEXT wish) stays clean
# of unrelated later events. Wishes: turn1 house -> got (turn2's build+done, in its window). turn3
# rainbow slide -> undecided (its window, turns 4-6, is just error rows, so it goes to the fake
# judge — and it's not among the last 3 wishes, so a streak ending can't sweep it into "nothing"
# either). turn7 pool -> cant_yet (kind=gap, its own row). turn8 trampoline -> nothing (streak
# ending, last-3; turn9's build decision in its window never bumps world_version, so no false
# "got"). turn10 swing set -> got, and its build (turn11->turn12, 300s apart) is also the "slow"
# defect. Other routes: turn1 bad_reply(vision), turn4 http_5xx, turn5 order_lost, turn6 exception,
# turn9 no_card_plan, turn13 wall_unanswered.
_SELFTEST_JSONL = """
{"turn": 1, "t": "2026-09-10T20:00:00Z", "wish": true, "i_type": "I want a house right here", "world_version_before": 0, "world_version_after": 0, "http_status": 200, "error": null, "streak_nothing": 0, "response": {"kind": "vision", "reply": "", "question": null}}
{"turn": 2, "t": "2026-09-10T20:00:30Z", "wish": false, "i_type": "build it", "world_version_before": 0, "world_version_after": 1, "http_status": 200, "error": null, "streak_nothing": 0, "card": {"id": "c1", "name": "Cottage", "decision": "build"}, "order": {"id": "o1", "stage": "done"}, "response": {"kind": "house"}}
{"turn": 3, "t": "2026-09-10T20:01:00Z", "wish": true, "i_type": "I want a rainbow slide", "world_version_before": 1, "world_version_after": 1, "http_status": 200, "error": null, "streak_nothing": 0, "response": {"kind": "command"}}
{"turn": 4, "t": "2026-09-10T20:01:30Z", "wish": false, "i_type": "", "http_status": 500, "error": "boom", "world_version_before": 1, "world_version_after": 1, "streak_nothing": 1, "response": {"kind": "unknown"}}
{"turn": 5, "t": "2026-09-10T20:02:00Z", "wish": false, "i_type": "", "http_status": 404, "error": "order 9 is gone after restart", "world_version_before": 1, "world_version_after": 1, "streak_nothing": 2, "order": {"id": "o9", "stage": "building"}, "response": null}
{"turn": 6, "t": "2026-09-10T20:02:30Z", "wish": false, "i_type": "", "http_status": null, "error": "TimeoutError: reset", "world_version_before": 1, "world_version_after": 1, "streak_nothing": 3, "response": null}
{"turn": 7, "t": "2026-09-10T20:03:00Z", "wish": true, "i_type": "I want a pool in the yard", "world_version_before": 1, "world_version_after": 1, "http_status": 200, "error": null, "streak_nothing": 0, "response": {"kind": "gap", "gaps_filed": ["a swimming pool"]}}
{"turn": 8, "t": "2026-09-10T20:03:30Z", "wish": true, "i_type": "I want a trampoline", "world_version_before": 1, "world_version_after": 1, "http_status": 200, "error": null, "streak_nothing": 1, "response": {"kind": "command"}}
{"turn": 9, "t": "2026-09-10T20:04:00Z", "wish": false, "i_type": "let's build the shed", "http_status": 200, "error": null, "world_version_before": 1, "world_version_after": 1, "streak_nothing": 0, "card": {"id": "c2", "name": "Shed", "decision": "build"}, "response": {"kind": "house", "card": {"id": "c2", "name": "Shed", "summary": "", "plan": []}}}
{"turn": 10, "t": "2026-09-10T20:04:30Z", "wish": true, "i_type": "I want a swing set", "world_version_before": 1, "world_version_after": 1, "http_status": 200, "error": null, "streak_nothing": 2, "response": {"kind": "command"}}
{"turn": 11, "t": "2026-09-10T20:05:00Z", "wish": false, "i_type": "ok build it", "http_status": 200, "error": null, "world_version_before": 1, "world_version_after": 1, "streak_nothing": 0, "card": {"id": "c3", "name": "Swing Set", "decision": "build"}, "response": {"kind": "house"}}
{"turn": 12, "t": "2026-09-10T20:10:00Z", "wish": false, "i_type": "", "http_status": 200, "error": null, "world_version_before": 1, "world_version_after": 2, "streak_nothing": 0, "order": {"id": "o3", "stage": "done"}, "response": {"kind": "command"}}
{"turn": 13, "t": "2026-09-10T20:10:30Z", "wish": false, "i_type": "put a fence here", "http_status": 200, "error": null, "world_version_before": 2, "world_version_after": 2, "streak_nothing": 0, "wall": {"station": "grounds-x1", "picked": null, "why": null}, "response": {"kind": "command"}}
{"final": true, "reason_ended": "streak", "turns": 13, "didnt_get": ["a trampoline"], "world_version_start": 0, "world_version_end": 2}
""".strip()

def _selftest_transcript() -> list[dict]:
    rows = [json.loads(line) for line in _SELFTEST_JSONL.splitlines()]
    for r in rows:
        if "turn" in r:
            r.setdefault("request", {"session": "sim-selftest-01", "message": r.get("i_type", "")})
            for k in ("card", "order", "wall"):
                r.setdefault(k, None)
    return rows

def _selftest() -> bool:
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        if cond:
            print(f"ok: {label}")
        else:
            ok = False
            print(f"FAIL: {label} {detail}".rstrip())

    def fake_ask(system, messages, schema):
        return {"json": {"verdicts": [{"turn": 3, "verdict": "other", "evidence": "asked for a slide, nothing more said"}]}}

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        round_dir = base / "runs" / "round-selftest"
        round_dir.mkdir(parents=True)
        with open(round_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
            for row in _selftest_transcript():
                f.write(json.dumps(row) + "\n")
        ledger = base / "ledger.jsonl"

        result = analyze(round_dir, ask=fake_ask, ledger=ledger, judge_model="selftest-judge")

        check("analysis.json written", (round_dir / "analysis.json").exists())
        check("REPORT.md written", (round_dir / "REPORT.md").exists())
        check("rolling report written", (base / "runs" / "SAM-LOOP-REPORT.md").exists())

        verdicts = {w["turn"]: w for w in result["wishes"]}
        check("wish@1 got", verdicts.get(1, {}).get("verdict") == "got", detail=str(verdicts.get(1)))
        check("wish@7 cant_yet", verdicts.get(7, {}).get("verdict") == "cant_yet", detail=str(verdicts.get(7)))
        check("wish@8 nothing", verdicts.get(8, {}).get("verdict") == "nothing", detail=str(verdicts.get(8)))
        check("wish@10 got (slow build)", verdicts.get(10, {}).get("verdict") == "got", detail=str(verdicts.get(10)))
        check("wish@3 judged (draft label)", str(verdicts.get(3, {}).get("judge", "")).startswith("draft:"),
              detail=str(verdicts.get(3)))
        check("judge_status ok", result["judge_status"] == "ok")

        kinds = {d["kind"] for d in result["defects"]}
        for k in ("http_5xx", "order_lost", "exception", "no_card_plan", "wall_unanswered", "slow", "bad_reply"):
            check(f"defect kind present: {k}", k in kinds, detail=str(sorted(kinds)))

        ledger_lines = common.read_jsonl(ledger)
        check("gap ledger has rows", len(ledger_lines) >= 2, detail=str(len(ledger_lines)))
        if ledger_lines:
            keys = set(ledger_lines[0].keys())
            expected = {"id", "at", "source", "session", "request", "phrase", "model", "context", "status"}
            check("gap row has the contract keys", keys == expected, detail=str(keys))
            check("gap id is 12 hex chars", bool(re.fullmatch(r"[0-9a-f]{12}", ledger_lines[0]["id"])))

        # a Backend-raising judge must never invent a verdict
        def broken_ask(system, messages, schema):
            raise common.Backend("simulated outage")

        result2 = analyze(round_dir, ask=broken_ask, ledger=ledger, judge_model="selftest-judge")
        v3 = {w["turn"]: w for w in result2["wishes"]}.get(3, {})
        check("Backend judge -> unjudged, not a default", v3.get("verdict") == "unjudged" and v3.get("judge") == "unjudged",
              detail=str(v3))
        check("judge_status backend", result2["judge_status"] == "backend")

    print("ALL GREEN" if ok else "SOME FAILED")
    return ok

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sam Loop round analysis")
    ap.add_argument("--round", type=Path, help="round folder containing transcript.jsonl")
    ap.add_argument("--no-judge", action="store_true", help="skip the judge; undecided wishes become 'unjudged'")
    ap.add_argument("--ledger", type=Path, default=None, help="capability-gaps ledger path (default: common.GAP_LEDGER)")
    ap.add_argument("--selftest", action="store_true", help="run the built-in fixture + fake judge and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return 0 if _selftest() else 1
    if not args.round:
        ap.error("--round is required unless --selftest")

    result = analyze(args.round, ledger=args.ledger, no_judge=args.no_judge)
    common.log(f"analyzed {result['round']}: {_headline(result['round'], result['wishes'], result['defects'])}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
