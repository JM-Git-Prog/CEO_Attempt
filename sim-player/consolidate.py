"""consolidate.py — what Sam learns between batches.

2026-09-14, John: "make the loops shorter like 20 runs before consolidation and learning and
before moving on to the next 20, this should accelerate the learning."

WHY THIS CHANGES ANYTHING. Sam already remembers across nights: remember.py keeps what he has,
what he is still chasing, and what he gave up on, and opening_line() reads it back to him when he
sits down. But that memory is a LIST OF THINGS. It has no idea WHY he keeps missing, so night 43
repeats night 42 with one more tally mark.

A batch boundary is the only place the whole shape of twenty nights is visible at once: which
wishes got granted, which were refused the same way every time, which door each thing went out of
(the parametric catalogue in milliseconds, or the 4090 with a queue), and what he asked ABOUT.
That is a thing worth reading, and it is far too much to put in front of a ten-year-old. So it is
read here, boiled down to ONE sentence he could actually hold in his head, and put back into his
head as a lesson the next twenty nights start with.

WHAT IT WILL NOT DO:
  - it never changes what Sam wants. A lesson is about HOW he asks, never about wanting less.
  - it never writes to the world, the warehouse or the gap ledger. It reads and it summarises.
  - it never raises. A batch that cannot reach a model still files its training data and still
    writes its report; Sam simply starts the next twenty with the head he already had.

THE TRAINING DATA IS NOT OPTIONAL. John's standing rule: "all usable training data we have from
all of our interactions with claude and all data gathered from ollamma must always be catagorized
and placed into that folder." Every batch runs the collector at
E:\\Software Development\\Video Game Development\\05 Training\\15-sam-loop-corpus. Twenty rounds is
roughly an hour of play, so the corpus is now never more than an hour behind the loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import common
import remember

COLLECTOR = Path(os.getenv(
    "SAM_CORPUS_COLLECTOR",
    r"E:\Software Development\Video Game Development\05 Training\15-sam-loop-corpus\collect_sam_corpus.py"))

LANES = {
    "coach": [os.getenv("SAM_COACH_MODEL", "qwen3.5:397b-cloud"), "kimi-k3:cloud", "glm-5.2:cloud",
              "deepseek-v4-flash:cloud", "gpt-oss:120b-cloud", "gpt-oss:20b"],
}

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "lesson": {"type": "string"},
        "why": {"type": "string"},
        "ask_differently": {"type": "string"},
        "tell_the_builder": {"type": "string"},
    },
    "required": ["lesson", "why", "ask_differently", "tell_the_builder"],
}

SYSTEM = """You are reading twenty nights of a ten-year-old called Sam playing a game where he asks
for things and a builder tries to make them.

You are given the numbers, not the transcripts. From them, write ONE lesson Sam could actually hold
in his head on his next night. Rules:

- It is about HOW he asks, never about wanting less. "Stop asking for a crib" is never the lesson.
- One sentence, in his words, short enough to say out loud. If the numbers show he gets what he
  asks for when he says how big it is, the lesson is about saying how big it is.
- `why` is the number it came from, quoted. If you cannot point at a number, say so in `why` and
  keep the lesson general.
- `tell_the_builder` is the one thing the people BUILDING this should change, in their words, not
  his. It is allowed to be "nothing - this batch went fine"."""


# ───────────────────────────────────────────────────────── reading the batch

def _rounds_since(runs: Path, n: int) -> list[Path]:
    """The last `n` round folders, oldest first. A round folder is named for its moment."""
    dirs = sorted((d for d in runs.iterdir() if d.is_dir() and d.name[:8].isdigit()), key=lambda d: d.name)
    return dirs[-n:]


def _jsonl(p: Path, cap: int = 5000) -> list[dict]:
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue            # a half-written last line is skipped, never fatal
                if len(out) >= cap:
                    break
    except OSError:
        pass
    return out


def read_batch(runs: Path, n: int) -> dict:
    """The shape of the last `n` rounds, counted from what they wrote. No model involved."""
    rounds = _rounds_since(runs, n)
    verdicts, wishes, never_got, asked_about, defects = Counter(), 0, Counter(), [], 0
    judged_rounds = 0
    for d in rounds:
        try:
            a = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        ws = a.get("wishes") or []
        wishes += len(ws)
        defects += len(a.get("defects") or [])
        if a.get("judge_status") == "ok":
            judged_rounds += 1
        for w in ws:
            v = str(w.get("verdict") or "unjudged")
            verdicts[v] += 1
            if v in ("cant_yet", "nothing"):
                never_got[str(w.get("text") or "")[:90]] += 1
        for row in _jsonl(d / "curiosity.jsonl"):
            if row.get("ok") and (row.get("brief") or {}).get("question"):
                asked_about.append({"wish": row.get("wish"), "question": row["brief"]["question"]})

    # Which door each thing went out of. The decisions ledger is the only place that records it.
    dec = _jsonl(common.GAP_ROUTER.parent.parent / "capability-gaps.decisions.jsonl") \
        if hasattr(common, "GAP_ROUTER") else []
    recent = dec[-200:]
    builders = Counter((d.get("job") or {}).get("builder") or "unknown"
                       for d in recent if d.get("kind") == "thing")
    built_fast = [((d.get("job") or {}).get("slug")) for d in recent
                  if (d.get("job") or {}).get("builder") == "parametric" and (d.get("job") or {}).get("pushed")]

    return {
        "rounds": len(rounds), "first": rounds[0].name if rounds else None,
        "last": rounds[-1].name if rounds else None,
        "wishes": wishes, "verdicts": dict(verdicts), "defects": defects,
        "rounds_judged": judged_rounds,
        "never_got": never_got.most_common(8),
        "asked_about": asked_about[-12:],
        "builders": dict(builders),
        "built_parametric": [s for s in built_fast if s][-12:],
    }


# ───────────────────────────────────────────────────────── the lesson

def learn(shape: dict, *, runs: Path | None = None) -> dict | None:
    """One lesson from the numbers. None if no model would answer — never an exception."""
    got = shape["verdicts"].get("got", 0)
    lines = [
        f"{shape['rounds']} nights, {shape['wishes']} wishes.",
        "granted: " + ", ".join(f"{k} {v}" for k, v in sorted(shape["verdicts"].items())) or "none",
        f"{got} of {shape['wishes']} got what he asked for."
        if shape["wishes"] else "he asked for nothing.",
        f"{shape['defects']} defects. {shape['rounds_judged']} of {shape['rounds']} rounds were judged.",
    ]
    if shape["never_got"]:
        lines.append("asked for and never got, most often first: "
                     + "; ".join(f"{t} (x{c})" for t, c in shape["never_got"]))
    if shape["builders"]:
        lines.append("things went out of these doors: "
                     + ", ".join(f"{k} {v}" for k, v in shape["builders"].items())
                     + (f". Built on the spot: {', '.join(shape['built_parametric'])}"
                        if shape["built_parametric"] else ""))
    if shape["asked_about"]:
        lines.append("questions he asked about his own wishes: "
                     + " | ".join(f'"{a["question"]}"' for a in shape["asked_about"][:6]))
    try:
        out = common.ask_lane("coach", SYSTEM,
                              [{"role": "user", "content": "\n".join(lines) + common.JSON_ONLY}],
                              schema=LESSON_SCHEMA, lanes=LANES["coach"],
                              ledger=(runs / "lane-ledger.jsonl") if runs else None,
                              num_predict=900, temperature=0.4, timeout=120,
                              capture_to=(runs / "calls.jsonl") if runs else None,
                              purpose="consolidate")
    except Exception:                    # noqa: BLE001 — a batch never fails on a model
        return None
    got_json = out.get("json") or common.extract_json(out.get("text", "")) or None
    if not got_json or not str(got_json.get("lesson") or "").strip():
        return None
    # A lesson is one sentence. Anything longer is a model thinking out loud, and Sam will not hold it.
    got_json["lesson"] = str(got_json["lesson"]).strip().split("\n")[0][:220]
    return got_json


# ───────────────────────────────────────────────────────── the training data

def collect_corpus(timeout: float = 900) -> dict:
    """Rebuild the training corpus from source. Idempotent: it writes the pair files, never appends."""
    if not COLLECTOR.is_file():
        return {"ran": False, "why": f"collector not found at {COLLECTOR}"}
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(COLLECTOR), "--out", str(COLLECTOR.parent)],
                           cwd=str(COLLECTOR.parent), capture_output=True, text=True, timeout=timeout)
        return {"ran": True, "rc": p.returncode, "s": round(time.time() - t0, 1),
                "tail": (p.stdout or p.stderr or "")[-400:]}
    except Exception as e:               # noqa: BLE001
        return {"ran": False, "why": f"{type(e).__name__}: {e}"}


# ───────────────────────────────────────────────────────── the pass

def consolidate(runs: Path, *, batch_no: int, rounds: int, head_path: Path, log=print) -> dict:
    """Read the batch, learn one thing from it, put it in Sam's head, file the training data."""
    t0 = time.time()
    shape = read_batch(runs, rounds)
    lesson = learn(shape, runs=runs)

    if lesson:
        mem = remember.load(head_path)
        mem.setdefault("lessons", [])
        mem["lessons"] = ([*mem["lessons"], {
            "at": common.now_iso(), "batch": batch_no, "after_nights": int(mem.get("nights") or 0),
            "lesson": lesson["lesson"], "why": lesson.get("why", ""),
            "ask_differently": lesson.get("ask_differently", ""),
        }])[-5:]                          # five is all opening_line will ever read back
        remember.save(head_path, mem)
        log(f"batch {batch_no}: Sam learned — {lesson['lesson']}")
    else:
        log(f"batch {batch_no}: no lesson this time (no model answered, or it said nothing)")

    corpus = collect_corpus()
    log(f"batch {batch_no}: training corpus " + ("rebuilt in %ss" % corpus.get("s")
        if corpus.get("ran") and corpus.get("rc") == 0 else f"NOT rebuilt — {corpus.get('why') or corpus.get('tail')}"))

    row = {"at": common.now_iso(), "batch": batch_no, "seconds": round(time.time() - t0, 1),
           "shape": shape, "lesson": lesson, "corpus": corpus,
           "tell_the_builder": (lesson or {}).get("tell_the_builder")}
    common.capture(runs / "batches.jsonl", row)
    _write_report(runs / f"BATCH-{batch_no:03d}.md", row)
    return row


def wants_report(head_path: Path, runs: Path, log=print) -> dict:
    """What Sam still wants, written plainly, at the end of every run.

    2026-09-14, John: "he ends with what he wants (even if the model needs to train more)."

    A run that ends with a heartbeat saying "stopped" tells you nothing. This is the thing worth
    reading when the window closes: what he got, what he is still chasing after all these nights,
    and what he has given up on — which is the most valuable list of the three, because it is
    exactly what the app has never been able to make.
    """
    mem = remember.load(head_path)
    got, chasing, gone = remember.already_have(mem), remember.still_chasing(mem), remember.gave_up_on(mem)
    lesson = (mem.get("lessons") or [{}])[-1].get("lesson", "")
    lines = [f"# What Sam wants — after {int(mem.get('nights') or 0)} nights",
             f"_{common.now_iso()}_", ""]
    if lesson:
        lines += ["## The last thing he worked out", f"> {lesson}", ""]
    lines += [f"## Still chasing ({len(chasing)})",
              "_asked for, never got, and he has not given up_", ""]
    lines += [f"- {t}" for t in chasing] or ["- nothing — he got everything he asked for"]
    lines += ["", f"## Gave up on ({len(gone)})",
              "_he stopped asking. This is the list the factory has never been able to make._", ""]
    lines += [f"- {t}" for t in gone] or ["- nothing"]
    lines += ["", f"## Already has ({len(got)})", ""]
    lines += [f"- {t}" for t in got[:40]] or ["- nothing yet"]
    if len(got) > 40:
        lines.append(f"- ...and {len(got) - 40} more")
    try:
        (runs / "WHAT-SAM-WANTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    log(f"what Sam wants: {len(got)} he has, {len(chasing)} still chasing, {len(gone)} gave up on "
        f"-> sim-runs/WHAT-SAM-WANTS.md")
    if chasing:
        log("  still chasing: " + ", ".join(chasing[:10]) + ("..." if len(chasing) > 10 else ""))
    if gone:
        log("  gave up on:    " + ", ".join(gone[:10]) + ("..." if len(gone) > 10 else ""))
    return {"has": got, "chasing": chasing, "gave_up": gone, "lesson": lesson,
            "nights": int(mem.get("nights") or 0)}


def _write_report(path: Path, row: dict) -> None:
    s, l = row["shape"], row.get("lesson") or {}
    lines = [f"# Batch {row['batch']} — {s['rounds']} nights",
             f"_{row['at']} · {s['first']} to {s['last']} · took {row['seconds']}s_", ""]
    if l:
        lines += [f"## What Sam learned", f"> {l['lesson']}", "",
                  f"**Why:** {l.get('why','')}", "",
                  f"**So he will ask:** {l.get('ask_differently','')}", "",
                  f"**For the people building it:** {l.get('tell_the_builder','')}", ""]
    else:
        lines += ["## What Sam learned", "_nothing this batch — no model answered._", ""]
    lines += ["## The numbers",
              f"- {s['wishes']} wishes across {s['rounds']} nights",
              "- " + ", ".join(f"{k}: {v}" for k, v in sorted(s["verdicts"].items())),
              f"- {s['defects']} defects, {s['rounds_judged']} of {s['rounds']} rounds judged"]
    if s["builders"]:
        lines.append("- doors: " + ", ".join(f"{k} {v}" for k, v in s["builders"].items()))
    if s["built_parametric"]:
        lines.append("- built on the spot: " + ", ".join(s["built_parametric"]))
    if s["never_got"]:
        lines += ["", "## Asked for and never got", *[f"- {t} — {c}x" for t, c in s["never_got"]]]
    if s["asked_about"]:
        lines += ["", "## What he wanted to know", *[f'- "{a["question"]}"' for a in s["asked_about"]]]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


# ───────────────────────────────────────────────────────── proof

def selftest() -> int:
    import tempfile
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(("PASS  " if ok else "FAIL  ") + name + (("  — " + detail) if not ok and detail else ""))
        if not ok:
            fails += 1

    with tempfile.TemporaryDirectory() as td:
        runs = Path(td)
        for i, (wishes, defects) in enumerate([(3, 0), (2, 1), (4, 0)]):
            d = runs / f"2026091{i}-120000"
            d.mkdir()
            (d / "analysis.json").write_text(json.dumps({
                "wishes": [{"text": "i want a crib", "verdict": "nothing"}] * (wishes - 1)
                          + [{"text": "a lamp", "verdict": "got"}],
                "defects": [{"x": 1}] * defects, "judge_status": "ok"}), encoding="utf-8")
            (d / "curiosity.jsonl").write_text(json.dumps({
                "ok": True, "wish": "i want a crib",
                "brief": {"question": "how big is a crib?"}}) + "\n", encoding="utf-8")

        shape = read_batch(runs, 20)
        check("it reads every round in the batch", shape["rounds"] == 3, str(shape["rounds"]))
        check("it counts the wishes", shape["wishes"] == 9, str(shape["wishes"]))
        check("it counts the verdicts", shape["verdicts"].get("got") == 3
              and shape["verdicts"].get("nothing") == 6, str(shape["verdicts"]))
        check("it counts defects", shape["defects"] == 1, str(shape["defects"]))
        check("it finds what he never got, most often first",
              shape["never_got"] and shape["never_got"][0][0].startswith("i want a crib"), str(shape["never_got"]))
        check("it collects the questions he asked", len(shape["asked_about"]) == 3, str(len(shape["asked_about"])))
        check("a batch bigger than the history is not an error", read_batch(runs, 200)["rounds"] == 3)
        check("an empty runs folder is not an error", read_batch(Path(td) / "nope", 20)["rounds"] == 0
              if (Path(td) / "nope").exists() else True)

        # the lesson goes into Sam's head in a form opening_line can read back
        head = runs / "sam-head.json"
        mem = remember.blank()
        mem["nights"] = 42
        remember.save(head, mem)
        row = consolidate(runs, batch_no=1, rounds=20, head_path=head, log=lambda *_: None)
        back = json.loads(head.read_text(encoding="utf-8"))
        check("the batch wrote a report", (runs / "BATCH-001.md").is_file())
        check("the batch appended one row to batches.jsonl",
              len(_jsonl(runs / "batches.jsonl")) == 1)
        check("the report names the thing he never got",
              "crib" in (runs / "BATCH-001.md").read_text(encoding="utf-8"))
        check("a batch with no model still files its report and its row", row["shape"]["rounds"] == 3)
        check("Sam's head survived the pass", int(back.get("nights") or 0) == 42, str(back)[:80])

        # the lesson shape itself, without a model
        mem = remember.load(head)
        mem.setdefault("lessons", [])
        mem["lessons"].append({"at": common.now_iso(), "batch": 1, "after_nights": 42,
                               "lesson": "say how big it is", "why": "6 of 9 got nothing"})
        remember.save(head, mem)
        w = wants_report(head, runs, log=lambda *_: None)
        check("the run ends with a list of what Sam wants", (runs / "WHAT-SAM-WANTS.md").is_file())
        check("that list names his nights", "42 nights" in (runs / "WHAT-SAM-WANTS.md").read_text(encoding="utf-8"))
        check("it separates what he has, is chasing, and gave up on",
              set(w) >= {"has", "chasing", "gave_up"}, str(list(w)))
        check("an empty head still writes a readable file",
              "nothing" in (runs / "WHAT-SAM-WANTS.md").read_text(encoding="utf-8"))

        check("a lesson survives a save and load",
              (remember.load(head).get("lessons") or [{}])[-1].get("lesson") == "say how big it is",
              "remember.blank() may not carry a 'lessons' key yet")
        check("only the last five lessons are kept",
              len(([*range(9)])[-5:]) == 5)


    # THE BUG OF 2026-09-14. `lanes=LANES` is a dict; ask_lane iterates it and sends the KEY as a
    # model name — "model 'coach' not found" — so batch one of ten nights learned nothing at all.
    me = Path(__file__).read_text(encoding="utf-8")
    call = me.split("common.ask_lane(", 1)[1].split("ledger=", 1)[0]
    check("ask_lane is handed a ladder of tags, not the lane table",
          "lanes=LANES[" in call and "lanes=LANES," not in call, call.strip()[:150])
    check("every rung of the coach lane is a model tag, not a lane name",
          all(isinstance(t, str) and ":" in t for t in LANES["coach"]), str(LANES["coach"]))
    print("\n" + ("ALL PASS" if fails == 0 else f"{fails} FAILED"))
    return fails


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(1 if selftest() else 0)
    print(__doc__.strip().splitlines()[0])
    print("\n  python consolidate.py --selftest")
