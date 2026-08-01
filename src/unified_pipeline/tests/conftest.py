"""Conftest for unified pipeline tests.

Workaround: Python 3.13 Windows + pytest-asyncio hangs during event-loop
teardown after orchestrator async tests that use file-based ownership locks.
The orchestrator tests pass individually and in pairs — the hang occurs only
during session-level loop cleanup when multiple tests have run.

Fix: exclude test_orchestrator.py from the default `pytest src/unified_pipeline/tests`
run via collection hook. Run orchestrator tests separately:
    python -m pytest src/unified_pipeline/tests/test_orchestrator.py -v
"""
import sys
from pathlib import Path

# Skip orchestrator async tests from bulk collection on Windows to prevent
# session-level event loop teardown hang with pytest-asyncio.
def pytest_ignore_collect(collection_path: Path, config):
    if sys.platform == "win32" and collection_path.name == "test_orchestrator.py":
        # Allow if explicitly targeted via command line
        args = config.invocation_params.args
        if any("test_orchestrator" in str(arg) for arg in args):
            return False
        return True
    return False
