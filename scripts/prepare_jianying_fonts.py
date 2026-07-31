#!/usr/bin/env python3
"""Download and verify all workflow fonts through Jianying's official cache."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_bridge.app import main


if __name__ == "__main__":
    raise SystemExit(main(["--no-gui", "--prepare-fonts", *sys.argv[1:]]))
