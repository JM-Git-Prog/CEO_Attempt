"""Conftest for unified pipeline tests.

Workaround: Python 3.13 Windows + pytest-asyncio hangs during event-loop
teardown after orchestrator async tests that use file-based ownership locks.
The orchestrator tests pass individually and in pairs — the hang occurs only
during session-level loop cleanup when multiple tests have run.

Fix: exclude test_orchestrator.py and test_orchestration_recovery.py from the
default `pytest src/unified_pipeline/tests` run via collection hook. Run them
separately:
    python -m pytest src/unified_pipeline/tests/test_orchestrator.py -v
    python -m pytest src/unified_pipeline/tests/test_orchestration_recovery.py -v
"""
import sys
from pathlib import Path

_EXCLUDED_ON_WINDOWS = {"test_orchestrator.py", "test_orchestration_recovery.py"}

# Skip orchestrator async tests from bulk collection on Windows to prevent
# session-level event loop teardown hang with pytest-asyncio.
def pytest_ignore_collect(collection_path: Path, config):
    if sys.platform == "win32" and collection_path.name in _EXCLUDED_ON_WINDOWS:
        # Allow if explicitly targeted via command line
        args = config.invocation_params.args
        stem = collection_path.stem
        if any(stem in str(arg) for arg in args):
            return False
        return True
    return False
