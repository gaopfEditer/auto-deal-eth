"""
AkShare 宏观经济日历：抓取高/中重要度数据，并映射为金十星级。

当前使用：macro_info_ws（华尔街见闻宏观日历，https://wallstreetcn.com/calendar）
华尔街见闻使用 1～3 星（或颜色条）标记重要度，与金十对应关系：
  - 3 星（红）= 金十 5 星（高重要度）
  - 2 星（黄）= 金十 3-4 星（中重要度）
  - 1 星     = 低重要度
结果中会添加「星级」列，格式如：3星(5星·高)、2星(3-4星·中)、1星(低)。
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Union

try:
    import akshare as ak
except ImportError:
    ak = None

# 华尔街见闻 1～3 星 → 金十对应描述（用于「星级」列）
WSCN_STAR_TO_JIN10 = {
    3: "3星(5星·高)",
    2: "2星(3-4星·中)",
    1: "1星(低)",
}


def _fetch_calendar_df(days_ahead: int = 7) -> Optional[pd.DataFrame]:
    """使用 macro_info_ws 获取宏观日历，合并多日数据。"""
    if ak is None:
        raise ImportError("请安装 akshare: pip install akshare")
    if not hasattr(ak, "macro_info_ws"):
        raise AttributeError(
            "当前 akshare 版本未找到经济日历接口 macro_info_ws。可尝试: pip install akshare --upgrade"
        )
    base = datetime.now().date()
    frames: List[pd.DataFrame] = []
    for i in range(days_ahead):
        d = base + timedelta(days=i)
        date_str = d.strftime("%Y%m%d")
        try:
            df = ak.macro_info_ws(date_str)
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def _normalize_wscn_star(v) -> Optional[int]:
    """将华尔街见闻重要度转为 1/2/3 星，无法解析则返回 None。"""
    if pd.isna(v):
        return None
    s = str(v).strip()
    try:
        n = int(float(s))
        if 1 <= n <= 3:
            return n
        return None
    except (ValueError, TypeError):
        return None


def _add_star_column(df: pd.DataFrame, imp_col: str) -> pd.DataFrame:
    """在 df 上添加「星级」列：华尔街 1～3 星 + 金十对应描述。"""
    stars = df[imp_col].map(_normalize_wscn_star)
    df = df.copy()
    df["星级"] = stars.map(lambda x: WSCN_STAR_TO_JIN10.get(x, "—") if x is not None else "—")
    return df


def get_high_impact_calendar(
    from_date: Optional[datetime] = None,
    importance_value: Union[str, int, None] = None,
    days_ahead: int = 7,
) -> Optional[pd.DataFrame]:
    """
    获取宏观经济日历（今日及以后），并添加「星级」列（华尔街 1～3 星 + 金十对应）。

    华尔街见闻 1～3 星与金十对应：
      - 3 星 = 金十 5 星（高）；2 星 = 金十 3-4 星（中）；1 星 = 低。

    Args:
        from_date: 筛选该日期及以后的事件；默认今日。
        importance_value: 重要度筛选。None = 仅高（3 星）；"高" 或 3 = 3 星；"中" 或 2 = 2 星；
            "中高" 或 "高与中" = 2 星 + 3 星。
        days_ahead: 拉取未来几天数据（默认 7 天）。

    Returns:
        带「星级」列的 DataFrame；列含：时间、地区、事件、重要度、星级、预测、前值等。
    """
    try:
        calendar_df = _fetch_calendar_df(days_ahead=days_ahead)
    except Exception as e:
        print(f"数据抓取失败: {e}")
        return None

    if calendar_df is None or calendar_df.empty:
        return None

    cols = list(calendar_df.columns)
    if len(cols) < 4:
        return calendar_df

    imp_col = None
    for name in ("重要度", "importance"):
        if name in cols:
            imp_col = name
            break
    if imp_col is None and len(cols) > 3:
        imp_col = cols[3]
    if imp_col is None:
        return calendar_df

    # 统一为华尔街 1～3 星数值，并添加「星级」列
    star_ser = calendar_df[imp_col].map(_normalize_wscn_star)
    calendar_df = _add_star_column(calendar_df, imp_col)

    # 按 importance_value 筛选（华尔街 3=高, 2=中, 1=低）
    if importance_value is None:
        importance_value = "高"  # 默认只取高影响（3 星）
    if importance_value in ("高", 3, "3"):
        mask = star_ser == 3
    elif importance_value in ("中", 2, "2"):
        mask = star_ser == 2
    elif importance_value in ("中高", "高与中", "中及以上"):
        mask = (star_ser == 2) | (star_ser == 3)
    elif importance_value in ("低", 1, "1"):
        mask = star_ser == 1
    else:
        # 兼容旧用法：金十「高」或 4/5 视为 3 星
        raw = calendar_df[imp_col].astype(str).str.strip()
        mask = raw.isin(("高", "4", "5", "3")) | (star_ser == 3)
    high_impact_df = calendar_df.loc[mask.fillna(False)].copy()

    if high_impact_df.empty:
        high_impact_df = calendar_df.copy()

    # 筛选日期：今日及以后
    date_col = None
    for name in ("时间", "date", "日期", "datetime"):
        if name in high_impact_df.columns:
            date_col = name
            break
    if date_col is None and len(high_impact_df.columns):
        date_col = high_impact_df.columns[0]
    if date_col:
        high_impact_df = high_impact_df.copy()
        high_impact_df["_date"] = pd.to_datetime(high_impact_df[date_col], errors="coerce").dt.date
        today = (from_date or datetime.now()).date()
        high_impact_df = high_impact_df[high_impact_df["_date"].notna() & (high_impact_df["_date"] >= today)]
        high_impact_df = high_impact_df.drop(columns=["_date"], errors="ignore")
    return high_impact_df


def get_high_impact_calendar_columns() -> list:
    """返回推荐展示列（含「星级」：华尔街 1～3 星 + 金十对应）。"""
    return ["时间", "地区", "事件", "重要度", "星级", "预测", "前值"]
