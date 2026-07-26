"""HTML shell for The Living Room web application."""

from src.workflow_provenance import normalize_interface_version


def get_index_html(version: int = 11) -> str:
    normalized = normalize_interface_version(version)
    if normalized != version:
        raise ValueError(f"Unsupported interface version: {version}")
    version = normalized
    refresh_control = '<button class="refresh-output" onclick="refreshOutput()">REFRESH OUTPUT ↻</button>' if version >= 4 else ""
    plan_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'floor\')"' if version >= 4 else ""
    blockout_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'blockout\')"' if version >= 4 else ""
    current_page = lambda selected: 'aria-current="page"' if selected else ""
    current_step = lambda selected: ' aria-current="step"' if selected else ""
    telemetry_live = ' aria-live="polite"' if version == 8 else ""
    version_nav = (
        f'<nav class="version-nav" aria-label="Interface version">'
        f'<a class="{"selected" if version == 3 else ""}" {current_page(version == 3)} href="/?v=3">V3 SIMPLE</a>'
        f'<a class="{"selected" if version == 4 else ""}" {current_page(version == 4)} href="/?v=4">V4</a>'
        f'<a class="{"selected" if version == 5 else ""}" {current_page(version == 5)} href="/?v=5">V5</a>'
        f'<a class="{"selected" if version == 6 else ""}" {current_page(version == 6)} href="/?v=6">V6</a>'
        f'<a class="{"selected" if version == 7 else ""}" {current_page(version == 7)} href="/?v=7">V7</a>'
        f'<a class="{"selected" if version == 8 else ""}" {current_page(version == 8)} href="/?v=8">V8</a>'
        f'<a class="{"selected" if version == 9 else ""}" {current_page(version == 9)} href="/?v=9">V9</a>'
        f'<a class="{"selected" if version == 10 else ""}" {current_page(version == 10)} href="/?v=10">V10</a>'
        f'<a class="{"selected" if version == 11 else ""}" {current_page(version == 11)} href="/?v=11">V11</a></nav>'
    )
    workspace_attr = ' id="workspace"' if version in (7, 8, 9, 10, 11) else ""
    splitter = (
        '<div id="workspaceSplitter" class="workspace-splitter" role="separator" tabindex="0" '
        'aria-label="Resize chat and preview panes" aria-orientation="vertical" '
        'aria-valuemin="25" aria-valuenow="44" aria-valuemax="70" aria-valuetext="44% chat width">'
        '<span aria-hidden="true"></span></div>'
        if version in (7, 8, 9, 10, 11) else ""
    )
    stage_rail = (
        '<nav class="stage-rail" aria-label="Build stages">'
        + ''.join(
            f'<button type="button" class="stage-step{" active" if stage == "brief" else ""}" '
            f'data-stage="{stage}"{current_step(stage == "brief")}>{stage.upper()}</button>'
            for stage in ("brief", "plan", "blockout", "canon", "world", "compare")
        )
        + '</nav>'
        if version >= 8
        else '<nav class="stage-rail" aria-label="Build stages"><span class="stage-step active" data-stage="brief">BRIEF</span><span class="stage-step" data-stage="plan"__PLAN_STAGE_ATTR__>PLAN</span><span class="stage-step" data-stage="blockout"__BLOCKOUT_STAGE_ATTR__>BLOCKOUT</span><span class="stage-step" data-stage="canon">CANON</span><span class="stage-step" data-stage="world">WORLD</span><span class="stage-step" data-stage="compare">COMPARE</span></nav>'
    )
    history_ui = (
        '<div id="historyBanner" class="history-banner" role="status" hidden>'
        '<span>Viewing a read-only historical run</span><button id="returnLiveBtn" type="button">Return to live</button></div>'
        '<div class="history-toolbar" aria-label="Run history">'
        '<label>Run<select id="historyRun"><option value="">Live session</option></select></label>'
        '<label>Revision<select id="historyRevision" disabled><option value="">Latest</option></select></label>'
        '<button id="historyReload" type="button" aria-label="Reload run history">↻</button></div>'
        f'<section id="telemetryPanel" class="telemetry-panel" aria-label="Build telemetry"{telemetry_live}>'
        '<span><b>SUBSTEP</b><em id="telemetrySubstep">Waiting</em></span>'
        '<span><b>ELAPSED</b><em id="telemetryElapsed">—</em></span>'
        '<span><b>HEARTBEAT</b><em id="telemetryHeartbeat">—</em></span>'
        '<span><b>ETA</b><em id="telemetryEta">collecting timing data</em></span></section>'
        if version >= 8 else ""
    )
    intro = (
        '<div class="intro"><span class="eyebrow">TEXT → PLAN → BLOCKOUT → CANON → WORLD</span>'
        '<h1>Build a room you can enter.</h1><p>Describe one interior. Approve its metric layout '
        'and camera first, then render a plan-conditioned canon and compile the world with UPBGE '
        'as primary and the declared Godot fallback when required.</p></div>'
        if version == 11 else
        '<div class="intro"><span class="eyebrow">TEXT → PLAN → BLOCKOUT → CANON → WORLD</span>'
        '<h1>Build a room you can enter.</h1><p>Describe one interior. Approve its metric layout and '
        'camera first, then render a plan-conditioned canon and build the world.</p></div>'
    )
    footer = (
        '<span>UPBGE primary</span><span>Declared Godot fallback</span><span>Compiler · parity · QA evidence</span>'
        if version == 11 else
        '<span>Orbit preview</span><span>Godot 4 export</span><span>Physics metadata</span>'
    )
    return (
        INDEX_HTML.replace("__VERSION__", str(version))
        .replace("__INTRO__", intro)
        .replace("__STAGE_FOOTER__", footer)
        .replace("__REFRESH_CONTROL__", refresh_control)
        .replace("__STAGE_RAIL__", stage_rail)
        .replace("__PLAN_STAGE_ATTR__", plan_attr)
        .replace("__BLOCKOUT_STAGE_ATTR__", blockout_attr)
        .replace("__VERSION_NAV__", version_nav)
        .replace("__WORKSPACE_ATTR__", workspace_attr)
        .replace("__WORKSPACE_SPLITTER__", splitter)
        .replace("__V8_HISTORY_UI__", history_ui)
        .replace(
            "__V8_SCOPE__",
            " ui-v8-scoped ui-v9-camera ui-v10-bounded ui-v11-runtime" if version == 11
            else " ui-v8-scoped ui-v9-camera ui-v10-bounded" if version == 10
            else " ui-v8-scoped ui-v9-camera" if version == 9
            else " ui-v8-scoped" if version == 8
            else "",
        )
    )


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b10">
  <title>The Living Room · World Builder</title>
  <script>
    (() => {
      const url = new URL(window.location.href);
      const requested = url.searchParams.get('v');
      if (requested === null) {
        url.searchParams.set('v', '11');
        window.location.replace(url);
      }
    })();
  </script>
  <link rel="stylesheet" href="/static/styles.css?v=__VERSION__">
</head>
<body class="ui-v__VERSION____V8_SCOPE__">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">LR</span><div><strong>The Living Room</strong><small>Describe any interior. Walk into it.</small></div></div>
    <div class="status-strip">__VERSION_NAV__<span class="chip" id="apiChip">API · checking</span><span class="chip" id="llmChip">Ollama · checking</span><span class="chip" id="imageChip">FLUX.2 · checking</span><span class="chip" id="gpuChip">GPU · checking</span></div>
  </header>
  <main class="workspace"__WORKSPACE_ATTR__>
    <section class="conversation">
      __INTRO__
      <div id="messages" class="messages" aria-live="polite"></div>
      <form id="composer" class="composer"><label class="composer-label" for="input">Describe your room</label><span class="composer-help" id="inputHelp">Include layout, era, materials, lighting, and openings. Enter submits; Shift+Enter adds a line.</span><textarea id="input" rows="3" aria-describedby="inputHelp" placeholder="A sunken 1970s lounge with walnut walls, amber lamps and rain against a wide window…"></textarea><div class="composer-actions"><button id="mvpBtn" type="button" class="mvp-generate-btn" onclick="sendDescriptionMvp()">Generate &amp; Play ⚡</button><button id="sendBtn" type="submit">Generate space plan <span>↗</span></button></div></form>
    </section>
    __WORKSPACE_SPLITTER__
    <aside class="stage">
      <div class="stage-head"><div><span class="eyebrow">LIVE OUTPUT · V__VERSION__</span><h2 id="stageTitle">Waiting for a description</h2></div><div class="stage-tools">__REFRESH_CONTROL__<span class="stage-state" id="stageState" role="status" aria-live="polite" aria-atomic="true">IDLE</span></div></div>
      __V8_HISTORY_UI__
      __STAGE_RAIL__
      <div id="stageBody" class="stage-body"><div class="empty-stage"><div class="wire-room"><i></i><i></i><i></i></div><p>Your plan, canon, and world preview will appear here.</p></div></div>
      <div id="stageFooter" class="stage-footer">__STAGE_FOOTER__</div>
    </aside>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script>window.APP_VERSION=__VERSION__;</script>
  <script src="/static/app.js?v=__VERSION__"></script>
</body>
</html>"""
