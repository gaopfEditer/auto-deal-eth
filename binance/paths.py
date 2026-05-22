"""binance 包路径常量（项目根目录、默认数据文件）。"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BINANCE_DIR = Path(__file__).resolve().parent

DEFAULT_POSTS_STATE_FILE = REPO_ROOT / "binance_posts_state.json"
DEFAULT_MARKET_LISTS_FILE = REPO_ROOT / "binance_market_lists.json"
MARKET_LISTS_PROMPT_FILE = REPO_ROOT / "prompts" / "binance_market_lists_selenium.txt"
