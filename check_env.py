#!/usr/bin/env python3
"""查看本机环境与项目配置"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 50)
    print("本机 / 项目配置")
    print("=" * 50)

    print("\n[Python]")
    print(f"  版本: {sys.version.split()[0]}")
    print(f"  路径: {sys.executable}")

    print("\n[代理]")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        v = os.getenv(k) or os.getenv(k.lower()) or "(未设置)"
        print(f"  {k}: {v}")

    print("\n[.env 相关]")
    key = os.getenv("GEMINI_API_KEY", "")
    print(f"  GEMINI_API_KEY: {'已设置 (' + key[:8] + '...)' if key and len(key) > 8 else '未设置'}")
    print(f"  GEMINI_MODEL: {os.getenv('GEMINI_MODEL', '(未设置)')}")
    print(f"  PROXY_PORT: {os.getenv('PROXY_PORT', '(未设置)')}")
    print(f"  PROXY_URL: {os.getenv('PROXY_URL', '(未设置)')}")

    try:
        from config import SCREENSHOT_DIR, GEMINI_REQUEST_TIMEOUT
        print(f"\n[项目]")
        print(f"  SCREENSHOT_DIR: {SCREENSHOT_DIR}")
        print(f"  GEMINI_REQUEST_TIMEOUT: {GEMINI_REQUEST_TIMEOUT}s")
    except Exception as e:
        print(f"\n[项目] 加载 config 失败: {e}")

    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()
