# tv_ws — TradingView WebSocket 推送

本目录集中维护原项目根目录下的 `tv_ws_*` 与 `ws_signal_handler` 脚本。

## 目录结构

| 文件 | 说明 |
|------|------|
| `signal_handler.py` | 周期过滤、格式化文案、POST publish/signal、TradingView 截图 |
| `pic_push_public.py` | 常驻 WSS 监听（asyncio + websockets） |
| `pic_push_public_test.py` | 本地联调：模拟一条 tradingview 消息 |
| `USAGE.md` | 完整使用说明 |

依赖仍在项目根目录：`notifier.py`、`dealMsg/runner.py`、`promat_publish.py`、`browser_automation` 等。

## 运行（在项目根目录）

```bash
# 生产：连 WSS，默认 POST + 截图
python -m tv_ws.pic_push_public

python -m tv_ws.pic_push_public --skip-screenshot
python -m tv_ws.pic_push_public --dry-run

# 联调：不连 WebSocket
python -m tv_ws.pic_push_public_test
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
