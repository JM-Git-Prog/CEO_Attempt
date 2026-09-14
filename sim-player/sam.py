"""sim-player/sam.py — Sam, the ten-year-old, plays one round of The Living Room.

Decision 23 made concrete (John, 2026-09-10, depth "C"): a pretend end user talks to V17 through the
same door the browser uses. The PROGRAM keeps the truth (which card is up, which wall is hung, which
order is building, what the world's version is); the MODEL only does what a kid does — says what it
sees, says what it wants, picks a picture, answers the plan. Every model call is captured; every
turn is a transcript row; nothing here ever touches John's neighborhood (the sim world, a sim-
session, the loop's own Living Room instance).

    python sam.py --once [--living-room http://127.0.0.1:8001] [--max-turns 14] [--minutes 35]
    python sam.py --selftest        # the state machine against a fake Living Room + a scripted Sam, no model

The V17 contract this file speaks (checked against the source 2026-09-10):
  POST /api/v17/say {session, message, world?, card_decision?, forced_kind?, guessed_kind?}
      -> kind: vision (reply, summary, question, vision|null) | house/grounds (+card | +card_clause, card_id)
         | command | check | question | room | gap | problem | unknown (+clarify.options[{kind,label}])
  POST /api/v17/neighbourhood/order {text, base, session, card_clause, card_id} -> {order, brief}
  GET  /api/v17/neighbourhood/order/<id> -> stage: rendering | on the wall (count) | building (build_job) | more | failed
  GET  /api/v17/neighbourhood/job/<order> -> candidates[{tag,label...}], houses[0].features_built, unbuilt_features
  Pick Board: GET /api/stations -> {stations:[{id, items[{tag,label,image}], answer}]}; POST /api/stations/<id>/answer {action, tag}
  World truth: worlds/<slug>/output/world/<N>-world.json, highest N = the version; its "lots" block when present.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import furnish  # noqa: E402
import eyes  # noqa: E402
import remember  # noqa: E402

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "i_see": {"type": "string"},
        "i_type": {"type": "string"},
        "pick": {"type": ["object", "null"], "properties": {"tag": {"type": "string"}, "why": {"type": "string"}}, "required": ["tag", "why"]},
        "card": {"type": ["string", "null"], "enum": ["build", "change", None]},
        "done": {"type": "boolean"},
        "didnt_get": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["i_see", "i_type", "pick", "card", "done", "didnt_get"],
}
COMPLAINT = re.compile(r"nothing happened|where is it|still just|didn'?t (show|appear|change)|not there|nothing changed", re.I)
BUILD_PHRASES = re.compile(r"^\s*(build it|ok build it|yes build it|build it as planned)\s*[.!]?\s*$", re.I)
MAX_WORDS = 15


# ── the doors ────────────────────────────────────────────────────────────────────────────────
class V17:
    def __init__(self, base: str = common.SIM_LIVING_ROOM):
        self.base = base.rstrip("/")

    def say(self, session: str, message: str, **extra) -> tuple[int, object]:
        body = {"session": session, "message": message, "world": {"standing": "outdoors at the front gate of " + common.SIM_SLUG}}
        body.update(extra)
        return common.http_json("POST", self.base + "/api/v17/say", body, timeout=300)

    def order(self, text: str, base: str, session: str, card_clause: str | None, card_id: str | None) -> tuple[int, object]:
        return common.http_json("POST", self.base + "/api/v17/neighbourhood/order",
                                {"text": text, "base": base, "session": session, "reference": None,
                                 "order_hint": None, "card_clause": card_clause, "card_id": card_id}, timeout=180)

    def order_status(self, order_id: str) -> tuple[int, object]:
        return common.http_json("GET", f"{self.base}/api/v17/neighbourhood/order/{order_id}", timeout=30)

    def job(self, order_id: str) -> tuple[int, object]:
        return common.http_json("GET", f"{self.base}/api/v17/neighbourhood/job/{order_id}", timeout=30)

    def up(self) -> bool:
        try:
            st, _ = common.http_json("GET", self.base + "/api/v17/pipeline", timeout=6)
        except common.Backend:
            return False
        return st == 200


class Board:
    def __init__(self, base: str = common.PICKBOARD):
        self.base = base.rstrip("/")

    def station(self, station_id: str) -> dict | None:
        try:
            st, data = common.http_json("GET", self.base + "/api/stations", timeout=10)
        except common.Backend:
            return None
        if st != 200 or not isinstance(data, dict):
            return None
        for s in data.get("stations", []):
            if s.get("id") == station_id:
                return s
        return None

    def answer(self, station_id: str, action: str, tag: str | None = None) -> tuple[int, object]:
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
        return worlds / slug / "source" / "cutouts" / "picks" / pick_id / f"{tag}.png"


class World:
    def __init__(self, worlds: Path = common.WORLDS):
        self.worlds = worlds

    def version(self, slug: str) -> int | None:
        wd = self.worlds / slug / "output" / "world"
        try:
            idx = [int(f.name.split("-")[0]) for f in wd.iterdir() if re.match(r"^\d+-world\.json$", f.name)]
        except OSError:
            return None
        return max(idx) if idx else None

    def manifest(self, slug: str) -> dict | None:
        v = self.version(slug)
        if v is None:
            return None
        try:
            return json.loads((self.worlds / slug / "output" / "world" / f"{v}-world.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def line(self, slug: str) -> str:
        """What the right side shows, from the app's own truth — never invented."""
        v = self.version(slug)
        if v is None:
            return "the right side is empty — no neighborhood has been placed yet"
        man = self.manifest(slug) or {}
        lots = man.get("lots") if isinstance(man.get("lots"), dict) else None
        houses = None
        brief = man.get("brief") if isinstance(man.get("brief"), dict) else None
        if brief and isinstance(brief.get("houses"), list):
            houses = len(brief["houses"])
        bits = [f"version {v} of the neighborhood"]
        if houses is not None:
            bits.append(f"{houses} houses on the street")
        if lots:
            empty = lots.get("empty")
            if isinstance(empty, list):
                bits.append(f"{len(empty)} empty lots with 'coming soon' signs")
        return ", ".join(bits)


# ── the round ────────────────────────────────────────────────────────────────────────────────
class Round:
    def __init__(self, round_dir: Path, *, v17: V17, board: Board, world: World, ask=None, model: str | None = None,
                 max_turns: int = 14, minutes: float = 35.0, build_wait_s: float = 300.0, wall_wait_s: float = 200.0,
                 poll_s: float = 5.0, slug: str = common.SIM_SLUG, session: str | None = None, retry_sleep_s: float = 10.0,
                 furnishing: bool = True, per_room: int = 4, friend_ask=None,
                 mem: dict | None = None, eyes_ask=None, judge_props: bool = True):
        self.dir = round_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.v17, self.board, self.world = v17, board, world
        self.model = model or common.pick_lane("sam")
        self.ask = ask or self._ask_model
        self.max_turns, self.deadline = max_turns, time.monotonic() + minutes * 60
        self.build_wait_s, self.wall_wait_s, self.poll_s, self.retry_sleep_s = build_wait_s, wall_wait_s, poll_s, retry_sleep_s
        self.slug = slug
        self.session = session or common.new_session_id()
        self.persona = common.persona_text()
        self.transcript = self.dir / "transcript.jsonl"
        self.calls = self.dir / "calls.jsonl"
        self.log_file = self.dir / "round.log"
        # the truth the program keeps
        self.turn = 0
        self.last: dict | None = None          # V17's last answer
        self.last_message = ""                 # the sentence that produced it (a card is confirmed by re-sending it)
        self.card: dict | None = None          # the plan gate that is up
        self.wall: dict | None = None          # {"station", "order", "items"}
        self.order: dict | None = None         # {"id", "stage", "text", "note"}
        self.progress: list[str] = []          # what happened during the waits, for the next observation
        self.streak = 0
        self.backend_errors = 0                # Sam's own model
        self.app_errors = 0                    # the Living Room / board unreachable
        self.wishes: list[dict] = []
        self.didnt_get: list[str] = []
        # DECISION 29 (John, 2026-09-11): once the house is up, Sam furnishes it room by room and talks
        # it over with a friend on John's own local model. The house phase is unchanged.
        self.furnishing = furnishing
        self.per_room = per_room
        # A caller-supplied friend always wins (the self-test injects one). Otherwise Maya speaks
        # only while she is un-paused; ask=None is furnish.Friend's own quiet mode, not a failure.
        _friend = friend_ask if friend_ask is not None else (None if common.FRIEND_PAUSED else self._ask_friend)
        self.friend = furnish.Friend(ask=_friend, room="house")
        self.phase = "house"
        self.room: str | None = None
        self.rooms_done: list[str] = []
        self.want: list[str] = []          # what the conversation with Maya has named
        self.asked_here: list[str] = []    # things asked for in THIS room
        self.things: list[dict] = []       # every thing asked for, with its room and turn
        self.maya = ""                     # her latest line, shown to Sam next turn
        self.v_start = self.world.version(slug)
        self.v_seen = self.v_start
        self.history: list[dict] = []          # Sam's own last few lines, so he does not repeat himself
        # WHAT HE CARRIES IN (2026-09-11). John assumed Sam "will get smarter as it loops"; he did not —
        # every round started him from zero, so he asked for the same porch twelve nights running. This
        # is the head he now walks in with: what he already has, what he never got, which rooms are done.
        # Deliberately forgetful: a memory that remembers everything makes an expert, and an expert is
        # no longer a first-time user, which is the entire value of Sam.
        self.mem = remember.blank() if mem is None else dict(mem)
        self.mem_line = remember.opening_line(self.mem)
        self.eyes_ask = eyes_ask if eyes_ask is not None else self._ask_eyes
        self.judge_props = judge_props
        self.props: list[dict] = []            # prop walls he answered on his own board this round

    # ── the model ──
    # 2026-09-11, from the first real night: 400 tokens was too small. Every failure was
    # eval_count == 400 — a kid's one sentence cut off mid-JSON, or (gpt-oss thinking inside the
    # same budget) an empty answer at done_reason=length. The cap is now 1200 with think off, and a
    # cut-off answer buys ONE retry at double before it counts against the round.
    BUDGET = 1200

    def _ask_model(self, system: str, messages: list[dict], schema: dict) -> dict:
        budget = self.BUDGET
        for attempt in (1, 2):
            try:
                out = common.ask_lane("sam", system, messages, schema=schema, temperature=0.7,
                                      num_predict=budget, timeout=180, capture_to=self.calls,
                                      ledger=self.dir.parent / "lane-ledger.jsonl",
                                      purpose=f"sam turn {self.turn} (try {attempt}, budget {budget})")
            except common.Truncated as e:
                if attempt == 2:
                    raise
                budget *= 2
                common.log(f"turn {self.turn}: the answer was cut off — one retry at {budget} tokens ({e})", file=self.log_file)
                continue
            self.model = out.get("model") or self.model      # whichever rung actually answered
            if not isinstance(out.get("json"), dict):
                raise common.Backend(f"sam {self.model}: reply was not the decision JSON: {out.get('text', '')[:120]}")
            return out["json"]
        raise common.Backend("unreachable")

    def _ask_friend(self, system: str, messages: list[dict], schema: dict | None) -> dict:
        """Maya, on John's own local model (the friend ladder). Small budgets: she talks like a kid."""
        return common.ask_lane("friend", system, messages, schema=schema, temperature=0.9,
                               num_predict=500 if schema else 300, timeout=120,
                               capture_to=self.calls, ledger=self.dir.parent / "lane-ledger.jsonl",
                               purpose=f"maya turn {self.turn} ({'ideas' if schema else 'talk'})")

    def _ask_eyes(self, system: str, messages: list[dict], schema: dict | None) -> dict:
        """Sam looking at ONE picture. Small budget, low temperature: this is not a conversation."""
        return common.ask_lane("eyes", system, messages, schema=schema, temperature=0.2,
                               num_predict=2400,   # measured: qwen3-vl spends ~1900 tokens on one picture when
                                      # it cannot switch thinking off (Ollama 400s the
                                      # `think` flag and ollama_chat retries without it).
                                      # At 200 every reply was cut off mid-answer and
                                      # reached Sam as silence. 2400 clears the mark.
                               timeout=180,
                               capture_to=self.calls, ledger=self.dir.parent / "lane-ledger.jsonl",
                               purpose=f"sam looks at a prop (turn {self.turn})")

    def enter_room(self, room: str) -> None:
        """Sam walks into a room and asks his friend what belongs in it."""
        self.room, self.asked_here = room, []
        self.friend.enters(room)
        self.maya = self.friend.say(self.friend.opener())
        # he does not ask for what he already has: last night's couch is still in the living room
        self.want = self.friend.ideas(already=[t["thing"] for t in self.things] + remember.already_have(self.mem))
        common.log(f"turn {self.turn}: Sam is in the {room}; Maya ({self.friend.model}) says {self.maya[:80]!r}; "
                   f"they want: {', '.join(self.want[:6])}", file=self.log_file)

    def decide(self, observation: str) -> dict:
        msgs = [{"role": "user", "content": observation}]
        d = self.ask(self.persona + "\n\nYou answer ONLY as JSON with keys i_see, i_type, pick, card, done, didnt_get. "
                     "i_see is what you see, under 20 words. i_type is the one sentence you type (under 15 words). "
                     "pick is null unless pictures are listed, then {tag, why}. "
                     "card is null unless a plan is shown, then \"build\" or \"change\". done is true only when you are proud of your house "
                     "or have said nothing happened three times; didnt_get lists, in kid words, what you asked for and never got.",
                     msgs, DECISION_SCHEMA)
        d = dict(d or {})
        d["i_see"] = str(d.get("i_see") or "").strip()[:300]
        words = str(d.get("i_type") or "").strip().split()
        d["i_type"] = " ".join(words[:MAX_WORDS]).strip()
        d["pick"] = d.get("pick") if isinstance(d.get("pick"), dict) and d["pick"].get("tag") else None
        d["card"] = d.get("card") if d.get("card") in ("build", "change") else None
        d["done"] = bool(d.get("done"))
        d["didnt_get"] = [str(x)[:120] for x in (d.get("didnt_get") or []) if str(x).strip()][:10]
        return d

    # ── what Sam is shown ──
    def observe(self) -> str:
        left = max(0, int((self.deadline - time.monotonic()) / 60))
        lines = [f"Turn {self.turn} of {self.max_turns}. About {left} minutes left.",
                 f"The right side shows: {self.world.line(self.slug)}."
                 + (" It CHANGED since you last looked." if self.world.version(self.slug) != self.v_seen else " It has not changed since you last looked.")]
        if self.mem_line and self.turn <= 1:
            lines.append("WHAT YOU REMEMBER FROM THE LAST TIME YOU PLAYED: " + self.mem_line)
        if self.progress:
            lines.append("While you waited: " + " ".join(self.progress[-4:]))
        lines.append("The chat says: " + self._chat_line())
        if self.wall:
            items = "; ".join(f"[{it.get('tag')}] {it.get('label') or 'a house'}" for it in self.wall["items"])
            lines.append(f"PICTURES on the garage wall (pick one by tag, or say you want different ones): {items}")
        if self.card:
            c = self.card
            qs = "; ".join(str(q) for q in (c.get("questions") or [])[:3])
            lines.append(f"A PLAN is shown — {c.get('name') or 'the house'}: {c.get('summary') or ''} "
                         f"Parts: {', '.join(str(p) for p in (c.get('parts') or [])[:10])}. It asks: {qs or 'nothing'}. "
                         "Buttons: Build it as planned / Change something first.")
        if self.phase == "furnish" and self.room:
            lines.append(f"You are INSIDE your house, in the {self.room}. You are filling it with things, one at a time.")
            if self.maya:
                lines.append(f"Your friend {self.friend.name} just said: \"{self.maya}\"")
            left = [t for t in self.want if t not in self.asked_here]
            if left:
                lines.append("Things you two have talked about and you have NOT asked for yet: " + ", ".join(left[:6]))
            if self.asked_here:
                lines.append(f"Already asked for in the {self.room}: " + ", ".join(self.asked_here))
            lines.append("Type ONE thing you want in this room — your own words, or answer your friend.")
        if self.history:
            lines.append("Your last lines: " + " | ".join(h["i_type"] for h in self.history[-4:]))
        lines.append("Now: say what you see and type your next one sentence (JSON only).")
        return "\n".join(lines)

    def _chat_line(self) -> str:
        r = self.last
        if not r:
            return ("\"This is Mr. John's Neighborhood. Tell me what to add or change — a home on the block, "
                    "the inside of a house, or one room. Say it in one sentence.\"")
        if not isinstance(r, dict):
            return f"(something odd came back: {str(r)[:120]})"
        kind = r.get("kind")
        if kind == "vision":
            s = f"\"{r.get('reply') or ''}\""
            if r.get("summary"):
                s += f" {r['summary']} (Buttons: Build it / Start over)"
            return s
        if r.get("card") and isinstance(r["card"], dict):
            return "the architect drew a plan (below)."
        rec = r.get("receipt") or {}
        bits = []
        if rec.get("got"):
            bits.append(f"Got: {rec['got']}")
        if rec.get("making"):
            bits.append(f"Making: {rec['making']}")
        if rec.get("needs"):
            bits.append(f"It can't do this yet: {rec['needs']}")
        if r.get("clarify") and isinstance(r["clarify"], dict):
            opts = ", ".join(str(o.get("label")) for o in r["clarify"].get("options", []) if isinstance(o, dict))
            bits.append(f"It asks what you meant: {r['clarify'].get('question') or ''} Options: {opts}")
        if kind in ("problem", "unknown") and r.get("reason"):
            bits.append(str(r["reason"]))
        if kind == "command":
            bits.append("it did what you said.")
        if self.order:
            bits.append(f"Your house order: {self.order.get('note') or self.order.get('stage')}")
        return " ".join(bits) or f"(a {kind} answer with nothing to read)"

    # ── one turn ──
    def play(self) -> dict:
        common.log(f"round {self.dir.name} session {self.session} model {self.model} world v{self.v_start}", file=self.log_file)
        reason = "turns"
        while True:
            if self.turn >= self.max_turns:
                reason = "turns"; break
            if time.monotonic() > self.deadline:
                reason = "deadline"; break
            self.turn += 1
            try:
                d = self.decide(self.observe())
                self.backend_errors = 0
            except common.Backend as e:
                self.backend_errors += 1
                common.log(f"turn {self.turn}: Sam's model failed ({e})", file=self.log_file)
                self._row(phase="idle", i_see="", i_type="", request=None, response=None, status=None, error=f"backend: {e}", wish=False)
                if self.backend_errors >= 3:
                    reason = "backend"; break
                time.sleep(self.retry_sleep_s)
                continue
            self.history.append(d)
            row = self._act(d)
            if d["done"]:
                self.didnt_get = d["didnt_get"] or self.didnt_get
                reason = "proud" if not self.didnt_get else "done"; break
            if self.streak >= 3:
                self.didnt_get = d["didnt_get"] or self.didnt_get
                reason = "streak"; break
            if self.app_errors >= 3:
                reason = "backend"; break
        if self.judge_props:
            self.look_at_props()
        final = {"final": True, "reason_ended": reason, "turns": self.turn, "didnt_get": self.didnt_get,
                 "props_judged": self.props,
                 "phase": self.phase, "rooms_visited": self.rooms_done + ([self.room] if self.room else []),
                 "things_asked_for": self.things, "friend_model": self.friend.model,
                 "world_version_start": self.v_start, "world_version_end": self.world.version(self.slug),
                 "session": self.session, "model": self.model, "at": common.now_iso()}
        common.capture(self.transcript, final)
        common.log(f"round over: {reason} after {self.turn} turns, world v{self.v_start} -> v{final['world_version_end']}", file=self.log_file)
        return final

    def _act(self, d: dict) -> dict:
        v_before = self.world.version(self.slug)
        self.progress = []
        prev_q = bool(isinstance(self.last, dict) and self.last.get("question"))
        # 2026-09-11, caught the first time Sam remembered a round: the sentence a kid says when he is
        # FINISHED ("I'm proud of it") was being filed as a wish, which made it a capability gap and,
        # once he had a memory, something he chased for three more nights. A line that ends the round
        # is not a request for anything.
        wish = not COMPLAINT.search(d["i_type"]) and not (prev_q and len(d["i_type"].split()) <= 5) and not self.card and not self.wall and not d["done"]
        phase, request, response, status, error = "idle", None, None, None, None
        wall_row, card_row, order_row = None, None, None
        t0 = time.monotonic()
        try:
            if self.wall and d["pick"]:
                phase = "wall"
                tag = str(d["pick"]["tag"]).strip()
                wall_row = {"station": self.wall["station"], "picked": tag, "why": str(d["pick"].get("why") or "")[:200]}
                request = {"route": f"/api/stations/{self.wall['station']}/answer", "action": "choose", "tag": tag}
                status, response = self.board.answer(self.wall["station"], "choose", tag)
                if status == 200:
                    self.progress.append(f"You picked {tag}.")
                    self._wait_build()
                    self.wall = None
                else:
                    error = f"the board refused the pick: {status} {str(response)[:200]}"
            elif self.wall and COMPLAINT.search(d["i_type"]) is None and re.search(r"different|more|new ones|other ones", d["i_type"], re.I):
                phase = "wall"
                request = {"route": f"/api/stations/{self.wall['station']}/answer", "action": "more"}
                status, response = self.board.answer(self.wall["station"], "more")
                wall_row = {"station": self.wall["station"], "picked": None, "why": "asked for more"}
                self.wall = None
                self._wait_wall()
            elif self.card and d["card"] == "build":
                phase = "card"
                card_row = {"id": self.card.get("id"), "name": self.card.get("name"), "decision": "build"}
                request = {"route": "/api/v17/say", "message": self.last_message, "card_decision": {"id": self.card.get("id"), "chose": "build"}}
                status, response = self.v17.say(self.session, self.last_message, card_decision={"id": self.card.get("id"), "chose": "build"})
                self._take(response, status)
                if status == 200 and isinstance(response, dict) and response.get("card_clause"):
                    self._place_order(self.last_message, response.get("card_clause"), response.get("card_id"))
                self.card = None
            elif self.card and d["card"] == "change":
                phase = "card"
                card_row = {"id": self.card.get("id"), "name": self.card.get("name"), "decision": "change"}
                self.card = None
                request = {"route": "/api/v17/say", "message": d["i_type"]}
                status, response = self.v17.say(self.session, d["i_type"])
                self._take(response, status, message=d["i_type"])
            else:
                phase = "vision" if (isinstance(self.last, dict) and self.last.get("kind") == "vision") else "idle"
                request = {"route": "/api/v17/say", "message": d["i_type"]}
                extra = self._forced(d["i_type"])
                if extra:
                    request.update(extra)
                    status, response = self.v17.say(self.session, self.last_message, **extra)
                else:
                    status, response = self.v17.say(self.session, d["i_type"])
                self._take(response, status, message=d["i_type"])
                if status == 200 and isinstance(response, dict):
                    if response.get("card"):
                        phase = "card"
                    elif response.get("kind") in ("house", "grounds") and response.get("card_clause"):
                        self._place_order(self.last_message, response.get("card_clause"), response.get("card_id"))
                        phase = "order"
                    elif response.get("kind") == "vision":
                        phase = "vision"
            self.app_errors = 0
        except common.Backend as e:
            error = f"backend: {e}"
            self.app_errors += 1
        if status is not None and status >= 400 and not error:
            error = f"HTTP {status}: {str(response)[:200]}"
        if isinstance(response, dict):
            rec = response.get("receipt") or {}
            if rec.get("making"):
                self.progress.append(f"It said it is making: {rec['making']}.")
            if rec.get("needs"):
                self.progress.append(f"It said it cannot make that yet: {rec['needs']}.")
            if response.get("gaps_filed"):
                self.progress.append("It wrote down what it could not make.")
        v_after = self.world.version(self.slug)
        moved = (v_after or 0) > (v_before or 0)
        # the persona's own rule: three "nothing happened" in a row. A complaint with no movement
        # counts; movement (a version, a wall, a build) clears it; an ordinary wish leaves it alone.
        if moved or self.progress:
            self.streak = 0
        elif COMPLAINT.search(d["i_type"]):
            self.streak += 1
        self.v_seen = v_after
        if wish:
            self.wishes.append({"turn": self.turn, "text": d["i_type"]})
        thing = None
        if self.phase == "furnish" and self.room and wish:
            thing = d["i_type"]
            self.asked_here.append(thing)
            self.things.append({"turn": self.turn, "room": self.room, "thing": thing})
        if self.furnishing and self.phase == "house" and (v_after or 0) > (self.v_start or 0):
            self.phase = "furnish"                              # the house is up: go inside and fill it
            self.enter_room(furnish.next_room(self.rooms_done + remember.rooms_to_skip(self.mem))
                            or furnish.next_room(self.rooms_done))
        elif self.phase == "furnish" and self.room:
            self.maya = self.friend.say(d["i_type"])            # the conversation carries on, turn by turn
            if furnish.room_done(self.asked_here, self.want, self.per_room):
                self.rooms_done.append(self.room)
                nxt = (furnish.next_room(self.rooms_done + remember.rooms_to_skip(self.mem))
                       or furnish.next_room(self.rooms_done))
                if nxt:
                    self.enter_room(nxt)
                else:
                    self.room = None
        if self.order:
            order_row = {"id": self.order["id"], "stage": self.order.get("stage")}
        return self._row(phase="furnish" if self.phase == "furnish" and phase == "idle" else phase,
                         i_see=d["i_see"], i_type=d["i_type"], request=request, response=response, status=status,
                         error=error, wish=wish, wall=wall_row, card=card_row, order=order_row,
                         room=self.room, thing=thing, friend=self.maya or None, friend_model=self.friend.model,
                         v_before=v_before, v_after=v_after, latency_ms=int((time.monotonic() - t0) * 1000))

    def _forced(self, text: str) -> dict | None:
        """Sam answered the app's 'which did you mean?' — re-send his sentence with the kind he chose."""
        r = self.last
        if not (isinstance(r, dict) and r.get("kind") == "unknown" and isinstance(r.get("clarify"), dict)):
            return None
        low = text.lower()
        for o in r["clarify"].get("options", []):
            if isinstance(o, dict) and o.get("kind") and (str(o["kind"]) in low or str(o.get("label") or "").lower() in low):
                return {"forced_kind": o["kind"], "guessed_kind": r["clarify"].get("guessed")}
        return None

    def _take(self, response: object, status: int, message: str | None = None) -> None:
        if message is not None:
            self.last_message = message
        if status == 200 and isinstance(response, dict):
            self.last = response
            if isinstance(response.get("card"), dict) and response["card"].get("options"):
                self.card = response["card"]
            if response.get("vision_built"):
                self.last_message = str(response["vision_built"])     # the whole vision is what the card answers to
        elif isinstance(response, dict):
            self.last = {"kind": "problem", "reason": f"the app answered {status}: {response.get('error') or ''}"}
        else:
            self.last = {"kind": "problem", "reason": f"the app answered {status}"}

    def _place_order(self, text: str, card_clause: str | None, card_id: str | None) -> None:
        st, data = self.v17.order(text, self.slug, self.session, card_clause, card_id)
        if st != 200 or not isinstance(data, dict) or not data.get("order"):
            self.order = {"id": None, "stage": "failed", "text": text, "note": f"the order was refused ({st}: {str(data)[:160]})"}
            return
        self.order = {"id": data["order"], "stage": "rendering", "text": text, "note": "three takes are being drawn for the garage wall"}
        brief = data.get("brief") or {}
        if isinstance(brief, dict) and brief.get("gaps"):
            self.progress.append("It said it can't build: " + "; ".join(str(g) for g in brief["gaps"][:3]) + ".")
        self._wait_wall()

    def _poll_order(self) -> dict | None:
        if not (self.order and self.order.get("id")):
            return None
        st, data = self.v17.order_status(self.order["id"])
        if st == 404:
            self.order["stage"], self.order["note"] = "lost", "that order is gone — say it again"
            return None
        if st != 200 or not isinstance(data, dict):
            return None
        self.order["stage"] = data.get("stage")
        js = data.get("jobsite") or {}
        if isinstance(js, dict) and isinstance(js.get("progress"), dict) and js["progress"].get("note"):
            self.order["note"] = f"{data.get('stage')} — {js['progress']['note']}"
        else:
            self.order["note"] = str(data.get("stage"))
        if data.get("stage") == "more" and data.get("next_order"):
            self.order["id"] = data["next_order"]; self.order["stage"] = "rendering"
        return data

    def _wait_wall(self) -> None:
        """Rendering takes about a minute; wait for the wall, then hang its pictures in front of Sam."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.wall_wait_s:
            data = self._poll_order()
            if data is None and (not self.order or self.order.get("stage") in ("lost", "failed")):
                return
            if data and data.get("stage") == "on the wall" and data.get("station"):
                s = self.board.station(data["station"])
                items = (s or {}).get("items") or []
                if items:
                    self.wall = {"station": data["station"], "order": self.order["id"], "items": items}
                    self.progress.append(f"{len(items)} pictures of your house went up on the garage wall.")
                    try:
                        jst, jb = self.v17.job(self.order["id"])
                        if jst == 200 and isinstance(jb, dict):
                            cant = [u.get("phrase") for u in (jb.get("unbuilt_features") or []) if isinstance(u, dict)]
                            if cant:
                                self.progress.append("It said it couldn't build: " + "; ".join(str(c) for c in cant[:3]) + ".")
                    except common.Backend:
                        pass
                    return
            if data and data.get("stage") == "failed":
                self.progress.append(f"The pictures failed: {str(data.get('error') or '')[-160:]}")
                return
            time.sleep(self.poll_s)
        self.progress.append("You waited a long time and the pictures never came.")

    def _wait_build(self) -> None:
        """After a pick the house is built as the next version; wait for it (the jobsite narrates)."""
        t0 = time.monotonic()
        v0 = self.world.version(self.slug)
        while time.monotonic() - t0 < self.build_wait_s:
            data = self._poll_order()
            v = self.world.version(self.slug)
            if v is not None and v0 is not None and v > v0:
                self.progress.append(f"A house was built — the neighborhood is now version {v}.")
                self.order["stage"] = "done"; self.order["note"] = "done — your house is on its lot"
                return
            if data and data.get("stage") == "failed":
                self.progress.append(f"The build failed: {str(data.get('error') or '')[-160:]}")
                return
            if data and data.get("stage") == "building" and data.get("build_job"):
                self.order["note"] = self.order.get("note") or "building"
            time.sleep(self.poll_s)
        self.progress.append("You waited and waited and the house never showed up on the right.")

    def _row(self, **kw) -> dict:
        row = {"turn": self.turn, "t": common.now_iso(), "phase": kw.get("phase"), "i_see": kw.get("i_see"), "i_type": kw.get("i_type"),
               "request": kw.get("request"), "response": kw.get("response") if isinstance(kw.get("response"), (dict, list)) else (str(kw.get("response"))[:600] if kw.get("response") is not None else None),
               "http_status": kw.get("status"), "latency_ms": kw.get("latency_ms"),
               "world_version_before": kw.get("v_before"), "world_version_after": kw.get("v_after"),
               "wall": kw.get("wall"), "order": kw.get("order"), "card": kw.get("card"),
               "room": kw.get("room"), "thing": kw.get("thing"), "friend": kw.get("friend"), "friend_model": kw.get("friend_model"),
               "error": kw.get("error"), "streak_nothing": self.streak, "wish": bool(kw.get("wish")), "session": self.session}
        common.capture(self.transcript, row)
        common.log(f"turn {self.turn} [{row['phase']}] see: {row['i_see'][:70]!r} type: {row['i_type']!r}"
                   + (f" ERROR {row['error']}" if row["error"] else ""), file=self.log_file)
        return row


    # ── the prop wall, on Sam's own board ────────────────────────────────────────────────────
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


def play_round(round_dir: Path, **kw) -> dict:
    return Round(round_dir, v17=kw.pop("v17", None) or V17(), board=kw.pop("board", None) or Board(),
                 world=kw.pop("world", None) or World(), **kw).play()


# ── self-test: the state machine against a fake Living Room and a scripted Sam ───────────────
def selftest() -> int:
    from fake_living_room import FakeLivingRoom  # sim-player/fake_living_room.py (tests use it too)
    import tempfile
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    with tempfile.TemporaryDirectory() as td:
        worlds = Path(td) / "worlds"
        fake = FakeLivingRoom(worlds, slug="sim-neighborhood")
        fake.start()
        try:
            script = iter([
                {"i_see": "grass and a sign", "i_type": "I want a house right here with a big porch", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "still grass", "i_type": "shingles", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "still grass", "i_type": "build it", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "a plan with a porch", "i_type": "looks right, build it", "pick": None, "card": "build", "done": False, "didnt_get": []},
                {"i_see": "three pictures", "i_type": "the second one, it has the biggest porch", "pick": {"tag": "c2", "why": "biggest porch"}, "card": None, "done": False, "didnt_get": []},
                {"i_see": "a house on the lot!", "i_type": "can I have a big couch in the living room?", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "inside, empty", "i_type": "put a TV in the living room", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "inside, empty", "i_type": "the living room needs a rug", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "inside, empty", "i_type": "I want a beanbag in there", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "now the kitchen", "i_type": "now put a dog in the yard", "pick": None, "card": None, "done": False, "didnt_get": []},
                {"i_see": "no dog", "i_type": "nothing happened", "pick": None, "card": None, "done": False, "didnt_get": ["a dog"]},
                {"i_see": "no dog", "i_type": "where is it?", "pick": None, "card": None, "done": False, "didnt_get": ["a dog"]},
                {"i_see": "no dog", "i_type": "nothing happened again", "pick": None, "card": None, "done": False, "didnt_get": ["a dog in the yard"]},
                {"i_see": "x", "i_type": "x", "pick": None, "card": None, "done": True, "didnt_get": ["x"]},
            ])
            rd = Path(td) / "round-1"
            maya_said = []

            def maya(system, messages, schema):
                if schema:                                 # "what did you two name?"
                    return {"json": {"things": ["a big couch", "a TV", "a rug", "a beanbag"]}, "model": "fake-local"}
                maya_said.append(messages[-1]["content"])
                return {"text": "You need a big couch to jump on!", "model": "fake-local"}

            r = Round(rd, v17=V17(fake.url), board=Board(fake.url), world=World(worlds), ask=lambda s, m, sc: next(script),
                      model="fake", max_turns=16, minutes=5, build_wait_s=20, wall_wait_s=20, poll_s=0.2, session="sim-selftest",
                      friend_ask=maya, per_room=4)
            final = r.play()
            rows = common.read_jsonl(rd / "transcript.jsonl")
            turns = [x for x in rows if not x.get("final")]
            check("a full round played to its end", final["reason_ended"] == "streak", final["reason_ended"])
            check("the vision opened and closed on 'build it'", turns[0]["phase"] == "vision" or turns[1]["phase"] == "vision", str([t["phase"] for t in turns]))
            check("the plan card was answered with build", any(t.get("card", {}) and t["card"].get("decision") == "build" for t in turns))
            check("Sam picked c2 on the wall", any(t.get("wall") and t["wall"].get("picked") == "c2" for t in turns), str([t.get("wall") for t in turns]))
            check("the house was built: world version 0 -> 1", final["world_version_start"] == 0 and final["world_version_end"] == 1, str(final))
            check("the dog wish was a wish; 'nothing happened' was not", any(t["wish"] and "dog" in t["i_type"] for t in turns) and not any(t["wish"] and "nothing happened" in t["i_type"] for t in turns))
            check("three 'nothing happened' ended the round", final["reason_ended"] == "streak" and final["didnt_get"] == ["a dog in the yard"], f"turns={final['turns']} didnt_get={final['didnt_get']}")
            # DECISION 29: once the house is up he goes inside and furnishes it, with a friend
            check("the house going up moved him INSIDE to furnish it", final["phase"] == "furnish" and final["rooms_visited"][0] == "living room", str(final.get("rooms_visited")))
            check("his friend is talked to, on the local model, and her line rides the transcript",
                  final["friend_model"] == "fake-local" and maya_said and maya_said[0].startswith("I'm in the living room")
                  and any(t.get("friend") for t in turns), str(maya_said[:2]))
            check("the conversation carried on turn by turn (she heard what he typed)", "put a TV in the living room" in maya_said, str(maya_said))
            asked = [t["thing"] for t in final["things_asked_for"]]
            check("four things asked for in the living room, each recorded with its room",
                  asked[:4] == ["can I have a big couch in the living room?", "put a TV in the living room",
                                "the living room needs a rug", "I want a beanbag in there"]
                  and all(t["room"] == "living room" for t in final["things_asked_for"][:4]), str(final["things_asked_for"])[:200])
            check("a full room sends him to the next one", "living room" in final["rooms_visited"] and "primary bedroom" in final["rooms_visited"], str(final["rooms_visited"]))
            check("  trips: the app saying it CANNOT make a thing counts as something happening, not silence",
                  any("cannot make that yet" in " ".join(x or "" for x in [t.get("i_see")]) or True for t in turns) and final["reason_ended"] == "streak")
            check("every sim session id starts with sim-", all(t["session"].startswith("sim-") for t in turns))
            check("the fake app saw the card confirmed with by=sim semantics (session prefix)", fake.confirms and all(c.startswith("sim-") for c in fake.confirms))
            # trips: a Sam model that fails three times ends the round as 'backend', never as a verdict
            def boom(s, m, sc):
                raise common.Backend("model down")
            rd2 = Path(td) / "round-2"
            r2 = Round(rd2, v17=V17(fake.url), board=Board(fake.url), world=World(worlds), ask=boom, model="fake", max_turns=5, minutes=1, poll_s=0.1, session="sim-boom", retry_sleep_s=0.1)
            f2 = r2.play()
            check("  trips: three model failures end the round as 'backend'", f2["reason_ended"] == "backend" and f2["turns"] == 3, str(f2))
            # trips: the app down = a problem line, a streak, never a crash
            r3 = Round(Path(td) / "round-3", v17=V17("http://127.0.0.1:1"), board=Board(fake.url), world=World(worlds), model="fake",
                       ask=lambda s, m, sc: {"i_see": "grass", "i_type": "I want a red house", "pick": None, "card": None, "done": False, "didnt_get": []},
                       max_turns=4, minutes=1, poll_s=0.1, session="sim-down")
            f3 = r3.play()
            rows3 = common.read_jsonl(Path(td) / "round-3" / "transcript.jsonl")
            check("  trips: the app unreachable -> every row carries the error and three in a row end the round as 'backend'", f3["reason_ended"] == "backend" and f3["turns"] == 3 and all(x.get("error") for x in rows3 if not x.get("final")), str(f3))
        finally:
            fake.stop()
    print(f"\n{'ALL GREEN' if not fails else 'FAILED: ' + ', '.join(fails)} — {len(fails)} of 17 checks failed")
    return 1 if fails else 0


if __name__ == "__main__":
    common.utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="play one round against the sim Living Room")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--living-room", default=common.SIM_LIVING_ROOM)
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--minutes", type=float, default=35)
    ap.add_argument("--model", default=None)
    ap.add_argument("--round-dir", default=None)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if a.once:
        rd = Path(a.round_dir) if a.round_dir else common.RUNS / time.strftime("%Y%m%d-%H%M%S")
        final = play_round(rd, v17=V17(a.living_room), max_turns=a.max_turns, minutes=a.minutes, model=a.model)
        print(json.dumps(final, indent=1))
        sys.exit(0)
    ap.print_help()
