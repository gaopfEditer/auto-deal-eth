"""
文生图：提示词 -> Gemini 网页版生成图并落盘。

与 runner（图/URL 分析）对称：
  runner:  资源 + prompt -> 文本分析
  tti:     prompt         -> 生成图片
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from browser_media_runner.runner import DEFAULT_HISTORY_DIR, DEFAULT_PROMPTS_DIR, load_prompt
from gemini_web_automation import generate_image_with_gemini_web

PACKAGE_DIR = Path(__file__).resolve().parent


def text_to_image(
    prompt_input: str,
    *,
    prompt_is_text: bool = False,
    prompts_dir: Optional[Union[str, Path]] = None,
    history_dir: Optional[Union[str, Path]] = None,
    out_dir: Optional[Union[str, Path]] = None,
    domain_tag: str = "",
    save_history: bool = True,
    keep_browser_open: bool = False,
) -> Dict[str, Any]:
    """
    主入口：提示词交给 Gemini 网页版文生图，保存到 out_dir / history。
    """
    pdir = Path(prompts_dir or DEFAULT_PROMPTS_DIR).resolve()
    hroot = Path(history_dir or DEFAULT_HISTORY_DIR).resolve()

    if prompt_is_text:
        prompt_text = (prompt_input or "").strip()
        prompt_name = "<inline>"
    else:
        prompt_name = prompt_input
        prompt_text = load_prompt(prompt_name, pdir)

    if not prompt_text:
        return {"ok": False, "error": "prompt 为空", "images": []}

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    if save_history:
        work = hroot / f"tti_{run_id}"
        work.mkdir(parents=True, exist_ok=True)
    else:
        work = Path(out_dir or (PACKAGE_DIR / "outputs" / run_id)).resolve()
        work.mkdir(parents=True, exist_ok=True)

    save_to = Path(out_dir).resolve() if out_dir else (work / "images")
    save_to.mkdir(parents=True, exist_ok=True)

    web_result = generate_image_with_gemini_web(
        prompt_text,
        out_dir=str(save_to),
        tag=domain_tag or "tti",
        keep_browser_open=keep_browser_open,
    )

    out: Dict[str, Any] = {
        "ok": bool(web_result.get("ok")),
        "domain_tag": domain_tag,
        "prompt_name": prompt_name,
        "run_id": run_id,
        "history_dir": str(work) if save_history else "",
        "out_dir": str(save_to),
        "images": web_result.get("images") or [],
        "web_result": web_result,
    }
    if web_result.get("error"):
        out["error"] = web_result["error"]

    if save_history:
        (work / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        (work / "result.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (work / "web_result.json").write_text(
            json.dumps(web_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="browser_media_runner 文生图：提示词 -> Gemini 网页版出图"
    )
    ap.add_argument(
        "-p",
        "--prompt",
        required=True,
        help="提示词；默认按 prompts/ 下文件名解析",
    )
    ap.add_argument(
        "--prompt-text",
        action="store_true",
        help="将 --prompt 视为正文，而非文件名",
    )
    ap.add_argument("--prompts-dir", default="", help="提示词根目录")
    ap.add_argument("--history-dir", default="", help="history 根目录")
    ap.add_argument(
        "--out",
        default="",
        help="图片输出目录（默认写到 history/tti_*/images）",
    )
    ap.add_argument("--tag", default="", help="业务标签")
    ap.add_argument("--no-history", action="store_true", help="不写 history 子目录")
    ap.add_argument(
        "--keep-browser",
        action="store_true",
        help="结束后保持浏览器打开",
    )
    args = ap.parse_args()

    result = text_to_image(
        args.prompt,
        prompt_is_text=args.prompt_text,
        prompts_dir=args.prompts_dir or None,
        history_dir=args.history_dir or None,
        out_dir=args.out or None,
        domain_tag=args.tag,
        save_history=not args.no_history,
        keep_browser_open=args.keep_browser,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
