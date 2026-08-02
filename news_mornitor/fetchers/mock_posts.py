"""演示帖库：个人向内容；mock 不伪造外链（前端页内看正文）。"""
from __future__ import annotations

from news_mornitor.models import Platform

# 仅作文档参考；mock 的 source_url 一律留空，避免点进去对不上
PLATFORM_HOME: dict[Platform, str] = {
    Platform.BINANCE: "https://www.binance.com/zh-CN/square",
    Platform.BITGET: "https://www.bitget.com/zh-CN/insights",
    Platform.OKX: "https://www.okx.com/zh-hans/copy-trading/signal-trader",
    Platform.BYBIT: "https://www.bybit.com/zh-MY/trade/spot/feed",
    Platform.REDDIT: "https://www.reddit.com/r/CryptoCurrency/hot/",
    Platform.TRADINGVIEW: "https://www.tradingview.com/markets/cryptocurrencies/ideas/",
    Platform.CRYPTOPANIC: "https://cryptopanic.com/news/",
    Platform.FARCASTER: "https://warpcast.com/",
    Platform.DEBANK: "https://debank.com/stream",
    Platform.TWITTER: "https://x.com/search?q=crypto",
}


def mock_home_url(_platform: Platform | None = None, *_args, **_kwargs) -> str:
    """Mock 无真实 permalink，返回空串，由前端页内展示正文。"""
    return ""


# (eid, author, title, content, likes, comments, shares)
PERSONAL_POOL: list[tuple] = [
    ("p01", "夜猫子阿凯", "刚把多单砍一半了",
     "昨晚 97k 影线把手吓抖了。原本想到 102，先走一半睡稳。剩下止损挪到成本附近。$BTC 纯个人操作，别跟。",
     1280, 210, 88),
    ("p02", "链上摸鱼周周", "SOL 我又加了一点",
     "上周割在 185 还疼，今天反手小仓现货。亏 10% 就滚。想用轻仓赌热度还能拖两周。$SOL",
     860, 145, 52),
    ("p03", "被套老王", "ETH 网格跑了三个月",
     "区间改了四次，真累，但比瞎追强。最大回撤约 11%。有一起做网格的吗？想对参数。不是老师别跟单。$ETH",
     640, 98, 31),
    ("p04", "小满", "FET 冲高我没跑",
     "设了提醒开会忘看，回来回吐一半。下次写条件单，别信手速。纯发泄。$FET",
     420, 76, 19),
    ("p05", "阿哲日记", "连续亏三天强制停手",
     "两次扛单一次报复开仓。账本锁了，明天只看不点。纪律比方向重要，写给自己。",
     510, 64, 22),
    ("p06", "Leo 实盘", "跟单这周我降杠杆了",
     "回撤到不舒服，5x 降到 2x。胜率先放一边，先活着。有从猛打改保守的吗？",
     920, 156, 41),
    ("p07", "短线阿南", "今天两笔一赢一亏",
     "早上假突破被扫；下午等回踩才进，赚回一点。我适合等不适合追。$BTC",
     540, 88, 27),
    ("p08", "摸鱼人", "SOL meme 我不碰了",
     "杂币亏的钱够吃一个月外卖。只留 SOL 底仓。劝还在追土狗的自己。$SOL",
     710, 102, 33),
    ("p09", "老张笔记", "最近三个月错误清单",
     "新闻一出就开；盈利不够就加杠杆；亏了想翻本。全是人性。下周计划外单截图发群骂我。",
     480, 71, 19),
    ("p10", "质押阿辉", "ETH 质押我暂时不撤",
     "不是多坚定，是懒得搬来搬去。你们撤出的理由是啥？想对比。$ETH",
     880, 134, 46),
    ("p11", "铭文小陈", "ORDI 我认栽了",
     "高位接的套大半年。今天不想画线，就想骂自己。铭文以后只围观。$ORDI",
     390, 67, 18),
    ("p12", "打工人圆圆", "FET 小仓试错",
     "工资抠 5% 试叙事。涨了开心跌了当电影票。没目标位。$FET",
     620, 95, 29),
    ("p13", "夜盘自白", "写给熬夜盯盘的自己",
     "三点半还看费率没必要。工作日 23 点后飞行模式。先立 flag。",
     510, 74, 21),
    ("p14", "Deriv阿强", "费率一翻脸我就平了",
     "想扛过夜，费率掉头直接走。少赚认了，熬不动。$BTC",
     720, 110, 48),
    ("p15", "Flow阿姐", "ETH 改小仓波段",
     "以前动不动 10x，现在 2x 都刺激。真爆过。给还在加杠杆的自己。$ETH",
     510, 76, 29),
    ("p16", "u/bagholder42", "Averaged down with too much leverage",
     "I sized too big into the dip and every wick makes me sick. Cutting to spot only tonight. Learning the hard way.",
     1180, 240, 70),
    ("p17", "u/coffee_charts", "Sticky-note rules after blowing up",
     "1) No trades after 1am. 2) No revenge entries. 3) Screenshot the plan first. I keep breaking #2 — roast me.",
     900, 160, 55),
    ("p18", "u/quiet_dca", "Still DCA on payday",
     "Fixed buy when salary hits. Boring, keeps me sane. Who still DCAs without trying to time FOMC?",
     760, 120, 40),
    ("p19", "ChartWizard", "My BTC invalidation this week",
     "Long from last HL. 4h close below = flat, no debate. Sharing the level I actually use.",
     420, 86, 55),
    ("p20", "VegasFlow", "ETH chopped me twice",
     "Faded both edges, stopped both times. Hands off until clean break. Posting so I don't revenge trade.",
     310, 64, 40),
    ("p21", "LiquidityMap", "Bag check — what I still hold",
     "Spot: BTC core, small ETH, tiny SOL. No alts until weekly bias flips. Accountability post.",
     265, 51, 33),
    ("p22", "@tiredtrader", "Liquidated on a nothingburger",
     "Size was stupid. Stepping away 48h. If you're about to revenge-enter, don't.",
     2100, 340, 410),
    ("p23", "@builder.eth", "Shipping through the chop",
     "I keep building when timeline is doom. Reminding myself why I started. Replies > vanity likes.",
     880, 120, 95),
    ("p24", "网格少女", "把网格区间又收窄了",
     "波动变小还用宽网格在空转。收窄后成交密了，但手续费也咬人。有同款体验吗？$ETH",
     455, 82, 28),
]


def samples_for(
    platform: Platform,
    *,
    n: int = 16,
    salt: str = "",
    offset: int = 0,
) -> list[tuple]:
    """按平台切一段池子（可 offset 错开），id 加平台前缀避免碰撞。"""
    out: list[tuple] = []
    prefix = platform.value.lower()[:4]
    pool = PERSONAL_POOL[offset:] + PERSONAL_POOL[:offset]
    for row in pool[:n]:
        eid, author, title, content, likes, comments, shares = row
        out.append(
            (
                f"{prefix}-{salt}{eid}",
                author,
                title,
                content,
                likes,
                comments,
                shares,
            )
        )
    return out
