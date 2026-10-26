# -*- coding: utf-8 -*-
"""统计与建模模块的界面：描述统计、显著性检验、回归、聚类、指标拆解、留存队列。"""
import numpy as np
import pandas as pd
import streamlit as st

import stats_models as SM
import explain as EX
from style import MUTED, TEXT, BI_NAVY, BI_BLUE, PALETTE, fmt


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _sect(title, sub=""):
    st.markdown(f"<div class='sect'>{title}<small>{sub}</small></div>", unsafe_allow_html=True)


def _fmt_p(p):
    if p is None or not np.isfinite(p):
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def render_stats(df, metric, qty_c, cost_c, dc, big, detail, cust_col, oc):
    # 排除程序内部注入的计算列（成本额_计算 / 订单键_计算），它们对用户是噪音
    num_cols = [c for c in df.columns
                if pd.api.types.is_numeric_dtype(df[c]) and not str(c).endswith("_计算")][:8]
    # 综合结论：各块算出结果后，往里追加一句话，最后在页面末尾统一渲染
    _summary = []

    st.markdown(
        "<div class='insight'><b>这一页是干什么的（一句话）</b><br>"
        "前面的页面回答「卖了多少、谁卖得好」；这一页回答两件事："
        "<b>为什么会这样</b>，以及<b>这个差别是真的、还是运气</b>。<br>"
        "举个例子：A 店比 B 店多卖 8%，可能是管理好，也可能只是那几天人多——"
        "这一页就是用数据把这两种可能分开。</div>", unsafe_allow_html=True)

    _cards = [
        ("描述统计", "先看清「正常」长什么样", "均值被几笔大单拉高时，中位数才不骗人"),
        ("差异检验", "两家店/两个方案的差别是真的吗", "p&lt;0.05 才算真差别，否则可能只是运气"),
        ("回归", "到底哪个因素在影响销量", "知道预算该花在哪个因素上，而不是全都撒一遍"),
        ("聚类", "不用你定标准，自动分组", "顾客/商品自动分成几类，每类怎么对待一目了然"),
    ]
    _cols = st.columns(4)
    for _i, (_t, _q, _a) in enumerate(_cards):
        with _cols[_i]:
            st.markdown(
                f"<div class='sumcard' style='min-height:118px'>"
                f"<div style='font-size:13.5px;font-weight:600;color:#B85532'>{_t}</div>"
                f"<div style='font-size:12.5px;color:#2A2723;margin:6px 0'>{_q}</div>"
                f"<div style='font-size:11.5px;color:#6E685E'>{_a}</div></div>",
                unsafe_allow_html=True)

    st.caption("什么时候这一页用不上：数据不足三个月、没有会员/订单级字段、样本太小（每组不到 30 条）。"
               "这时候模型给的是参考，不能当结论。")

    # ---------- 1. 描述统计 ----------
    _sect("描述统计", "均值 / 中位数 / 标准差 / 分位数 / 偏度，先看清分布再谈结论")
    if num_cols:
        desc = SM.describe(df, num_cols)
        show = desc.copy()
        for c in ["均值", "中位数", "标准差", "最小值", "P25", "P75", "最大值"]:
            show[c] = show[c].map(lambda v: f"{v:,.2f}" if pd.notna(v) else "—")
        show["变异系数"] = show["变异系数"].map(lambda v: f"{v*100:.1f}%" if pd.notna(v) else "—")
        show["偏度"] = show["偏度"].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
        st.dataframe(show, width="stretch", hide_index=True)
        sk = desc.set_index("指标")["偏度"].dropna()
        if len(sk):
            worst = sk.abs().idxmax()
            st.caption(f"分布最偏的是「{worst}」（偏度 {sk[worst]:.2f}）："
                       + ("右偏，少数大值在拉高均值 → 看中位数更稳" if sk[worst] > 0.5
                          else "左偏，少数小值在拖低均值" if sk[worst] < -0.5
                          else "接近对称，均值可用"))
            _summary.append(
                f"「{worst}」分布偏斜（偏度 {sk[worst]:.2f}），均值会被少数极端值带偏，"
                "判断「典型水平」应看中位数而不是平均。")

    # ---------- 2. 两组差异检验 ----------
    _sect("两组差异是否显著", "Welch t 检验：均值差是真实差异还是随机波动")
    sk_cols = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    sk_cols = [c for c in sk_cols if 1 < df[c].nunique() <= 30]
    if sk_cols and metric:
        c1, c2, c3 = st.columns(3)
        dim = c1.selectbox("分组维度", sk_cols, key="tt_dim")
        vals = df[dim].dropna().astype(str).value_counts().head(12).index.tolist()
        if len(vals) >= 2:
            a = c2.selectbox("A 组", vals, index=0, key="tt_a")
            b_val = c3.selectbox("B 组", vals, index=1, key="tt_b")
            col = st.selectbox("比较的指标", [c for c in num_cols if c != metric] or [metric], key="tt_col")
            ga = _num(df.loc[df[dim].astype(str) == a, col]).dropna()
            gb = _num(df.loc[df[dim].astype(str) == b_val, col]).dropna()
            res = SM.welch_ttest(ga, gb)
            if res:
                sig = res["p"] < 0.05
                st.markdown(
                    f"<div class='insight'><b>{a}</b> 均值 {fmt(res['mean_a'])}（n={res['n_a']:,}） vs "
                    f"<b>{b_val}</b> 均值 {fmt(res['mean_b'])}（n={res['n_b']:,}）<br>"
                    f"差值 {fmt(res['diff'])}，t={res['t']:.2f}，p={_fmt_p(res['p'])}，"
                    f"Cohen's d={res['cohens_d']:.2f} → "
                    + ("<b>差异显著</b>（p&lt;0.05，不太可能是抽样偶然）" if sig
                       else "<b>差异不显著</b>（p≥0.05，不能排除随机波动，别急着下结论）")
                    + "</div>", unsafe_allow_html=True)
                _summary.append(
                    f"「{a}」和「{b_val}」的{col}差异{'显著' if sig else '不显著'}（p={_fmt_p(res['p'])}，"
                    f"相差 {fmt(res['diff'])}）：{'说明这个差别是真的，值得追因' if sig else '还不足以排除随机波动，先别据此下结论'}。")

    # ---------- 3. 线性回归 ----------
    _sect("线性回归", "谁在影响结果、影响多大、模型解释了多少")
    if metric and len(num_cols) >= 2:
        xs_pool = [c for c in num_cols if c != metric]
        c1, c2 = st.columns([1, 2])
        y_col = c1.selectbox("因变量 Y", [metric] + [c for c in num_cols if c != metric], key="reg_y")
        xs = c2.multiselect("自变量 X（可多选）", [c for c in xs_pool if c != y_col],
                            default=[c for c in xs_pool if c != y_col][:2], key="reg_x")
        if xs:
            m = SM.ols(df, y_col, xs)
            if m:
                tb = m["table"].copy()
                tb["系数"] = tb["系数"].map(lambda v: f"{v:,.4f}")
                tb["标准误"] = tb["标准误"].map(lambda v: f"{v:,.4f}")
                tb["t 值"] = tb["t 值"].map(lambda v: f"{v:,.2f}")
                tb["p 值"] = tb["p 值"].map(_fmt_p)
                st.dataframe(tb, width="stretch", hide_index=True)
                st.markdown(
                    f"<div class='insight'>R² = <b>{m['r2']:.3f}</b>（模型解释了 {m['r2']*100:.1f}% 的波动），"
                    f"调整 R² = {m['adj_r2']:.3f}，F = {m['f']:.2f}（p={_fmt_p(m['f_p'])}），样本 {m['n']:,} 行。<br>"
                    f"{'模型整体显著，可以看系数方向；' if np.isfinite(m['f_p']) and m['f_p'] < 0.05 else '模型整体不显著，这些变量解释力不够；'}"
                    f"系数为正表示该变量越大 Y 越大。注意：这是相关关系，不是因果关系。</div>",
                    unsafe_allow_html=True)
                with st.expander("这说明了什么？（每个系数的人话解释）", expanded=True):
                    for line in EX.coef_sentences(m, y_col):
                        st.markdown(f"<div class='insight'>{line}</div>", unsafe_allow_html=True)
                    st.markdown("<div class='sect' style='margin-top:14px'>模型结论</div>",
                                unsafe_allow_html=True)
                    for line in EX.model_readout(m, y_col):
                        st.caption("· " + line)
                # 找影响最大的显著变量，写进综合结论
                _sig_vars = [(n, float(m["coef"][i + 1]))
                             for i, n in enumerate(m["xs"])
                             if i + 1 < len(m["table"]) and float(m["table"]["p 值"][i + 1]) < 0.05]
                if _sig_vars:
                    _top_n, _top_c = max(_sig_vars, key=lambda x: abs(x[1]))
                    _summary.append(
                        f"影响 {y_col} 最显著的是「{_top_n}」（系数 {_top_c:,.2f}，方向{'正' if _top_c > 0 else '负'}），"
                        f"模型整体解释力 {'强' if m['r2'] >= 0.7 else '中' if m['r2'] >= 0.4 else '弱'}（R²={m['r2']:.3f}）——"
                        "这是最值得先动的杠杆，但注意相关不等于因果。")
                else:
                    _summary.append(
                        f"对 {y_col} 的回归里没有任何自变量显著（R²={m['r2']:.3f}），"
                        "这份数据里还看不出稳定的影响因素，先别用这个模型做决策。")

    # ---------- 4. 聚类 ----------
    _sect("K-Means 聚类", "不预设分类，让数据自己分组（客户/商品/门店都适用）")
    if len(num_cols) >= 2:
        c1, c2, c3 = st.columns([2, 1, 1])
        feats = c1.multiselect("聚类用的数值列", num_cols,
                               default=[metric] + [qty_c] if qty_c and qty_c in num_cols and metric in num_cols
                               else num_cols[:2], key="km_feat")
        k = c2.slider("分几群", 2, 6, 3, key="km_k")
        by = c3.selectbox("按什么分组看结果", [c for c in [detail, big, cust_col] if c] or ["（不分组）"],
                          key="km_by")
        if len(feats) >= 2:
            sub = df.dropna(subset=feats)
            if len(sub) > 10:
                X = sub[feats].to_numpy(dtype=float)
                km = SM.kmeans(X, k=k, seed=0)
                lab = pd.Series(km["labels"], index=sub.index, name="群")
                tmp = sub.copy()
                tmp["群"] = lab
                if by != "（不分组）" and by in tmp.columns:
                    agg = tmp.groupby("群").agg(
                        数量=(by, "nunique"),
                        **{f"{f}均值": (f, "mean") for f in feats}).round(2)
                    agg["占比"] = (agg["数量"] / agg["数量"].sum() * 100).round(1).astype(str) + "%"
                    st.dataframe(agg.reset_index(), width="stretch", hide_index=True)
                else:
                    agg = tmp.groupby("群")[feats].mean().round(2)
                    agg["样本数"] = tmp.groupby("群").size()
                    st.dataframe(agg.reset_index(), width="stretch", hide_index=True)
                st.caption(f"组内平方和 {km['inertia']:,.1f}；同一份数据每次结果一致（固定随机种子），可复现。")
                if by == "（不分组）":
                    prof = EX.cluster_profiles(tmp, feats)
                else:
                    prof = EX.cluster_profiles(tmp, feats)
                st.markdown("<div class='sect' style='margin-top:12px'>每一群是什么"
                            "<small>相对整体均值看，偏高还是偏低</small></div>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(prof), width="stretch", hide_index=True)
                _summary.append(
                    f"数据自然分成 {km['k']} 群，差别最大的特征是「{feats[0]}」——"
                    "这 {0} 群意味着不同的经营对象需要区别对待，而不是一刀切。".format(km['k']))

    # ---------- 5. 指标拆解 ----------
    _sect("指标拆解", "收入为什么变？拆成「量」和「价」各自贡献了多少")
    if dc and metric and oc:
        try:
            dts = pd.to_datetime(df[dc], errors="coerce")
            per = dts.dt.to_period("M")
            months = sorted(per.dropna().unique())
            if len(months) >= 2:
                c1, c2 = st.columns(2)
                cur_m = c1.selectbox("本期", months[-1:], index=0, format_func=str, key="dec_cur")
                prev_m = c2.selectbox("对比期", months[-2:-1] + months[:-1][::-1][:5],
                                      index=0, format_func=str, key="dec_prev")
                cur = df[per == cur_m]
                prev = df[per == prev_m]
                orders_cur, orders_prev = cur[oc].nunique(), prev[oc].nunique()
                rev_cur, rev_prev = _num(cur[metric]).sum(), _num(prev[metric]).sum()
                if orders_cur and orders_prev and rev_prev:
                    aov_cur, aov_prev = rev_cur / orders_cur, rev_prev / orders_prev
                    d = SM.decompose(orders_prev, aov_prev, orders_cur, aov_cur, "订单数", "客单价")
                    st.markdown(
                        f"<div class='insight'>收入 {fmt(d['prev'])} → {fmt(d['cur'])}，"
                        f"变化 <b>{d['delta']:+,.0f}</b>（{d['delta']/d['prev']*100:+.1f}%）<br>"
                        f"· 订单数 {orders_prev:,} → {orders_cur:,}（{orders_cur-orders_prev:+,}），"
                        f"贡献 {d['eff_a']:+,.0f}（占 {d['share_a']*100:.0f}%）<br>"
                        f"· 客单价 {aov_prev:.2f} → {aov_cur:.2f}（{aov_cur-aov_prev:+.2f}），"
                        f"贡献 {d['eff_b']:+,.0f}（占 {d['share_b']*100:.0f}%）<br>"
                        f"· 两者交互 {d['interaction']:+,.0f}<br>"
                        f"→ {'主要由量带动' if abs(d['eff_a']) > abs(d['eff_b']) else '主要由价带动'}"
                        f"，三项相加严格等于总收入变化。</div>", unsafe_allow_html=True)
                    _summary.append(
                        f"{cur_m} 比 {prev_m} 的收入变化{'主要由订单量带动' if abs(d['eff_a']) > abs(d['eff_b']) else '主要由客单价带动'}——"
                        f"{'要增收得先把客流/订单做起来' if abs(d['eff_a']) > abs(d['eff_b']) else '靠提价或提高连带，而不是盲目冲量'}。")
        except Exception as e:
            st.caption(f"拆解暂不可用：{e}")

    # ---------- 6. 留存 / 复购 ----------
    if cust_col and dc:
        _sect("复购与留存", "同期人群在后续每个月还回来多少")
        c = SM.cohort(df, cust_col, dc)
        if c is not None and len(c["matrix"]):
            rate = c["rate"].copy()
            rate.index = [str(i) for i in rate.index]
            rate.columns = [f"第 {i} 月" for i in rate.columns]
            st.dataframe(rate.round(0), width="stretch")
            if rate.shape[1] >= 2:
                m1 = rate.iloc[:, 1].mean()
                st.caption(f"次月平均留存 {m1:.0f}%；留存曲线掉得快说明复购没做起来，"
                           f"比拉新更值得投入的是让老客回来。")
                _summary.append(
                    f"次月平均留存只有 {m1:.0f}%——客户来得快去得也快，"
                    "把资源从「拉新」转到「让老客回来」通常更划算。")

    # ============ 综合结论（把上面所有建模结果串成一句话） ============
    if _summary:
        st.markdown("<div class='sect' style='margin-top:20px'>综合结论"
                    "<small>把上面的建模结果串起来，回答「到底该做什么」</small></div>",
                    unsafe_allow_html=True)
        for _i, _s in enumerate(_summary, 1):
            st.markdown(
                f"<div class='sumcard' style='border-left:4px solid #B85532;margin-bottom:8px'>"
                f"<div style='font-size:13px;line-height:1.7'>{_i}. {_s}</div></div>",
                unsafe_allow_html=True)
        st.markdown(
            "<div class='insight' style='border-left-color:#6F8A63'>"
            "<b>一句话</b>：上面的结论都来自当前这份数据、当前选的模型参数；"
            "它们是「相关关系 + 显著性」的证据，不是因果，动手前先用对照实验或时间先后再验证一次。</div>",
            unsafe_allow_html=True)
    else:
        st.info("当前数据或选择还没跑出可用的建模结果（样本不足 / 缺少字段），"
                "所以没有综合结论。补足字段或换一份数据再试。")
