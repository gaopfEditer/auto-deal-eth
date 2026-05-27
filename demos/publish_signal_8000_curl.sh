#!/usr/bin/env bash
# 与 publish_signal_8000_demo.py 等价的 curl 示例（默认仅润色，不发布广场）
# 用法:
#   bash publish_signal_8000_curl.sh
#   PUBLISH=true bash publish_signal_8000_curl.sh   # 发布到广场

set -euo pipefail

URL="${SIGNAL_PUBLISH_URL:-http://127.0.0.1:8000/api/publish/signal}"
PUBLISH="${PUBLISH:-false}"

SIGNAL='📊 BTCUSD 倒锤子

触发信号

💰 交易对: BTCUSD
📈 类型: 倒锤子
⏰ 周期: 1h
⏰ 时间: 2026-05-18 23:00:00
💵 价格: 76348.01
📈 最高: 76425.95
📉 最低: 75992.0

👤 来源: TradingView'

BODY=$(PUBLISH="$PUBLISH" SIGNAL="$SIGNAL" python3 - <<'PY'
import json, os
signal = os.environ["SIGNAL"]
publish = os.environ.get("PUBLISH", "false").lower() in ("1", "true", "yes")
print(json.dumps({
    "signal": signal,
    "style_ids": ["style_tianya_classic"],
    "strategy_id": "strategy_left_ambush",
    "compose_mode": "manual",
    "publish": publish,
}, ensure_ascii=False))
PY
)

echo "POST $URL (publish=$PUBLISH)"
curl -sS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -d "$BODY" | python3 -m json.tool 2>/dev/null || curl -sS -X POST "$URL" -H 'Content-Type: application/json' -d "$BODY"
