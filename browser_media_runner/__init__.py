"""
资源列表 + 提示词 -> Gemini 网页版分析；或提示词 -> 网页版文生图。
运行痕迹写入 history。核心交互由 ``gemini_web_automation`` 负责。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "analyze_resources",
    "text_to_image",
    "default_history_dir",
    "default_prompts_dir",
]


def analyze_resources(*args, **kwargs):
    from browser_media_runner.runner import analyze_resources as _impl

    return _impl(*args, **kwargs)


def text_to_image(*args, **kwargs):
    from browser_media_runner.tti import text_to_image as _impl

    return _impl(*args, **kwargs)


def default_history_dir():
    from browser_media_runner.runner import default_history_dir as _impl

    return _impl()


def default_prompts_dir():
    from browser_media_runner.runner import default_prompts_dir as _impl

    return _impl()
