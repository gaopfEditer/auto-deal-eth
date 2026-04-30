#!/usr/bin/env python3
"""
AgentMonitor - 兼容层，委托给 AgentLogger

推荐直接使用 shared.logger.AgentLogger。
"""
from shared.logger import AgentLogger


class AgentMonitor:
    """兼容旧接口，内部使用 AgentLogger"""

    def __init__(self, agent_id: str, log_dir: str | None = None, webhook_url: str | None = None):
        self._logger = AgentLogger(agent_id, log_path=log_dir, webhook_url=webhook_url)
        self.agent_id = agent_id

    def log(self, msg: str, level: str = "INFO"):
        if level.upper() == "WARN":
            self._logger.warning(msg, audit=False, notify=False)
        elif level.upper() == "ERROR":
            self._logger.error(msg, audit=False, notify=False)
        else:
            self._logger.info(msg, audit=False, notify=False)

    def report_progress(self, stage: str, data: dict):
        self._logger.report_progress(stage, data)
