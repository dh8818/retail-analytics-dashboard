# -*- coding: utf-8 -*-
"""
新增分析板块（订单级 / 购物篮 / 毛利结构 / RFM / 目标达成 / 两期对比 / 预测与异常）
由 app.py 调用，图表风格与主看板一致。
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import timedelta

import analytics as AN

from style import (BI_BLUE, BI_NAVY, PALETTE, MUTED, GRID, fmt, fig_base)


def kpi_row(items, cols=6):
    cs = st.columns(min(cols, max(len(items), 1)))
    for i, (lab, val, sub) in enumerate(items[:cols]):
        with cs[i]:
            st.markdown(f"<div class='kpi'><div class='kpi-label'>{lab}</div>"
                        f"<div class='kpi-value'>{val}</div><div class='kpi-sub'>{sub}</div></div>",
                        unsafe_allow_html=True)


# ---------------- 订单级 ----------------
def section_orders(df, oc, metric, qty_col, dc, card, key_mode="auto", tie="qty", include_refunds=False):
    orders, m = AN.order_metrics(df, oc, metric, qty_col, dc, key_mode, tie, include_refunds)
    if orders is None:
        return
    st.markdown("<div class='sect'>订单视角<small>客单价、连带率——零售最常被问的三个数</small></div>",
                unsafe_allow_html=True)
    kpi_row([("订单数", f"{m['订单数']:,}", "单号去重"),
             ("客单价", fmt(m["客单价"]), "金额 ÷ 订单数"),
             ("连带率", f"{m['连带率']:.2f}", "件数 ÷ 订单数"),
             ("件单价", fmt(m["件单价"]), "金额 ÷ 件数"),
             ("客单价中位数", fmt(m["客单价中位数"]), "抗极值"),
             ("最高单笔", fmt(m["最高单笔"]), "异常大单")])
    if m.get("复合键"):
        st.caption("⚠ 检测到订单号在多期数据里被复用，已按「单号 + 日期」作为订单键")

    c1, c2 = st.columns(2)
    with c1:
        s = orders["金额"]
        s = s[s < s.quantile(0.99)]
        f = go.Figure(go.Histogram(x=s, nbinsx=30, marker=dict(color=BI_BLUE)))
        fig_base(f, 300, "客单价分布（看主力价位和长尾）")
        card(f, "o_hist")
    with c2:
        bands = pd.cut(orders["金额"], [0, 5, 10, 15, 20, 30, 50, 1e9],
                       labels=["5元以下", "5-10", "10-15", "15-20", "20-30", "30-50", "50以上"])
        share = bands.value_counts(normalize=True).sort_index() * 100
        f = go.Figure(go.Bar(x=list(share.index.astype(str)), y=list(share.values),
                             marker_color=BI_BLUE, text=[f"{v:.0f}%" for v in share.values],
                             textposition="outside", textfont=dict(size=10, color=MUTED)))
        fig_base(f, 300, "客单价区间占比")
        f.update_yaxes(range=[0, float(share.max()) * 1.25])
        card(f, "o_band")

    if dc and "日期" in orders.columns:
        daily = orders.groupby(orders["日期"].dt.normalize()).size()
        f = go.Figure(go.Scatter(x=list(daily.index), y=list(daily.values), mode="lines",
                                 line=dict(color=BI_NAVY, width=2),
                                 fill="tozeroy", fillcolor="rgba(18,35,158,0.08)"))
        fig_base(f, 280, "每日订单数")
        card(f, "o_daily")


# ---------------- 购物篮 ----------------
def section_basket(df, oc, item_col, card):
    rules = AN.basket_rules(df, oc, item_col)
    if rules is None or rules.empty:
        return
    st.markdown("<div class='sect'>购物篮<small>谁跟谁一起买——做套餐和陈列的依据</small></div>",
                unsafe_allow_html=True)
    top = rules.head(10).iloc[::-1]
    f = go.Figure(go.Bar(x=list(top["提升度"]), y=[f"{a} + {b}"[:24] for a, b in zip(top["商品A"], top["商品B"])],
                         orientation="h", marker_color=BI_BLUE,
                         text=[f"{v:.1f}×" for v in top["提升度"]], textposition="outside",
                         textfont=dict(size=10, color=MUTED)))
    fig_base(f, 380, "关联强度 Top 10（提升度 > 1 表示经常一起买）")
    f.update_xaxes(range=[0, float(top["提升度"].max()) * 1.3], showgrid=True, gridcolor=GRID)
    c1, c2 = st.columns([3, 2])
    with c1:
        card(f, "basket_bar")
    with c2:
        st.markdown("<div class='sect' style='font-size:13px;margin:0 0 6px'>怎么读这张表</div>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div class='insight'><b>提升度</b>：买 A 的人买 B 的概率 ÷ B 本身的购买率。"
            "1.0 表示没关系，3.0 表示买 A 的人买 B 的概率是普通人的 3 倍。</div>"
            "<div class='insight'><b>置信度</b>：买了 A 之后再买 B 的比例，用来估套餐的命中率。</div>",
            unsafe_allow_html=True)
        st.dataframe(rules.head(10), width="stretch", hide_index=True)


# ---------------- 毛利结构 ----------------
def section_margin(df, big, metric, cost_col, card, qty_col=None, force="auto"):
    ms = AN.margin_structure(df, big, metric, cost_col, qty_col, force)
    if ms is None or len(ms) < 2:
        return
    st.markdown("<div class='sect'>毛利结构<small>钱从哪来 ≠ 利润从哪来</small></div>",
                unsafe_allow_html=True)
    d = ms.sort_values("占比差")
    f = go.Figure()
    f.add_trace(go.Bar(x=list(d["金额占比%"]), y=[str(i)[:12] for i in d.index], orientation="h",
                       name="金额占比", marker_color="#C8C6C4"))
    f.add_trace(go.Bar(x=list(d["毛利占比%"]), y=[str(i)[:12] for i in d.index], orientation="h",
                       name="毛利占比", marker_color=BI_BLUE))
    fig_base(f, 340, "金额占比 vs 毛利占比（蓝条比灰条长的，才是真正赚钱的）", legend=True)
    f.update_layout(barmode="group")
    c1, c2 = st.columns([2, 3])
    with c1:
        card(f, "margin_bar")
    with c2:
        show = ms[["金额占比%", "毛利占比%", "毛利率%", "占比差"]].copy()
        show.index = [str(i)[:12] for i in show.index]
        st.dataframe(show, width="stretch")
        top = ms["占比差"].idxmax()
        st.markdown(f"<div class='insight'>「{top}」的毛利占比比金额占比高 "
                    f"{ms.loc[top,'占比差']:.1f} 个百分点——同样的销售规模，它带来的利润更多，"
                    f"值得给它更好的货架位置。</div>", unsafe_allow_html=True)


# ---------------- 客户分层 ----------------
def section_rfm(df, cust_col, dc, metric, card):
    rfm = AN.rfm_table(df, cust_col, dc, metric)
    if rfm is None:
        return
    summ = AN.rfm_summary(rfm)
    st.markdown("<div class='sect'>客户分层（RFM）<small>最近买没买 / 买了几次 / 花了多少</small></div>",
                unsafe_allow_html=True)
    c1, c2 = st.columns([3, 2])
    with c1:
        st.dataframe(summ, width="stretch", hide_index=True)
    with c2:
        f = go.Figure(go.Pie(labels=list(summ["分层"]), values=list(summ["金额"]),
                             hole=0.6, marker=dict(colors=PALETTE, line=dict(color="white", width=2)),
                             textinfo="percent", textfont=dict(size=11)))
        f.add_annotation(text=f"{len(rfm):,}<br><span style='font-size:10px;color:{MUTED}'>客户数</span>",
                         showarrow=False, font=dict(size=15))
        fig_base(f, 300, "各分层贡献的金额")
        card(f, "rfm_pie")
    worst = summ.iloc[0]
    st.markdown(f"<div class='insight'>占用金额最多的是「{worst['分层']}」："
                f"{int(worst['人数']):,} 人（{worst['人数占比%']:.0f}%），贡献 {worst['金额占比%']:.0f}% 的金额。"
                f"流失预警的客户要优先召回——他们已经买过，召回成本比拉新低得多。</div>",
                unsafe_allow_html=True)


# ---------------- 目标达成 ----------------
def section_target(df, dc, metric, gran, target, card):
    if not target or target <= 0 or not dc:
        return
    d = df.dropna(subset=[dc]).copy()
    d[metric] = AN._num(d[metric])
    if gran == "年":
        key = d[dc].dt.year.astype(str)
    elif gran == "季度":
        key = d[dc].dt.year.astype(str) + "Q" + d[dc].dt.quarter.astype(str)
    elif gran == "月":
        key = d[dc].dt.strftime("%Y-%m")
    elif gran == "周":
        key = d[dc].dt.strftime("%Y-W%W")
    else:
        key = d[dc].dt.strftime("%Y-%m-%d")
    g = d.groupby(key)[metric].sum().sort_index()
    if g.empty:
        return
    last = d[dc].max()
    if gran == "月":
        elapsed = last.day / last.days_in_month
    elif gran == "季度":
        elapsed = (last - last.to_period("Q").start_time).days / 92
    elif gran == "年":
        elapsed = last.dayofyear / 365
    else:
        elapsed = 1.0
    elapsed = min(max(elapsed, 0.03), 1.0)
    tp = AN.target_progress(g, target, elapsed)
    if tp is None:
        return
    st.markdown("<div class='sect'>目标达成<small>跟预算比，不跟自己比</small></div>",
                unsafe_allow_html=True)
    rate = max(0.0, min(tp["rate"], 200))
    f = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(tp["rate"], 1),
        number={"suffix": "%", "font": {"size": 30}},
        gauge={"axis": {"range": [0, 200]},
               "bar": {"color": BI_BLUE if tp["rate"] >= 100 else "#E66C37", "thickness": 0.3},
               "steps": [{"range": [0, 60], "color": "#FDE7E9"},
                         {"range": [60, 100], "color": "#FFF4CE"},
                         {"range": [100, 200], "color": "#E7F4E4"}],
               "threshold": {"line": {"color": BI_NAVY, "width": 3}, "value": 100}}))
    fig_base(f, 280, f"本期 {gran}目标 {fmt(tp['target'])}，实际 {fmt(tp['actual_y'])}")
    c1, c2 = st.columns([2, 3])
    with c1:
        card(f, "target_gauge")
    with c2:
        need = max(tp["gap"], 0)
        st.markdown(
            f"<div class='insight'>已完成 {tp['rate']:.1f}%，"
            f"{'超出目标 ' + fmt(-tp['gap']) if tp['gap'] < 0 else '还差 ' + fmt(need)}。</div>"
            f"<div class='insight'>按当前速度推算，本期预计达成 <b>{tp['proj_rate']:.0f}%</b>"
            f"（约 {fmt(tp['run_rate'])}）。</div>", unsafe_allow_html=True)


# ---------------- 两期对比 ----------------
def section_compare(df, dc, metric, cat_cols, card):
    if not dc:
        return
    st.markdown("<div class='sect'>任意两期对比<small>不只看环比，可以挑任意两个时间段</small></div>",
                unsafe_allow_html=True)
    dts = df[dc].dropna()
    if dts.empty:
        return
    dmin, dmax = dts.min().date(), dts.max().date()
    span = max((dmax - dmin).days + 1, 2)
    win = min(30, max(span // 4, 7))
    cur_start = max(dmin, dmax - timedelta(days=win - 1))
    base_end = max(dmin, cur_start - timedelta(days=1))
    base_start = max(dmin, base_end - timedelta(days=win - 1))
    cur_def = (cur_start, dmax)
    base_def = (base_start, base_end)
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        cur = st.date_input("本期", value=cur_def, key="cmp_cur_v2")
    with c2:
        base = st.date_input("对比期", value=base_def, key="cmp_base_v2")
    with c3:
        dim = st.selectbox("拆解维度", ["（不拆）"] + cat_cols, key="cmp_dim_v2")
    dim = None if dim == "（不拆）" else dim
    if not (isinstance(cur, tuple) and len(cur) == 2 and isinstance(base, tuple) and len(base) == 2):
        return
    res = AN.compare_periods(df, dc, metric, cur, base, dim)
    if not res:
        st.warning("选的两段时间里没有数据。")
        return
    for line in res["lines"]:
        st.markdown(f"<div class='insight'>{line}</div>", unsafe_allow_html=True)
    if "delta_series" in res and len(res["delta_series"]) > 1:
        dl = res["delta_series"]
        top = pd.concat([dl.head(5), dl.tail(5)]).drop_duplicates()
        f = go.Figure(go.Bar(x=[str(i)[:12] for i in top.index], y=list(top.values),
                             marker_color=["#A4262C" if v < 0 else "#107C10" for v in top.values],
                             text=[fmt(v) for v in top.values], textposition="outside",
                             textfont=dict(size=10, color=MUTED)))
        fig_base(f, 340, f"{dim} 的变化（红＝下降，绿＝上升）")
        f.update_xaxes(tickangle=-35)
        card(f, "cmp_bar")
        with st.expander("查看对比明细"):
            st.dataframe(res["table"], width="stretch")


# ---------------- 预测与异常 ----------------
def section_forecast(df, dc, metric, gran, card):
    if not dc:
        return
    d = df.dropna(subset=[dc]).copy()
    d[metric] = AN._num(d[metric])
    key = d[dc].dt.normalize() if gran == "日" else d[dc].dt.to_period("M").astype(str)
    s = d.groupby(key)[metric].sum().sort_index()
    min_len = 14 if gran == "日" else (8 if gran == "月" else 6)
    if len(s) < min_len:
        return
    periods = 14 if gran == "日" else 3
    fc, fit = AN.forecast(s, periods=periods, window=7 if gran == "日" else 3)
    if fc is None:
        return
    st.markdown("<div class='sect'>预测与异常<small>未来走势 + 哪天不正常</small></div>",
                unsafe_allow_html=True)
    f = go.Figure()
    f.add_trace(go.Scatter(x=list(s.index), y=list(s.values), name="实际",
                           mode="lines", line=dict(color=BI_BLUE, width=1.4)))
    if fit is not None:
        f.add_trace(go.Scatter(x=list(fit.index), y=list(fit.values), name="趋势(移动平均)",
                               mode="lines", line=dict(color="#C8C6C4", width=1.6, dash="dot")))
    f.add_trace(go.Scatter(x=list(fc.index), y=list(fc["预测"]), name="预测",
                           mode="lines+markers", line=dict(color="#E66C37", width=2.4)))
    f.add_trace(go.Scatter(x=list(fc.index) + list(fc.index)[::-1],
                           y=list(fc["上界"]) + list(fc["下界"])[::-1],
                           fill="toself", fillcolor="rgba(230,108,55,0.15)",
                           line=dict(width=0), name="预测区间(95%)", hoverinfo="skip"))
    an = AN.detect_anomalies(s)
    if an is not None and an["异常"].any():
        pts = an[an["异常"]]
        f.add_trace(go.Scatter(x=list(pts.index), y=list(pts["值"]), name="异常点",
                               mode="markers", marker=dict(color="#A4262C", size=9,
                                                           symbol="x", line=dict(width=2))))
    fig_base(f, 380, f"{metric}：历史 + 未来 {periods} 个{gran}预测（阴影为 95% 区间）", legend=True)
    card(f, "forecast", 400)
    if an is not None:
        bad = an[an["异常"]]
        if len(bad):
            txt = "、".join(str(i) for i in list(bad.index)[:6])
            st.markdown(f"<div class='insight'>检测到 {len(bad)} 个异常点：{txt}。"
                        f"先排查当天是不是缺货、系统故障或大促，再决定要不要从趋势里剔除。</div>",
                        unsafe_allow_html=True)


# ---------------- 折扣与退货 ----------------
def section_discount(df, metric, qty_col, price_col, cat_col, card):
    if not (qty_col and price_col):
        return
    d = df.copy()
    q = AN._num(d[qty_col]); p = AN._num(d[price_col]); amt = AN._num(d[metric])
    exp = q * p
    valid = exp.notna() & amt.notna() & (exp.abs() > 0)
    diff = (exp - amt)
    disc_rows = valid & (diff.abs() > 0.02) & (diff > 0)
    if int(disc_rows.sum()) == 0:
        return
    d["_exp"] = exp.where(valid)
    d["_give"] = diff.where(disc_rows, 0.0)
    d["_is_disc"] = disc_rows

    st.markdown("<div class='sect'>折扣与退货<small>让了多少利、退了多少货</small></div>",
                unsafe_allow_html=True)
    total_amt = float(amt[amt > 0].sum())
    give = float(d["_give"].sum())
    st.markdown(
        f"<div class='insight'>有 <b>{int(disc_rows.sum()):,}</b> 行成交价低于 单价×数量"
        f"（占 {disc_rows.mean()*100:.1f}%），合计让利 <b>{fmt(give)}</b>，"
        f"相当于销售额的 {give/max(total_amt,1e-9)*100:.1f}%。"
        f"这些行就是表里的折扣记录——之前只当数据质量问题报，其实能直接算折扣深度。</div>",
        unsafe_allow_html=True)

    if cat_col:
        g = d[valid].groupby(cat_col).agg(销售额=(metric, "sum"), 让利=("_give", "sum"),
                                          折扣行=("_is_disc", "sum"), 行数=("_is_disc", "size"))
        g["折扣行占比%"] = (g["折扣行"] / g["行数"].replace(0, np.nan) * 100).round(1)
        g["让利率%"] = (g["让利"] / g["销售额"].replace(0, np.nan) * 100).round(1)
        g = g.sort_values("让利", ascending=False).head(10)
        f = go.Figure(go.Bar(x=list(g.index.astype(str)), y=list(g["让利率%"]),
                             marker_color="#E66C37",
                             text=[f"{v:.1f}%" for v in g["让利率%"]], textposition="outside",
                             textfont=dict(size=10, color=MUTED)))
        fig_base(f, 320, f"{cat_col} 的让利率（让利金额 ÷ 销售额）")
        f.update_yaxes(range=[0, float(g["让利率%"].max()) * 1.25])
        card(f, "disc_rate")
        with st.expander("折扣明细（按让利金额排序）"):
            st.dataframe(g[["销售额", "让利", "折扣行占比%", "让利率%"]].round(1), width="stretch")

    # 退货
    neg = amt < 0
    if neg.any():
        if cat_col:
            rg = d[neg].groupby(cat_col)[metric].sum().abs()
            sg = d[~neg].groupby(cat_col)[metric].sum()
            rate = (rg / sg.replace(0, np.nan) * 100).dropna().sort_values(ascending=False).head(10)
            if len(rate):
                f = go.Figure(go.Bar(x=list(rate.index.astype(str)), y=list(rate.values),
                                     marker_color="#A4262C",
                                     text=[f"{v:.1f}%" for v in rate.values], textposition="outside",
                                     textfont=dict(size=10, color=MUTED)))
                fig_base(f, 320, f"{cat_col} 的退货率（退货金额 ÷ 正向销售额）")
                f.update_yaxes(range=[0, float(rate.max()) * 1.25])
                card(f, "ret_rate")
