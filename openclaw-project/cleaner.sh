#!/bin/bash
# 全局清理脚本：删除过期日志、临时文件等
# 建议 cron 每周执行: 0 3 * * 0 /path/to/cleaner.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 1. 日志：TimedRotatingFileHandler 已按 backupCount=7 自动清理，此处仅作兜底
# 删除 logs/ 下超过 7 天的 .log.* 滚动文件（若存在）
find logs -name "*.log.*" -mtime +7 -delete 2>/dev/null || true

# 2. temp 临时目录
rm -rf temp/* 2>/dev/null || true

# 3. 临时视频分片 .ts
find . -name "*.ts" -path "*/temp/*" -mtime +1 -delete 2>/dev/null || true

echo "[OK] cleaner.sh 执行完成"
