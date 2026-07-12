#!/usr/bin/env python3
"""在 oi_mornitor 目录内直接运行: python run.py [--dev]"""
from __future__ import annotations

import sys
from pathlib import Path

# 未 pip install -e . 时，把仓库根目录加入 sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from oi_mornitor.__main__ import main

if __name__ == "__main__":
    main()
