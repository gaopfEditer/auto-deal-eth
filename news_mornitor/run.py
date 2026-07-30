#!/usr/bin/env python3
"""在 news_mornitor 目录内: python run.py"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from news_mornitor.__main__ import main

if __name__ == "__main__":
    main()
