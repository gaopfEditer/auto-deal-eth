#!/usr/bin/env python3
"""
双层日志体系：

1. 角色专有日志 (Agent-Specific): logs/{agent_id}/{agent_id}.log
   - 按天滚动 (TimedRotatingFileHandler)
   - 记录详细执行步骤、API 原始响应
   - backupCount=7，自动清理 7 天前文件

2. 全局审计日志 (Global Audit): logs/audit.log
   - 仅记录任务分发、流转状态、最终结果

3. 关键节点 notify=True → Webhook 上报
4. 日志脱敏：API Key、Token 等敏感信息自动 replace
"""
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


# 需脱敏的键名（日志中若出现则替换为 ***）
_SENSITIVE_KEYS = frozenset({
    "GEMINI_API_KEY", "api_key", "apiKey", "token", "authorization",
    "password", "secret", "Bearer",
})


def _desensitize(text: str) -> str:
    """脱敏：替换敏感信息"""
    if not text or not isinstance(text, str):
        return text
    # API Key 形如 AIzaSy... 的替换
    out = re.sub(r"AIza[A-Za-z0-9_-]{35}", "***API_KEY***", text)
    # Bearer xxx
    out = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer ***", out, flags=re.I)
    return out


def _load_config(root: Path) -> dict:
    cfg_path = root / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class AgentLogger:
    """供各 Agent 使用的双层日志"""

    def __init__(
        self,
        agent_id: str,
        log_path: str | None = None,
        webhook_url: str | None = None,
        backup_count: int = 7,
    ):
        self.agent_id = agent_id
        root = Path(__file__).resolve().parents[1]
        cfg = _load_config(root)

        # 路径：config.json 优先
        logs = log_path or cfg.get("logging", {}).get("LOG_PATH") or "logs"
        self.log_dir = Path(logs).expanduser()
        if not self.log_dir.is_absolute():
            self.log_dir = root / self.log_dir

        self.agent_dir = self.log_dir / agent_id
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.log_dir / "audit.log"

        self._webhook_url = webhook_url or cfg.get("webhook", {}).get("url") or os.environ.get("WEBHOOK_URL")
        self._backup_count = backup_count or cfg.get("logging", {}).get("backup_count", 7)
        self._agent_logger: logging.Logger | None = None
        self._audit_logger: logging.Logger | None = None

    def _get_agent_logger(self) -> logging.Logger:
        if self._agent_logger is not None:
            return self._agent_logger
        log_file = self.agent_dir / f"{self.agent_id}.log"
        logger = logging.getLogger(f"agent.{self.agent_id}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        fh = TimedRotatingFileHandler(
            str(log_file),
            when="midnight",
            interval=1,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        fh.suffix = "%Y-%m-%d"
        fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
        self._agent_logger = logger
        return logger

    def _get_audit_logger(self) -> logging.Logger:
        if self._audit_logger is not None:
            return self._audit_logger
        logger = logging.getLogger("audit")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        fh = logging.FileHandler(str(self.audit_path), encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
        self._audit_logger = logger
        return logger

    def _notify_webhook(self, stage: str, data: dict, level: str = "INFO"):
        if not self._webhook_url:
            return
        payload = {
            "agent": self.agent_id,
            "stage": stage,
            "level": level,
            "data": data,
        }
        try:
            import urllib.request
            req = urllib.request.Request(
                self._webhook_url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json", "User-Agent": "OpenClaw-Logger/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as _:
                pass
        except Exception as e:
            self._get_agent_logger().warning("Webhook 上报失败: %s", _desensitize(str(e)))

    def info(self, msg: str, *, audit: bool = False, notify: bool = False, stage: str = ""):
        """记录到角色专有日志；audit=True 同时写入全局审计；notify=True 触发 Webhook"""
        msg_safe = _desensitize(msg)
        self._get_agent_logger().info(msg_safe)
        print(f"[{self.agent_id}] {msg_safe}", file=sys.stderr)
        if audit:
            self._get_audit_logger().info("[%s] %s", self.agent_id, msg_safe)
        if notify:
            self._notify_webhook(stage or "info", {"message": msg_safe})

    def debug(self, msg: str, *, audit: bool = False):
        msg_safe = _desensitize(msg)
        self._get_agent_logger().debug(msg_safe)
        if audit:
            self._get_audit_logger().debug("[%s] %s", self.agent_id, msg_safe)

    def warning(self, msg: str, *, audit: bool = True, notify: bool = True, stage: str = "warn"):
        msg_safe = _desensitize(msg)
        self._get_agent_logger().warning(msg_safe)
        print(f"[{self.agent_id}] WARN: {msg_safe}", file=sys.stderr)
        if audit:
            self._get_audit_logger().warning("[%s] %s", self.agent_id, msg_safe)
        if notify:
            self._notify_webhook(stage, {"message": msg_safe}, level="WARNING")

    def error(self, msg: str, *, audit: bool = True, notify: bool = True, stage: str = "error"):
        msg_safe = _desensitize(msg)
        self._get_agent_logger().error(msg_safe)
        print(f"[{self.agent_id}] ERROR: {msg_safe}", file=sys.stderr)
        if audit:
            self._get_audit_logger().error("[%s] %s", self.agent_id, msg_safe)
        if notify:
            self._notify_webhook(stage, {"message": msg_safe}, level="ERROR")

    def api_response(self, stage: str, raw: str, *, truncate: int = 500):
        """记录 API 原始响应（自动脱敏、截断）"""
        safe = _desensitize(raw)
        if len(safe) > truncate:
            safe = safe[:truncate] + f"...[truncated {len(raw)-truncate} chars]"
        self._get_agent_logger().debug("[API %s] %s", stage, safe)

    def report_progress(self, stage: str, data: dict):
        """进度上报：写日志 + Webhook"""
        msg = f"stage={stage} data={json.dumps(data, ensure_ascii=False)[:200]}"
        self.info(msg, audit=True, notify=True, stage=stage)
