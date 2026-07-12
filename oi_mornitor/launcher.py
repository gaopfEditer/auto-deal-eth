"""一键启动：自动构建前端 + 拉起后端 / 开发双进程。"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from oi_mornitor.config import WEB_HOST, WEB_PORT

logger = logging.getLogger("OI_Launcher")

_PKG_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = _PKG_ROOT / "frontend"
DIST_INDEX = _PKG_ROOT / "static" / "dist" / "index.html"
DEV_PORT = 5173


def _pids_on_port(port: int) -> list[int]:
    """返回监听指定 TCP 端口的 PID 列表（Unix）。"""
    if sys.platform == "win32":
        return []
    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    pids: list[int] = []
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def kill_processes_on_ports(*ports: int) -> None:
    """启动前释放占用端口的旧进程，避免 address already in use。"""
    my_pid = os.getpid()
    for port in ports:
        targets = [p for p in _pids_on_port(port) if p != my_pid]
        if not targets:
            continue
        for pid in targets:
            logger.info("释放端口 %s：终止旧进程 PID %s", port, pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(0.6)
        for pid in targets:
            if pid == my_pid:
                continue
            if pid in _pids_on_port(port):
                logger.warning("端口 %s PID %s 未退出，强制 kill", port, pid)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _npm_available() -> bool:
    return shutil.which("npm") is not None


def ensure_frontend_built(*, force: bool = False) -> None:
    """若 dist 不存在则自动 npm install && npm run build。"""
    if DIST_INDEX.exists() and not force:
        logger.info("前端构建产物已存在: %s", DIST_INDEX)
        return
    if not _npm_available():
        raise RuntimeError(
            "未检测到 npm，无法构建前端。请安装 Node.js 后重试，"
            "或手动执行: cd oi_mornitor/frontend && npm install && npm run build"
        )
    if not (FRONTEND_DIR / "package.json").exists():
        raise FileNotFoundError(f"缺少前端工程: {FRONTEND_DIR}")

    logger.info("正在构建 React 前端 (npm install && npm run build) …")
    subprocess.run(["npm", "install"], cwd=FRONTEND_DIR, check=True)
    subprocess.run(["npm", "run", "build"], cwd=FRONTEND_DIR, check=True)
    if not DIST_INDEX.exists():
        raise RuntimeError(f"前端构建失败，未生成 {DIST_INDEX}")
    logger.info("前端构建完成")


def run_production_web() -> None:
    """生产模式：aiohttp 同时提供 API + 静态前端。"""
    from oi_mornitor.server import main as web_main

    kill_processes_on_ports(WEB_PORT)
    url = f"http://{WEB_HOST}:{WEB_PORT}"
    print(f"🛰️  OI 雷达已启动（前端 + 后端）→ {url}")
    web_main()


def run_dev_stack() -> None:
    """开发模式：后端 API (8765) + Vite 热更新 (5173) 双进程。"""
    if not _npm_available():
        raise RuntimeError("开发模式需要 npm，请安装 Node.js")

    kill_processes_on_ports(WEB_PORT, DEV_PORT)

    procs: list[subprocess.Popen[bytes]] = []

    def _shutdown(*_args: object) -> None:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        deadline = time.time() + 5
        for p in procs:
            if p.poll() is None and time.time() < deadline:
                try:
                    p.wait(timeout=max(0, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    p.kill()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    backend_cmd = [
        sys.executable,
        str(_PKG_ROOT / "run.py"),
        "web",
        "--skip-build",
        "--backend-only",
    ]
    vite_cmd = ["npm", "run", "dev", "--", "--host", WEB_HOST, "--port", str(DEV_PORT)]

    logger.info("启动后端 API …")
    procs.append(subprocess.Popen(backend_cmd))
    time.sleep(1.5)
    logger.info("启动 Vite 开发服务器 …")
    procs.append(subprocess.Popen(vite_cmd, cwd=FRONTEND_DIR))

    api_url = f"http://{WEB_HOST}:{WEB_PORT}"
    ui_url = f"http://{WEB_HOST}:{DEV_PORT}"
    print(f"🛰️  OI 雷达开发模式")
    print(f"   前端 (HMR): {ui_url}")
    print(f"   后端 API:   {api_url}")
    print("   Ctrl+C 退出")

    try:
        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    raise RuntimeError(f"子进程异常退出 code={code}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
