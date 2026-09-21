#!/usr/bin/env python3
"""Run the bundled radar CLI from an installed skill, without changing cwd."""
from pathlib import Path
import sys


# Place the skill's package ahead of this script (also named radar.py) and any
# unrelated radar package in the caller's workspace.
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

if __name__ == "__main__":
    from radar.__main__ import main

    sys.exit(main())
