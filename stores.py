# -*- coding: utf-8 -*-
"""
多门店模型与权限：总部 — 区域 — 门店 三级结构 + 数据隔离 + 跨店对比。

对应第 3 项需求。设计原则（与现有产品哲学一致）：
- 门店结构是「组织树」：总部(root) → 区域 → 门店。用 parent 指针存。
- 权限按「可见范围 scope」隔离：店长只看自己店，区域经理看本区域所有店，
  老板看全部。数据隔离是「按门店编码过滤」，不是软删，可追溯。
- 跨店对比：把单店分析在 N 个门店上并行跑，产出「门店 × 指标」对比表，
  供老板看哪家店好、哪家店拖后腿。

持久化走 datasources.Store（SQLite）。本模块只做「结构 + 权限 + 对比」的纯逻辑，
不碰 Streamlit，方便单测。
"""
from __future__ import annotations

import pandas as pd

# 角色 → 可见范围语义
ROLES = {
    "boss": "总部（看全部）",
    "region_manager": "区域经理（看本区域）",
    "store_manager": "店长（看本店）",
}


class StoreTree:
    """门店组织树 + 权限判定。"""

    def __init__(self, store=None):
        # store 是 datasources.Store（可选），这里只存引用，避免循环依赖
        self._db = store

    @staticmethod
    def build_from(df: pd.DataFrame) -> dict:
        """从门店表 DataFrame 构建 {code: {name, region, parent}} 字典。"""
        tree = {}
        for _, r in df.iterrows():
            tree[str(r["code"])] = {
                "name": r.get("name", r["code"]),
                "region": r.get("region", ""),
                "parent": r.get("parent", ""),
            }
        return tree

    @staticmethod
    def visible_codes(tree: dict, role: str, scope: str | None) -> list[str]:
        """按角色+范围算出可见门店编码列表。

        - boss：全部门店
        - region_manager：scope 为区域名，返回该区域所有门店
        - store_manager：scope 为门店编码，返回该店
        """
        all_codes = list(tree.keys())
        if role == "boss":
            return all_codes
        if role == "region_manager":
            return [c for c, m in tree.items() if m.get("region") == scope]
        if role == "store_manager":
            return [scope] if scope in tree else []
        return all_codes


def scope_filter(df: pd.DataFrame, store_col: str, visible: list[str]) -> pd.DataFrame:
    """数据隔离：只保留可见门店的行。无门店列时原样返回（单店/无门店维度场景）。"""
    if store_col not in df.columns or not visible:
        return df
    return df[df[store_col].astype(str).isin(visible)]


def cross_store_compare(df: pd.DataFrame, store_col: str, metric: str,
                        visible: list[str] | None = None) -> pd.DataFrame:
    """跨店对比：每个门店的销售额/毛利等，输出对比表 + 排名 + 份额。

    返回列：门店 / 销售额 / 占比% / 排名。
    """
    if store_col not in df.columns or metric not in df.columns:
        return pd.DataFrame()
    d = df if visible is None else df[df[store_col].astype(str).isin(visible)]
    g = d.groupby(store_col)[metric].sum().sort_values(ascending=False)
    if g.empty:
        return pd.DataFrame()
    total = g.sum()
    out = pd.DataFrame({
        "门店": [str(i) for i in g.index],
        "销售额": g.values,
        "占比%": (g.values / total * 100 if total else 0).round(1),
        "排名": range(1, len(g) + 1),
    })
    return out.reset_index(drop=True)


def cross_store_kpi(df: pd.DataFrame, store_col: str, metric: str,
                    cost_line: pd.Series | None = None,
                    visible: list[str] | None = None) -> dict:
    """跨店 KPI：给每个门店算收入、毛利、毛利率（如有成本），返回门店级汇总。"""
    if store_col not in df.columns or metric not in df.columns:
        return {}
    d = df if visible is None else df[df[store_col].astype(str).isin(visible)]
    g = d.groupby(store_col)[metric].sum()
    out = {str(k): {"销售额": float(v)} for k, v in g.items()}
    if cost_line is not None and len(cost_line) == len(df):
        tmp = df.assign(_cost=cost_line.values)
        c = tmp[tmp[store_col].astype(str).isin(visible)].groupby(store_col)["_cost"].sum()
        for k in out:
            cost = float(c.get(k, 0))
            rev = out[k]["销售额"]
            out[k]["毛利"] = rev - cost
            out[k]["毛利率%"] = round((rev - cost) / rev * 100, 1) if rev else None
    return out
