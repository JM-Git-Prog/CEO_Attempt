"""sim-player/teach_sam.py — turn the nights Sam played into a training set Unsloth can read.

2026-09-14. John: "get sam training and learning how to build video game using v17", and then the
shape of it: "starting with text to create the picture that has the data needed to generate the
world." That is exactly one row of events-sim.jsonl, read left to right:

    input.prompt_rendered   a sentence a player typed, plus where they were standing
    card                    a complete build spec — name, style, material, footprint in cm,
                            storeys, roof, rooms, a build plan and replication notes

Sentence in, buildable data out. Teaching a model that mapping IS teaching it to build the world
from text, and every round Sam plays writes more of them for free.

WHY THIS FILE HAD TO EXIST. The loop has written those rows since 2026-09-10 and nothing on disk
has ever read them. `training-data/export.py` opens `events.jsonl` with the path hard-coded and no
override, so it cannot see `events-sim.jsonl` at all; `v17_say_routes.py` names a `train_student.py`
that filters `by == "john"`, and that file is not on this machine. Sam has been generating training
data into a dead end for four days.

WHAT IT REFUSES TO LEARN FROM, and why each one matters:
  * a row with no card                       — nothing to learn; the architect never answered
  * outcome.ok false, or an error            — teaching a model a failed turn teaches it to fail
  * confidence below V17's own floor (0.75)  — the app itself would not have acted on it
  * a card whose own gates did not pass      — the gate is the only judge that ran at the time
  * a duplicate sentence+card pair           — repetition is not evidence, it is weight
  * the underscore bookkeeping on a card     — _model, _latency_s, _id, _gates describe the RUN,
                                               not the house. A model that learns them learns to
                                               predict its own latency, which is noise wearing a
                                               field name.

PROVENANCE IS KEPT, NEVER MIXED. Every row carries `by`: "sim" when Sam typed the sentence,
"john" when John did. They are written to separate files and counted separately, because they are
different things — Sam's rows teach the MECHANICS of turning a sentence into a card, John's carry
his taste. Mixing them silently is how a taste model learns that a robot's opinion is its owner's.

stdlib only, so it runs on John's plain Python. Nothing here spends, renders or trains: it reads
two append-only logs and writes three files. Run the trainer separately, on purpose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CEO_DIR = Path(os.getenv("CEO_OF_MY_LIFE",
                         r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"))
EVENTS_SIM = Path(os.getenv("EVENTS_SIM", str(CEO_DIR / "training-data" / "events-sim.jsonl")))
EVENTS_JOHN = Path(os.getenv("EVENTS_JOHN", str(CEO_DIR / "training-data" / "events.jsonl")))
# Where the lessons land. 2026-09-14, John: "dont forget to save your training data to the proper
# folders." It was writing into sim-player/sim-runs/training - the LOOP's scratch space, which is
# reset, pruned and reasoned about as run debris. Training data is not debris. It belongs beside
# the other training data, in CEO-of-My-Life-Inc/training-data/, next to events.jsonl and export/,
# where RUN-EXPORT-TRAINING-DATA.bat and the trainer already look.
OUT_DIR = Path(os.getenv("SAM_TRAINSET", str(CEO_DIR / "training-data" / "sam-cards")))

CONFIDENCE_FLOOR = float(os.getenv("V17_CONFIDENCE_FLOOR", "0.75"))   # V17's own floor, same default
HOLDOUT_EVERY = 5                        # every 5th kept row is held out — a 20% exam, like the bench
# TWO MARKS, and I had been quoting only the soft one as if it were the standard.
#   SHAPE  200 is the size of the one training set that has actually produced a model on this
#          machine - data/flywheel/training/probe-v1.jsonl, 202 train + 50 holdout, through
#          bench/train_probe.py. Enough to teach a model the SHAPE of the job: emit a well-formed
#          build card with real centimetres in it. It is a precedent, not a threshold.
#   GATE   2000 accepted pairs is JOHN'S OWN written standard - doc 28, printed on screen every
#          time CATCH-UP-TRAINING-DATA.bat runs, line 50: "Training gate for your own model is
#          2000 accepted pairs (doc 28)." That is the bar for a model he would rely on.
# Reporting 200 as "the gate" was me reading the size of the last training set and mistaking it for
# the rule. Both are reported now, and the summary says which is which.
MIN_ROWS_TO_TRAIN = int(os.getenv("SAM_TRAIN_SHAPE", "200"))
TRAIN_GATE = int(os.getenv("SAM_TRAIN_GATE", "2000"))

# Card keys that describe the RUN rather than the house. Dropped from every target.
BOOKKEEPING = re.compile(r"^_")

SYSTEM = (
    "You are the architect of a 3D world. A player types one sentence and tells you where they are "
    "standing. Answer with the build card for what they asked for, as JSON only: what it is, its "
    "style, its materials and colours, its footprint in centimetres, and how to build it. "
    "Give real measurements, never placeholders."
)


# ----------------------------------------------------------------------------- reading

def rows(path: Path) -> list[dict]:
    """Every JSON object in an append-only log. A half-written last line is skipped, not fatal —
    the loop may be mid-write while this runs, and that must never cost the whole file."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def who(row: dict) -> str:
    """Who typed the sentence. The session prefix is the reliable marker: `card_decision.by` is
    present on only 5 of the first 74 sim rows, so filtering on it alone would let 69 through."""
    d = row.get("card_decision") or row.get("correction") or {}
    if isinstance(d, dict) and d.get("by"):
        return str(d["by"])
    return "sim" if str(row.get("session") or "").startswith("sim-") else "john"


def clean_card(card: dict) -> dict:
    """The house, with the paperwork removed. Order is preserved so the JSON a model learns to emit
    is stable across rows — a shuffled key order is a different string for the same house."""
    return {k: v for k, v in card.items() if not BOOKKEEPING.match(k) and v not in (None, "", [], {})}


def gates_passed(card: dict) -> bool:
    """The card's own gate verdicts, when it carries them. Absent gates are not a failure — early
    rows predate the field — but a recorded failure is."""
    g = card.get("_gates")
    if not isinstance(g, (dict, list)):
        return True
    vals = g.values() if isinstance(g, dict) else g
    for v in vals:
        s = str((v or {}).get("status") if isinstance(v, dict) else v).lower()
        if s in ("fail", "failed", "error"):
            return False
    return True


def usable(row: dict) -> tuple[bool, str]:
    """One row, one verdict, with the reason it was refused — the reasons are the report."""
    card = row.get("card")
    if not isinstance(card, dict) or not card:
        return False, "no card — the architect never answered"
    out = row.get("outcome") or {}
    if out.get("ok") is False or out.get("error"):
        return False, "the turn failed"
    res = row.get("result") or {}
    try:
        conf = float(res.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < CONFIDENCE_FLOOR:
        return False, f"confidence {conf:.2f} below V17's own floor {CONFIDENCE_FLOOR}"
    if not gates_passed(card):
        return False, "a gate on the card recorded a failure"
    msg = ((row.get("input") or {}).get("prompt_rendered")
           or (row.get("input") or {}).get("message") or "").strip()
    if len(msg) < 8:
        return False, "no sentence to learn from"
    if not clean_card(card):
        return False, "the card was nothing but bookkeeping"
    return True, ""


def sft_row(row: dict) -> dict:
    """ChatML, the shape bench/train_probe.py already trains on."""
    inp = row.get("input") or {}
    user = (inp.get("prompt_rendered") or inp.get("message") or "").strip()
    card = clean_card(row["card"])
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(card, ensure_ascii=False)},
        ],
        "by": who(row),
        "event_id": row.get("event_id"),
        "ts": row.get("ts"),
        "teacher": ((row.get("model") or {}).get("architect")
                    or (row.get("model") or {}).get("route")),
    }


def fingerprint(r: dict) -> str:
    """A sentence answered the same way twice is one lesson, not two."""
    m = r["messages"]
    return hashlib.sha1((m[1]["content"] + "\x00" + m[2]["content"]).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- building

def build(sim_path: Path, john_path: Path, out_dir: Path, *, include_john: bool = False) -> dict:
    raw = [(r, "sim") for r in rows(sim_path)]
    if include_john:
        raw += [(r, "john") for r in rows(john_path)]

    kept, refused, seen = [], {}, set()
    for row, _src in raw:
        ok, why = usable(row)
        if not ok:
            refused[why] = refused.get(why, 0) + 1
            continue
        r = sft_row(row)
        fp = fingerprint(r)
        if fp in seen:
            refused["a duplicate sentence and card"] = refused.get("a duplicate sentence and card", 0) + 1
            continue
        seen.add(fp)
        kept.append(r)

    kept.sort(key=lambda r: r.get("ts") or "")
    train = [r for i, r in enumerate(kept) if (i + 1) % HOLDOUT_EVERY]
    exam = [r for i, r in enumerate(kept) if not (i + 1) % HOLDOUT_EVERY]

    out_dir.mkdir(parents=True, exist_ok=True)
    t_path, e_path = out_dir / "sam-cards-v1.jsonl", out_dir / "sam-cards-v1-holdout.jsonl"
    for path, data in ((t_path, train), (e_path, exam)):
        with open(path, "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by = {}
    for r in kept:
        by[r["by"]] = by.get(r["by"], 0) + 1
    teachers = {}
    for r in kept:
        teachers[r["teacher"] or "unknown"] = teachers.get(r["teacher"] or "unknown", 0) + 1

    report = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "read": {"events-sim.jsonl": len(rows(sim_path)),
                 "events.jsonl": len(rows(john_path)) if include_john else "not read"},
        "kept": len(kept), "train": len(train), "holdout": len(exam),
        "by": by, "teachers": teachers, "refused": refused,
        "train_file": str(t_path), "holdout_file": str(e_path),
        "ready_to_train": len(train) >= MIN_ROWS_TO_TRAIN,
        "rows_still_needed": max(0, MIN_ROWS_TO_TRAIN - len(train)),
        "gate": TRAIN_GATE, "rows_to_gate": max(0, TRAIN_GATE - len(train)),
        "past_gate": len(train) >= TRAIN_GATE,
    }
    (out_dir / "SUMMARY.md").write_text(summary_md(report), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def summary_md(rep: dict) -> str:
    lines = [f"# Sam's training set — {rep['at']}", "",
             f"**{rep['kept']} lessons kept** — {rep['train']} to train on, {rep['holdout']} held back as an exam.", ""]
    if rep["past_gate"]:
        lines += [f"**Past your own gate** — {rep['train']} of the {rep['gate']} accepted pairs doc 28 "
                  f"asks for. Train it.", ""]
    elif rep["ready_to_train"]:
        lines += [f"**Enough to teach the shape** ({MIN_ROWS_TO_TRAIN}+) — a run now would produce a model "
                  f"that emits a well-formed build card. That is the size of the probe set that has "
                  f"trained on this machine before, not a quality bar.",
                  f"**Your own gate is {rep['gate']}** (doc 28, accepted pairs) and is "
                  f"{rep['rows_to_gate']} rows away. A model trained at {rep['train']} can copy the "
                  f"format; one trained at {rep['gate']} is the one you said you would rely on.", ""]
    else:
        lines += [f"**Not enough for either mark.** {rep['rows_still_needed']} more rows to reach "
                  f"{MIN_ROWS_TO_TRAIN} (the smallest set that has ever trained here — teaches the shape), "
                  f"{rep['rows_to_gate']} more to reach {rep['gate']} (doc 28, your own gate). "
                  f"Keep the loop running.", ""]
    lines += ["## Who taught what", ""]
    for k, v in sorted(rep["by"].items()):
        lines.append(f"- **{k}** — {v} rows")
    lines += ["", "## Which architect wrote the card", ""]
    for k, v in sorted(rep["teachers"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{k}` — {v}")
    lines += ["", "## What was refused, and why", ""]
    if not rep["refused"]:
        lines.append("- nothing")
    for k, v in sorted(rep["refused"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- {v} × {k}")
    lines += ["", "---", f"Read: `{rep['read']}`", f"Train file: `{rep['train_file']}`"]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- proof

def selftest() -> int:
    import tempfile
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (("  — " + detail) if detail and not ok else ""))
        if not ok:
            fails.append(name)

    def ev(**kw):
        base = {"event_id": kw.pop("eid", "e" + str(len(made))), "ts": kw.pop("ts", "2026-09-14T00:00:0%dZ" % (len(made) % 10)),
                "session": kw.pop("session", "sim-aaa"), "stage": "say",
                "input": {"prompt_rendered": kw.pop("msg", "I want a red house with a porch")},
                "outcome": {"ok": True}, "result": {"confidence": 0.99},
                "model": {"architect": "gpt-oss:120b-cloud"},
                "card": {"name": "A House", "style": "Colonial", "width_cm": 900,
                         "_model": "x", "_latency_s": [1, 2], "_id": "abc"}}
        base.update(kw)
        made.append(base)
        return base

    print("teach_sam self-test")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        made: list[dict] = []
        good = ev()
        ev(msg="I want a blue house", card={"name": "Blue", "style": "Cape", "_id": "z"})
        ev(msg="nothing happened", result={"confidence": 0.2})                       # below the floor
        ev(msg="I want a shed", card=None)                                            # no card
        ev(msg="I want a barn", outcome={"ok": False, "error": "backend"})            # failed turn
        ev(msg="I want a red house with a porch")                                     # duplicate of good
        ev(msg="I want a gated house", card={"name": "G", "_gates": {"plan": {"status": "fail"}}})
        john = ev(session="7f3c-not-a-sim", msg="I want John's house", ts="2026-09-14T00:00:09Z")

        simf, johnf = tmp / "events-sim.jsonl", tmp / "events.jsonl"
        with open(simf, "w", encoding="utf-8") as f:
            for r in made:
                if r is not john:
                    f.write(json.dumps(r) + "\n")
            f.write("{ this line is half-written\n")            # the loop, mid-write
        johnf.write_text(json.dumps(john) + "\n", encoding="utf-8")

        rep = build(simf, johnf, tmp / "out")
        check("a half-written last line does not cost the file", rep["kept"] == 2, json.dumps(rep["refused"]))
        check("the low-confidence turn was refused", any("floor" in k for k in rep["refused"]))
        check("the card-less turn was refused", any("no card" in k for k in rep["refused"]))
        check("the failed turn was refused", any("failed" in k for k in rep["refused"]))
        check("the failed gate was refused", any("gate" in k for k in rep["refused"]))
        check("the duplicate was refused", any("duplicate" in k for k in rep["refused"]))
        check("John's row was not read unless asked for", rep["by"].get("john") is None, str(rep["by"]))

        got = [json.loads(l) for l in open(tmp / "out" / "sam-cards-v1.jsonl", encoding="utf-8")]
        card = json.loads(got[0]["messages"][2]["content"])
        check("the bookkeeping is gone from what it learns",
              not any(k.startswith("_") for k in card), str(list(card)))
        check("the house itself survived", card.get("width_cm") == 900 and card.get("style") == "Colonial", str(card))
        check("the sentence is the question", "red house" in got[0]["messages"][1]["content"])
        check("every row says who typed it", all(r["by"] == "sim" for r in got), str([r["by"] for r in got]))
        check("it knows it is not ready to train yet", rep["ready_to_train"] is False and rep["rows_still_needed"] > 0)

        rep2 = build(simf, johnf, tmp / "out2", include_john=True)
        check("John's rows come in only when asked, and stay labelled",
              rep2["by"].get("john") == 1 and rep2["by"].get("sim") == 2, str(rep2["by"]))
        check("a summary is written for a human to read", (tmp / "out2" / "SUMMARY.md").exists())

    print("ALL GREEN" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails))
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Turn Sam's played rounds into an Unsloth training set.")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--include-john", action="store_true",
                    help="also read John's own events.jsonl (kept labelled by=john, never merged silently)")
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    rep = build(EVENTS_SIM, EVENTS_JOHN, Path(a.out), include_john=a.include_john)
    print(summary_md(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
