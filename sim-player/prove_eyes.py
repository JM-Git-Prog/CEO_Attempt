"""sim-player/prove_eyes.py — prove Sam's eyes against the only honest yardstick: John's own picks.

John, 2026-09-11, the moment his sim Pick Board came up: *"it ran, now prove the eyes against it."*

`eyes.py` shipped green in tests and had never had a live reply from a real vision model. A synthetic
wall would have proved the plumbing and nothing about the judgement. But John has already judged **35
prop picks** in `worlds/warehouse/source/cutouts/picks/` — 210 real variant PNGs with his recorded
winner beside each one. That is a gold set, and it is the right thing to measure against.

TWO PHASES.

  PHASE 1 — AGREEMENT (read-only, touches nothing).
      Score every variant of every decided pick, then ask three questions in order of honesty:
        * did a vision model answer at all, and which rung of the ladder won        <- the unproven bit
        * how often is Sam's top score John's recorded winner, against the random floor
        * DOES JOHN'S WINNER SCORE ABOVE THE REST ON AVERAGE                        <- the real measure
      The third is the one that matters. Sam is not trying to BE John — he is ten, and John's taste
      is twenty years of looking at buildings. The question is whether these eyes can tell a good
      render from a bad one at all. If John's winner sits at or near the top of the scores, they can.
      If the scores are flat, they cannot, and no amount of agreement percentage would have said so.
      A separate count that matters more than either: how often Sam would have DENIED the very take
      John chose. That is the number that says these eyes are not safe to let near a preference file.

  PHASE 2 — END TO END, LIVE (writes only inside the sim's own world and the sim's own board).
      Copy a real variant set into `worlds/sim-neighborhood/.../picks/` as a fresh, undecided pick,
      let Sam look at it and POST his answer to HIS board on :8294, then check three things:
        * a decision.json appeared in the sim world
        * a line appeared in sim-player/sim-board/preferences.jsonl
        * JOHN'S art/preferences.jsonl DID NOT MOVE BY ONE BYTE                     <- the isolation proof
      The last check is the whole reason the second board exists.

NOTHING HERE EVER WRITES TO JOHN'S BOARD, HIS WORLDS, OR HIS TASTE LEDGER. Phase 1 only reads.
Phase 2 refuses to run against any slug that is not the sim's, and refuses any board on John's port.

    python prove_eyes.py                 # 12 picks + the live end-to-end
    python prove_eyes.py --picks 0       # all 35 (slower: ~210 images)
    python prove_eyes.py --no-live       # phase 1 only
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import eyes  # noqa: E402
import sim_board  # noqa: E402

GOLD_WORLD = "warehouse"          # where John's decided picks live
OUT = common.RUNS / "eyes-proof"


def picks_dir(worlds: Path, slug: str) -> Path:
    return worlds / slug / "source" / "cutouts" / "picks"


def gold(worlds: Path, slug: str = GOLD_WORLD) -> list[dict]:
    """Every pick John actually decided, with the pictures he decided between."""
    out = []
    root = picks_dir(worlds, slug)
    if not root.exists():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        req, dec = d / "request.json", d / "decision.json"
        pngs = sorted(d.glob("v*.png"), key=lambda p: int("".join(c for c in p.stem[1:] if c.isdigit()) or 0))
        if not req.exists() or not dec.exists() or len(pngs) < 2:
            continue
        try:
            r = json.loads(req.read_text(encoding="utf-8"))
            w = json.loads(dec.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not w.get("winner"):
            continue
        out.append({"id": d.name, "dir": d, "subject": r.get("subject") or d.name,
                    "prompt": r.get("prompt") or "", "winner": w["winner"],
                    "pictures": [{"tag": p.stem, "png": p} for p in pngs]})
    return out


def ask(out_dir: Path):
    """Sam's eyes on the live ladder — proves each rung and falls through the dead ones."""
    def _ask(system, messages, schema):
        return common.ask_lane("eyes", system, messages, schema=schema, temperature=0.2,
                               num_predict=200, timeout=180, capture_to=out_dir / "calls.jsonl",
                               ledger=out_dir / "lane-ledger.jsonl", purpose="prove sam's eyes")
    return _ask


# ── phase 1 ──────────────────────────────────────────────────────────────────────────────────
def agreement(worlds: Path, limit: int, out_dir: Path) -> dict:
    rows, gold_set = [], gold(worlds)
    if not gold_set:
        return {"error": f"no decided picks found in worlds/{GOLD_WORLD}/source/cutouts/picks"}
    if limit:
        gold_set = gold_set[:limit]
    look = ask(out_dir)
    print(f"\nPHASE 1 — {len(gold_set)} picks John already decided, "
          f"{sum(len(g['pictures']) for g in gold_set)} pictures to look at.\n")
    print(f"  {'john':5s} {'sam':5s} {'rank':5s} {'score':11s} subject")
    print("  " + "-" * 76)
    for g in gold_set:
        t0 = time.monotonic()
        seen = eyes.look(look, g["subject"], g["pictures"], asked_for=g["prompt"] or g["subject"])
        took = round(time.monotonic() - t0, 1)
        row = {"id": g["id"], "subject": g["subject"], "john": g["winner"], "pictures": len(g["pictures"]),
               "seconds": took}
        if not seen:
            row.update({"sam": None, "scores": None, "why": "no reply from any rung of the eyes ladder"})
            print(f"  {g['winner']:5s} {'--':5s} {'--':5s} {'--':11s} {g['subject'][:44]}   (no reply)")
        else:
            sc = seen["scores"]
            johns = sc.get(g["winner"])
            others = [v for t, v in sc.items() if t != g["winner"]]
            ranked = sorted(sc, key=lambda t: -sc[t])
            rank = ranked.index(g["winner"]) + 1 if g["winner"] in ranked else None
            row.update({"sam": seen["winner"], "scores": sc, "johns_score": johns,
                        "others_mean": round(statistics.fmean(others), 2) if others else None,
                        "rank_of_johns": rank, "denied_johns": g["winner"] in (seen["denied"] or []),
                        "why": seen["why"]})
            flag = "  <-- would have DENIED John's pick" if row["denied_johns"] else ""
            print(f"  {g['winner']:5s} {str(seen['winner'] or '-'):5s} {str(rank or '-'):5s} "
                  f"{str(johns) + ' vs ' + str(row['others_mean']):11s} {g['subject'][:44]}{flag}")
        rows.append(row)
        common.capture(out_dir / "agreement.jsonl", row)

    judged = [r for r in rows if r.get("scores")]
    if not judged:
        return {"rows": rows, "judged": 0,
                "verdict": "NOT PROVEN — no rung of the eyes ladder answered. Sam has no eyes."}
    exact = sum(1 for r in judged if r["sam"] == r["john"])
    top2 = sum(1 for r in judged if r["rank_of_johns"] and r["rank_of_johns"] <= 2)
    floor = statistics.fmean(1 / r["pictures"] for r in judged)
    lift = [r["johns_score"] - r["others_mean"] for r in judged if r["others_mean"] is not None]
    # the clean sign test: how often did John's winner beat the average of the ones he passed over?
    # A coin flip is 50%. This needs no model, no scale and no calibration to interpret.
    above = sum(1 for x in lift if x > 0)
    denied = sum(1 for r in judged if r["denied_johns"])
    spread = [max(r["scores"].values()) - min(r["scores"].values()) for r in judged]
    return {"rows": rows, "judged": len(judged), "unjudged": len(rows) - len(judged),
            "exact": exact, "exact_pct": round(100 * exact / len(judged)),
            "top2_pct": round(100 * top2 / len(judged)), "random_floor_pct": round(100 * floor),
            "lift": round(statistics.fmean(lift), 2) if lift else None,
            "above_rest": above, "above_rest_pct": round(100 * above / len(lift)) if lift else None,
            "denied_johns_pick": denied, "flat_scores": sum(1 for s in spread if s == 0),
            "model": common._lane_winner.get("eyes")}


# ── phase 2 ──────────────────────────────────────────────────────────────────────────────────
def live(worlds: Path, out_dir: Path, board_url: str | None = None) -> dict:
    import sam
    board_url = board_url or common.PICKBOARD
    if board_url.rstrip("/").endswith(f":{sim_board.JOHNS_PORT}"):
        return {"ran": False, "why": f"refusing: {board_url} is John's own board"}
    if not common.SIM_SLUG.startswith(common.SIM_PREFIX):
        return {"ran": False, "why": f"refusing: {common.SIM_SLUG} is not a sim world"}
    johns_prefs = worlds.parent / "art" / "preferences.jsonl"
    before = johns_prefs.stat().st_size if johns_prefs.exists() else 0
    sim_prefs = sim_board.HOME / "preferences.jsonl"
    sim_before = sim_prefs.stat().st_size if sim_prefs.exists() else 0

    src = next((g for g in gold(worlds) if len(g["pictures"]) == 4), None)
    if src is None:
        return {"ran": False, "why": "no four-picture pick to copy"}
    pid = f"proof-{time.strftime('%H%M%S')}"
    dst = picks_dir(worlds, common.SIM_SLUG) / pid
    dst.mkdir(parents=True, exist_ok=True)
    for p in src["pictures"]:
        shutil.copy2(p["png"], dst / f"{p['tag']}.png")
    (dst / "request.json").write_text(json.dumps(
        {"subject": src["subject"], "prompt": src["prompt"] or src["subject"],
         "created": common.now_iso(), "seeds": {p["tag"]: None for p in src["pictures"]}}, indent=1), encoding="utf-8")
    print(f"\nPHASE 2 — a real four-picture wall for '{src['subject']}' hung in the SIM world as {pid}.")

    board = sam.Board(board_url)
    waiting = [p for p in board.picks(common.SIM_SLUG) if p.get("id") == pid]
    if not waiting:
        return {"ran": False, "why": f"the board on {board_url} does not show the sim pick {pid} "
                                     "(is it running, and pointed at the sim's stations?)", "pick": pid}
    r = sam.Round(out_dir / "live", v17=sam.V17("http://127.0.0.1:1"), board=board, world=sam.World(worlds),
                  ask=lambda *a, **k: {}, model="proof", slug=common.SIM_SLUG, session="sim-eyes-proof")
    r.eyes_ask = ask(out_dir)
    props = r.look_at_props()
    got = next((p for p in props if p["id"] == pid), None)
    dec = dst / "decision.json"
    after = johns_prefs.stat().st_size if johns_prefs.exists() else 0
    sim_after = sim_prefs.stat().st_size if sim_prefs.exists() else 0
    return {"ran": True, "pick": pid, "subject": src["subject"], "result": got,
            "sim_decision_written": dec.exists(),
            "sim_decision": json.loads(dec.read_text(encoding="utf-8")) if dec.exists() else None,
            "sim_prefs_grew": sim_after > sim_before, "sim_prefs_bytes": [sim_before, sim_after],
            "johns_prefs_untouched": after == before, "johns_prefs_bytes": [before, after],
            "board": board_url, "where": str(dst)}


def main() -> int:
    common.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--picks", type=int, default=12, help="how many decided picks to score (0 = all)")
    ap.add_argument("--no-live", action="store_true", help="phase 1 only — read nothing but John's picks")
    ap.add_argument("--worlds", default=str(common.WORLDS))
    a = ap.parse_args()
    worlds = Path(a.worlds)
    out_dir = OUT / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("  PROVING SAM'S EYES — against John's own recorded picks")
    print("  Nothing here writes to John's board, his worlds, or his taste file.")
    print("=" * 80)

    ag = agreement(worlds, a.picks, out_dir)
    print("\n" + "-" * 80)
    if ag.get("error") or not ag.get("judged"):
        print("  " + (ag.get("error") or ag.get("verdict")))
        return 1
    print(f"  A vision model answered: {ag['model']}   ({ag['judged']} picks judged, {ag['unjudged']} silent)")
    print(f"  Same winner as John:     {ag['exact_pct']}%   (random would be {ag['random_floor_pct']}%)")
    print(f"  John's pick in his top 2:{ag['top2_pct']}%")
    if ag["lift"] is None:
        print("  John's pick vs the rest: not measurable (every pick had one picture)")
    else:
        print(f"  John's pick beat the rest in {ag['above_rest']} of {ag['judged']} picks "
              f"({ag['above_rest_pct']}%)   <-- a coin flip is 50%")
        print(f"  ...by {ag['lift']:+.2f} points on average")
        print("     ^ THESE TWO are the verdict. Near 50% and 0.00 means these eyes are noise,")
        print("       however well the winner happened to match.")
    print(f"  Would have DENIED John's own pick: {ag['denied_johns_pick']} of {ag['judged']}"
          + ("   <-- not safe near a preference file" if ag["denied_johns_pick"] else ""))
    print(f"  Picks where every score was identical (no opinion at all): {ag['flat_scores']}")

    lv = {"ran": False, "why": "--no-live"}
    if not a.no_live:
        lv = live(worlds, out_dir)
        print("\n" + "-" * 80)
        if not lv.get("ran"):
            print("  PHASE 2 did not run: " + str(lv.get("why")))
        else:
            g = lv.get("result") or {}
            print(f"  Sam looked at 4 real takes of '{lv['subject']}' and "
                  + (f"picked {g.get('winner')} — {g.get('why')}" if g.get("winner") else f"picked nobody ({g.get('why')})"))
            print(f"  Posted to his own board:            {g.get('posted')}  ({lv['board']})")
            print(f"  Decision written in the sim world:  {lv['sim_decision_written']}")
            print(f"  The SIM's taste file grew:          {lv['sim_prefs_grew']}  {lv['sim_prefs_bytes']}")
            print(f"  JOHN'S taste file untouched:        {lv['johns_prefs_untouched']}  {lv['johns_prefs_bytes']}")

    (out_dir / "PROOF.json").write_text(json.dumps({"agreement": {k: v for k, v in ag.items() if k != "rows"},
                                                    "live": lv, "at": common.now_iso()}, indent=1, default=str),
                                        encoding="utf-8")
    print("\n  Full record: " + str(out_dir))
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
