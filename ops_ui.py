# -*- coding: utf-8 -*-
"""经营诊断：把《零售数据运营实战手册》第 3–5 章的算法做成可操作的一页。

输入整店流水 + 固定开销 → 自动判断「该促销 / 该保本 / 该砍商品」，
每条结论都带判断依据、影响测算和验证指标。

本模块只负责输入与呈现；所有公式在 retail_ops.compute / diagnose 里，
改口径只改那一处，页面自动跟着变。
"""
from __future__ import annotations

import html as _html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics as AN
import retail_ops as RO
from style import BAD, BI_BLUE, BI_NAVY, GOOD, MUTED, TEXT, WARN, fig_base, fmt

_BAD, _WARN, _OK = BAD, WARN, GOOD
_TONE = {"bad": _BAD, "warn": _WARN, "ok": _OK}

# 固定开销默认值：社区便利店常见水平（明确标注为示例，不是用户真实成本）
_FIXED_DEMO = {"rent": 6000, "labor": 19000, "utility": 2200, "dep": 800, "other": 800}
_FIXED_LABEL = {"rent": "房租", "labor": "人工", "utility": "水电", "dep": "折旧摊销", "other": "其他固定"}

# 这些字段能从 POS 明细重算；换数据时重置它们，但不动用户手填的成本项
_DATA_KEYS = ["days", "sales", "cogs", "orders", "qty", "sku_active", "sku_sold", "sku_oos",
              "mom_sales", "mom_traffic", "mom_aov"]


# ---------------------------------------------------------------- 小组件
def _sect(t: str, sub: str = ""):
    st.html(f"<div class='sect'>{t}<small>{sub}</small></div>")


def _kpi(items, cols: int | None = None):
    """KPI 卡按 cols 一行的节奏排；超过一行自动换行（不能只渲染前 cols 个）。"""
    cols = max(1, cols or len(items) or 1)
    for start in range(0, len(items), cols):
        chunk = items[start:start + cols]
        cs = st.columns(len(chunk))
        for c, (lab, val, sub, tone) in zip(cs, chunk):
            color = {"ok": _OK, "warn": _WARN, "bad": _BAD}.get(tone or "", BI_NAVY)
            c.html(
                f"<div class='kpi'><div class='kpi-label'>{_html.escape(lab)}</div>"
                f"<div class='kpi-value' style='color:{color}'>{val}</div>"
                f"<div class='kpi-sub'>{_html.escape(sub)}</div></div>")


def _money(v) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    return ("-¥" if v < 0 else "¥") + f"{abs(v):,.0f}"


def _pct(v, d: int = 1) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v * 100:.{d}f}%"


def _table(headers, rows, aligns=None, widths=None, caption=""):
    """轻量 HTML 表：贴在卡片里，比 st.dataframe 更贴合这套暖陶土视觉。

    只输出**单个根节点**的 HTML，样式统一放 ui.css 的 .ops-tbl——
    在 st.markdown 里夹 <style> 会让 React 卸载节点时找不到子节点（removeChild）。
    """
    aligns = aligns or ["left"] * len(headers)
    widths = widths or [None] * len(headers)
    th = "".join(
        f"<th style='text-align:{a};{f'width:{w};' if w else ''}'>{_html.escape(h)}</th>"
        for h, a, w in zip(headers, aligns, widths))
    body = []
    for r in rows:
        tds = "".join(
            f"<td style='text-align:{a}'>{c}</td>" for c, a in zip(r, aligns))
        body.append(f"<tr>{tds}</tr>")
    html = (
        "<div class='ops-tbl-wrap'><table class='ops-tbl'>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")
    if caption:
        html += f"<div style='font-size:11.5px;color:{MUTED};margin-top:6px'>{caption}</div>"
    return html


def _pill(text: str, tone: str = "") -> str:
    c = {"bad": _BAD, "warn": _WARN, "ok": _OK}.get(tone, MUTED)
    bg = {"bad": "#F8E6E2", "warn": "#F9F0DC", "ok": "#EAF1E8"}.get(tone, "#F0ECE4")
    return (f"<span style='display:inline-block;padding:1px 8px;border-radius:9px;"
            f"background:{bg};color:{c};font-size:11px;white-space:nowrap'>{_html.escape(text)}</span>")


def _verdict(tone: str, tag: str, title: str, why: str, chips: list[tuple[str, str]]):
    c = _TONE.get(tone, _OK)
    chip_html = "".join(
        f"<span style='display:inline-block;padding:3px 10px;border-radius:12px;"
        f"background:#F4EFE6;color:#4A453D;font-size:11.5px;margin:0 6px 4px 0'>{k} <b>{v}</b></span>"
        for k, v in chips)
    st.html(
        f"<div style='background:#fff;border:1px solid #E8E2D8;border-top:4px solid {c};"
        f"border-radius:12px;padding:18px 20px;margin:6px 0 10px;box-shadow:0 1px 2px rgba(42,39,35,.04)'>"
        f"<div style='font-size:11px;letter-spacing:.18em;color:{MUTED}'>{_html.escape(tag)}</div>"
        f"<div style='font-size:24px;font-weight:600;color:{TEXT};margin:6px 0 8px;line-height:1.35'>"
        f"{_html.escape(title)}</div>"
        f"<div style='font-size:13px;color:#4A453D;line-height:1.85'>{_html.escape(why)}</div>"
        f"<div style='margin-top:10px'>{chip_html}</div></div>")


# ---------------------------------------------------------------- 默认值
def _auto(df, metric, date_col, cost_col, qty_col, order_col, key_col, cost_force):
    sales = float(pd.to_numeric(df[metric], errors="coerce").fillna(0).sum()) if metric else 0.0
    line = AN.cost_line(df, cost_col, qty_col, cost_force) if cost_col else None
    cogs = float(line.fillna(0).sum()) if line is not None else 0.0
    qty = float(pd.to_numeric(df[qty_col], errors="coerce").fillna(0).sum()) if qty_col else float(len(df))
    orders = int(df[order_col].nunique()) if order_col else int(len(df))

    days, mom_s, mom_t, mom_a = 30, 0.0, 0.0, 0.0
    if date_col:
        dts = pd.to_datetime(df[date_col], errors="coerce")
        if dts.notna().any():
            days = max(1, int((dts.max() - dts.min()).days) + 1)
            last = df[dts > dts.max() - pd.Timedelta(days=30)]
            prev = df[(dts <= dts.max() - pd.Timedelta(days=30)) & (dts > dts.max() - pd.Timedelta(days=60))]
            if len(last) and len(prev):
                s1 = float(pd.to_numeric(last[metric], errors="coerce").fillna(0).sum()) if metric else 0
                s0 = float(pd.to_numeric(prev[metric], errors="coerce").fillna(0).sum()) if metric else 0
                mom_s = (s1 - s0) / s0 * 100 if s0 else 0
                o1 = last[order_col].nunique() if order_col else len(last)
                o0 = prev[order_col].nunique() if order_col else len(prev)
                mom_t = (o1 - o0) / o0 * 100 if o0 else 0
                a1 = s1 / o1 if o1 else 0
                a0 = s0 / o0 if o0 else 0
                mom_a = (a1 - a0) / a0 * 100 if a0 else 0

    sku_active = sku_sold = 0
    if key_col:
        sku_active = int(df[key_col].nunique())
        if qty_col:
            g = df.groupby(key_col)[qty_col].sum()
            sku_sold = int((g > 0).sum())
        else:
            sku_sold = sku_active

    # 库存不猜：POS 明细里没有库存，填 0 就表示「不知道」，周转类指标会显示「待填」而不是 0 天
    close_inv = 0
    return {
        "days": days, "sales": round(sales, 2), "cogs": round(cogs, 2),
        "orders": orders, "qty": int(qty),
        "open_inv": close_inv, "close_inv": close_inv, "loss": 0, "shrink": 0,
        "sku_active": sku_active, "sku_sold": sku_sold, "sku_oos": 0,
        "area": 68, "staff": 5,
        **_FIXED_DEMO,
        "promo_spend": 0, "promo_incr": 0,
        "mom_sales": round(mom_s, 1), "mom_traffic": round(mom_t, 1), "mom_aov": round(mom_a, 1),
    }


# ---------------------------------------------------------------- 输入区
def _inputs(defaults):
    keys = ["days", "sales", "cogs", "orders", "qty", "open_inv", "close_inv", "loss", "shrink",
            "sku_active", "sku_sold", "sku_oos", "area", "staff",
            "rent", "labor", "utility", "dep", "other", "promo_spend", "promo_incr",
            "mom_sales", "mom_traffic", "mom_aov"]
    for k in keys:
        st.session_state.setdefault(f"ops_{k}", defaults[k])

    st.html(
        "<div class='insight' style='border-left-color:#5F7A96'>"
        "<b>这些数从哪来</b>：销售额、销货成本、订单数、件数、天数由左侧选定的列自动汇总；"
        "<b>库存、报损、固定开销、面积、人数</b>在 POS 明细里没有，必须按门店实际填。"
        "固定开销首次进入时按社区便利店常见水平<b>预填示例值</b>（房租 6000、人工 19000…），"
        "不改成你的实际成本，保本点和净利都不作数；库存填 0 表示「不知道」，"
        "周转类指标会显示「待填」而不是编一个数出来。</div>")

    with st.expander("① 整店流水与固定开销（默认已按当前数据填好）", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.number_input("统计天数", min_value=1, step=1, key="ops_days")
            st.number_input("销售额（元）", min_value=0.0, step=1000.0, format="%.2f", key="ops_sales")
            st.number_input("销货成本（元）", min_value=0.0, step=1000.0, format="%.2f", key="ops_cogs")
            st.number_input("订单数（单）", min_value=0, step=10, key="ops_orders")
            st.number_input("销售件数（件）", min_value=0, step=10, key="ops_qty")
        with c2:
            st.number_input("期初库存（成本价）", min_value=0.0, step=500.0, key="ops_open_inv",
                            help="没有盘点数就填 0，周转按期末库存算")
            st.number_input("期末库存（成本价）", min_value=0.0, step=500.0, key="ops_close_inv",
                            help="按成本价填盘点数；没有就填 0，周转类指标会显示「待填」而不是乱算")
            st.number_input("报损（成本价）", min_value=0.0, step=100.0, key="ops_loss",
                            help="过期/破损销毁；没有报损单就填 0")
            st.number_input("盘亏", min_value=0.0, step=100.0, key="ops_shrink")
        with c3:
            st.number_input("房租（元/月）", min_value=0.0, step=500.0, key="ops_rent")
            st.number_input("人工（元/月）", min_value=0.0, step=500.0, key="ops_labor")
            st.number_input("水电（元/月）", min_value=0.0, step=100.0, key="ops_utility")
            st.number_input("折旧摊销（元/月）", min_value=0.0, step=100.0, key="ops_dep")
            st.number_input("其他固定（元/月）", min_value=0.0, step=100.0, key="ops_other")
        with c4:
            st.number_input("营业面积（㎡）", min_value=0.0, step=5.0, key="ops_area")
            st.number_input("员工数（人）", min_value=0, step=1, key="ops_staff")
            st.number_input("在售 SKU", min_value=0, step=1, key="ops_sku_active")
            st.number_input("有销量 SKU", min_value=0, step=1, key="ops_sku_sold")
            st.number_input("缺货 SKU", min_value=0, step=1, key="ops_sku_oos")
        st.caption("固定开销按「每月」填，系统按 统计天数÷30 折算到本期——这是最容易算错的一处。")
        c5, c6 = st.columns([1, 3])
        if c5.button("↺ 用当前数据重填", key="ops_reset", width="stretch"):
            for k in keys:
                st.session_state[f"ops_{k}"] = defaults[k]
            st.rerun()
        c6.caption("改完任意一个数，下面的结论、行动清单和图表都会跟着重算。")

    return {k: st.session_state[f"ops_{k}"] for k in keys}


# ---------------------------------------------------------------- 结论区
def _render_diagnosis(m, dg, ctx):
    tone = dg["level"]
    _verdict(
        tone,
        f"诊断结论 · {'需要立即处置' if tone == 'bad' else '需要优化结构' if tone == 'warn' else '经营健康'}"
        f" · 依据 {m['days']} 天数据",
        dg["headline"], dg["why"],
        [("净利", _money(m["net"])), ("安全边际", _pct(m["safety"])),
         ("周转", f"{m['turn_days']:.1f} 天" if m["inv_known"] else "待填库存"),
         ("损耗率", _pct(m["waste_rate"])),
         ("保本日均", _money(m["be_daily"])), ("实际日均", _money(m["daily_sales"]))])

    _kpi([
        ("净利", _money(m["net"]), f"净利率 {_pct(m['net_margin'])}",
         "bad" if m["net"] < 0 else ("warn" if m["net_margin"] < 0.03 else "ok")),
        ("安全边际", _pct(m["safety"]), f"保本日均 {_money(m['be_daily'])}",
         "bad" if m["safety"] < 0.05 else ("warn" if m["safety"] < 0.15 else "ok")),
        ("商品周转", f"{m['turn_days']:.1f} 天" if m["inv_known"] else "待填",
         f"年化 {m['turn_annual']:.0f} 次" if m["inv_known"] else "填期末库存后计算",
         ("bad" if m["turn_days"] > 21 else ("warn" if m["turn_days"] > 14 else "ok")) if m["inv_known"] else None),
        ("毛利率", _pct(m["gm"]), f"毛利额 {_money(m['gp'])}",
         "bad" if m["gm"] < 0.28 else ("warn" if m["gm"] < 0.32 else "ok")),
        ("动销率", _pct(m["active_rate"]), f"{ctx['sku_sold']}/{ctx['sku_active']} 个 SKU",
         "bad" if m["active_rate"] < 0.7 else ("warn" if m["active_rate"] < 0.8 else "ok")),
        ("损耗率", _pct(m["waste_rate"]), f"报损 {_money(m['loss'])}",
         "bad" if m["waste_rate"] > 0.035 else ("warn" if m["waste_rate"] > 0.025 else "ok")),
        ("租售比", _pct(m["rent_ratio"]), f"房租 {_money(ctx['rent'])}/月",
         "bad" if m["rent_ratio"] > 0.15 else ("warn" if m["rent_ratio"] > 0.1 else "ok")),
        ("坪效", _money(m["psm"]), "元/㎡/月",
         "warn" if m["psm"] < 800 else "ok"),
    ], cols=4)

    # ---- 行动清单 ----
    _sect("行动清单", "按优先级排序：P0 立即做 · P1 本周做 · P2 本月做 · P3 观察")
    total = sum(a["impact"] for a in dg["actions"])
    if total > 0:
        st.caption(f"全部动作做完，按当前测算月改善约 {_money(total)}"
                   f"（净利 {_money(m['net'])} → {_money(m['net'] + total)}）。这是粗估，不是承诺。")
    for a in dg["actions"]:
        c = {"P0": "#A8402F", "P1": BI_NAVY, "P2": _WARN, "P3": _OK}.get(a["priority"], MUTED)
        imp_txt = (("月改善 " + _money(a["impact"])) if a["impact"] > 0
                   else ("一次性释放现金" if a["code"] == "B8" else "无直接金额测算"))
        head = (
            f"<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap'>"
            f"<span style='background:{c};color:#fff;font-size:10.5px;font-weight:700;"
            f"letter-spacing:.06em;padding:2px 7px;border-radius:4px'>{a['priority']}</span>"
            f"<span style='font-size:14px;font-weight:600;color:{TEXT}'>{_html.escape(a['title'])}</span>"
            f"<span style='margin-left:auto;font-size:12px;color:{MUTED}'>{imp_txt}</span></div>")
        st.html(
            f"<div style='background:#fff;border:1px solid #E8E2D8;border-left:3px solid {c};"
            f"border-radius:10px;padding:12px 14px;margin:8px 0 0'>{head}</div>")
        with st.expander("看判断依据 / 动作 / 验证指标", expanded=(a["priority"] == "P0")):
            st.markdown("**判断依据**")
            for b in a["basis"]:
                st.markdown(f"- {b}")
            st.markdown("**动作**")
            for b in a["actions"]:
                st.markdown(f"- {b}")
            st.markdown("**验证指标**")
            for b in a["verify"]:
                st.markdown(f"- {b}")

    # ---- 判断路径 ----
    left, right = st.columns([3, 2])
    with left:
        _sect("判断路径", "六道门槛，任意一道不过，后面的动作就换顺序")
        rows = []
        for p in dg["path"]:
            rows.append([
                _pill("通过" if p["pass"] else "未过", "ok" if p["pass"] else "bad"),
                _html.escape(p["q"]),
                _html.escape(p["val"]),
                f"<span style='color:{MUTED}'>{_html.escape(p['note'])}</span>",
            ])
        st.html(_table(["判定", "门槛", "当前值", "说明"], rows,
                           aligns=["left", "left", "left", "left"]))
    with right:
        _sect("不建议做的事", "这一栏比行动清单更能说明判断力")
        if dg["not_do"]:
            for n in dg["not_do"]:
                st.html(
                    f"<div style='background:#FBF8F2;border-left:3px solid {_BAD};"
                    f"border-radius:0 8px 8px 0;padding:10px 12px;margin-bottom:8px;font-size:12.5px'>"
                    f"<b>{_html.escape(n['t'])}</b>：{_html.escape(n['d'])}</div>")
        else:
            st.html(
                f"<div style='font-size:12.5px;color:{MUTED}'>当前没有明确的「不要做」事项，"
                "但任何动作都要先算增量线再执行。</div>")


# ---------------------------------------------------------------- 页签：盈利模型
def _tab_profit(m, fixed_items):
    _sect("五层减法", "销售额 → 商品成本 → 毛利 → 固定费用 → 经营利润 → 损耗 → 净利")
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "total", "relative", "total", "relative", "total"],
        x=["销售额", "商品成本", "毛利额", "固定费用", "经营利润", "损耗", "净利"],
        y=[m["sales"], -m["cogs"], 0, -m["fixed"], 0, -(m["loss"] + m["shrink"]), 0],
        text=[fmt(m["sales"]), "-" + fmt(m["cogs"]), fmt(m["gp"]), "-" + fmt(m["fixed"]),
              fmt(m["op_profit"]), "-" + fmt(m["loss"] + m["shrink"]), fmt(m["net"])],
        textposition="outside",
        connector=dict(line=dict(color="#C9C0B2", width=1)),
        increasing=dict(marker_color=_OK), decreasing=dict(marker_color=BAD),
        totals=dict(marker_color="#3F382D"),
    ))
    fig_base(fig, 360, "五层减法：钱在哪一层被决定")
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="ops_wf")

    c1, c2 = st.columns(2)
    with c1:
        _sect("保本点", "保本销售额 = 固定费用 ÷ 毛利率")
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(y=["日均"], x=[m["be_daily"]], orientation="h",
                              name="保本日均", marker_color="#E8C9BC",
                              hovertemplate="保本 %{x:,.0f} 元<extra></extra>"))
        fig2.add_trace(go.Bar(y=["日均"], x=[m["daily_sales"]], orientation="h",
                              name="实际日均", marker_color=BI_NAVY,
                              hovertemplate="实际 %{x:,.0f} 元<extra></extra>"))
        fig2.add_vline(x=m["be_daily"], line_dash="dash", line_color="#3F382D")
        fig_base(fig2, 190, None, legend=True)
        fig2.update_layout(barmode="overlay", bargap=0.45)
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False}, key="ops_be")
        gap = m["daily_sales"] - m["be_daily"]
        gap_orders = int(gap / m["aov"]) if m["aov"] else 0
        st.html(
            f"<div style='font-size:12.5px;color:{MUTED};line-height:1.8'>"
            f"保本销售额 <b>{_money(m['be_sales'])}</b>，保本日均 <b>{_money(m['be_daily'])}</b>；"
            f"实际日均 <b>{_money(m['daily_sales'])}</b>，每天还能少卖 "
            f"<b>{_money(gap)}</b>（约 {gap_orders} 单）才碰到保本线。</div>")
    with c2:
        _sect("固定费用结构", "不随销售额变化的钱，按每月口径")
        rows = [[_FIXED_LABEL[k], _money(v), _pct(v / m["sales_month"] if m["sales_month"] else 0),
                 _pct(v / m["fixed_month"] if m["fixed_month"] else 0)] for k, v in fixed_items]
        rows.append(["合计", _money(m["fixed_month"]), _pct(m["fixed_ratio"]), "100%"])
        st.html(_table(["项目", "金额/月", "占销售额", "占固定费用"], rows,
                           aligns=["left", "right", "right", "right"]))

    _sect("敏感性矩阵", "销售额与毛利率同时动，才知道安全垫有多薄")
    ds, gs = [-0.1, -0.05, 0, 0.05, 0.1], [-0.03, 0, 0.03]
    rows = []
    for d in ds:
        cells = []
        for g in gs:
            s = m["sales"] * (1 + d)
            np_ = s * (m["gm"] + g) - m["fixed"] - m["loss"] - m["shrink"]
            color = _BAD if np_ < 0 else TEXT
            cells.append(f"<span style='color:{color}'>{_money(np_)}</span>")
        rows.append([f"{d * 100:+.0f}%"] + cells)
    st.html(_table(["销售额变化", "毛利率 −3pt", "毛利率不变", "毛利率 +3pt"], rows,
                       aligns=["left", "right", "right", "right"]))
    st.caption(f"经营杠杆 DOL = {m['dol']:.2f}：销售额每降 1%，经营利润降约 {m['dol']:.2f}%。"
               "固定费用不跟着销售下降，这就是老板为 3% 下滑睡不着的真实原因。")


# ---------------------------------------------------------------- 页签：效率指标
def _tab_eff(m, extra):
    _sect("效率指标一览", "同一组数，换个口径就是另一个结论——口径写在最后一列")
    if not m["inv_known"]:
        st.html(
            f"<div class='insight' style='border-left-color:{_WARN}'>"
            "<b>周转类指标待填</b>：POS 明细里没有库存，所以「周转率 / 周转天数 / 年化次数」暂时不算。"
            "在页面顶部填「期末库存（成本价）」后，这几项会自动出现——"
            "宁可留空，也不用假设值算出一个看起来正常的数。</div>")

    def st_of(v, good, warn, low_is_good=True):
        if not np.isfinite(v):
            return _pill("未计算", "")
        ok = v <= good if low_is_good else v >= good
        mid = v <= warn if low_is_good else v >= warn
        return _pill("健康", "ok") if ok else (_pill("关注", "warn") if mid else _pill("预警", "bad"))

    unk = _pill("待填", "")
    rows = [
        ["商品周转率（本期）", f"{m['turnover']:.2f} 次" if m["inv_known"] else "—", "—",
         _pill("参考", "") if m["inv_known"] else unk, "销货成本 ÷ 平均库存成本"],
        ["周转天数", f"{m['turn_days']:.1f} 天" if m["inv_known"] else "—", "7–14 天",
         st_of(m["turn_days"], 14, 21) if m["inv_known"] else unk, "平均库存 ÷ 日均销货成本"],
        ["年化周转次数", f"{m['turn_annual']:.0f} 次" if m["inv_known"] else "—", "26–52 次",
         st_of(m["turn_annual"], 26, 17, False) if m["inv_known"] else unk, "365 ÷ 周转天数"],
        ["坪效", _money(m["psm"]), "1,000–2,000", st_of(m["psm"], 1000, 800, False), "销售额 ÷ 面积（折算月）"],
        ["人效", _money(m["labor_eff"]), "10,000–20,000", st_of(m["labor_eff"], 10000, 8000, False), "销售额 ÷ 人数（折算月）"],
        ["租售比", _pct(m["rent_ratio"]), "≤10%", st_of(m["rent_ratio"], 0.10, 0.15), "房租 ÷ 销售额（月口径）"],
        ["售罄率", _pct(m["sell_through"]) if m["inv_known"] else "—", "60%–85%",
         (_pill("预警", "bad") if (m["sell_through"] > 0.93 or m["sell_through"] < 0.5) else _pill("健康", "ok"))
         if m["inv_known"] else unk,
         "销量 ÷（销量 + 期末库存件数）"],
        ["缺货率", _pct(m["oos_rate"]), "≤5%", st_of(m["oos_rate"], 0.05, 0.08), "缺货 SKU ÷ 在售 SKU"],
        ["报损率", _pct(m["loss_rate"]), "≤1.5%", st_of(m["loss_rate"], 0.015, 0.03), "报损 ÷ 销售额"],
        ["损耗率", _pct(m["waste_rate"]), "≤2.5%", st_of(m["waste_rate"], 0.025, 0.035), "（报损+盘亏）÷ 销售额"],
        ["动销率", _pct(m["active_rate"]), "≥80%", st_of(m["active_rate"], 0.8, 0.7, False), "有销量 SKU ÷ 在售 SKU"],
    ]
    if extra.get("idle_share") is not None:
        rows.append(["长尾销售占比", _pct(extra["idle_share"]), "≤10%",
                     st_of(extra["idle_share"], 0.10, 0.20),
                     f"超 45 天无销售 SKU 的销售额 ÷ 总销售额（{extra['idle_n']} 个）"])
    st.html(_table(["指标", "当前值", "参考区间", "状态", "计算口径"], rows,
                       aligns=["left", "right", "right", "left", "left"]))
    st.caption("参考区间是社区便利业态经验值，用于判断方向，不是考核标准；换城市、换商圈要重设基准。")

    c1, c2 = st.columns(2)
    with c1:
        _sect("两个命门是乘法关系", "一年赚的钱 ≈ 投入资金 × 毛利率 × 周转次数")
        cap = st.number_input("投入库存资金（元）", min_value=0.0,
                              value=float(round(m["avg_inv"])) or 60000.0,
                              step=1000.0, key="ops_eff_cap")
        gmv = st.number_input("毛利率（%）", min_value=0.0, max_value=100.0,
                              value=float(round(m["gm"] * 100, 1)), step=0.5, key="ops_eff_gm")
        tn = st.number_input("年周转次数", min_value=0.0,
                             value=float(round(m["turn_annual"], 1)) or 12.0,
                             step=1.0, key="ops_eff_turn")
        ygp = cap * gmv / 100 * tn
        st.html(
            f"<div class='kpi'><div class='kpi-label'>年毛利 = 投入 × 毛利率 × 周转</div>"
            f"<div class='kpi-value' style='color:{BI_NAVY}'>{_money(ygp)}</div>"
            f"<div class='kpi-sub'>折算每月 {_money(ygp / 12)}</div></div>")
        st.caption("这就是为什么大卖场敢把毛利率压到十几个点：它靠周转把钱赚回来。")
    with c2:
        _sect("现金周期", "存货周转天数 + 应收 − 应付")
        ar = st.number_input("应收天数", min_value=0.0, value=0.0, step=1.0, key="ops_cc_ar",
                             help="现金销售填 0；团购/月结客户才填")
        ap = st.number_input("应付天数", min_value=0.0, value=15.0, step=1.0, key="ops_cc_ap")
        cc = m["turn_days"] + ar - ap
        tone = _OK if cc < 0 else (_BAD if cc > 30 else _WARN)
        st.html(
            f"<div class='kpi'><div class='kpi-label'>现金周期</div>"
            f"<div class='kpi-value' style='color:{tone}'>{cc:,.0f} 天</div>"
            f"<div class='kpi-sub'>{'先收钱后付货款，占用的是供应商的钱' if cc < 0 else '每卖一轮要先垫资，扩张会吃现金'}</div></div>")
        st.caption("一旦开始给企业客户账期（团购、月结），这个数会立刻变正。")


# ---------------------------------------------------------------- 商品结构
def _sku_frame(df, metric, qty_col, cost_col, date_col, key_col, cost_force):
    d = pd.DataFrame(index=df.index)
    d["_amt"] = pd.to_numeric(df[metric], errors="coerce").fillna(0)
    d["_qty"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0) if qty_col else 1.0
    line = AN.cost_line(df, cost_col, qty_col, cost_force) if cost_col else None
    d["_cost"] = line.fillna(0) if line is not None else 0.0
    d["_key"] = df[key_col].astype(str)
    g = d.groupby("_key").agg(销量=("_qty", "sum"), 销售额=("_amt", "sum"), 成本=("_cost", "sum"))
    g["毛利"] = g["销售额"] - g["成本"]
    g = g.sort_values("销售额", ascending=False)
    total = g["销售额"].sum() or 1
    g["占比"] = g["销售额"] / total
    g["累计占比"] = g["占比"].cumsum()
    g["ABC"] = np.where(g["累计占比"] <= 0.70, "A", np.where(g["累计占比"] <= 0.90, "B", "C"))
    if date_col:
        p = d.pivot_table(index=df[date_col], columns="_key", values="_qty", aggfunc="sum").fillna(0)
        mu = p.mean().replace(0, np.nan)
        cv = (p.std() / mu).fillna(1.2)
        g["CV"] = g.index.map(cv).astype(float)
    else:
        g["CV"] = 0.0
    g["XYZ"] = np.where(g["CV"] < 0.3, "X", np.where(g["CV"] < 0.7, "Y", "Z"))
    return g


def _tab_goods(df, metric, qty_col, cost_col, date_col, key_col, cost_force, m):
    g = _sku_frame(df, metric, qty_col, cost_col, date_col, key_col, cost_force)
    if g.empty:
        st.caption("没有可用的商品维度（需要商品名称或编码列）。")
        return

    c1, c2 = st.columns([3, 2])
    with c1:
        _sect("ABC 帕累托", "前 70% 为 A，70–90% 为 B，后 10% 为 C")
        top = g.head(30)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=list(top.index), y=list(top["销售额"]), name="销售额",
                             marker_color=[BI_BLUE if a == "A" else "#5F7A96" if a == "B" else "#C6BCAF"
                                           for a in top["ABC"]]))
        fig.add_trace(go.Scatter(x=list(top.index), y=list(top["累计占比"] * 100), name="累计占比",
                                 yaxis="y2", mode="lines+markers", line=dict(color="#3F382D", width=1.6)))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], dtick=25,
                                      showgrid=False, ticksuffix="%", tickfont=dict(color=MUTED, size=10)))
        fig_base(fig, 320, "销售额与累计占比", legend=True)
        fig.update_xaxes(showticklabels=False)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key="ops_pareto")
    with c2:
        _sect("ABC × XYZ", "贡献 × 波动，两个维度才够用")
        strat = {"AX": "固定量定期订", "AY": "按同期+趋势订", "AZ": "小批量高频",
                 "BX": "按周调量", "BY": "按周调量", "BZ": "缩到最小陈列",
                 "CX": "淘汰或并品", "CY": "缩排面、测位置", "CZ": "直接淘汰"}
        rows = []
        for a in "ABC":
            row = [f"<b>{a} 类</b>"]
            for x in "XYZ":
                sub = g[(g["ABC"] == a) & (g["XYZ"] == x)]
                row.append(f"<b>{len(sub)}</b><br><span style='color:{MUTED};font-size:11px'>"
                           f"{strat[a + x]}</span>")
            rows.append(row)
        st.html(_table(["", "X 稳定", "Y 季节", "Z 不规则"], rows))
        st.caption("格子里的数字是 SKU 个数；策略直接对应订货动作，不是好坏标签。")

    _sect("SKU 明细与处置建议", "按销售额降序；处置建议由规则生成，不替代现场判断")
    view = g.reset_index().rename(columns={"_key": "商品"})
    view["毛利率"] = np.where(view["销售额"] > 0, view["毛利"] / view["销售额"], 0)
    view["建议"] = [
        "淘汰" if (a == "C" and s < 0.004) else ("缩排面" if a == "C" else ("保供" if a == "A" else "维持"))
        for a, s in zip(view["ABC"], view["占比"])]
    show = view[["商品", "销量", "销售额", "占比", "毛利率", "ABC", "XYZ", "建议"]].head(40).copy()
    show["销量"] = show["销量"].map(lambda v: f"{v:,.0f}")
    show["销售额"] = show["销售额"].map(lambda v: f"{v:,.0f}")
    show["占比"] = show["占比"].map(lambda v: f"{v:.1%}")
    show["毛利率"] = show["毛利率"].map(lambda v: f"{v:.1%}")
    st.dataframe(show, width="stretch", hide_index=True, key="ops_sku_table")

    _sect("清退清单", "先砍「C 类 + 贡献极低」的 SKU：释放货架与资金，比打折清库更快")
    cand = view[(view["ABC"] == "C") & (view["占比"] < 0.004)].sort_values("销售额")
    if cand.empty:
        st.caption("当前没有明显该清的 SKU：C 类的销售占比与贡献都在合理范围。")
    else:
        est = m["close_inv"] * (cand["成本"].sum() / (g["成本"].sum() or 1))
        st.html(_table(
            ["商品", "销售额", "销售占比", "毛利率", "建议"],
            [[_html.escape(r["商品"]), _money(r["销售额"]), _pct(r["占比"]),
              _pct(r["毛利率"]), "清退"] for _, r in cand.head(12).iterrows()],
            aligns=["left", "right", "right", "right", "left"]))
        _cap = (f"这 {min(12, len(cand))} 个 SKU 合计销售占比 {_pct(cand.head(12)['占比'].sum())}，"
                f"按期末库存成本估算占用约 {_money(est)}（按销货成本占比分摊）。"
                if m["inv_known"] else
                f"这 {min(12, len(cand))} 个 SKU 合计销售占比 {_pct(cand.head(12)['占比'].sum())}；"
                "期末库存没填，暂时估不出释放多少资金。")
        st.caption(_cap)


# ---------------------------------------------------------------- 订货
def _tab_order(df, metric, qty_col, date_col, key_col):
    _sect("订货三件套", "订货点 = 日均销量 × 交货天数 + 安全库存")
    if not (date_col and qty_col and key_col):
        st.caption("需要「时间 + 数量 + 商品」三列才能做订货测算。")
        return

    g = (df.groupby(key_col)[qty_col].sum().sort_values(ascending=False))
    top = list(g.head(40).index)
    pick = st.selectbox("选一个商品", top, key="ops_ord_sku")
    dts = pd.to_datetime(df[date_col], errors="coerce")
    days = max(1, int((dts.max() - dts.min()).days) + 1)
    daily = float(g.loc[pick]) / days
    sub = df.assign(_d=dts)
    series = sub[sub[key_col].astype(str) == str(pick)].groupby("_d")[qty_col].sum()
    cv = float(series.std() / series.mean()) if len(series) > 1 and series.mean() else 0.4

    c1, c2, c3, c4 = st.columns(4)
    lead = c1.number_input("交货天数", min_value=0.5, value=1.0, step=0.5, key="ops_ord_lead")
    cv_in = c2.number_input("销量波动系数（CV）", min_value=0.0, value=round(cv, 2),
                            step=0.05, key="ops_ord_cv")
    cover = c3.number_input("目标覆盖天数", min_value=0.5, value=7.0, step=0.5, key="ops_ord_cover")
    stock = c4.number_input("现有库存（件）", min_value=0.0, value=0.0, step=10.0, key="ops_ord_stock")
    o = RO.order_point(daily, lead, cv_in, cover, stock, 0)

    _kpi([
        ("日均销量", f"{daily:.1f} 件", f"{pick} · {days} 天平均", None),
        ("安全库存", f"{o['safety']:.1f} 件", f"日均 × CV × √{lead:g}", None),
        ("订货点", f"{o['rop']:.1f} 件", "库存降到这个数就下单", "warn"),
        ("建议订货量", f"{o['qty']:.0f} 件", f"目标 {o['target']:.0f} 件 − 现有 {stock:.0f}", "ok"),
    ], cols=4)

    _sect("补货建议（销售额前 12）", "订少了丢销售，订多了报废；两头都是损失")
    rows = []
    for k in g.head(12).index:
        d_ = float(g.loc[k]) / days
        oo = RO.order_point(d_, lead, cv_in, cover, 0, 0)
        rows.append([_html.escape(str(k)), f"{d_:.1f}", f"{d_ * lead:.0f}",
                     f"{oo['safety']:.1f}", f"{oo['rop']:.1f}", f"{oo['target']:.0f}"])
    st.html(_table(["商品", "日均", "交货期用量", "安全库存", "订货点", "目标库存"], rows,
                       aligns=["left", "right", "right", "right", "right", "right"]))
    st.caption("目标库存按你设的覆盖天数算；实际下单要扣掉现有库存和在途。")

    _sect("鲜食订货：用报废成本倒推（报童模型）", "最优服务水平 = 毛利 ÷（毛利 + 成本），数值上等于毛利率")
    a, b = st.columns(2)
    price = a.number_input("售价（元）", min_value=0.01, value=12.0, step=0.5, key="ops_nb_price")
    cost = b.number_input("成本（元）", min_value=0.0, value=7.0, step=0.5, key="ops_nb_cost")
    nb = RO.newsboy(price, cost)
    st.html(
        f"<div style='font-size:13px;line-height:1.9'>最优服务水平 <b>{_pct(nb['service'])}</b>："
        f"只订到「有 {_pct(nb['service'])} 的把握能卖完」的量，也就是低于中位需求。"
        f"毛利率越低越该订得保守——多订一个损失全部成本，少卖一个只损失一点毛利。</div>")


# ---------------------------------------------------------------- 促销
def _tab_promo(m):
    _sect("折扣模拟器", "改折扣与预计增量，结论实时变")
    c1, c2 = st.columns(2)
    d = c1.slider("折扣力度（%）", 0, 50, 10, 1, key="ops_pm_d",
                  help="10 = 九折；20 = 八折")
    up = c2.slider("预计销量提升（%）", 0, 100, 15, 1, key="ops_pm_u")
    sim = RO.promo_sim(m, d, up)

    tone = "bad" if sim["verdict"].startswith("不可行") else ("warn" if "有条件" in sim["verdict"] else "ok")
    tc = _TONE[tone]
    st.html(
        f"<div style='background:#fff;border:1px solid #E8E2D8;border-left:4px solid {tc};"
        f"border-radius:10px;padding:14px 16px;margin-bottom:10px'>"
        f"<div style='font-size:14px;font-weight:600;color:{tc}'>{_html.escape(sim['verdict'])}</div>"
        f"<div style='font-size:12.5px;color:{MUTED};margin-top:4px'>"
        f"折后毛利率 {_pct(sim['gm_new'])}；促销打平需增量 {_pct(sim['need_lift_promo'])}；"
        f"门店回到保本线需增量 {_pct(sim['need_lift_store'])}</div></div>")

    _kpi([
        ("折后毛利率", _pct(sim["gm_new"]), f"原 {_pct(m['gm'])}", "bad" if sim["gm_new"] < 0.25 else "warn"),
        ("促销打平需增量", _pct(sim["need_lift_promo"]), "销量涨不到这个数就是白做", None),
        ("预计增量毛利", _money(sim["inc_gp"]), f"投入 {_money(sim['spend'])}",
         "ok" if sim["inc_gp"] > 0 else "bad"),
        ("促销 ROI", f"{sim['roi']:.2f}" if sim["roi"] is not None else "—",
         "增量毛利 ÷ 让利投入", "ok" if (sim["roi"] or 0) >= 1 else "bad"),
    ], cols=4)

    _sect("促销方式对比", "同样的让利，打折方式不同，毛利差很多")
    rows = []
    for name, dd, note in [("全场 9 折", 0.10, "每一件都让利，毛利掉得最快"),
                           ("第二件半价", 0.25, "只对买两件的顾客让利，客单会升"),
                           ("满 50 减 10", 0.1818, "客单越高越接近理论折扣"),
                           ("买一赠一", 0.50, "相当于半价，除非清库否则不要做")]:
        s2 = RO.promo_sim(m, dd * 100, up)
        rows.append([name, _pct(dd), _pct(s2["gm_new"]),
                     _pct(s2["need_lift_promo"]) if np.isfinite(s2["need_lift_promo"]) else "—", note])
    st.html(_table(["方式", "实际折扣", "折后毛利率", "打平需增量", "说明"], rows,
                       aligns=["left", "right", "right", "right", "left"]))
    st.caption("折后毛利率用的是精确式（毛利率−折扣率）÷（1−折扣率），不是直接相减——"
               "45.7% 打八折是 32.1%，不是 25.7%，差 6 个点足以把「能做」判成「不能做」。")


# ---------------------------------------------------------------- 口径字典
def _tab_dict():
    rows = RO.ops_dict_rows()
    groups = {}
    for r in rows:
        groups.setdefault(r["分组"], []).append(r)
    for gname, items in groups.items():
        _sect(gname, f"{len(items)} 项")
        st.html(_table(
            ["指标", "层级", "公式 / 计算口径", "单位", "口径分歧 / 注意"],
            [[f"<b>{_html.escape(i['指标'])}</b>", i["层级"],
              f"<span style='font-family:Consolas,monospace;font-size:11.5px'>{_html.escape(i['公式'])}</span>",
              i["单位"], f"<span style='color:{MUTED}'>{_html.escape(i['口径说明'])}</span>"]
             for i in items],
            aligns=["left", "left", "left", "left", "left"]))


# ---------------------------------------------------------------- 主入口
def render(df, metric, date_col=None, cost_col=None, qty_col=None, order_col=None,
           name_col=None, sku_col=None, cat_col=None, cost_force="auto", lite=False):
    _sect("经营诊断", "输入整店流水与固定开销，自动判断该促销、该保本，还是该砍商品")

    if not metric:
        st.info("至少需要一列金额（销售额）才能做经营诊断。")
        return

    # 展示优先用商品名（重复名时上层已换成「名称 (编码)」）；没有名称列才退回编码
    key_col = name_col or sku_col
    defaults = _auto(df, metric, date_col, cost_col, qty_col, order_col, key_col, cost_force)

    # 数据换了就重置默认值；同一份数据保留用户的修改
    sig = f"{metric}|{cost_col}|{qty_col}|{date_col}|{len(df)}|{round(defaults['sales'], 2)}"
    if st.session_state.get("_ops_sig") != sig:
        st.session_state["_ops_sig"] = sig
        # 只重置「从明细算出来」的字段；固定开销、库存、面积、人数是用户手填的，
        # 换个主指标/日期不该把它们清掉（这是之前的一个坑）
        for k in _DATA_KEYS:
            st.session_state[f"ops_{k}"] = defaults[k]

    inp = _inputs(defaults)
    m = RO.compute(inp)

    ctx = {
        "sku_active": inp["sku_active"], "sku_sold": inp["sku_sold"], "rent": inp["rent"],
        "c_sku_count": 0, "c_sku_sales_share": 0.0,
        "idle_share": None, "idle_n": 0,
    }
    # 商品维度的补充信息（C 类占比、呆滞占比）若能算就带上，让结论更贴近实际
    if key_col:
        try:
            g = _sku_frame(df, metric, qty_col, cost_col, date_col, key_col, cost_force)
            c = g[g["ABC"] == "C"]
            ctx["c_sku_count"] = int(len(c))
            ctx["c_sku_sales_share"] = float(c["销售额"].sum() / (g["销售额"].sum() or 1))
            if date_col:
                dts = pd.to_datetime(df[date_col], errors="coerce")
                last_sale = df.assign(_d=dts).groupby(df[key_col].astype(str))["_d"].max()
                idle_days = (dts.max() - last_sale).dt.days
                idle_keys = set(idle_days[idle_days > 45].index)
                if idle_keys:
                    share = g.loc[g.index.intersection(idle_keys), "销售额"].sum() / (g["销售额"].sum() or 1)
                    ctx["idle_share"] = float(share)
                    ctx["idle_n"] = len(idle_keys)
        except Exception:
            pass

    dg = RO.diagnose(m, ctx)
    _render_diagnosis(m, dg, ctx)

    st.html("<div style='height:6px'></div>")
    t1, t2, t3, t4, t5, t6 = st.tabs(["盈利模型", "效率指标", "商品结构", "库存订货", "促销决策", "口径字典"])
    with t1:
        _tab_profit(m, [(k, inp[k]) for k in _FIXED_LABEL])
    with t2:
        _tab_eff(m, ctx)
    with t3:
        if key_col:
            _tab_goods(df, metric, qty_col, cost_col, date_col, key_col, cost_force, m)
        else:
            st.caption("需要商品名称或编码列才能做 ABC 结构与清退清单。")
    with t4:
        _tab_order(df, metric, qty_col, date_col, key_col)
    with t5:
        _tab_promo(m)
    with t6:
        _tab_dict()
