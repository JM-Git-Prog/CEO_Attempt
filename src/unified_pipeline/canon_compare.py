"""Three-view identity and Scene Canon fidelity comparison.

The comparator consumes measured observations from the Plan-derived Blockout,
the approved Scene Canon, and the first-person World render.  It never treats
presence or ordering as sufficient evidence: GREEN additionally requires
metric shell/opening/object truth, zero forbidden overlap, and appearance
fidelity.  Verdict evidence is deterministically bound to the Plan revision,
Plan/Camera/Canon/WorldContract hashes, and all three view artifact hashes.

**Validates: Requirements 22.6**
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class FidelityVerdict(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class RegionKind(str, Enum):
    SHELL = "shell"
    OPENING = "opening"
    OBJECT = "object"


class FinalQABlockedError(ValueError):
    """Raised when configured release policy rejects comparison evidence."""


class EvidenceWriteError(ValueError):
    """Raised rather than replacing different immutable comparison evidence."""
