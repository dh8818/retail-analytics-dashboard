# -*- coding: utf-8 -*-
"""
演示大屏：给老板 / 客户看的全屏深色大屏。

这一版针对反馈重做：
- 字更大更亮（对比度拉满），标题带渐变色条；
- 可交互：时间粒度切换（日/周/月）、品类下钻（选哪个品类，趋势和 Top 都跟着切）、
  Top N 可调；
- 图更多：KPI（带环比箭头）、趋势、品类环形、Top N、星期规律热力、毛利 vs 金额对比。
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analytics as AN
from style import fmt

BG = "#1D1712"
CARD = "#2A211A"
CARD2 = "#3A2C20"
ACCENT = "#E08A5E"
ACCENT2 = "#E3B25A"
GOOD = "#8FC093"
BAD = "#E58A7E"
TXT = "#F6F1E8"
SUB = "#B4A591"
GRID = "#3E3228"


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _dark(fig, height=320, title=None):
    fig.update_layout(
        height=height, margin=dict(l=20, r=20, t=44 if title else 14, b=20),
        paper_bgcolor=CARD, plot_bgcolor=CARD,
        font=dict(family="Microsoft YaHei, sans-serif", size=13, color=TXT),
        title=dict(text=f"<b>{title}</b>", font=dict(size=16, color=TXT), x=0.012, y=0.97)
        if title else None,
        showlegend=False, hoverlabel=dict(bgcolor=CARD2, font_size=13, font_color=TXT),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID,
                     tickfont=dict(color=SUB, size=12))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=SUB, size=12))
    return fig


def _kpi(val, label, sub, color=ACCENT, arrow=None):
    a = f"<span style='font-size:16px;margin-left:8px'>{arrow}</span>" if arrow else ""
    return (f"<div style='background:linear-gradient(135deg,{CARD} 60%,{CARD2});"
            f"border:1px solid {GRID};border-top:3px solid {color};border-radius:12px;"
            f"padding:20px 18px'>"
            f"<div style='font-size:13px;color:{SUB};letter-spacing:2px'>{label}</div>"
            f"<div style='font-size:34px;font-weight:800;color:{TXT};margin:8px 0 4px'>{val}{a}</div>"
            f"<div style='font-size:12px;color:{SUB}'>{sub}</div></div>")


def render(df, metric, date_col=None, big_col=None, qty_col=None, cost_col=None,
           order_col=None, cost_force="auto"):
    if metric not in df.columns:
        st.warning("没有可展示的指标。")
        return

    # ---------- 交互控制（大屏也要能点） ----------
    ctl = st.columns([2, 2, 2])
    with ctl[0]:
        gran = st.radio("时间粒度", ["月", "周", "日"], horizontal=True, key="db_gran")
    with ctl[1]:
        drill = "（全部）"
        if big_col and big_col in df.columns:
            drill = st.selectbox("品类下钻", ["（全部）"] + sorted(
                df[big_col].dropna().astype(str).unique().tolist()), key="db_drill")
    with ctl[2]:
        top_n = st.slider("Top N", 5, 20, 10, key="db_topn")

    d = df.copy()
    if drill != "（全部）" and big_col:
        d = d[d[big_col].astype(str) == drill]

    # ---------- 头部 ----------
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:16px'>"
        f"<div style='font-size:32px;font-weight:800;background:linear-gradient(90deg,{ACCENT},{GOOD});"
        f"-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px'>门店经营驾驶舱</div>"
        f"<div style='font-size:14px;color:{SUB}'>{len(d):,} 行"
        + (f" ｜ {d[date_col].min():%Y-%m-%d} ~ {d[date_col].max():%Y-%m-%d}" if date_col and date_col in d.columns else "")
        + (f" ｜ {drill}" if drill != "（全部）" else "") + "</div></div>"
        f"<div style='height:3px;background:linear-gradient(90deg,{ACCENT},{GOOD},transparent);"
        f"border-radius:2px;margin:6px 0 18px'></div>", unsafe_allow_html=True)

    rev = float(_num(d[metric]).sum())
    profit = margin = None
    if cost_col and cost_col in d.columns:
        line = AN.cost_line(d, cost_col, qty_col, cost_force)
        if line is not None:
            cost = float(line.sum())
            profit = rev - cost
            margin = profit / rev * 100 if rev else None
    orders = int(d[order_col].nunique()) if order_col and order_col in d.columns else len(d)
    aov = rev / orders if orders else None

    # 环比（上一期 vs 本期，按所选粒度）
    arrow_rev, note_rev = None, ""
    if date_col and date_col in d.columns:
        dd = d.dropna(subset=[date_col])
        freq = {"月": "M", "周": "W", "日": "D"}[gran]
        gser = dd.groupby(dd[date_col].dt.to_period(freq))[metric].sum().sort_index()
        if len(gser) >= 2 and gser.iloc[-2] > 0:
            chg = (gser.iloc[-1] / gser.iloc[-2] - 1) * 100
            arrow_rev = "🔺" if chg >= 0 else "🔻"
            note_rev = f"最新一期环比 {chg:+.1f}%"

    # ---------- KPI ----------
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_kpi(fmt(rev), "销售收入", note_rev or f"{orders:,} 单",
                         ACCENT, arrow_rev), unsafe_allow_html=True)
    with c2:
        st.markdown(_kpi(fmt(profit) if profit is not None else "—", "毛利",
                         f"毛利率 {margin:.1f}%" if margin is not None else "缺成本列",
                         GOOD if (margin or 0) >= 20 else BAD), unsafe_allow_html=True)
    with c3:
        st.markdown(_kpi(fmt(aov) if aov else "—", "客单价",
                         f"{orders:,} 单", ACCENT2), unsafe_allow_html=True)
    with c4:
        qty = float(_num(d[qty_col]).sum()) if qty_col and qty_col in d.columns else float(len(d))
        st.markdown(_kpi(f"{qty:,.0f}", "销售数量", "件", GOOD), unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ---------- 趋势（按所选粒度） ----------
    if date_col and date_col in d.columns:
        dd = d.dropna(subset=[date_col])
        freq = {"月": "M", "周": "W", "日": "D"}[gran]
        g = dd.groupby(dd[date_col].dt.to_period(freq))[metric].sum().sort_index()
        if len(g) >= 2:
            x = [str(i) for i in g.index]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x, y=list(g.values), mode="lines",
                                     line=dict(color=ACCENT, width=3),
                                     fill="tozeroy", fillcolor="rgba(224,138,94,0.14)",
                                     hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=x, y=list(g.values), mode="markers",
                                     marker=dict(size=7, color=ACCENT,
                                                 line=dict(color=TXT, width=1))))
            _dark(fig, 340, f"{gran}度销售趋势")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ---------- 品类环形 + 星期规律 ----------
    left, right = st.columns([2, 3])
    with left:
        if big_col and big_col in d.columns:
            g = d.groupby(big_col)[metric].sum().sort_values(ascending=False)
            g = g[g > 0]
            if len(g):
                fig = go.Figure(go.Pie(
                    labels=[str(i) for i in g.index], values=list(g.values), hole=0.6,
                    marker=dict(colors=[ACCENT, GOOD, ACCENT2, "#A98F9F", "#E58A7E",
                                        "#C9A86A", "#7A8FA8", "#7FB0A0"],
                                line=dict(color=CARD, width=2)),
                    textinfo="label+percent", textfont=dict(size=13, color=TXT),
                    hovertemplate="%{label}<br>%{value:,.0f}（%{percent}）<extra></extra>"))
                fig.add_annotation(text=f"<b>{fmt(g.sum())}</b><br><span style='font-size:12px;color:{SUB}'>"
                                        f"{len(g)} 类</span>",
                                   showarrow=False, font=dict(size=18, color=TXT))
                _dark(fig, 340, "品类结构")
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right:
        if date_col and date_col in d.columns and big_col and big_col in d.columns:
            dd = d.dropna(subset=[date_col, big_col]).copy()
            dd["_wk"] = dd[date_col].dt.dayofweek
            wkmap = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            pv = dd.pivot_table(index="_wk", columns=big_col, values=metric, aggfunc="sum").fillna(0)
            top_cols = dd.groupby(big_col)[metric].sum().nlargest(5).index
            pv = pv[[c for c in top_cols if c in pv.columns]]
            if len(pv) >= 2 and pv.shape[1] >= 1:
                fig = go.Figure(go.Heatmap(
                    z=pv.values, x=[str(c)[:8] for c in pv.columns],
                    y=[wkmap[i] for i in pv.index],
                    colorscale=[[0, "#2A211A"], [0.5, "#8A4E33"], [1, ACCENT]],
                    hovertemplate="%{y} · %{x}<br>%{z:,.0f}<extra></extra>",
                    colorbar=dict(tickfont=dict(color=SUB, size=11), thickness=10)))
                _dark(fig, 340, "星期 × 品类热力（哪天什么品类发力）")
                fig.update_yaxes(autorange="reversed")
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ---------- Top N + 毛利结构 ----------
    bl, br = st.columns([3, 2])
    with bl:
        item_col = None
        for cand in ("产品名称", "商品名称", "名称", "品名"):
            if cand in d.columns:
                item_col = cand
                break
        use_col = item_col or big_col
        if use_col and use_col in d.columns:
            g = d.groupby(use_col)[metric].sum().sort_values(ascending=False).head(top_n)
            fig = go.Figure(go.Bar(
                x=list(g.values), y=[str(i)[:16] for i in g.index], orientation="h",
                marker=dict(color=g.values, colorscale=[[0, "#8A4E33"], [1, ACCENT2]],
                            line=dict(width=0)),
                text=[fmt(v) for v in g.values], textposition="outside",
                textfont=dict(size=12, color=TXT),
                hovertemplate="%{y}<br>%{x:,.0f}<extra></extra>"))
            _dark(fig, 380, f"{use_col} Top {top_n}")
            fig.update_xaxes(rangemode="tozero")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with br:
        if cost_col and cost_col in d.columns and big_col and big_col in d.columns:
            line = AN.cost_line(d, cost_col, qty_col, cost_force)
            if line is not None:
                t = d.assign(_c=line).groupby(big_col).agg(rev=(metric, "sum"), cost=("_c", "sum"))
                t = t[t["rev"] > 0].nlargest(8, "rev")
                t["毛利率"] = ((t["rev"] - t["cost"]) / t["rev"] * 100).round(1)
                t = t.sort_values("毛利率")
                fig = go.Figure(go.Bar(
                    x=list(t["毛利率"]), y=[str(i)[:10] for i in t.index], orientation="h",
                    marker_color=[GOOD if v >= 20 else ACCENT2 if v >= 0 else BAD for v in t["毛利率"]],
                    text=[f"{v:.1f}%" for v in t["毛利率"]], textposition="outside",
                    textfont=dict(size=12, color=TXT)))
                _dark(fig, 380, "各品类毛利率（%）")
                fig.update_xaxes(rangemode="tozero")
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.markdown(f"<div style='color:{SUB};font-size:12px;margin-top:14px'>"
                f"本页为演示大屏（深色）。上面的筛选（粒度/品类/TopN）都会实时联动所有图表；"
                f"日常分析请用「老板视角」或「专业分析」。</div>",
                unsafe_allow_html=True)
