"""HTML shell for The Living Room web application."""


def get_index_html(version: int = 4) -> str:
    version = 3 if version <= 3 else 4
    refresh_control = '<button class="refresh-output" onclick="refreshOutput()">REFRESH OUTPUT ↻</button>' if version >= 4 else ""
    plan_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'floor\')"' if version >= 4 else ""
    blockout_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'blockout\')"' if version >= 4 else ""
    version_nav = (
        f'<nav class="version-nav" aria-label="Interface version">'
        f'<a class="{"selected" if version == 3 else ""}" href="/?v=3">V3 SIMPLE</a>'
        f'<a class="{"selected" if version == 4 else ""}" href="/?v=4">V4</a></nav>'
    )
    return (
        INDEX_HTML.replace("__VERSION__", str(version))
        .replace("__REFRESH_CONTROL__", refresh_control)
        .replace("__PLAN_STAGE_ATTR__", plan_attr)
        .replace("__BLOCKOUT_STAGE_ATTR__", blockout_attr)
        .replace("__VERSION_NAV__", version_nav)
    )


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b10">
  <title>The Living Room · World Builder</title>
  <link rel="stylesheet" href="/static/styles.css?v=__VERSION__">
</head>
<body class="ui-v__VERSION__">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">LR</span><div><strong>The Living Room</strong><small>Describe any interior. Walk into it.</small></div></div>
    <div class="status-strip">__VERSION_NAV__<span class="chip" id="apiChip">API · checking</span><span class="chip" id="llmChip">Ollama · checking</span><span class="chip" id="imageChip">FLUX.2 · checking</span><span class="chip" id="gpuChip">GPU · checking</span></div>
  </header>
  <main class="workspace">
    <section class="conversation">
      <div class="intro"><span class="eyebrow">TEXT → PLAN → BLOCKOUT → CANON → WORLD</span><h1>Build a room you can enter.</h1><p>Describe one interior. Approve its metric layout and camera first, then render a plan-conditioned canon and build the world.</p></div>
      <div id="messages" class="messages" aria-live="polite"></div>
      <form id="composer" class="composer"><textarea id="input" rows="3" placeholder="A sunken 1970s lounge with walnut walls, amber lamps and rain against a wide window…"></textarea><button id="sendBtn" type="submit">Generate space plan <span>↗</span></button></form>
    </section>
    <aside class="stage">
      <div class="stage-head"><div><span class="eyebrow">LIVE OUTPUT · V__VERSION__</span><h2 id="stageTitle">Waiting for a description</h2></div><div class="stage-tools">__REFRESH_CONTROL__<span class="stage-state" id="stageState">IDLE</span></div></div>
      <nav class="stage-rail" aria-label="Build stages"><span class="stage-step active" data-stage="brief">BRIEF</span><span class="stage-step" data-stage="plan"__PLAN_STAGE_ATTR__>PLAN</span><span class="stage-step" data-stage="blockout"__BLOCKOUT_STAGE_ATTR__>BLOCKOUT</span><span class="stage-step" data-stage="canon">CANON</span><span class="stage-step" data-stage="world">WORLD</span><span class="stage-step" data-stage="compare">COMPARE</span></nav>
      <div id="stageBody" class="stage-body"><div class="empty-stage"><div class="wire-room"><i></i><i></i><i></i></div><p>Your plan, canon, and world preview will appear here.</p></div></div>
      <div id="stageFooter" class="stage-footer"><span>Orbit preview</span><span>Godot 4 export</span><span>Physics metadata</span></div>
    </aside>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script>window.APP_VERSION=__VERSION__;</script>
  <script src="/static/app.js?v=__VERSION__"></script>
</body>
</html>"""
