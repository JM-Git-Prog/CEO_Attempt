"""Wire the sim's own Pick Board (sim_board.py), Sam's eyes (eyes.py) and Sam's memory
(remember.py) into common.py, sam.py and sam_loop.py. Byte-exact, exact-once matches, refuses
the whole file if any anchor is not unique."""
import sys
from pathlib import Path

D = Path(sys.argv[1])

EDITS = {}

# ── common.py ───────────────────────────────────────────────────────────────────────────────
EDITS["common.py"] = [
    ('PICKBOARD = os.getenv("PICKBOARD", "http://127.0.0.1:8194")',
     '# 2026-09-11, John: "Give the sim its own Pick Board". Sam answers walls and judges props on\n'
     '# HIS board (sim_board.py, :8294, its own stations and its own preferences.jsonl), never on\n'
     "# John's :8194 — a robot's pick in John's taste ledger is a corrupted training set, and the\n"
     "# rule that a robot never acts as John is the same rule that governs me.\n"
     'SIM_PICK_PORT = int(os.getenv("SAM_PICK_PORT", "8294"))\n'
     'PICKBOARD = os.getenv("PICKBOARD", f"http://127.0.0.1:{SIM_PICK_PORT}")'),
    ('    "friend":   [os.getenv("SAM_FRIEND_MODEL", "qwen3.8:27b"), "gpt-oss:20b", "gemma4:26b", "gpt-oss:120b-cloud"],\n}',
     '    "friend":   [os.getenv("SAM_FRIEND_MODEL", "qwen3.8:27b"), "gpt-oss:20b", "gemma4:26b", "gpt-oss:120b-cloud"],\n'
     "    # Sam's EYES (2026-09-11). A prop wall is four PNGs; a chooser who cannot see them is rolling a\n"
     "    # die, and a die's answer in a preferences file teaches a style model that taste is random. Local\n"
     "    # and small on purpose — these are cheap, they answer in seconds, and they release the card after.\n"
     '    "eyes":     [os.getenv("SAM_EYES_MODEL", "qwen3-vl:8b"), "qwen2.5vl:7b", "minicpm-v:latest",\n'
     '                 "ibm/granite3.3-vision:2b"],\n}'),
]

# ── sam.py ──────────────────────────────────────────────────────────────────────────────────
EDITS["sam.py"] = [
    ("import furnish  # noqa: E402",
     "import furnish  # noqa: E402\nimport eyes  # noqa: E402\nimport remember  # noqa: E402"),

    # the Board grows the half it was never allowed to touch
    ('''    def answer(self, station_id: str, action: str, tag: str | None = None) -> tuple[int, object]:
        body = {"action": action}
        if tag:
            body["tag"] = tag
        return common.http_json("POST", f"{self.base}/api/stations/{station_id}/answer", body, timeout=15)''',
     '''    def answer(self, station_id: str, action: str, tag: str | None = None) -> tuple[int, object]:
        body = {"action": action}
        if tag:
            body["tag"] = tag
        return common.http_json("POST", f"{self.base}/api/stations/{station_id}/answer", body, timeout=15)

    # ── the PROP wall (2026-09-11, the sim's own board) ──
    # Four takes of one object, waiting for somebody to choose. Until Sam had a board of his own this
    # was closed to him, because a pick appends to preferences.jsonl. On HIS board it is his to answer.
    def picks(self, slug: str) -> list[dict]:
        """Undecided prop picks for this world only. Another world's picks are never Sam's business."""
        try:
            st, data = common.http_json("GET", self.base + "/api/picks", timeout=20)
        except common.Backend:
            return []
        if st != 200 or not isinstance(data, dict):
            return []
        out = []
        for p in data.get("pending", []) or []:
            if isinstance(p, dict) and p.get("slug") == slug and p.get("variants"):
                out.append(p)
        return out

    def pick(self, slug: str, pick_id: str, winner: str, notes: dict | None = None,
             denied: list | None = None) -> tuple[int, object]:
        body = {"slug": slug, "id": pick_id, "winner": winner}
        if notes:
            body["notes"] = notes
        if denied:
            body["denied"] = list(denied)
        return common.http_json("POST", self.base + "/api/pick", body, timeout=20)

    def variant_png(self, slug: str, pick_id: str, tag: str, worlds: Path) -> Path:
        """Where the board reads that PNG from. Sam reads the same file, not the HTTP copy."""
        return worlds / slug / "source" / "cutouts" / "picks" / pick_id / f"{tag}.png"'''),

    # the round remembers, and can see
    ("""                 furnishing: bool = True, per_room: int = 4, friend_ask=None):""",
     """                 furnishing: bool = True, per_room: int = 4, friend_ask=None,
                 mem: dict | None = None, eyes_ask=None, judge_props: bool = True):"""),

    ("""        self.history: list[dict] = []          # Sam's own last few lines, so he does not repeat himself""",
     """        self.history: list[dict] = []          # Sam's own last few lines, so he does not repeat himself
        # WHAT HE CARRIES IN (2026-09-11). John assumed Sam "will get smarter as it loops"; he did not —
        # every round started him from zero, so he asked for the same porch twelve nights running. This
        # is the head he now walks in with: what he already has, what he never got, which rooms are done.
        # Deliberately forgetful: a memory that remembers everything makes an expert, and an expert is
        # no longer a first-time user, which is the entire value of Sam.
        self.mem = remember.blank() if mem is None else dict(mem)
        self.mem_line = remember.opening_line(self.mem)
        self.eyes_ask = eyes_ask if eyes_ask is not None else self._ask_eyes
        self.judge_props = judge_props
        self.props: list[dict] = []            # prop walls he answered on his own board this round"""),

    ('''    def enter_room(self, room: str) -> None:
        """Sam walks into a room and asks his friend what belongs in it."""
        self.room, self.asked_here = room, []
        self.friend.enters(room)
        self.maya = self.friend.say(self.friend.opener())
        self.want = self.friend.ideas(already=[t["thing"] for t in self.things])''',
     '''    def _ask_eyes(self, system: str, messages: list[dict], schema: dict | None) -> dict:
        """Sam looking at ONE picture. Small budget, low temperature: this is not a conversation."""
        return common.ask_lane("eyes", system, messages, schema=schema, temperature=0.2,
                               num_predict=200, timeout=180,
                               capture_to=self.calls, ledger=self.dir.parent / "lane-ledger.jsonl",
                               purpose=f"sam looks at a prop (turn {self.turn})")

    def enter_room(self, room: str) -> None:
        """Sam walks into a room and asks his friend what belongs in it."""
        self.room, self.asked_here = room, []
        self.friend.enters(room)
        self.maya = self.friend.say(self.friend.opener())
        # he does not ask for what he already has: last night's couch is still in the living room
        self.want = self.friend.ideas(already=[t["thing"] for t in self.things] + remember.already_have(self.mem))'''),

    # start somewhere he has not just been
    ("            self.enter_room(furnish.next_room())",
     "            self.enter_room(furnish.next_room(self.rooms_done + remember.rooms_to_skip(self.mem))\n"
     "                            or furnish.next_room(self.rooms_done))"),

    ("                nxt = furnish.next_room(self.rooms_done)",
     "                nxt = (furnish.next_room(self.rooms_done + remember.rooms_to_skip(self.mem))\n"
     "                       or furnish.next_room(self.rooms_done))"),

    # what he remembers is the first thing he is told
    ('''        if self.progress:
            lines.append("While you waited: " + " ".join(self.progress[-4:]))''',
     '''        if self.mem_line and self.turn <= 1:
            lines.append("WHAT YOU REMEMBER FROM THE LAST TIME YOU PLAYED: " + self.mem_line)
        if self.progress:
            lines.append("While you waited: " + " ".join(self.progress[-4:]))'''),

    # the props he asked for last night are waiting for him tonight
    ('''        final = {"final": True, "reason_ended": reason, "turns": self.turn, "didnt_get": self.didnt_get,''',
     '''        if self.judge_props:
            self.look_at_props()
        final = {"final": True, "reason_ended": reason, "turns": self.turn, "didnt_get": self.didnt_get,
                 "props_judged": self.props,'''),

    ('''def play_round(round_dir: Path, **kw) -> dict:''',
     '''    # ── the prop wall, on Sam's own board ────────────────────────────────────────────────────
    def look_at_props(self, limit: int = 6) -> list[dict]:
        """The things Sam asked for on earlier nights come back as four pictures each. He looks at
        them one at a time and picks, or denies them all. No eyes, no opinion — the pick stays open."""
        try:
            waiting = self.board.picks(self.slug)[:limit]
        except Exception as exc:                       # the board is not the round: it never ends it
            common.log(f"prop wall: could not read the board ({type(exc).__name__}: {exc})", file=self.log_file)
            return self.props
        for p in waiting:
            pid, subject = str(p.get("id") or ""), str(p.get("subject") or p.get("id") or "")
            pics = [{"tag": v.get("tag"), "png": self.board.variant_png(self.slug, pid, str(v.get("tag")), self.world.worlds)}
                    for v in p.get("variants") or [] if isinstance(v, dict) and v.get("tag")]
            seen = eyes.look(self.eyes_ask, subject, pics, asked_for=str(p.get("prompt") or subject))
            row = {"id": pid, "subject": subject, "pictures": len(pics),
                   "winner": (seen or {}).get("winner"), "scores": (seen or {}).get("scores"),
                   "why": (seen or {}).get("why"), "denied": (seen or {}).get("denied") or [], "posted": False}
            if seen is None:
                row["why"] = "Sam could not see the pictures — left for John"
            elif seen.get("winner"):
                st, resp = self.board.pick(self.slug, pid, seen["winner"],
                                           notes=seen.get("notes"), denied=seen.get("denied"))
                row["posted"] = st == 200
                row["status"] = st
                if st != 200:
                    row["error"] = str(resp)[:200]
            self.props.append(row)
            common.log(f"prop wall {pid} ({subject}): " + (
                f"picked {row['winner']}" + (" and posted" if row["posted"] else f" but the board said {row.get('status')}")
                if row["winner"] else f"no pick — {row['why']}"), file=self.log_file)
        return self.props


def play_round(round_dir: Path, **kw) -> dict:'''),
]

# ── sam_loop.py ─────────────────────────────────────────────────────────────────────────────
EDITS["sam_loop.py"] = [
    ("import mechanic  # noqa: E402",
     "import mechanic  # noqa: E402\nimport remember  # noqa: E402\nimport sim_board  # noqa: E402"),

    ('CEO_DIR = Path(r"C:\\Users\\JohnM\\Artificial Intelligence\\Projects\\CEO-of-My-Life-Inc")\nPICKBOARD_BAT = CEO_DIR / "CEO-3D-World" / "START-PICK-BOARD.bat"',
     'CEO_DIR = Path(r"C:\\Users\\JohnM\\Artificial Intelligence\\Projects\\CEO-of-My-Life-Inc")\n'
     "# 2026-09-11: the loop used to START JOHN'S OWN Pick Board if it was down. It no longer touches it —\n"
     "# Sam runs his own (sim_board.py). John's :8194 can be up, down or mid-restart and the night is\n"
     "# unaffected, and nothing Sam decides can land in John's stations or his taste ledger.\n"
     'SAM_HEAD = common.HERE / "sam-head.json"          # what Sam carries from one night to the next'),

    ('''            if not ensure_bat_service(common.PICKBOARD + "/api/stations", PICKBOARD_BAT, "the Pick Board :8194", 90):
                log("Pick Board not available — waiting 5 minutes"); time.sleep(300); continue''',
     '''            if not board.start(free_port=free_sim_port):
                log("the sim Pick Board did not come up — waiting 5 minutes"); time.sleep(300); continue'''),

    ("    lr = SimLivingRoom()\n    played = 0",
     "    lr = SimLivingRoom()\n    board = sim_board.SimBoard()\n    played = 0"),

    ('''        heartbeat(phase="stopped", rounds_played=played)
        if a.once:
            lr.stop()''',
     '''        heartbeat(phase="stopped", rounds_played=played)
        if a.once:
            lr.stop()
        board.stop(free_port=free_sim_port)'''),

    # the sim Living Room must talk to the sim board, not John's
    ('''        env = dict(os.environ)
        env["V17_PORT"] = str(self.port)
        env["V17_EVENT_LOG"] = str(EVENTS_SIM)''',
     '''        env = dict(os.environ)
        env["V17_PORT"] = str(self.port)
        env["V17_EVENT_LOG"] = str(EVENTS_SIM)
        env["PICKBOARD"] = common.PICKBOARD          # its walls hang on Sam's board, never John's'''),

    # the gap router pushes prop jobs to the sim board too
    ('''    cmd = ["node", str(common.GAP_ROUTER)] + (["--live"] if live else [])
    try:
        r = subprocess.run(cmd, cwd=str(common.GAP_ROUTER.parent), capture_output=True, text=True, timeout=600, creationflags=DETACHED)''',
     '''    cmd = ["node", str(common.GAP_ROUTER)] + (["--live"] if live else [])
    env = dict(os.environ, PICKBOARD=common.PICKBOARD)   # prop jobs land in the SIM's job bay
    try:
        r = subprocess.run(cmd, cwd=str(common.GAP_ROUTER.parent), capture_output=True, text=True, timeout=600,
                           creationflags=DETACHED, env=env)'''),

    # the round is folded into Sam's head
    ('''    heartbeat(round=rid, phase="playing")
    final = sam.play_round(rd, v17=sam.V17(lr.url), world=world, max_turns=max_turns, minutes=minutes, model=model)''',
     '''    heartbeat(round=rid, phase="playing")
    mem = remember.load(SAM_HEAD)
    if mem.get("nights"):
        log(f"Sam has played {mem['nights']} nights before: has {len(remember.already_have(mem))} things, "
            f"still chasing {len(remember.still_chasing(mem))}, gave up on {len(remember.gave_up_on(mem))}")
    final = sam.play_round(rd, v17=sam.V17(lr.url), world=world, max_turns=max_turns, minutes=minutes,
                           model=model, mem=mem)'''),

    ('''    heartbeat(round=rid, phase="analyzing")
    an = analysis.analyze(rd)''',
     '''    heartbeat(round=rid, phase="analyzing")
    an = analysis.analyze(rd)
    # what he got is the analyzer's verdict, not his hope: "got" is the only one that counts as having it.
    got = [w.get("text") or "" for w in an.get("wishes", []) if w.get("verdict") == "got"]
    mem = remember.remember_round(mem, things=final.get("things_asked_for") or [], got=got,
                                  rooms=final.get("rooms_visited") or [],
                                  house=_house_line(world))
    remember.save(SAM_HEAD, mem)'''),

    ('''def one_round(lr: SimLivingRoom, *, depth: str''',
     '''def _house_line(world) -> str | None:
    """One short sentence naming the house Sam ended the night with, so tomorrow he builds a different
    one. From the world manifest — the app's own truth, never the model's memory of it."""
    man = world.manifest(common.SIM_SLUG) or {}
    brief = man.get("brief") if isinstance(man.get("brief"), dict) else None
    houses = (brief or {}).get("houses") if isinstance((brief or {}).get("houses"), list) else None
    if not houses:
        return None
    h = houses[0] if isinstance(houses[0], dict) else {}
    bits = [str(h.get(k)) for k in ("style", "stories", "roof") if h.get(k)]
    return ", ".join(bits)[:120] or None


def one_round(lr: SimLivingRoom, *, depth: str'''),
]


def apply(name, edits):
    p = D / name
    data = p.read_bytes()
    before = len(data)
    for old, new in edits:
        ob, nb = old.encode("utf-8"), new.encode("utf-8")
        n = data.count(ob)
        if n != 1:
            print("REFUSED %s: %d matches for %r" % (name, n, old[:70]))
            return False
        data = data.replace(ob, nb)
    p.write_bytes(data)
    a = p.read_bytes()
    print("OK %s: %d -> %d bytes, %d edits, CR %d" % (name, before, len(a), len(edits), a.count(b"\x0d")))
    return True


ok = True
for name, edits in EDITS.items():
    if not apply(name, edits):
        ok = False
print("ALL APPLIED" if ok else "SOMETHING WAS REFUSED — nothing partial was written for that file")
sys.exit(0 if ok else 1)
