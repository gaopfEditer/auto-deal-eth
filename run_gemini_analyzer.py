#!/usr/bin/env python3
"""
单独执行 Gemini 分析逻辑

用法:
  # 分析单张图片（API 模式，默认）
  python run_gemini_analyzer.py path/to/image.png
  python run_gemini_analyzer.py path/to/image.png ETH
  python run_gemini_analyzer.py path/to/image.png tophub

  # 使用浏览器网页版模式
  python run_gemini_analyzer.py path/to/image.png --web

  # 使用 screenshots 目录下的图片（默认找 combined.png 或第一张图）
  python run_gemini_analyzer.py
  python run_gemini_analyzer.py --dir ./screenshots
"""
import os
import sys
import json

# 立即清除代理，否则 Gemini 请求会因失效代理报错
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SCREENSHOT_DIR
from gemini_analyzer import analyze_chart, analyze_all_timeframes, init_gemini, get_analysis_prompt


def find_image_to_analyze(directory: str):
    """在目录中查找可分析的图片，优先 combined.png，否则任意一张 png"""
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return None
    combined = os.path.join(directory, "combined.png")
    if os.path.isfile(combined):
        return combined
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".png"):
            return os.path.join(directory, name)
    return None


def find_timeframe_images(directory: str):
    """在目录中查找多周期截图 chart_15m.png, chart_30m.png 等"""
    from config import TIME_PERIODS
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return {}
    paths = {}
    for tf in TIME_PERIODS:
        path = os.path.join(directory, f"chart_{tf}.png")
        if os.path.isfile(path):
            paths[tf] = path
    return paths


def main():
    use_web = "--web" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--web"]

    # 解析可选目录
    img_dir = SCREENSHOT_DIR
    if "--dir" in sys.argv:
        i = sys.argv.index("--dir")
        if i + 1 < len(sys.argv):
            img_dir = sys.argv[i + 1]
        args = [a for a in args if a != "--dir" and a != img_dir]

    image_path = None
    symbol = "ETH"

    if len(args) >= 1 and os.path.isfile(args[0]):
        image_path = os.path.abspath(args[0])
        if len(args) >= 2:
            symbol = args[1].strip()
    elif len(args) >= 1 and os.path.isdir(args[0]):
        img_dir = args[0]
        image_path = find_image_to_analyze(img_dir)
        if len(args) >= 2:
            symbol = args[1].strip()
    else:
        image_path = find_image_to_analyze(img_dir)
        if not image_path:
            # 尝试多周期分析
            timeframe_paths = find_timeframe_images(img_dir)
            if timeframe_paths:
                print(f"[INFO] 找到多周期截图: {list(timeframe_paths.keys())}，使用多周期分析")
                model = init_gemini()
                if model is None:
                    print("[ERROR] 请配置 GEMINI_API_KEY 后重试")
                    sys.exit(1)
                result = analyze_all_timeframes(timeframe_paths)
                for tf, data in result.items():
                    print(f"\n--- {tf} ---")
                    if data.get("status") == "success" and data.get("analysis"):
                        try:
                            print(json.dumps(json.loads(data["analysis"]), indent=2, ensure_ascii=False))
                        except Exception:
                            print(data["analysis"])
                    else:
                        print(data.get("error", data))
                return
        if not image_path:
            print("用法: python run_gemini_analyzer.py [图片路径] [symbol] [--web] [--dir 目录]")
            print("示例: python run_gemini_analyzer.py ./screenshots/combined.png ETH")
            print("      python run_gemini_analyzer.py  # 使用 " + SCREENSHOT_DIR + " 下的图片")
            sys.exit(1)

    print(f"[INFO] 分析图片: {image_path}")
    print(f"[INFO] 符号/类型: {symbol}")
    print(f"[INFO] 模式: {'浏览器网页版' if use_web else 'API'}")

    result = analyze_chart(image_path, symbol, use_api=not use_web)

    if not result:
        print("[WARNING] 无返回结果")
        sys.exit(1)

    if result.get("status") == "success":
        print("\n[OK] 分析完成")
        analysis = result.get("analysis") or result.get("analysis_text") or ""
        if analysis:
            try:
                parsed = json.loads(analysis)
                print(json.dumps(parsed, indent=2, ensure_ascii=False))
            except Exception:
                print(analysis)
    else:
        err = result.get("error", result)
        err_str = str(err)
        print(f"[ERROR] {err}")
        if err and ("Remote end closed" in err_str or "Connection aborted" in err_str):
            print("\n  可能原因：代理关闭了连接或网络不稳定。")
            print("  建议：1) 检查代理软件是否开启并允许 HTTPS  2) 取消代理重试: unset HTTP_PROXY HTTPS_PROXY; 或 .env 中注释 PROXY_PORT")
        elif err and ("429" in err_str or "quota" in err_str.lower() or "Quota exceeded" in err_str):
            print("\n  原因：Gemini API 免费额度已用尽或触发限流。")
            print("  建议：1) 约 1 分钟后再试  2) 到 https://ai.google.dev 查看用量与计费  3) 换新 API Key 或开通付费")
        sys.exit(1)


if __name__ == "__main__":
    main()
