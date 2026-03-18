"""
测试AKShare接口可用性
"""
import akshare as ak
import pandas as pd
import os
import sys

# 禁用代理
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

print("=" * 60)
print("测试AKShare接口可用性")
print("=" * 60)

# 测试1: 测试基础接口
print("\n【测试1】测试基础接口...")
try:
    # 测试获取指数列表
    print("尝试获取指数列表...")
    index_list = ak.index_zh_a_hist(symbol="000300", period="daily", start_date="20240101", end_date="20240213")
    print(f"[OK] 成功获取数据，共 {len(index_list)} 条记录")
    print(f"列名: {list(index_list.columns)}")
    print(f"前5行数据:")
    print(index_list.head())
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试2: 测试其他接口
print("\n【测试2】测试其他接口...")
try:
    print("尝试使用 stock_zh_index_daily...")
    data = ak.stock_zh_index_daily(symbol="sh000300")
    print(f"[OK] 成功获取数据，共 {len(data)} 条记录")
    print(f"列名: {list(data.columns)}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试3: 测试实时数据
print("\n【测试3】测试实时数据接口...")
try:
    print("尝试获取指数实时行情...")
    spot = ak.stock_zh_index_spot()
    print(f"[OK] 成功获取数据，共 {len(spot)} 条记录")
    if '000300' in str(spot.values):
        print("[OK] 找到沪深300数据")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试4: QDII 基金列表（东方财富）
print("\n【测试4】QDII基金列表 fund_qdii_category_holding_em...")
try:
    if hasattr(ak, "fund_qdii_category_holding_em"):
        qdii_df = ak.fund_qdii_category_holding_em()
        print(f"[OK] 成功获取 QDII 列表，共 {len(qdii_df)} 条记录")
        print(f"列名: {list(qdii_df.columns)}")
        print("前10行:")
        print(qdii_df.head(10))
    else:
        print("[WARN] 当前 akshare 版本不包含 fund_qdii_category_holding_em")
        print("将使用可用的 QDII 相关接口（JSL 数据源）:")
        funcs = [x for x in dir(ak) if "qdii" in x.lower() and not x.startswith("_")]
        print("  " + ", ".join(sorted(funcs)))

        frames = []
        sources = [
            ("qdii_a_index_jsl", "A股指数相关 QDII"),
            ("qdii_e_comm_jsl", "商品相关 QDII"),
            ("qdii_e_index_jsl", "海外指数相关 QDII"),
        ]
        for fn, desc in sources:
            if not hasattr(ak, fn):
                print(f"[WARN] 缺少接口: {fn}")
                continue
            try:
                df = getattr(ak, fn)()
                if df is not None and not df.empty:
                    df = df.copy()
                    df["来源"] = fn
                    df["来源说明"] = desc
                    frames.append(df)
                    print(f"[OK] {fn} 共 {len(df)} 条")
                else:
                    print(f"[WARN] {fn} 返回空数据")
            except Exception as sub_e:
                print(f"[ERROR] {fn} 获取失败: {str(sub_e)[:200]}")

        if frames:
            all_df = pd.concat(frames, ignore_index=True)
            # 尝试按常见“代码”列去重
            code_col = None
            for c in ("代码", "基金代码", "symbol", "code"):
                if c in all_df.columns:
                    code_col = c
                    break
            if code_col:
                dedup_df = all_df.drop_duplicates(subset=[code_col, "来源"], keep="first")
            else:
                dedup_df = all_df.drop_duplicates(keep="first")

            print(f"\n[OK] 合并后共 {len(all_df)} 条（按来源保留），可用去重后 {len(dedup_df)} 条")
            print("前10行（合并结果）:")
            print(dedup_df.head(10))
        else:
            print("[ERROR] 未获取到任何 QDII 数据")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

# 测试5: 全量公募基金实时行情中筛选 QDII（东方财富）
print("\n【测试5】全量公募基金实时行情 fund_open_fund_daily_em -> 筛选 QDII...")
try:
    if hasattr(ak, "fund_open_fund_daily_em"):
        all_funds = ak.fund_open_fund_daily_em()
        print(f"[OK] 全量基金记录数: {len(all_funds)}")
        # 兼容列名（不同环境可能编码/列名不同）
        type_col = None
        for c in ("基金类型", "类型", "fund_type"):
            if c in all_funds.columns:
                type_col = c
                break
        if type_col is None:
            # 无法识别类型列，则尝试在“名称/简称”里搜索 QDII
            name_col = None
            for c in ("基金简称", "简称", "名称", "fund_name"):
                if c in all_funds.columns:
                    name_col = c
                    break
            if name_col is None:
                print("[WARN] 未找到基金类型/名称列，无法筛选 QDII；列名如下:")
                print(list(all_funds.columns))
            else:
                qdii_full_list = all_funds[all_funds[name_col].astype(str).str.contains("QDII", na=False)]
                print(f"[OK] 通过 {name_col} 搜索 QDII，共 {len(qdii_full_list)} 条")
                show_cols = [c for c in ("基金代码", "基金简称", name_col) if c in qdii_full_list.columns]
                print(qdii_full_list[show_cols].head(10))
        else:
            qdii_full_list = all_funds[all_funds[type_col].astype(str).str.contains("QDII", na=False)]
            print(f"[OK] 全量 QDII 列表共: {len(qdii_full_list)} 条（按列 {type_col}）")
            show_cols = [c for c in ("基金代码", "基金简称", "单位净值", "累计净值") if c in qdii_full_list.columns]
            if show_cols:
                print(qdii_full_list[show_cols].head(10))
            else:
                print("列名不含常见字段，打印前 10 行:")
                print(qdii_full_list.head(10))
    else:
        print("[WARN] 当前 akshare 版本不包含 fund_open_fund_daily_em")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:200]}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)

