# -*- coding: utf-8 -*-
"""库存与订货界面：缺货风险、临期预警、报损、订货建议（含计算过程）。"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import inventory as INV
import perf
from style import BI_BLUE, BI_NAVY, MUTED, TEXT, fig_base, fmt

_BAD, _WARN, _OK = "#D64550", "#C55A11", "#548235"


def _sect(t, sub=""):
    st.markdown(f"<div class='sect'>{t}<small>{sub}</small></div>", unsafe_allow_html=True)


def _kpi(items):
    cols = st.columns(len(items))
    for c, (lab, val, sub) in zip(cols, items):
        c.markdown(f"<div class='kpi'><div class='kpi-label'>{lab}</div>"
                   f"<div class='kpi-value'>{val}</div><div class='kpi-sub'>{sub}</div></div>",
                   unsafe_allow_html=True)


def render(df, sku_col, date_col, qty_col, name_col, cat_col, cost_col):
    _sect("库存与订货", "缺货、临期、报损、该订多少——每个结论都能摊开算给你看")
    st.markdown(
        "<div class='insight' style='border-left-color:#C55A11'>"
        "<b>数据说明（请如实告知面试官）</b>：销量与金额来自你上传的真实销售明细；"
        "<b>期初库存、到货、在途、保质期、报损为策略仿真生成</b>（补货点 + 目标库存策略，FIFO 过期报损）。"
        "接入门店系统的库存快照后，这一页无需改代码即可换成真实数据。</div>",
        unsafe_allow_html=True)

    snap, meta = perf.get("inv_snap", lambda: INV.build_snapshot(
        df, sku_col, date_col, qty_col, name_col, cat_col, cost_col))
    if snap is None:
        st.warning("缺少商品编码或数量列，无法做库存分析。")
        return

    g = INV.sku_summary(snap)
    k = INV.health_kpis(g)
    _kpi([("SKU 数", f"{k['SKU 数']}", "在售商品"),
          ("缺货率", f"{k['缺货率%']}%", f"{k['缺货 SKU']} 个 SKU 出现过缺货"),
          ("平均周转", f"{k['平均周转天数']} 天", "期末库存 ÷ 日均销量"),
          ("报损率", f"{k['报损率%']}%", "报损 ÷ 销量"),
          ("待补货", f"{k['待补货 SKU']}", "按目标库存测算"),
          ("库存金额", fmt(k["库存金额"]), "期末库存 × 成本")])

    # ---------- 缺货风险 ----------
    _sect("缺货风险 Top 10", "按缺货天数排序：卖得动却没货，是最直接的销售损失")
    risk = g[g["缺货率%"] > 0].nlargest(10, "缺货率%")
    if risk.empty:
        st.caption("当前没有缺货记录。")
    else:
        show = risk[["商品名称", "品类", "日均销量", "期末库存", "在途", "缺货率%", "建议订货"]].copy()
        st.dataframe(show, width="stretch", hide_index=True)

    # ---------- 临期预警 ----------
    _sect("临期与报损", "保质期短的先动，报损是直接吃掉毛利的部分")
    fresh = g[g["保质期"] <= 15].copy()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div style='font-size:12.5px;color:{MUTED}'>保质期 ≤15 天的 SKU</div>",
                    unsafe_allow_html=True)
        if fresh.empty:
            st.caption("没有短保商品。")
        else:
            st.dataframe(fresh.nlargest(10, "报损率%")[
                ["商品名称", "保质期", "日均销量", "期末库存", "报损率%"]],
                width="stretch", hide_index=True)
    with c2:
        top = g.nlargest(8, "报损率%")[["商品名称", "报损率%"]].iloc[::-1]
        if not top.empty:
            f = go.Figure(go.Bar(x=list(top["报损率%"]), y=list(top["商品名称"]),
                                 orientation="h", marker_color=_WARN,
                                 text=[f"{v:.1f}%" for v in top["报损率%"]],
                                 textposition="outside"))
            fig_base(f, 300, "报损率最高 Top 8")
            st.plotly_chart(f, width="stretch", config={"displayModeBar": False})

    # ---------- 周转 ----------
    _sect("库存周转", "周转天数太长＝压钱，太短＝容易缺货")
    c1, c2 = st.columns([3, 2])
    with c1:
        turn = g["周转天数"].replace([float("inf"), float("-inf")], pd.NA).dropna()
        f = go.Figure(go.Histogram(x=turn, nbinsx=20, marker_color=BI_BLUE))
        fig_base(f, 300, "周转天数分布（中位数 "
                          f"{float(turn.median()) if len(turn) else 0:.1f} 天）")
        st.plotly_chart(f, width="stretch", config={"displayModeBar": False})
    with c2:
        slow = g.nlargest(6, "周转天数")[["商品名称", "周转天数", "库存金额"]]
        st.markdown(f"<div style='font-size:12.5px;color:{MUTED}'>周转最慢的 6 个</div>",
                    unsafe_allow_html=True)
        st.dataframe(slow, width="stretch", hide_index=True)

    # ---------- 订货建议 ----------
    _sect("订货建议", "目标库存 = 日均销量 × 覆盖天数 + 交期需求；建议订货 = 目标 − 库存位置")
    st.caption("库存位置 = 期末库存 + 在途；鲜食按保质期封顶，避免「订了卖不掉」。")
    plan = g[g["建议订货"] > 0].nlargest(15, "建议订货")
    if plan.empty:
        st.caption("当前所有 SKU 库存充足，无需补货。")
    else:
        st.dataframe(plan[["商品名称", "品类", "日均销量", "期末库存", "在途",
                           "库存位置", "交货周期", "建议订货"]],
                     width="stretch", hide_index=True)
        with st.expander("看某一只商品是怎么算出来的", expanded=False):
            pick = st.selectbox("选择商品", plan["商品名称"].tolist(), key="inv_pick")
            row = plan[plan["商品名称"] == pick].iloc[0]
            st.markdown(f"<div class='qbox'>{INV.reorder_explain(row)}</div>",
                        unsafe_allow_html=True)
            hist = snap[snap["商品编码"] == row["商品编码"]].tail(30)
            f = go.Figure()
            f.add_trace(go.Scatter(x=hist["日期"], y=hist["期末库存"], name="期末库存",
                                   line=dict(color=BI_NAVY, width=2)))
            f.add_trace(go.Scatter(x=hist["日期"], y=hist["在途"], name="在途",
                                   line=dict(color=BI_BLUE, width=2, dash="dot")))
            f.add_trace(go.Bar(x=hist["日期"], y=hist["销量"], name="日销量",
                               marker_color="#9DC3E6"))
            fig_base(f, 320, f"{pick} 最近 30 天：库存、在途与销量", legend=True)
            st.plotly_chart(f, width="stretch", config={"displayModeBar": False})

    st.download_button("下载库存快照 CSV", snap.to_csv(index=False).encode("utf-8-sig"),
                       file_name="库存快照_模拟.csv", mime="text/csv", key="inv_dl")
