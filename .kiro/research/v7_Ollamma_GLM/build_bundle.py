from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("application_bundle.md")
FILES = [
    ROOT / "README.md", ROOT / "pyproject.toml", ROOT / "requirements.txt",
    ROOT / "run.py", ROOT / "build_demo.py",
    ROOT / ".kiro/release-checklist.md", ROOT / ".kiro/steering/ui-versioning.md",
]
FILES += sorted((ROOT / "src").rglob("*.py"))
FILES += sorted((ROOT / "src/web/static").glob("*.*"))
FILES = [path for path in FILES if path.is_file() and "__pycache__" not in path.parts]
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
parts = [
    "# The Living Room — GLM 5.2 Application Research Bundle",
    "",
    f"- Generated: {datetime.now(timezone.utc).isoformat()}",
    f"- Branch: `{branch}`", f"- Commit: `{commit}`",
    "- Scope: tracked application source, entry points, dependency manifests, README, release checklist, and UI-versioning policy.",
    "- Excluded: `.git`, `.kirograph`, MCP settings, environment files, generated output/sessions, model files, binaries, caches, and user data.",
    "",
    "## File manifest", "",
]
for path in FILES:
    raw = path.read_bytes()
    rel = path.relative_to(ROOT).as_posix()
    parts.append(f"- `{rel}` — {len(raw)} bytes — SHA-256 `{hashlib.sha256(raw).hexdigest()}`")
parts += ["", "## Full application text", ""]
for path in FILES:
    rel = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    language = {".py":"python", ".js":"javascript", ".css":"css", ".toml":"toml"}.get(path.suffix, "text")
    parts += [f"### `{rel}`", "", f"```{language}", text, "```", ""]
OUT.write_text("\n".join(parts), encoding="utf-8")
print(f"Wrote {OUT.relative_to(ROOT)} with {len(FILES)} files and {OUT.stat().st_size} bytes")
