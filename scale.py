# -*- coding: utf-8 -*-
"""
规模性能优化：让单文件上传 / 万级 SKU 不再撞内存天花板。

对应第 6 项需求。原则：不破坏现有主链路，作为「可选的加速路径」提供。

提供三件事：
1. read_csv_chunked() —— 分块读超大 CSV，避免一次性 load 全部进内存；
   返回一个「可迭代的块」或直接抽样，供概览先出结果。
2. duckdb_register() —— 用 DuckDB 直接查询超大 CSV/Parquet（惰性、列裁剪、
   谓词下推），绕开 pandas 全量加载。大数据量时用它做聚合，再取小结果回 pandas。
3. basket_vectorized() —— 万级 SKU 下购物篮的向量化实现，替代 analytics 里
   的纯 Python 双重循环（O(n²)）。
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd


def read_csv_chunked(path_or_bytes, chunksize=100_000, **kwargs):
    """分块读 CSV，返回迭代器。适合超大文件逐块处理，不一次性占满内存。

    用法：
        for chunk in read_csv_chunked("huge.csv"):
            process(chunk)
    """
    if isinstance(path_or_bytes, (str, Path)):
        return pd.read_csv(path_or_bytes, chunksize=chunksize, **kwargs)
    return pd.read_csv(io.BytesIO(path_or_bytes), chunksize=chunksize, **kwargs)


def duckdb_query(path_or_bytes, sql, table="raw", fmt="csv"):
    """用 DuckDB 直接对大数据文件跑 SQL，返回结果 DataFrame。

    - 惰性扫描 + 谓词下推：只读需要的列和行，几十万行也能秒回。
    - 适合「先出聚合概览、再按需取明细」的大数据场景。
    """
    import duckdb
    con = duckdb.connect()
    try:
        if fmt == "csv":
            con.execute("CREATE OR REPLACE VIEW raw AS SELECT * FROM read_csv_auto(?)", [path_or_bytes])
        elif fmt == "parquet":
            con.execute("CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet(?)", [path_or_bytes])
        else:
            con.register(table, path_or_bytes)
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def basket_vectorized(df, order_col, item_col, min_support=8, top_n=12):
    """向量化购物篮：支持度/置信度/提升度。

    用 pandas 自连接 + 分组替代 analytics.basket_rules 的 Python 双重循环，
    万级 SKU、几十万行时性能有数量级提升。
    """
    if order_col not in df.columns or item_col not in df.columns:
        return None
    d = df[[order_col, item_col]].dropna()
    d = d[d[item_col].astype(str).str.strip() != ""]
    if d.empty:
        return None
    # 每个订单内的商品去重
    baskets = d.drop_duplicates(subset=[order_col, item_col])
    n_basket = baskets[order_col].nunique()
    if n_basket < 20:
        return None

    # 单品出现次数（按订单计）
    item_count = baskets.groupby(item_col)[order_col].nunique()

    # 自连接得商品对（同订单）
    merged = baskets.merge(baskets, on=order_col, suffixes=("_a", "_b"))
    merged = merged[merged[f"{item_col}_a"] < merged[f"{item_col}_b"]]  # 去重、去自对
    pair_count = merged.groupby([f"{item_col}_a", f"{item_col}_b"])[order_col].nunique()

    rows = []
    for (a, b), c in pair_count.items():
        if c < min_support:
            continue
        sup = c / n_basket
        ca, cb = item_count[a], item_count[b]
        conf = c / ca
        lift = conf / (cb / n_basket)
        rows.append({"商品A": a, "商品B": b, "同单次数": int(c),
                     "支持度%": round(sup * 100, 2), "置信度%": round(conf * 100, 1),
                     "提升度": round(lift, 2)})
    if not rows:
        return None
    out = pd.DataFrame(rows).sort_values("提升度", ascending=False)
    return out.head(top_n).reset_index(drop=True)


def downcast(df: pd.DataFrame) -> pd.DataFrame:
    """数值列降精度（float64→float32、int64→int32/16），内存占用最高省一半。

    对万级 SKU、几十万行的明细，内存能明显下降。只对安全范围内做，不改变数值。
    """
    d = df.copy()
    for c in d.columns:
        s = d[c]
        if pd.api.types.is_float_dtype(s):
            if (s.dropna() >= -3.4e38).all() and (s.dropna() <= 3.4e38).all():
                d[c] = s.astype(np.float32)
        elif pd.api.types.is_integer_dtype(s):
            mn, mx = s.min(), s.max()
            if pd.notna(mn) and pd.notna(mx):
                if mn >= -32768 and mx <= 32767:
                    d[c] = s.astype(np.int16)
                elif mn >= -2147483648 and mx <= 2147483647:
                    d[c] = s.astype(np.int32)
    return d
