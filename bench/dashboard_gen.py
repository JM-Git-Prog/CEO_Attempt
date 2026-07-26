"""Generates bench/flywheel-dashboard.html - a plain-English snapshot of:
  - the vision this loop serves
  - an executive overview of where things actually stand right now
  - the working objective and an honest time-to-target estimate (or a plain
    "not enough data yet" if there isn't a real trend to project)
  - the loop itself, explained step by step

Reads only, from the SAME files the Training Monitor app already trusts.
The corpus/history counting logic below is intentionally kept IDENTICAL to
tools/training_monitor.py's _corpus_composition()/_scan_history() (copied,
not imported - that module pulls in tkinter for its GUI, which this
headless report generator has no reason to require). If that app's counting
logic ever changes, mirror the change here too, so the two never disagree.

Writes one self-contained HTML file. Re-run any time (the Desktop launcher
does this automatically) to refresh it.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
TRAINED_DIR = BENCH / "trained"
CORPUS_FILES = (ROOT / "data" / "flywheel" / "corpus.jsonl",
                ROOT / "data" / "flywheel" / "corpus-bench.jsonl")
TIMESTAMP_RE = re.compile(r"(\d{8}T\d{6})")

OUT = BENCH / "flywheel-dashboard.html"

TELEMETRY = ROOT / "output" / "qualification" / "telemetry.json"
FLYWHEEL_STATE = BENCH / "flywheel-state.json"
FLYWHEEL_LOG = BENCH / "flywheel-log.txt"
BENCH_LOOP_LOG = BENCH / "bench-loop-log.txt"
PROGRESS = BENCH / "training-progress.json"

TARGET_LEGAL_RATE = 0.90       # working default - tell Claude to change it
MIN_POINTS_FOR_TREND = 4       # fewer real comparisons than this = no trend math
ACTIVE_WINDOW_S = 10 * 60      # a log touched within this window counts as "running"
CORPUS_THRESHOLD = 50          # rows needed to trigger the next training cycle

# Blockers that are purely a question of WHERE something sits - i.e. fixable by
# moving geometry, which src/solver_repair.py already does. Anything else
# (schema errors, timeouts) is not a placement problem.
SPATIAL_CODES = {"physical_overlap", "out_of_bounds",
                 "opening_blocked", "camera_inside_geometry"}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _last_line(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return lines[-1] if lines else "(no entries yet)"
    except Exception:
        return "(not found)"


def _fresh(path: Path) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) < ACTIVE_WINDOW_S
    except Exception:
        return False


def _fmt_pct(x) -> str:
    return f"{x * 100:.0f}%" if x is not None else "-"


def _corpus_composition() -> dict:
    """Copied verbatim (logic-wise) from tools/training_monitor.py. Organic
    (harvested from the llama3.1 loop) vs synthetic (cloud-lane top-up) rows
    in the corpus right now, and how many actually pass validation."""
    organic = synthetic = other = accepted = 0
    for p in CORPUS_FILES:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            lane = d.get("model_lane") or ""
            if lane == "llama3.1":
                organic += 1
            elif "cloud" in lane:
                synthetic += 1
            else:
                other += 1
            verdict = (d.get("per_gate_verdicts") or {}).get("plan")
            status = verdict.get("status") if isinstance(verdict, dict) else verdict
            if status in ("passed", "pass"):
                accepted += 1
    return {"organic": organic, "synthetic": synthetic, "other": other,
            "accepted": accepted, "total": organic + synthetic + other}


def _scan_history() -> list[dict]:
    """Copied verbatim (logic-wise) from tools/training_monitor.py. Matches
    each trained generation to the exam that actually graded it, trusting
    only >=20-prompt exams as real comparisons (a 15-prompt harvester/top-up
    batch is not a baseline reading) and only the literal planner-probe-v1
    lane as the trained model's own result."""
    if not TRAINED_DIR.exists():
        return []
    runs = []
    for d in sorted(TRAINED_DIR.iterdir()):
        if not d.is_dir() or d.name.endswith("_gguf"):
            continue
        m = TIMESTAMP_RE.search(d.name)
        if not m:
            continue
        trained_epoch = time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        runs.append({"name": d.name, "trained_epoch": trained_epoch})

    parsed_results = []
    for rf in BENCH.glob("results-*.json"):
        m = TIMESTAMP_RE.search(rf.name)
        if not m:
            continue
        ts = time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
        parsed_results.append((ts, rf))
    parsed_results.sort()

    def latest_baseline_at_or_before(ts_cutoff):
        best = None
        for ts, rf in parsed_results:
            if ts > ts_cutoff:
                continue
            data = _read_json(rf)
            if not data or "lanes" not in data:
                continue
            base = data["lanes"].get("llama3.1")
            total = data.get("prompts")
            if not base or not total or total < 20:
                continue
            if base.get("total") != total:
                continue
            if best is None or ts > best[0]:
                best = (ts, base)
        return best[1] if best else None

    for run in runs:
        best_trained = None
        for ts, rf in parsed_results:
            if ts < run["trained_epoch"] or (best_trained is not None and ts <= best_trained[0]):
                continue
            data = _read_json(rf)
            if not data or "lanes" not in data:
                continue
            trained_lane = data["lanes"].get("planner-probe-v1")
            total = data.get("prompts")
            if not trained_lane:
                continue
            if total and trained_lane.get("total") != total:
                continue
            best_trained = (ts, trained_lane)

        run["exam"] = None
        if best_trained:
            ts, trained_lane = best_trained
            base = latest_baseline_at_or_before(ts)
            run["exam"] = {
                "baseline_rate": base.get("legal_rate") if base else None,
                "baseline_legal": base.get("legal") if base else None,
                "baseline_total": base.get("total") if base else None,
                "trained_rate": trained_lane.get("legal_rate", 0.0),
                "trained_legal": trained_lane.get("legal", 0),
                "trained_total": trained_lane.get("total", 0),
            }
    return list(reversed(runs))


def _failure_census() -> dict:
    """WHY rows get thrown away, across every bench result ever recorded.

    The split that matters: a row whose blockers are ALL spatial (something
    overlaps, sticks out of the room, blocks a door, or the camera is inside
    geometry) is geometry that pure math can move - src/solver_repair.py
    already does exactly that, in <=19ms, with no model call. A row that
    errored, timed out, or failed schema validation is NOT recoverable by
    moving furniture. Counting them together hides which fix buys more data.
    """
    passed = spatial_only = errored = timed_out = mixed = rescued = 0
    codes = {}
    for rf in BENCH.glob("results-*.json"):
        data = _read_json(rf)
        if not data:
            continue
        for lane in (data.get("lanes") or {}).values():
            for row in lane.get("rows") or []:
                status = row.get("status")
                if status == "legal":
                    passed += 1
                    if row.get("repaired_by_math"):
                        rescued += 1
                    continue
                blockers = set(row.get("blockers") or [])
                for c in blockers:
                    codes[c] = codes.get(c, 0) + 1
                if status == "timeout":
                    timed_out += 1
                elif status == "error" or not blockers:
                    errored += 1
                elif blockers <= SPATIAL_CODES:
                    spatial_only += 1
                else:
                    mixed += 1
    failed = spatial_only + errored + timed_out + mixed
    return {"passed": passed, "failed": failed, "spatial_only": spatial_only,
            "errored": errored, "timed_out": timed_out, "mixed": mixed,
            "rescued": rescued, "total": passed + failed,
            "codes": sorted(codes.items(), key=lambda kv: -kv[1])}


def _real_history():
    """Only the runs with a genuine >=20-prompt exam AND a known baseline -
    the same bar _scan_history() already enforces. Returned oldest-first."""
    runs = [r for r in _scan_history() if r.get("exam") and r["exam"].get("baseline_rate") is not None]
    runs.sort(key=lambda r: r["trained_epoch"])
    return runs


def _trend(points):
    """points: list of (epoch_seconds, trained_rate). Plain least-squares
    slope, no numpy. Returns None if there aren't enough points, or the
    slope is flat/negative (nothing honest to project)."""
    if len(points) < MIN_POINTS_FOR_TREND:
        return None
    n = len(points)
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    den = sum((x - mean_x) ** 2 for x, y in points)
    if den == 0:
        return None
    slope = num / den  # rate-per-second
    if slope <= 0:
        return None
    return slope


def build():
    telemetry = _read_json(TELEMETRY) or {}
    totals = telemetry.get("totals", {})
    fstate = _read_json(FLYWHEEL_STATE) or {}
    progress = _read_json(PROGRESS) or {}
    comp = _corpus_composition()
    history = _real_history()
    fail = _failure_census()

    harvester_active = _fresh(BENCH_LOOP_LOG)
    flywheel_active = _fresh(FLYWHEEL_LOG)
    training_now = progress.get("stage") in ("training", "loading_model", "saving_gguf") and \
        (time.time() - progress.get("updated", 0)) < 30 * 60

    latest_rate = history[-1]["exam"]["trained_rate"] if history else None
    latest_base = history[-1]["exam"]["baseline_rate"] if history else None

    # corpus velocity, using real observed numbers (includes any stalls -
    # deliberately not cherry-picked to look better than it was)
    rows_now = comp["total"]
    rows_last_cycle = fstate.get("last_trained_rows")
    velocity_line = "Not enough history yet to estimate a pace."
    threshold_eta_line = None
    if rows_last_cycle is not None and fstate.get("last_cycle_finished"):
        try:
            last_epoch = time.mktime(time.strptime(fstate["last_cycle_finished"], "%Y-%m-%d %H:%M:%S"))
            hours_elapsed = (time.time() - last_epoch) / 3600
            rows_gained = rows_now - rows_last_cycle
            if hours_elapsed > 0.1:
                rate_per_hour = rows_gained / hours_elapsed
                velocity_line = (f"{rows_gained} new rows in {hours_elapsed:.1f} hours "
                                  f"(~{rate_per_hour:.1f}/hour, real observed pace including any stalls).")
                remaining = CORPUS_THRESHOLD - rows_gained
                if remaining > 0 and rate_per_hour > 0.05:
                    eta_hours = remaining / rate_per_hour
                    threshold_eta_line = (f"At that pace, about {eta_hours:.1f} more hours "
                                           f"until the next training cycle triggers ({remaining} rows to go).")
        except Exception:
            pass

    trend_slope = _trend([(r["trained_epoch"], r["exam"]["trained_rate"]) for r in history])
    if trend_slope and latest_rate is not None and latest_rate < TARGET_LEGAL_RATE:
        seconds_to_target = (TARGET_LEGAL_RATE - latest_rate) / trend_slope
        days_to_target = seconds_to_target / 86400
        eta_text = (f"At the current improvement trend, roughly <b>{days_to_target:.1f} days</b> "
                    f"of continued cycles to reach the {_fmt_pct(TARGET_LEGAL_RATE)} target.")
    elif latest_rate is not None and latest_rate >= TARGET_LEGAL_RATE:
        eta_text = f"Target already reached in the most recent real exam ({_fmt_pct(latest_rate)})."
    else:
        eta_text = (f"<b>Not enough clean data yet to give a real estimate.</b> Only "
                    f"{len(history)} real comparison(s) exist so far (need at least "
                    f"{MIN_POINTS_FOR_TREND}) - most of today's cycles never got measured "
                    f"because of bugs that are now fixed. This will turn into a real number "
                    f"once a few more training cycles complete and get benched.")

    def _share(n):
        return f"{n / fail['failed'] * 100:.0f}%" if fail["failed"] else "-"

    code_rows = "".join(
        f"<tr><td>{c}</td><td>{n}</td>"
        f"<td>{'movable geometry' if c in SPATIAL_CODES else 'not a placement problem'}</td></tr>"
        for c, n in fail["codes"][:8]
    ) or "<tr><td colspan='3'>No bench results recorded yet.</td></tr>"

    history_rows = "".join(
        f"<tr><td>{time.strftime('%b %d %H:%M', time.localtime(r['trained_epoch']))}</td>"
        f"<td>{_fmt_pct(r['exam']['baseline_rate'])} ({r['exam']['baseline_legal']}/{r['exam']['baseline_total']})</td>"
        f"<td>{_fmt_pct(r['exam']['trained_rate'])} ({r['exam']['trained_legal']}/{r['exam']['trained_total']})</td></tr>"
        for r in history
    ) or "<tr><td colspan='3'>No real (20+ prompt) comparison exams yet.</td></tr>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>The Living Room - Flywheel Dashboard</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 900px;
         margin: 30px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.55; }}
  h1 {{ font-size: 1.5em; margin-bottom: 0; }}
  h2 {{ border-bottom: 2px solid #ddd; padding-bottom: 6px; margin-top: 2.2em; }}
  .sub {{ color: #666; margin-top: 2px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  td, th {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.95em; }}
  th {{ background: #f4f4f4; }}
  .card {{ background: #f8f8f8; border: 1px solid #e0e0e0; border-radius: 8px;
           padding: 14px 18px; margin: 10px 0; }}
  .ok {{ color: #1a7a1a; font-weight: bold; }}
  .warn {{ color: #b35900; font-weight: bold; }}
  .bad {{ color: #b30000; font-weight: bold; }}
  .footer {{ color: #888; font-size: 0.85em; margin-top: 3em; border-top: 1px solid #eee; padding-top: 10px; }}
  ol li {{ margin-bottom: 6px; }}
</style></head><body>

<h1>The Living Room - Flywheel Dashboard</h1>
<div class="sub">Generated {time.strftime('%Y-%m-%d %H:%M:%S')} - reopen the Desktop launcher any time to refresh.</div>

<h2>The vision</h2>
<p>You describe a room in plain conversation. The AI designs it - proposes a look, furniture,
and layout - and shows you a photorealistic image to approve. Once approved, the AI builds
it as a real, walkable 3D space: correct room shape, every object in a physically sensible
place, right down to trim and outlets. Then it's usable in "real mode" (your actual tools
and tasks live inside it) or "game mode" (the same space becomes a game built around it).
Every world built adds reusable pieces to a shared warehouse, so each new world gets faster
to build than the last one. Runs on open, local models - no dependence on any one paid API.</p>

<p><b>What this specific loop is responsible for:</b> before any of that can happen, the AI
has to reliably turn a room description into a correct blueprint - room size, where every
piece of furniture goes, doors and windows, the camera - numbers a math checker can verify
don't collide, don't leave the room, and don't block a doorway. This flywheel's only job is
teaching a small, free, local model to write that blueprint correctly on the first try, as
often as possible, across all kinds of rooms. Get this reliable and the
"conversation -> approved image -> real world" promise holds up without constant manual fixes.</p>

<h2>Executive overview</h2>
<div class="card">
<b>Corpus right now:</b> {comp['organic']} organic (llama3.1 harvester) + {comp['synthetic']} synthetic
(cloud top-up) + {comp['other']} from earlier pipeline runs = {comp['total']} rows -&gt;
<b>{comp['accepted']} pass validation</b> and become trainable exemplars.<br>
<b>Pace:</b> {velocity_line}{'<br>' + threshold_eta_line if threshold_eta_line else ''}
</div>

<div class="card">
<b>System health (right now):</b><br>
Harvester (bench_loop.py): <span class="{'ok' if harvester_active else 'bad'}">
{'active' if harvester_active else 'not active - restart the supervisor'}</span><br>
Flywheel loop: <span class="{'ok' if flywheel_active else 'bad'}">
{'active' if flywheel_active else 'not active - restart the supervisor'}</span><br>
Training right now: <span class="{'warn' if training_now else 'ok'}">
{'yes, mid-cycle' if training_now else 'no - idle, waiting or between cycles'}</span><br>
GPU: {totals.get('gpu_util_pct', '?')}% util, {totals.get('vram_used_gb', '?')}/{totals.get('vram_total_gb', '?')} GB VRAM
</div>

<div class="card">
<b>Most recent real comparison:</b> llama3.1 baseline {_fmt_pct(latest_base)} vs. trained model
{_fmt_pct(latest_rate)} {'(no comparison exam has completed yet)' if latest_rate is None else ''}
</div>

<h2>Why rows get thrown away</h2>
<p>Every generated blueprint that fails the checker is discarded. Corpus growth =
how fast we generate x how many survive. Right now <b>{fail['passed']} of
{fail['total']}</b> attempts ever recorded survived. Here's what happened to the
{fail['failed']} that didn't:</p>
<div class="card">
<b>Rescued by the free repair pass so far:</b> <span class="{'ok' if fail['rescued'] else 'warn'}">
{fail['rescued']} rows</span> that would have been discarded were nudged back into
legality by math alone (no model call, ~0.6ms each) and banked as training
examples. They're tagged <code>repaired_by_math</code> in the corpus so we can
train with and without them and check they actually help.
{'Nothing rescued yet - this counts only rows generated since the repair pass was wired in, so it stays 0 until the harvester produces new rows.' if not fail['rescued'] else ''}
</div>

<div class="card">
<b>Historically thrown away on placement alone:</b> <span class="warn">{fail['spatial_only']} rows
({_share(fail['spatial_only'])} of failures)</span> failed <i>only</i> because
something was in the wrong place - overlapping, outside the room, blocking a door,
or the camera stuck in a wall. Nothing wrong with the model's thinking; just the
numbers. <code>src/solver_repair.py</code> already fixes exactly this in ~19ms with
no model call, but it is only wired into the full pipeline - <b>not</b> into the
harvester that feeds this corpus. So these were generated, then thrown away.<br><br>
<b>Not a placement problem:</b> {fail['timed_out']} timed out
({_share(fail['timed_out'])}), {fail['errored']} errored or failed schema
({_share(fail['errored'])}), {fail['mixed']} had both a placement fault and a
schema fault ({_share(fail['mixed'])}). Moving furniture cannot save these - they
need a faster/stricter generation step, not a repair pass.
</div>
<p style="color:#666;font-size:0.9em">Individual blocker codes below. Timeouts and
errors don't appear here - they die before the checker ever reports a blocker, which
is why they're easy to under-count.</p>
<table>
<tr><th>Blocker</th><th>Times seen</th><th>Fixable by moving things?</th></tr>
{code_rows}
</table>

<h2>Objective and progress</h2>
<p><b>Working target (my proposed default - tell me to change it):</b> the trained model should
correctly build {_fmt_pct(TARGET_LEGAL_RATE)} of room layouts on the first try, across a wide
range of room types - reliable enough that a broken layout becomes a rare exception, not a
regular occurrence.</p>
<p>{eta_text}</p>
<table>
<tr><th>Trained</th><th>Baseline (llama3.1)</th><th>Trained model</th></tr>
{history_rows}
</table>

<h2>The loop, plain English</h2>
<ol>
<li>A room description goes to a model (llama3.1 locally, a cloud model, or the model being trained).</li>
<li>The model writes a JSON blueprint: room size, every item's position/size, doors, windows, camera.</li>
<li>A strict math checker verifies it - no collisions, nothing out of bounds, no blocked doors.</li>
<li>Passing blueprints get banked as training examples ("trainable exemplars").</li>
<li>Once {CORPUS_THRESHOLD} new passing examples pile up, the harvester pauses and the model is
fine-tuned on them.</li>
<li>The freshly-trained model gets tested against the old baseline on a fixed set of prompts
it has never seen.</li>
<li>Repeat, forever. Every 10th cycle, different training settings are also tried, and
whichever setting wins becomes the new default automatically.</li>
</ol>

<div class="footer">
Corpus: data/flywheel/corpus.jsonl + corpus-bench.jsonl &middot;
Health/history: bench/flywheel-state.json, bench/training-progress.json, bench/results-*.json &middot;
Numbers reuse tools/training_monitor.py's own counting logic, so this page and that app never disagree.
</div>

</body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
