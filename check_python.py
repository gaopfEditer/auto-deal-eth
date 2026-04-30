#!/usr/bin/env python3
"""检查当前 Python 是否适合安装本项目依赖（pandas/numpy 等）。
若为 MSYS2 MingW Python，pip 会从源码编译，易报错，请改用 Windows 官方 CPython 建 venv。
"""
import sys
import platform

def main():
    exe = sys.executable
    plat = sys.platform
    # 在 MingW 下 platform.platform() 可能含 "MSYSTEM" 或 exe 路径含 msys64
    is_likely_mingw = "msys64" in exe.replace("\\", "/").lower() or "mingw" in exe.lower()
    if is_likely_mingw:
        print("当前 Python 来自 MSYS2/MingW，不适合直接 pip 安装 pandas/numpy。")
        print("建议：用 Windows 官方 CPython 新建 venv 后再安装依赖。")
        print("  python.org 下载 → 安装 → 用该 Python 执行: python -m venv venv")
        print("  然后: .\\venv\\Scripts\\activate  →  pip install -r requirements.txt")
        return 1
    print("当前 Python 路径:", exe)
    print("平台:", plat, "— 适合用 pip 安装预编译依赖。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
