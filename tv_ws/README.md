# tv_ws — TradingView WebSocket 推送

本目录集中维护原项目根目录下的 `tv_ws_*` 与 `ws_signal_handler` 脚本。

## 目录结构

| 文件 | 说明 |
|------|------|
| `signal_handler.py` | 周期过滤、格式化文案、POST publish/signal、TradingView 截图 |
| `pic_push_public.py` | 常驻 WSS 监听（asyncio + websockets） |
| `pic_push_public_only_telegram.py` | 仅 Telegram：15m/1h/4h 原文+截图，不润色 |
| `pic_push_public_test.py` | 本地联调：模拟一条 tradingview 消息 |
| `USAGE.md` | 完整使用说明 |

依赖仍在项目根目录：`notifier.py`、`dealMsg/runner.py`、`promat_publish.py`、`browser_automation` 等。

TradingView 截图目录与 `gainers_top20` 相同：`config.SCREENSHOT_DIR`（默认 `/Volumes/RamDisk/app_screenshots`，`.env` 可覆盖）。

## 运行（在项目根目录）

```bash
# 生产：默认润色 + Telegram 图文 + 截图，不发布广场
python -m tv_ws.pic_push_public
python -m tv_ws.pic_push_public --public          # 发布到广场

python -m tv_ws.pic_push_public --skip-screenshot
python -m tv_ws.pic_push_public --dry-run

# 仅 Telegram（15m/1h/4h，不润色、不发广场）
python -m tv_ws.pic_push_public --only-telegram
python -m tv_ws.pic_push_public_only_telegram

# 联调：不连 WebSocket（同样默认不发布，加 --public 才发广场）
python -m tv_ws.pic_push_public_test
python -m tv_ws.pic_push_public_test --public
python -m tv_ws.pic_push_public_test --ticker BTCUSD --period 4h
```

## Python 调用

```python
from tv_ws import process_tradingview_ws_message, is_allowed_ws_period
```

`main.py --ws` 同样使用 `tv_ws.signal_handler.process_tradingview_ws_message`。

## 兼容旧命令

```bash
python tv_ws_pic_push_public.py
python tv_ws_pic_push_public_test.py
```

详见 [USAGE.md](USAGE.md)。
