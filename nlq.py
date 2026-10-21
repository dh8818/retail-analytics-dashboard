# -*- coding: utf-8 -*-
"""
中文问数：把「上个月各品类销售额前 5 名」这类问题，翻译成 SQL 并解释理解过程。

不依赖任何大模型 / API key —— 用规则解析：
    时间（本月/上月/今年/最近30天/2026-08/第三季度/2026年）
    维度（品类/商品/门店/省份/月份/星期…按实际列名匹配）
    指标（销售额/数量/订单数/客单价/毛利率/件单价）
    排序与条数（前 N / 最高 / 最低 / 最少）
    过滤（问题里出现了某个维度的取值，如「饮料」）

解析不出来时明确说"没听懂"，并给出能答的问题样式，而不是瞎编 SQL。
"""
import re
from datetime import datetime

import pandas as pd

# ---------- 词表 ----------
METRIC_WORDS = {
    "毛利率": ["毛利率", "毛利占比", "利润率"],
    "毛利": ["毛利", "毛利润", "赚了多少"],
    "客单价": ["客单价", "平均每单", "每单多少钱"],
    "件单价": ["件单价", "每件多少钱"],
    "订单数": ["订单数", "多少单", "单量", "订单量", "几单"],
    "数量": ["销量", "数量", "卖了多少件", "件数"],
    "收入": ["销售额", "收入", "金额", "营收", "卖了多少", "营业额", "GMV", "gmv"],
}
DIM_WORDS = {
    "月份": ["每个月", "各月", "按月", "月度", "每月", "月份"],
    "星期": ["星期", "周几", "每星期"],
    "省份": ["省份", "各省", "地区", "大区"],
    "城市": ["城市", "各城市"],
    "门店": ["门店", "店铺", "店", "分店"],
    "商品": ["商品", "产品", "单品", "sku", "SKU", "货"],
    "品类": ["品类", "类目", "大类", "分类", "类别"],
    "会员": ["会员", "客户", "顾客", "用户"],
}
ORDER_HINT = ["订单号", "单号", "小票", "流水号", "交易号"]


class Result(dict):
    """作为 dict 用，方便界面直接取值。"""


def _q(name):
    return '"' + str(name).replace('"', '""') + '"'


def _find_col(cols, hints, exclude=()):
    for h in hints:
        for c in cols:
            if c in exclude:
                continue
            if h.lower() in str(c).lower():
                return c
    return None


def build_schema(df, metric=None, qty=None, date=None, cost=None, cat=None, item=None):
    cols = [str(c) for c in df.columns]
    order = _find_col(cols, ORDER_HINT)
    return {
        "df": df,
        "cols": cols,
        "metric": metric if metric in cols else _find_col(cols, ["金额", "销售额", "收入", "amount"]),
        "qty": qty if qty in cols else _find_col(cols, ["数量", "销量", "qty"]),
        "date": date if date in cols else _find_col(cols, ["日期", "时间", "date"]),
        "cost": cost if cost in cols else _find_col(cols, ["进货价", "成本", "cost"]),
        "cat": cat if cat in cols else _find_col(cols, ["品类", "类别", "分类"]),
        "item": item if item in cols else _find_col(cols, ["商品名称", "名称", "品名", "商品"]),
        "order": order,
        "cust": _find_col(cols, ["会员", "客户", "顾客", "卡号"]),
    }


def _detect_period(q, s):
    """返回 (SQL 条件 或 None, 人话描述)。"""
    df, dcol = s["df"], s["date"]
    if not dcol:
        return None, ""
    d = pd.to_datetime(df[dcol], errors="coerce")
    d = d.dropna()
    if d.empty:
        return None, ""
    q = q.lower()

    m = re.search(r"(20\d{2})[-/年](\d{1,2})月?", q)
    if m:
        y, mo = m.group(1), int(m.group(2))
        return (f"date_trunc('month', {_q(dcol)}) = DATE '{y}-{mo:02d}-01'",
                f"{y} 年 {mo} 月")

    # 只写「8 月」：取数据里存在该月的最近年份
    m = re.search(r"(?<!\d)(\d{1,2})\s*月", q)
    if m and 1 <= int(m.group(1)) <= 12:
        mo = int(m.group(1))
        have = d[d.dt.month == mo]
        y = have.dt.year.max() if len(have) else d.dt.year.max()
        return (f"date_trunc('month', {_q(dcol)}) = DATE '{int(y)}-{mo:02d}-01'",
                f"{int(y)} 年 {mo} 月")

    m = re.search(r"第([一二三四1234])季度", q)
    if m:
        qn = "一二三四".index(m.group(1)) + 1 if m.group(1) in "一二三四" else int(m.group(1))
        y = re.search(r"(20\d{2})", q)
        year = y.group(1) if y else str(d.max().year)
        start = (qn - 1) * 3 + 1
        end = start + 2
        return (f"{_q(dcol)} >= DATE '{year}-{start:02d}-01' AND {_q(dcol)} < "
                f"(DATE '{year}-{end:02d}-01' + INTERVAL 1 MONTH)",
                f"{year} 年第 {qn} 季度")

    if "上个月" in q or "上月" in q:
        last = (d.max().to_period("M") - 1)
        return (f"date_trunc('month', {_q(dcol)}) = DATE '{last.start_time:%Y-%m-%d}'",
                f"上月（{last}）")
    if "本月" in q or "这个月" in q:
        cur = d.max().to_period("M")
        return (f"date_trunc('month', {_q(dcol)}) = DATE '{cur.start_time:%Y-%m-%d}'",
                f"本月（{cur}）")
    if "今年" in q:
        y = d.max().year
        return (f"date_part('year', {_q(dcol)}) = {y}", f"今年（{y}）")
    if "去年" in q:
        y = d.max().year - 1
        return (f"date_part('year', {_q(dcol)}) = {y}", f"去年（{y}）")

    m = re.search(r"最近\s*(\d+)\s*天", q)
    if m:
        n = int(m.group(1))
        end = d.max()
        return (f"{_q(dcol)} >= DATE '{end:%Y-%m-%d}' - INTERVAL {n} DAY",
                f"最近 {n} 天")
    m = re.search(r"最近\s*(\d+)\s*个?月", q)
    if m:
        n = int(m.group(1))
        end = d.max()
        return (f"{_q(dcol)} >= DATE '{end:%Y-%m-%d}' - INTERVAL {n} MONTH",
                f"最近 {n} 个月")
    return None, ""


def _detect_dim(q, s):
    for dim, words in DIM_WORDS.items():
        if any(w.lower() in q.lower() for w in words):
            col = {"月份": s["date"], "星期": s["date"], "省份": _find_col(s["cols"], ["省份"]),
                   "城市": _find_col(s["cols"], ["城市"]), "门店": _find_col(s["cols"], ["门店", "店铺"]),
                   "商品": s["item"], "品类": s["cat"], "会员": s["cust"]}[dim]
            if not col:
                return None, None, "", dim      # 提到了但这个维度不存在
            if dim == "月份":
                return f"strftime({_q(s['date'])}, '%Y-%m')", col, "月份", None
            if dim == "星期":
                return f"dayname({_q(s['date'])})", col, "星期", None
            return _q(col), col, dim, None
    return None, None, "", None


def _detect_metric(q, s):
    for name, words in METRIC_WORDS.items():
        if any(w.lower() in q.lower() for w in words):
            if name == "收入":
                return (f"SUM({_q(s['metric'])}) AS 收入", "收入", "元")
            if name == "数量":
                return (f"SUM({_q(s['qty'])}) AS 数量", "销售数量", "件")
            if name == "订单数":
                return (f"COUNT(DISTINCT {_q(s['order'])}) AS 订单数", "订单数", "单")
            if name == "客单价":
                return (f"ROUND(SUM({_q(s['metric'])}) / NULLIF(COUNT(DISTINCT {_q(s['order'])}),0), 2) AS 客单价",
                        "客单价", "元/单")
            if name == "件单价":
                return (f"ROUND(SUM({_q(s['metric'])}) / NULLIF(SUM({_q(s['qty'])}),0), 2) AS 件单价",
                        "件单价", "元/件")
            if name == "毛利":
                return (f"ROUND(SUM({_q(s['metric'])}) - SUM({_q(s['cost'])}), 2) AS 毛利", "毛利", "元")
            if name == "毛利率":
                return (f"ROUND(100.0*(SUM({_q(s['metric'])}) - SUM({_q(s['cost'])}))"
                        f" / NULLIF(SUM({_q(s['metric'])}),0), 2) AS 毛利率",
                        "毛利率", "%")
    # 没写指标时，默认看收入
    if s["metric"]:
        return f"SUM({_q(s['metric'])}) AS 收入", "收入（默认）", "元"
    return None, "", ""


def _detect_top(q, s):
    m = re.search(r"前\s*(\d+)", q)
    if m:
        return int(m.group(1)), "DESC"
    if re.search(r"(最高|最多|最大|最好|排名前|top|Top|TOP)", q):
        return 10, "DESC"
    if re.search(r"(最低|最少|最小|最差|垫底)", q):
        return 10, "ASC"
    return None, "DESC"


def _detect_value(q, s, dim_col):
    """问题里出现的维度取值，比如「饮料」「S01」。"""
    if not dim_col or dim_col not in s["df"].columns:
        return None
    vals = s["df"][dim_col].dropna().astype(str).unique()
    vals = [v for v in vals if v and len(v) <= 12]
    for v in sorted(vals, key=len, reverse=True):
        if len(v) >= 2 and v in q:
            return v
    return None


def _detect_value_any(q, s):
    """没指明维度时，扫一遍类别列，看问题里是否提到了某个具体取值。"""
    for col in [s["cat"], s["item"], _find_col(s["cols"], ["门店", "店铺"]),
                _find_col(s["cols"], ["省份"]), _find_col(s["cols"], ["城市"]), s["cust"]]:
        if not col or col not in s["df"].columns:
            continue
        v = _detect_value(q, s, col)
        if v:
            return col, v
    return None, None


def to_sql(question, s):
    """返回 {'ok', 'sql', 'explain', 'metric', 'dim', 'hint'}"""
    q = (question or "").strip()
    if not q:
        return {"ok": False, "reason": "问题为空"}
    if not s.get("metric"):
        return {"ok": False, "reason": "没找到金额列，无法计算"}

    period_sql, period_txt = _detect_period(q, s)
    dim_sql, dim_col, dim_txt, missing_dim = _detect_dim(q, s)
    if missing_dim:
        avail = [d for d in ("品类", "商品", "门店", "省份", "城市", "月份", "会员")
                 if {"品类": s["cat"], "商品": s["item"], "月份": s["date"], "会员": s["cust"]}.get(d)
                 or _find_col(s["cols"], [d])]
        return {"ok": False,
                "reason": f"这份数据里没有「{missing_dim}」这一列。目前能按这些维度看：{'、'.join(avail) or '（无）'}"}
    metric_sql, metric_txt, unit = _detect_metric(q, s)
    limit, direction = _detect_top(q, s)

    where = []
    if period_sql:
        where.append(period_sql)

    # 值过滤：只有维度不是被聚合对象时才当作筛选条件
    val = _detect_value(q, s, dim_col) if dim_col else None
    if not val and not dim_sql:
        _c, _v = _detect_value_any(q, s)
        if _v:
            val, dim_col, dim_txt = _v, _c, str(_c)
    filter_txt = ""
    if val and dim_col:
        # 同时按这个维度分组又要筛它 -> 说明用户想筛别的维度，交给 WHERE 不分组
        where.append(f"{_q(dim_col)} = '{val}'")
        filter_txt = f"{dim_txt} = {val}"
        dim_sql, dim_txt = None, None

    if not metric_sql:
        return {"ok": False, "reason": "没听出要算哪个指标（比如销售额、数量、订单数、客单价、毛利率）"}

    if not dim_sql and not where:
        return {"ok": False, "reason": "没听出按什么分组或什么时间范围，试着加上「各品类」「上个月」「近 30 天」"}

    if dim_sql:
        sql = f"SELECT {dim_sql} AS {_q(dim_txt or '维度')}, {metric_sql} FROM t"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" GROUP BY 1 ORDER BY 2 {direction}"
        if limit:
            sql += f" LIMIT {limit}"
    else:
        sql = f"SELECT {metric_sql} FROM t"
        if where:
            sql += " WHERE " + " AND ".join(where)

    parts = []
    parts.append(f"按「{dim_txt}」统计{metric_txt}" if dim_sql else f"统计{metric_txt}")
    if filter_txt:
        parts.append(f"只看 {filter_txt}")
    if period_txt:
        parts.append(f"时间范围：{period_txt}")
    if limit and dim_sql:
        parts.append(f"取{'最多' if direction == 'DESC' else '最少'}的 {limit} 个")
    explain = "，".join(parts) + "。"

    return {"ok": True, "sql": sql, "explain": explain, "metric": metric_txt,
            "dim": dim_txt, "unit": unit,
            "hint": "只读查询，结果可下载 CSV"}
