# demos — 8000 publish/signal 联调

## Python（推荐，无第三方依赖）

```bash
# 默认 publish=false，仅润色
python demos/publish_signal_8000_demo.py

# 发布到广场
python demos/publish_signal_8000_demo.py --public

# 自定义地址 / 正文
python demos/publish_signal_8000_demo.py \
  --url http://127.0.0.1:8000/api/publish/signal \
  --signal-file ./my_signal.txt

# 只看将要 POST 的 JSON
python demos/publish_signal_8000_demo.py --dry-run
```

拷贝 `publish_signal_8000_demo.py` 到其它项目即可，仅需 Python 3.9+。

## curl

```bash
bash demos/publish_signal_8000_curl.sh
PUBLISH=true bash demos/publish_signal_8000_curl.sh
```

## 请求体字段

| 字段 | 说明 |
|------|------|
| `signal` | TradingView 标准纯文本（见 demo 内 `SAMPLE_SIGNAL`） |
| `style_ids` | 如 `["style_tianya_classic"]` |
| `strategy_id` | 如 `strategy_left_ambush` |
| `compose_mode` | 默认 `manual` |
| `publish` | `false` 仅润色；`true` 发布到广场 |
