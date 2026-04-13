"""
资源列表 + 提示词输入 -> Gemini 网页版文件上传分析，运行痕迹写入 history。

不做浏览器截图，不做直链下载，不走 Gemini REST。
核心上传与网页端交互由 ``gemini_web_automation`` 负责。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "analyze_resources",
    "default_history_dir",
    "default_prompts_dir",
]


def analyze_resources(*args, **kwargs):
    from browser_media_runner.runner import analyze_resources as _impl

    return _impl(*args, **kwargs)


def default_history_dir():
    from browser_media_runner.runner import default_history_dir as _impl

    return _impl()


def default_prompts_dir():
    from browser_media_runner.runner import default_prompts_dir as _impl

    return _impl()
