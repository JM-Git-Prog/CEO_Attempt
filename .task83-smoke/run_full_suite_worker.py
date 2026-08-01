from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
status = root / ".task83-smoke" / "full-suite-status.json"
output = root / ".task83-smoke" / "full-suite-output.txt"
status.unlink(missing_ok=True)
completed = subprocess.run(
    [sys.executable, "-m", "pytest", "src/unified_pipeline/tests", "-q"],
    cwd=root,
    capture_output=True,
    text=True,
)
output.write_text(completed.stdout + completed.stderr, encoding="utf-8")
temporary = status.with_suffix(".tmp")
temporary.write_text(
    json.dumps({"returncode": completed.returncode, "command": "python -m pytest src/unified_pipeline/tests -q"}),
    encoding="utf-8",
)
temporary.replace(status)
