"""sim-player/prove_sam.py — the three things that have never happened, in one run.

2026-09-14. Everything built on 09-11 — the sim's own Pick Board, Sam's eyes, his memory — has
never executed in production. Not once. The unit tests pass in a Linux container with no GPU, no
Ollama and no local servers; they prove the LOGIC and nothing about the RUNTIME.

Worse, the loop log carries two lines nobody read:
    REFUSING to start the sim Pick Board: port 8194 is John's own board
The guard fired. Whatever started that day, the board was not it — and `sim-player/sim-board/`
does not exist on disk, which is the folder the board creates before it spawns.

This proves, live, in order, and stops at the first failure:
  1. THE BOARD    — starts on :8294, answers /api/ping, and leaves its folder on disk.
  2. THE EYES     — a real vision model answers on a real PNG, and says which rung of the ladder won.
  3. THE MEMORY   — a round folds into sam-head.json and loads back.
Nothing here spends the factory: no render, no mesh, no paint. Read-only against John's picks.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common          # noqa: E402
import eyes            # noqa: E402
import remember        # noqa: E402
import sim_board       # noqa: E402

OK, BAD = "  ok   ", "  FAIL "
fails: list[str] = []


def check(name: str, good: bool, detail: str = "") -> bool:
    print((OK if good else BAD) + name + (("  — " + detail) if detail else ""))
    if not good:
        fails.append(name)
    return good


def prove_board() -> bool:
    print("\n1. THE BOARD — never once served a request")
    bad = sim_board.check()
    if not check("guard rails clear", not bad, "; ".join(bad)):
        return False
    b = sim_board.SimBoard()
    print(f"       starting {b.url} (this is the step that has never worked)")
    if not check("the board came up", b.start(wait_s=90)):
        return False
    ok = True
    ok &= check("it answers /api/ping", b.up())
    ok &= check("its folder exists on disk", (sim_board.HOME / "stations").is_dir(), str(sim_board.HOME))
    ok &= check("it is NOT John's board", str(sim_board.JOHNS_PORT) not in b.url, b.url)
    try:
        b.stations()
        check("its stations API answers", True)
    except Exception as exc:
        ok &= check("its stations API answers", False, f"{type(exc).__name__}: {exc}")
    b.stop()
    return ok


def prove_eyes() -> bool:
    print("\n2. THE EYES — no vision model has ever replied")
    root = common.WORLDS / "warehouse" / "source" / "cutouts" / "picks"
    png = next((p for d in sorted(root.iterdir()) if d.is_dir()
                for p in sorted(d.glob("v*.png"))), None) if root.exists() else None
    if not check("found a real picture to look at", png is not None, str(root)):
        return False
    out = common.RUNS / "eyes-proof"
    out.mkdir(parents=True, exist_ok=True)

    def ask(system, messages, schema):
        return common.ask_lane("eyes", system, messages, schema=schema, temperature=0.2,
                               num_predict=2400,   # measured: qwen3-vl spends ~1900 tokens on one picture when
                                      # it cannot switch thinking off (Ollama 400s the
                                      # `think` flag and ollama_chat retries without it).
                                      # At 200 every reply was cut off mid-answer and
                                      # reached Sam as silence. 2400 clears the mark.
                               timeout=180, capture_to=out / "calls.jsonl",
                               ledger=out / "lane-ledger.jsonl", purpose="prove sam's eyes")

    # score_one fails soft to None by design - it must never turn a backend fault into a low score.
    # Right in production, useless in a proof: for three days this printed "every rung of the ladder
    # is dead" while four healthy vision models sat on an idle GPU. So make ONE raw call first and
    # let it throw. The exception type and message ARE the diagnosis.
    try:
        raw = ask(eyes.SYSTEM,
                  [{"role": "user", "content": "This is supposed to be: a roof. What do you think of it?",
                    "images": [eyes.read_png(png)]}],
                  eyes.SCORE_SCHEMA)
        print(f"       raw call came back from {raw.get('model')}: {str(raw.get('text'))[:90]!r}")
    except Exception as exc:
        print(f"       RAW CALL THREW  {type(exc).__name__}: {str(exc)[:300]}")

    t0 = time.monotonic()
    got = eyes.score_one(ask, png.parent.name, png, asked_for=png.parent.name.replace("-", " "))
    took = round(time.monotonic() - t0, 1)
    if not check("a vision model answered", got is not None,
                 "every rung of the ladder is dead or unreachable"):
        return False
    check("the winning rung is recorded", bool(common._lane_winner.get("eyes")),
          str(common._lane_winner.get("eyes")))
    check("the score is in range", 1 <= int(got["score"]) <= 5, str(got.get("score")))
    check("it said what it saw", bool(got.get("why")), str(got.get("why"))[:70])
    print(f"       {got.get('model')} scored {got.get('score')}/5 in {took}s — {got.get('why')}")
    # THE SILENT FAILURE (the one the unit tests can never catch): a model that returns a
    # plausible number for everything is indistinguishable from one that works. Three pictures,
    # three different subjects — identical scores with identical reasons means no opinion at all.
    more = []
    for d in sorted(p for p in root.iterdir() if p.is_dir())[1:4]:
        p = next(iter(sorted(d.glob("v*.png"))), None)
        if p:
            g = eyes.score_one(ask, d.name, p, asked_for=d.name.replace("-", " "))
            if g:
                more.append((d.name, g["score"], g.get("why", "")))
    if more:
        print("       three more, to see whether it is really looking:")
        for nm, sc, why in more:
            print(f"         {sc}/5  {nm[:38]:40s} {why[:52]}")
        flat = len({s for _, s, _ in more}) == 1 and len(more) > 2
        check("its scores are not all identical", not flat,
              "every picture scored the same — that is a model saying nothing, not a model judging")
    return True


def prove_memory() -> bool:
    print("\n3. THE MEMORY — sam-head.json has never been written by a round")
    head = common.RUNS / "sam-head.json"
    before = remember.load(head)
    print(f"       nights on record before this: {before.get('nights', 0)}")
    m = remember.remember_round(before, things=[{"room": "living room", "thing": "a proof couch"}],
                                got=["a proof couch"], rooms=["living room"], house="proof run")
    remember.save(head, m)
    back = remember.load(head)
    ok = check("the head wrote to disk", head.exists(), str(head))
    ok &= check("it loads back", back.get("nights") == m.get("nights"))
    ok &= check("it remembers what he got", "a proof couch" in remember.already_have(back))
    ok &= check("he is told about it next round", "proof couch" in remember.opening_line(back))
    # leave nothing behind: this was a proof, not a night
    remember.save(head, before)
    check("the proof round was rolled back", remember.load(head).get("nights", 0) == before.get("nights", 0))
    return ok


def main() -> int:
    common.utf8_console()
    print("=" * 78)
    print("  PROVING SAM — the three things that have only ever been unit-tested")
    print("  No render, no mesh, no paint. John's board on :8194 is not touched.")
    print("=" * 78)
    board = prove_board()
    eyes_ok = prove_eyes() if board else False
    mem = prove_memory() if board else False
    print("\n" + "=" * 78)
    if not board:
        print("  STOP — the sim Pick Board still does not serve. Nothing downstream can be trusted.")
    elif not eyes_ok:
        print("  THE BOARD WORKS, THE EYES DO NOT. Sam can answer house walls but must never")
        print("  judge a prop: with no eyes, a pick would be a coin flip written into a taste file.")
    elif fails:
        print(f"  {len(fails)} CHECK(S) FAILED: " + ", ".join(fails))
    else:
        print("  ALL THREE PROVEN LIVE. Sam is ready for a real round: RUN-SAM-ONCE.bat")
    print("=" * 78)
    return 0 if (board and eyes_ok and mem and not fails) else 1


if __name__ == "__main__":
    raise SystemExit(main())
