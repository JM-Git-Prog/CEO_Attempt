"""Is the problem narrowable? Four questions the archive can already answer.

Q1  Is legality STOCHASTIC per prompt, or deterministic?
    If the same prompt sometimes passes and sometimes fails, then sampling N
    times and keeping the legal one converts a 25% model into a 90% product,
    with no training at all - the validator is deterministic and costs ~1 ms.
    If instead some prompts always pass and the rest never do, sampling is
    useless and the hard prompts need a different approach.

Q2  Does legality fall off with COMPLEXITY (item count, room size, openings)?
    If small rooms are reliable and big ones are not, the product can ship a
    narrowed scope today.

Q3  Which single feature best separates legal from illegal?

Q4  What is the observed legal rate inside a NARROWED scope - the estimate of
    what a tighter problem definition buys with today's model?

Backend errors and timeouts are excluded from every denominator: they are
transport failures, not task failures (CLAUDE.md, 2026-07-27).
"""
from __future__ import annotations

import glob
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "bench" / "scope-analysis.json"


def load():
    """Every ATTEMPT that actually reached the validator."""
    rows = []
    for path in glob.glob(str(ROOT / "bench" / "results-*.json")):
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for lane, data in (doc.get("lanes") or {}).items():
            for row in data.get("rows") or []:
                status = row.get("status")
                if status not in ("legal", "blocked"):
                    continue          # error / timeout = transport, not task
                rows.append({
                    "lane": lane,
                    "prompt_id": row.get("prompt_id", "?"),
                    "legal": status == "legal",
                    "plan": row.get("plan") if isinstance(row.get("plan"), dict) else None,
                    "blockers": row.get("blockers") or [],
                })
    return rows


def q1_stochastic(rows):
    print("=" * 72)
    print("Q1  Is legality stochastic per prompt?")
    print("=" * 72)
    by_prompt = defaultdict(lambda: [0, 0])
    for r in rows:
        by_prompt[r["prompt_id"]][0] += 1
        by_prompt[r["prompt_id"]][1] += r["legal"]

    repeated = {p: v for p, v in by_prompt.items() if v[0] >= 4}
    always = sum(1 for v in repeated.values() if v[1] == v[0])
    never = sum(1 for v in repeated.values() if v[1] == 0)
    mixed = len(repeated) - always - never

    print(f"  prompts attempted 4+ times : {len(repeated)}")
    print(f"    ALWAYS legal             : {always}")
    print(f"    NEVER legal              : {never}")
    print(f"    MIXED (sometimes legal)  : {mixed}   <-- these are winnable by retrying")
    if repeated:
        print(f"    -> {mixed / len(repeated) * 100:.0f}% of repeated prompts are stochastic")

    rates = [v[1] / v[0] for v in repeated.values()]
    overall = sum(v[1] for v in repeated.values()) / sum(v[0] for v in repeated.values())
    print(f"\n  pooled per-attempt legality : {overall * 100:.1f}%")

    # best-of-N, computed per prompt from its OWN rate, not the pooled rate -
    # pooling would overstate it by ignoring the never-legal prompts
    print("\n  best-of-N ceiling (each prompt uses its own observed rate):")
    for n in (1, 2, 3, 5, 8, 12):
        expected = statistics.mean(1 - (1 - r) ** n for r in rates) if rates else 0
        print(f"    N={n:>2} : {expected * 100:5.1f}% of prompts expected legal")
    print("    (a NEVER-legal prompt contributes 0 at every N - that is the ceiling)")
    return {"repeated": len(repeated), "always": always, "never": never, "mixed": mixed,
            "pooled_rate": round(overall, 4),
            "best_of_n": {str(n): round(statistics.mean(1 - (1 - r) ** n for r in rates), 4)
                          for n in (1, 2, 3, 5, 8, 12)} if rates else {}}


def features(plan):
    items = plan.get("items") or []
    room = plan.get("room") or {}
    w, d = float(room.get("width", 0)), float(room.get("depth", 0))
    area = w * d
    if area <= 0 or not items:
        return None
    foot = sum(i.get("width", 0) * i.get("depth", 0) for i in items)
    kinds = [r.get("kind") for r in plan.get("relationships") or []]
    return {
        "n_items": len(items),
        "area": area,
        "occupancy": foot / area,
        "n_openings": len(plan.get("openings") or []),
        "n_ceiling": sum(1 for i in items if i.get("mount") == "ceiling"),
        "n_repeats": len(items) - len({(i.get("name") or "").rstrip("0123456789 ").lower()
                                       for i in items}),
        "adjacent_to": kinds.count("adjacent_to"),
        "centered": kinds.count("centered"),
    }


def q2_q3(rows):
    data = [(features(r["plan"]), r["legal"]) for r in rows if r["plan"]]
    data = [(f, ok) for f, ok in data if f]
    print()
    print("=" * 72)
    print(f"Q2  Legality vs complexity   (n={len(data)} plans with geometry)")
    print("=" * 72)

    def table(name, key, bins):
        print(f"\n  by {name}:")
        for lo, hi in bins:
            sel = [ok for f, ok in data if lo <= f[key] < hi]
            if len(sel) < 15:
                continue
            print(f"    {lo:>5} - {hi:<5} n={len(sel):5d}   legal {sum(sel) / len(sel) * 100:5.1f}%")

    table("item count", "n_items", [(0, 4), (4, 6), (6, 8), (8, 11), (11, 99)])
    table("room area m2", "area", [(0, 15), (15, 25), (25, 40), (40, 999)])
    table("occupancy", "occupancy", [(0, .1), (.1, .2), (.2, .35), (.35, 9)])
    table("ceiling items", "n_ceiling", [(0, 1), (1, 3), (3, 99)])
    table("repeated items", "n_repeats", [(0, 1), (1, 3), (3, 99)])
    table("adjacent_to uses", "adjacent_to", [(0, 1), (1, 3), (3, 99)])

    print()
    print("=" * 72)
    print("Q3  Which feature separates legal from illegal best?")
    print("=" * 72)
    print(f"  {'feature':16} {'mean(legal)':>12} {'mean(illegal)':>14}   separation")
    seps = []
    for key in ("n_items", "area", "occupancy", "n_openings", "n_ceiling",
                "n_repeats", "adjacent_to", "centered"):
        a = [f[key] for f, ok in data if ok]
        b = [f[key] for f, ok in data if not ok]
        if len(a) < 10 or len(b) < 10:
            continue
        ma, mb = statistics.mean(a), statistics.mean(b)
        sa, sb = statistics.pstdev(a), statistics.pstdev(b)
        pooled = math.sqrt((sa ** 2 + sb ** 2) / 2) or 1e-9
        cohen = abs(ma - mb) / pooled           # standardised effect size
        seps.append((cohen, key, ma, mb))
    for cohen, key, ma, mb in sorted(seps, reverse=True):
        flag = "STRONG" if cohen >= 0.8 else "moderate" if cohen >= 0.5 else "weak"
        print(f"  {key:16} {ma:12.2f} {mb:14.2f}   d={cohen:.2f}  {flag}")
    return data, seps


def q4_narrow(data):
    print()
    print("=" * 72)
    print("Q4  What does a NARROWED problem scope buy, with today's model?")
    print("=" * 72)
    scopes = {
        "everything (today)": lambda f: True,
        "<=5 items": lambda f: f["n_items"] <= 5,
        "<=5 items, no ceiling items": lambda f: f["n_items"] <= 5 and f["n_ceiling"] == 0,
        "<=5 items, no repeats": lambda f: f["n_items"] <= 5 and f["n_repeats"] == 0,
        "<=5, no ceiling, no repeats": lambda f: (f["n_items"] <= 5 and f["n_ceiling"] == 0
                                                  and f["n_repeats"] == 0),
        "<=5, none of the above + no adjacent_to": lambda f: (
            f["n_items"] <= 5 and f["n_ceiling"] == 0 and f["n_repeats"] == 0
            and f["adjacent_to"] == 0),
        "occupancy < 20%": lambda f: f["occupancy"] < 0.20,
        "<=5 items AND occupancy < 20%": lambda f: f["n_items"] <= 5 and f["occupancy"] < 0.20,
    }
    out = {}
    print(f"  {'scope':44} {'n':>6} {'legal':>8}")
    for label, test in scopes.items():
        sel = [ok for f, ok in data if test(f)]
        if len(sel) < 15:
            print(f"  {label:44} {len(sel):6d}   (too few to judge)")
            continue
        rate = sum(sel) / len(sel)
        out[label] = {"n": len(sel), "rate": round(rate, 4)}
        print(f"  {label:44} {len(sel):6d} {rate * 100:7.1f}%")
    return out


def main() -> int:
    rows = load()
    print(f"attempts that reached the validator: {len(rows)}"
          f"   (backend errors and timeouts excluded)\n")
    q1 = q1_stochastic(rows)
    data, seps = q2_q3(rows)
    q4 = q4_narrow(data)
    OUT.write_text(json.dumps({"q1": q1, "q4": q4,
                               "separation": [{"feature": k, "cohen_d": round(c, 3)}
                                              for c, k, _, _ in sorted(seps, reverse=True)]},
                              indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
