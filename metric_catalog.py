# -*- coding: utf-8 -*-
"""
指标中心（语义层）：让「指标」定义一次、全局复用，跨人、跨报表口径一致。

解决的问题：
- 原来 9 个内置指标公式散在 metrics.py 里，报告、字典、导出一处写一处，
  换人接手或换数据源时，口径容易漂移。
- 这里提供一份「权威指标定义」，所有消费方（概览卡、口径字典、报告、
  分析包、推送结论）都从同一处取，而不是各自再写一遍。

设计：
- 每个指标 = {name, formula(模板), unit, kind(amount/ratio/count), desc, aliases}
- formula 里的 {rev}/{qty}/{cost}/{order} 是「语义占位符」，运行时按数据源
  实际列名绑定（bind_columns），因此同一份定义能套到不同数据源的列名上。
- 与 metrics.py 的关系：metrics.py 仍负责「求值」，这里负责「定义的唯一来源」。
  两者不冲突——catalog 是字典/元数据，metrics 是执行器。
"""
from __future__ import annotations

# 指标类型：amount=金额类、ratio=比率类、count=计数类、price=单价类
# 类型决定 display 时的格式（比率加 %，单价保留两位小数等）
KIND = {
    "amount": "金额", "ratio": "比率", "count": "计数", "price": "单价",
}


# 权威指标定义（语义占位符：{rev}=收入列 {qty}=数量列 {cost}=成本列 {order}=订单键）
# 注意：这里只放「口径」，不放具体列名——列名由 bind_columns 按数据源绑定。
CATALOG: dict[str, dict] = {
    "销售收入": {
        "formula": "sum({rev})", "unit": "元", "kind": "amount",
        "desc": "全部行的收入求和；退款（负金额）是否冲减取决于退款口径",
        "aliases": ["销售额", "营收", "收入", "成交额", "GMV"],
    },
    "销售数量": {
        "formula": "sum({qty})", "unit": "件", "kind": "count",
        "desc": "销售件数合计；退货行负数量会冲减",
        "aliases": ["销量", "件数", "数量"],
    },
    "订单数": {
        "formula": "nunique({order})", "unit": "单", "kind": "count",
        "desc": "去重订单号；订单号跨期复用时按「单号+日期」去重",
        "aliases": ["单量", "多少单"],
    },
    "成本": {
        "formula": "sum({cost} * {qty})", "unit": "元", "kind": "amount",
        "desc": "成本按「单价×数量」换算；列名像总额时直接求和（口径可切）",
        "aliases": ["进货成本", "商品成本"],
    },
    "毛利": {
        "formula": "[销售收入] - [成本]", "unit": "元", "kind": "amount",
        "desc": "收入减成本；不含人工、房租、平台佣金，是商品毛利非净利",
        "aliases": ["毛利润", "赚了多少"],
    },
    "毛利率": {
        "formula": "[毛利] / [销售收入]", "unit": "%", "kind": "ratio",
        "desc": "毛利÷收入；低毛利走量生意不宜用它做唯一考核",
        "aliases": ["利润率", "毛利占比"],
    },
    "客单价": {
        "formula": "[销售收入] / [订单数]", "unit": "元", "kind": "price",
        "desc": "金额÷订单数；是否含退款单影响分母",
        "aliases": ["每单金额", "平均每单"],
    },
    "连带率": {
        "formula": "[销售数量] / [订单数]", "unit": "件/单", "kind": "ratio",
        "desc": "件数÷订单数；按件数或按 SKU 数两种口径",
        "aliases": [],
    },
    "件单价": {
        "formula": "[销售收入] / [销售数量]", "unit": "元/件", "kind": "price",
        "desc": "金额÷件数，反映每件卖多少钱",
        "aliases": ["每件价格"],
    },
}


def list_metrics():
    """返回按展示顺序排好的指标名列表（与 metrics.py 的 ORDER 对齐）。"""
    return [
        "销售收入", "销售数量", "订单数", "成本", "毛利",
        "毛利率", "客单价", "连带率", "件单价",
    ]


def get(name) -> dict | None:
    return CATALOG.get(name)


def bind_columns(rev_col, qty_col, cost_col, order_col):
    """把语义占位符绑定到某数据源的实际列名，返回「指标名 → 可执行公式」的映射。

    返回的公式可直接交给 custom_metrics.evaluate / metrics.resolve 求值。
    这是「定义一次、适配多数据源」的关键：同一份 CATALOG，换个列名绑一次即可。
    """
    rev = rev_col or ""
    qty = qty_col or ""
    cost = cost_col or ""
    order = order_col or ""

    def _fill(formula: str) -> str:
        return (formula.replace("{rev}", rev)
                .replace("{qty}", qty)
                .replace("{cost}", cost)
                .replace("{order}", order))

    out = {}
    for name in list_metrics():
        meta = CATALOG[name]
        expr = _fill(meta["formula"])
        # 占位符没绑上（该数据源缺列）时，产出空公式，由求值层显示「不可计算」
        if any(p in expr for p in ("{rev}", "{qty}", "{cost}", "{order}")):
            out[name] = ""
            continue
        # 成本公式依赖成本列：缺成本时不能产出 sum( * 数量) 这种坏公式
        if name == "成本" and not cost:
            out[name] = ""
            continue
        out[name] = expr
    return out


def dict_rows(bindings: dict[str, str]):
    """生成口径字典表格行：指标 / 公式 / 单位 / 口径说明。报告与页面共用。"""
    rows = []
    for name in list_metrics():
        meta = CATALOG[name]
        rows.append({
            "指标": name,
            "分组": meta.get("group", "未分组"),
            "公式": bindings.get(name, meta["formula"]),
            "单位": meta["unit"],
            "口径说明": meta["desc"],
        })
    return rows


# ---------------- 指标中心元数据（分组 + 版本） ----------------
# 指标分组：把 9 个指标按业务主题归类，供「指标中心」按主题浏览。
GROUPS = {
    "销售规模": ["销售收入", "销售数量", "订单数"],
    "利润": ["成本", "毛利", "毛利率"],
    "客单效率": ["客单价", "连带率", "件单价"],
}

# 指标中心版本号：改口径定义时递增，用于追溯「这份数字是按哪个版本算的」。
CATALOG_VERSION = "1.0"


def group_map() -> dict[str, str]:
    """指标名 → 分组名。"""
    m = {}
    for g, names in GROUPS.items():
        for n in names:
            m[n] = g
    return m


def catalog_rows(bindings: dict[str, str] | None = None):
    """指标中心表格：指标 / 分组 / 公式 / 单位 / 口径说明 / 别名。

    bindings 传入时公式用实际列名，否则显示语义占位符模板。
    """
    rows = []
    gmap = group_map()
    for name in list_metrics():
        meta = CATALOG[name]
        expr = (bindings or {}).get(name) or meta["formula"]
        rows.append({
            "指标": name,
            "分组": gmap.get(name, "未分组"),
            "公式": expr,
            "单位": meta["unit"],
            "口径说明": meta["desc"],
            "别名": "、".join(meta.get("aliases", [])),
        })
    return rows
