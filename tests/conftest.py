"""Shared pytest configuration for the cloude workflow test suite.

Puts `bin/` on `sys.path` so the tests can import the stdlib-only
workflow modules (`cloude_workflow`, `cloude_render`) the same way the
hooks do.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
