# promat — TradingView 信号润色（publish/signal）

供 `http://127.0.0.1:8000/api/publish/signal` 使用的提示词模板。  
`compose_mode=manual` + `style_tianya_classic` + `strategy_left_ambush` 时，将三份文件拼进模型 system/user prompt。

## 文件

| 文件 | 对应 ID |
|------|---------|
| `style_tianya_classic.txt` | `style_ids: ["style_tianya_classic"]` |
| `strategy_left_ambush.txt` | `strategy_id: "strategy_left_ambush"` |
| `tv_signal_compose.txt` | 总装模板（含 `{{STYLE_*}}` / `{{SIGNAL_INPUT}}` 占位符） |

## 拼装示例（伪代码）

```python
style = Path("prompts/promat/style_tianya_classic.txt").read_text()
strategy = Path("prompts/promat/strategy_left_ambush.txt").read_text()
tpl = Path("prompts/promat/tv_signal_compose.txt").read_text()
prompt = tpl.replace("{{STYLE_TIANYA_CLASSIC}}", style).replace(
    "{{STRATEGY_LEFT_AMBUSH}}", strategy
).replace("{{SIGNAL_INPUT}}", signal_plain_text)
# → 送 Ollama / gemma-uncensored
```

## content 目标版式示例

```
【小故事】
菜场里杀鱼的老张从不跟第一个冲进来的顾客抢价。他说：「鱼刚上岸最贵，等一刻，肉才实在。」炒币也一样——冲高那一下是给别人看的，真便宜往往在回调里。

【盘面摘要】
PAXGUSD，1 小时出现倒锤子。
多头在 4529 一带有承接，但 4541 上方压力仍在。
不宜在现价硬追。

【关键价位】
交易对：PAXGUSD
周期：1h
形态：倒锤子
时间：2026-05-18 23:00:00
现价：4538.23
最高：4541.93
最低：4529.25

【操作思路】
· 左侧埋伏：等健康回调，沿下跌轨迹分批接，不追 4541 冲高。
· 4529 附近是多头守过的底，可当作心理支撑区。
· 踏空一小段冲高没关系，性价比优先。

【风险提示】
仅供参考，不构成投资建议；请自控仓位并设好止损。
```

更新本目录后，需重启或热加载 8000 端口上的 publish 服务使提示词生效。
