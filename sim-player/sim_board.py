"""sim-player/sim_board.py — Sam's own Pick Board, on :8294, in its own folder.

John, 2026-09-11: *"Give the sim its own Pick Board"*.

WHY THIS EXISTS. Until now Sam could answer a garage wall (which house of four to build) on John's
real board on :8194, because that wall was hung for him and nobody else. But the board's OTHER half —
the prop wall, where four takes of a couch go up and somebody picks the one that gets meshed and
painted — was closed to him, because every pick there appends a line to `art/preferences.jsonl`,
which is JOHN'S TASTE: the file the style model learns from. A robot's opinion in that file is not a
small mess, it is a corrupted training set, and the rule that a robot never acts as John applies to a
robot exactly as it applies to me.

So Sam gets a board of his own. Same server, same code, same screen if John ever wants to look at it
— a different port and a different folder underneath. Everything the Pick Board writes now comes from
an env var (PICK_PORT was already there; PICK_STATIONS, PICK_PREFS, PICK_REROLL and PICK_FLAGS are
new, each defaulting to exactly what it was), so:

    John's board   :8194   tools/stations/    CEO-3D-World/art/preferences.jsonl   <- untouched
    Sam's board    :8294   sim-player/sim-board/stations/  .../sim-board/preferences.jsonl

Nothing of John's is read-only-by-accident or shared-by-accident: the two instances share only the
worlds folder (read) and the ComfyUI servers behind /api/make (one job bay each, one 4090 between
them — which is why the loop still waits for a free GPU before every round).

THE GUARD RAIL IS THE POINT, not the port number. `check()` refuses to start if the port is John's,
if the stations folder resolves inside his tools folder, or if the prefs file resolves to his taste
ledger. A config typo that would have quietly poisoned the training set stops the loop instead.

    python sim_board.py --start | --stop | --status | --selftest
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

PORT = getattr(common, "SIM_PICK_PORT", int(os.getenv("SAM_PICK_PORT", "8294")))
URL = f"http://127.0.0.1:{PORT}"
HOME = Path(os.getenv("SAM_BOARD_HOME", str(common.HERE / "sim-board")))
SERVER = Path(os.getenv("PICK_SERVER", str(
    Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc")
    / "CEO-3D-World" / "tools" / "pick-server.mjs")))

JOHNS_PORT = 8194
DETACHED = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str) -> None:
    common.log(msg, file=common.RUNS / "loop-log.txt")


def env(base: dict | None = None, home: Path | None = None, port: int | None = None) -> dict:
    """The environment that turns pick-server.mjs into the SIM's board. Every writable path moves."""
    home = Path(home or HOME)
    e = dict(base if base is not None else os.environ)
    e["PICK_PORT"] = str(port or PORT)
    e["PICK_STATIONS"] = str(home / "stations")
    e["PICK_PREFS"] = str(home / "preferences.jsonl")
    e["PICK_REROLL"] = str(home / "reroll-queue.json")
    e["PICK_FLAGS"] = str(home / "prop-flags.json")
    return e


def check(home: Path | None = None, port: int | None = None, server: Path | None = None) -> list[str]:
    """Everything that must be true before a second board is allowed to exist. [] means safe."""
    home, port, server = Path(home or HOME), int(port or PORT), Path(server or SERVER)
    bad: list[str] = []
    if port == JOHNS_PORT:
        bad.append(f"port {port} is John's own board — the sim board must never be :{JOHNS_PORT}")
    tools = server.parent
    try:
        home.resolve().relative_to(tools.resolve())
        bad.append(f"the sim board's folder is inside John's tools folder: {home}")
    except (ValueError, OSError):
        pass
    e = env({}, home, port)
    johns_prefs = (tools.parent / "art" / "preferences.jsonl")
    if Path(e["PICK_PREFS"]).name == "preferences.jsonl" and _same(Path(e["PICK_PREFS"]), johns_prefs):
        bad.append("the sim board would write into John's taste ledger (art/preferences.jsonl)")
    if not server.exists():
        bad.append(f"pick-server.mjs not found: {server}")
    else:
        try:
            if "PICK_STATIONS" not in server.read_text(encoding="utf-8", errors="ignore"):
                bad.append("this pick-server.mjs has no PICK_STATIONS — it would use John's stations folder")
        except OSError as exc:
            bad.append(f"could not read pick-server.mjs: {exc}")
    return bad


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


def up(url: str | None = None, timeout: float = 5.0) -> bool:
    try:
        st, _ = common.http_json("GET", (url or URL) + "/api/ping", timeout=timeout)
    except common.Backend:
        return False
    return st == 200


class SimBoard:
    """The loop's own Pick Board process. Started with the loop, stopped with it, never John's."""

    def __init__(self, port: int = PORT, home: Path = HOME, server: Path = SERVER):
        self.port, self.home, self.server = int(port), Path(home), Path(server)
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def up(self) -> bool:
        return up(self.url)

    def start(self, wait_s: float = 90, free_port=None) -> bool:
        bad = check(self.home, self.port, self.server)
        if bad:
            for b in bad:
                log("REFUSING to start the sim Pick Board: " + b)
            return False
        if self.proc is not None and self.proc.poll() is None and self.up():
            return True
        if self.up() and self.proc is None:
            # Something is already on :8294 — either a board we lost the handle to (the last loop's,
            # which outlives the window that started it: it is spawned DETACHED on purpose) or a
            # stranger. A board we did not start writes who-knows-where, so it must be freed or
            # PROVED before it is used. is_mine() is the proof, and it is a real one: it makes a file
            # appear in Sam's own stations folder and asks the server whether it can see it. A server
            # reading any other folder cannot.
            if self.is_mine():
                log(f"the board already on :{self.port} serves Sam's own stations folder "
                    f"({self.home}) — adopting it instead of killing it")
                return True
            if free_port is None or not free_port(self.port):
                log(f"something is already listening on :{self.port} and it could not be freed")
                return False
        for sub in ("stations",):
            (self.home / sub).mkdir(parents=True, exist_ok=True)
        if not (self.home / "README.txt").exists():
            try:
                (self.home / "README.txt").write_text(
                    "Sam's Pick Board lives here (sim_board.py, 2026-09-11).\n"
                    "stations/           the sim's garage walls — John's are in CEO-3D-World/tools/stations\n"
                    "preferences.jsonl   the SIM's taste, never John's. Nothing here trains the style model.\n"
                    "Delete this whole folder any time; the next round recreates it.\n", encoding="utf-8")
            except OSError:
                pass
        if not shutil_which("node"):
            log("node is not on PATH — the sim Pick Board cannot start")
            return False
        log(f"starting the sim Pick Board on :{self.port} (writes under {self.home})")
        try:
            self.proc = subprocess.Popen(
                ["node", str(self.server)], cwd=str(self.server.parent), env=env(None, self.home, self.port),
                creationflags=DETACHED, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            log(f"could not start the sim Pick Board: {type(exc).__name__}: {exc}")
            self.proc = None
            return False
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if self.up():
                log(f"the sim Pick Board is up after {int(time.time() - t0)} s")
                return True
            if self.proc.poll() is not None:
                log(f"the sim Pick Board exited immediately (rc={self.proc.returncode})")
                return False
            time.sleep(2)
        log(f"the sim Pick Board never answered on :{self.port} after {int(wait_s)} s")
        return False

    def stop(self, free_port=None) -> None:
        if self.proc is None:
            return
        log("stopping the sim Pick Board")
        try:
            self.proc.terminate()
            self.proc.wait(timeout=15)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None
        t0 = time.time()
        while self.up() and time.time() - t0 < 20:
            time.sleep(2)
        if self.up() and free_port is not None:
            free_port(self.port)

    def is_mine(self) -> bool:
        """Does the server on this port read SAM'S stations folder? Proved, not assumed: drop a file
        into that folder and ask the server whether its station list grew. A board serving John's
        folder — or any other — cannot see it, so a false answer is impossible in the dangerous
        direction. Any failure at all reads as "not mine", so the caller falls back to freeing it."""
        import json as _json
        import uuid as _uuid
        d = self.home / "stations"
        try:
            d.mkdir(parents=True, exist_ok=True)
            before = len(self.stations())
            marker = d / f"_whoami-{_uuid.uuid4().hex[:10]}.json"
            marker.write_text(_json.dumps({"id": marker.stem, "kind": "whoami", "options": []}),
                              encoding="utf-8")
            try:
                return len(self.stations()) > before
            finally:
                try:
                    marker.unlink()
                except OSError:
                    pass
        except Exception:
            return False

    def stations(self) -> list[dict]:
        try:
            st, data = common.http_json("GET", self.url + "/api/stations", timeout=10)
        except common.Backend:
            return []
        return (data or {}).get("stations", []) if st == 200 else []


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def clear_stations(home: Path | None = None, keep_answered: bool = False) -> int:
    """Between rounds: a wall from last night is not a wall Sam should answer tonight."""
    d = Path(home or HOME) / "stations"
    n = 0
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        if keep_answered:
            try:
                import json
                if (json.loads(p.read_text(encoding="utf-8")) or {}).get("answer"):
                    continue
            except Exception:
                pass
        try:
            p.unlink(); n += 1
        except OSError:
            pass
    return n


def selftest() -> int:
    import json
    import tempfile
    fails = []

    def check_(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (("  — " + detail) if detail and not ok else ""))
        if not ok:
            fails.append(name)

    print("sim_board self-test")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        tools = tmp / "tools"; tools.mkdir()
        (tools.parent / "art").mkdir(parents=True, exist_ok=True)
        server = tools / "pick-server.mjs"
        server.write_text('const STATIONS_DIR = process.env.PICK_STATIONS || join(HERE, "stations");', encoding="utf-8")
        home = tmp / "sim-board"

        e = env({}, home, 8294)
        check_("every writable path is redirected",
               all(str(home) in e[k] for k in ("PICK_STATIONS", "PICK_PREFS", "PICK_REROLL", "PICK_FLAGS")), json.dumps(e))
        check_("the port is set", e["PICK_PORT"] == "8294", e["PICK_PORT"])
        check_("a clean config passes", check(home, 8294, server) == [], str(check(home, 8294, server)))
        check_("John's port is refused", any("John's own board" in b for b in check(home, 8194, server)))
        check_("John's tools folder is refused", any("inside John's tools" in b for b in check(tools / "stations", 8294, server)))
        check_("John's taste ledger is refused",
               any("taste ledger" in b for b in check(tools.parent / "art", 8294, server)))

        old = server.read_text(encoding="utf-8")
        server.write_text('const STATIONS_DIR = join(HERE, "stations");', encoding="utf-8")
        check_("an unpatched pick-server is refused", any("no PICK_STATIONS" in b for b in check(home, 8294, server)))
        server.write_text(old, encoding="utf-8")
        check_("a missing pick-server is refused", any("not found" in b for b in check(home, 8294, tmp / "nope.mjs")))

        (home / "stations").mkdir(parents=True)
        (home / "stations" / "a.json").write_text('{"id":"a","items":[],"answer":null}', encoding="utf-8")
        (home / "stations" / "b.json").write_text('{"id":"b","items":[],"answer":{"action":"choose"}}', encoding="utf-8")
        check_("clear_stations keeps answered walls when asked", clear_stations(home, keep_answered=True) == 1)
        check_("clear_stations clears the rest", clear_stations(home) == 1)

        b = SimBoard(port=8194, home=home, server=server)
        check_("SimBoard refuses to start on John's port", b.start(wait_s=1) is False)

    print(("ALL GREEN" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails)))
    return 0 if not fails else 1


def main() -> int:
    common.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    b = SimBoard()
    if a.start:
        print(f"the sim Pick Board is {'up' if b.start() else 'NOT up'} — {b.url}")
        print("Leave this window open: the board stops when this process does.")
        try:
            while b.up():
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        b.stop()
        return 0
    if a.stop:
        b.stop()
        print("stopped (if this session started it). If it is still up, close its window.")
        return 0
    bad = check()
    print(f"sim Pick Board {b.url}  —  {'UP' if b.up() else 'down'}")
    print(f"  writes under: {HOME}")
    print(f"  server:       {SERVER}")
    print("  guard rails:  " + ("all clear" if not bad else "; ".join(bad)))
    if b.up():
        print(f"  walls hanging: {len(b.stations())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
