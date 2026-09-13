"""The chat brain's own turn, replayed without FastAPI or a model (John, 2026-09-11).

vision_talk.py proves its rules in isolation; this proves the WIRING - that the exact
sequence v17_say_routes.py performs on each sentence produces, end to end, what John
asked for on his cards:

  CARD 1  it follows what he just said, and the builder still never goes short
  CARD 3  nothing is built until the order has been read back and he has said yes
  CARD 5  a change of mind reaches the builder as ONE answer, and is said out loud

The model call is stubbed, because the one thing that must not depend on a model is
whether the right words reach the builder.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from src.web import vision_talk  # noqa: E402

FAILS = []


def ok(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))
    if not cond:
        FAILS.append(name)


def stub_reply(topic=None, question=None):
    if topic:
        return f"A {topic}, nice. What colour should the {topic} be?"
    return f"[model would ask] {question}"


def ask(v, message, changes):
    """Mirrors _vision_ask in v17_say_routes.py, line for line."""
    note = vision_talk.change_text(changes)
    say = (note + " ") if note else ""
    topic = vision_talk.follow_topic(v) if vision_talk.should_follow(v) else None
    if topic:
        reply = stub_reply(topic=topic)
        vision_talk.note_asked(
            v, vision_talk.question_in(reply) or vision_talk.fallback_follow_question(topic),
            topic=topic)
        return say + reply, None
    q = vision_talk.next_question(v)
    if q:
        v["asked"].append(q)
        return say + stub_reply(question=q), q
    v["confirm_pending"] = True
    return say + vision_talk.confirm_text(v), None


def turn(session, message, log):
    """Mirrors the vision branch of /say."""
    v = vision_talk.get(session)
    if v is None:
        v = vision_talk.open_vision(session, message)
        reply, _ = ask(v, message, None)
        log.append(("open", reply))
        return None
    if vision_talk.is_build_command(message) or (
            v.get("confirm_pending") and vision_talk.is_yes(message)):
        built = vision_talk.brief_text(v)
        vision_talk.close(session)
        log.append(("BUILD", built))
        return built
    vision_talk.add(session, message)
    reply, _ = ask(v, message, list(v.get("last_changes") or []))
    log.append(("turn", reply))
    return None


def run(session, script):
    vision_talk.close(session)
    log, built = [], None
    for line in script:
        got = turn(session, line, log)
        if got is not None:
            built = got
    return log, built


print("\nCARD 1 - HE MENTIONS A SWING, SO IT ASKS ABOUT THE SWING")
log, _ = run("f", ["I want a house with a swing in the yard"])
for kind, text in log:
    print(f"    {kind:<5} {text}")
ok("it asks about the swing, not the floors", "swing" in log[0][1].lower(), log[0][1])
ok("and not about floors", "floor" not in log[0][1].lower(), log[0][1])
log2 = []
turn("f", "a red one, by the back door", log2)
print(f"    turn  {log2[0][1]}")
ok("then it gets back to what the builder needs",
   "floor" in log2[0][1].lower() or "wall" in log2[0][1].lower(), log2[0][1])

print("\n   ...and the builder is never left short (the guarantee)")
log, built = run("g", [
    "I want a house with a swing in the yard",
    "a red one",
    "two floors",
    "white siding",
    "shingle roof",
    "no garage",
])
v = vision_talk.get("g")
missing = [k for k, _ in vision_talk._QUESTIONS if not vision_talk._covered(k, v)]
ok("every thing the builder needs was answered", not missing, missing)
ok("his swing was chased first", "swing" in (v.get("topics_asked") or []), v.get("topics_asked"))

print("\nCARD 5 - HE CHANGES HIS MIND HALFWAY THROUGH")
log, built = run("a", [
    "I want a yellow house",
    "two floors",
    "actually make it blue",
    "shingle roof",
    "a porch",
    "yes",
])
for kind, text in log:
    print(f"    {kind:<5} {text}")
ok("the builder is never handed both colours", built and "yellow" not in built.lower(), built)
ok("the builder is handed the colour he ended on", built and "blue" in built.lower(), built)
ok("the swap was said out loud", any("blue instead of yellow" in t for _, t in log),
   [t for _, t in log])

print("\nCARD 3 - NOTHING IS BUILT UNTIL HE SAYS YES")
log, built = run("b", [
    "a two storey house with white siding",
    "metal roof",
    "no porch",
    "a swing in the yard",
    "a red one",
])
for kind, text in log:
    print(f"    {kind:<5} {text}")
ok("nothing was built", built is None, built)
ok("the order was read back", any("So - " in t for _, t in log), [t for _, t in log])
v = vision_talk.get("b")
ok("the read-back IS the order the builder would get",
   vision_talk.brief_text(v).rstrip(".") in log[-1][1], log[-1][1])
log2 = []
built2 = turn("b", "yes", log2)
print(f"    {log2[0][0]:<5} {log2[0][1]}")
ok("a plain yes builds it", built2 and "white siding" in built2, built2)

print("\n   ...a yes that is not a yes")
vision_talk.close("c")
log, _ = run("c", ["a blue house"])
ok("mid-conversation nothing is waiting on a yes",
   not vision_talk.get("c").get("confirm_pending"), "")
turn("c", "yes", log)
ok("so a stray yes is kept, not built", vision_talk.get("c") is not None, "closed by a stray yes")

print("\n   ...he changes his mind AFTER the read-back")
log, _ = run("d", ["a yellow two storey house", "shingle roof", "a porch", "a flag by the path",
                   "a small one"])
ok("the order was read back", any("So - " in t for _, t in log), [t for _, t in log])
log2 = []
turn("d", "actually blue", log2)
print(f"    turn  {log2[0][1]}")
ok("the change is heard after the read-back too", "blue instead of yellow" in log2[0][1], log2[0][1])
readback = log2[0][1].split("So - ", 1)[-1]
ok("and it reads the CORRECTED order back again", "yellow" not in readback.lower(), readback)
built = turn("d", "yep", [])
ok("then a yes builds the corrected order", built and "yellow" not in built.lower(), built)

print()
if FAILS:
    print(f"  CHAT BRAIN WIRING FAILED: {len(FAILS)} check(s) - " + ", ".join(FAILS))
    sys.exit(1)
print("  CHAT BRAIN WIRING OK - it follows what he just said without ever leaving the")
print("  builder short, a change of mind reaches the builder as ONE answer, and the order")
print("  is read back and agreed to before anything is built.")
