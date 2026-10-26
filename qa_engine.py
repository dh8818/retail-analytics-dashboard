# -*- coding: utf-8 -*-
"""
问答式归因 + 报告导出
问一句「上月华东销售额为什么下降」，自动找期间、找维度、做量价拆解、出瀑布图、导出报告。
不依赖任何大模型 API —— 规则解析 + 加性分解，离线可用、结果可复现。
"""
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.offline import get_plotlyjs

from style import (BI_BLUE, BI_NAVY, TEXT, MUTED, GRID,
                   FONT, fmt, fig_base, MODEBAR)

DIM_HINT = ("区域", "大区", "省", "城市", "地区", "门店", "渠道", "品类", "大类", "分类",
            "商品", "产品", "客户", "部门", "品牌", "region", "channel", "category", "store")
QTY_HINT = ("数量", "销量", "件数", "qty", "quantity", "num")


def to_num(s):
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(s.astype(str).str.replace(r"[¥$,\s]", "", regex=True), errors="coerce")


# ---------------- 解析问题 ----------------
PERIOD_RULES = [
    ("最近三个月", "3m"), ("近三个月", "3m"), ("最近3个月", "3m"), ("近3个月", "3m"),
    ("上个季度", "lq"), ("上季度", "lq"), ("本季度", "tq"), ("这个季度", "tq"), ("这季度", "tq"),
    ("上个月", "lm"), ("上月", "lm"), ("本月", "tm"), ("这个月", "tm"), ("这月", "tm"),
    ("去年", "ly"), ("上年", "ly"), ("今年", "ty"), ("本年", "ty"),
]


def parse_period(q, dmax):
    dmax = pd.Timestamp(dmax)
    for key, code in PERIOD_RULES:
        if key in q:
            return code
    return "lm"


def period_masks(df, dc, code, mode="环比"):
    """返回 (本期标签, 上期标签, 本期mask, 上期mask)。mode='同比' 时上期取去年同期。"""
    d = df[dc]
    m = d.dt.to_period("M")
    q = d.dt.to_period("Q")
    y = d.dt.year
    anchor_m = d.max().to_period("M")
    anchor_q = d.max().to_period("Q")
    anchor_y = int(d.max().year)
    yoy = (mode == "同比")

    if code == "lm":
        cur = anchor_m - 1
        prev = cur - 12 if yoy else cur - 1
        return str(cur), str(prev), (m == cur), (m == prev)
    if code == "tm":
        cur = anchor_m
        prev = cur - 12 if yoy else cur - 1
        return str(cur), str(prev), (m == cur), (m == prev)
    if code == "lq":
        cur = anchor_q - 1
        prev = cur - 4 if yoy else cur - 1
        return str(cur), str(prev), (q == cur), (q == prev)
    if code == "tq":
        cur = anchor_q
        prev = cur - 4 if yoy else cur - 1
        return str(cur), str(prev), (q == cur), (q == prev)
    if code == "ty":
        return f"{anchor_y}年", f"{anchor_y-1}年", (y == anchor_y), (y == anchor_y - 1)
    if code == "ly":
        return f"{anchor_y-1}年", f"{anchor_y-2}年", (y == anchor_y - 1), (y == anchor_y - 2)
    if code == "3m":
        months = sorted(m.dropna().unique())
        if len(months) >= 3:
            cur = months[-3:]
            prev = ([x - 12 for x in cur] if yoy else months[-6:-3]) if len(months) >= 6 else [x - 12 for x in cur]
            return (f"{cur[0]}~{cur[-1]}", f"{prev[0]}~{prev[-1]}",
                    m.isin(cur), m.isin(prev))
        cur = months[-1] if months else anchor_m
        return str(cur), str(cur - 1), (m == cur), (m == cur - 1)
    cur = anchor_m
    prev = cur - 12 if yoy else cur - 1
    return str(cur), str(prev), (m == cur), (m == prev)


def parse_filters(q, df, cat_cols):
    """问题里出现某个维度值就当作筛选条件，例如「华东」。"""
    hits = {}
    for c in cat_cols:
        vals = df[c].dropna().astype(str).unique()
        if len(vals) > 200:
            continue
        for v in vals:
            v = str(v).strip()
            if len(v) >= 2 and v in q:
                hits[c] = v
                break
    return hits


def parse_metric(q, num_cols, default):
    for c in num_cols:
        if str(c) in q:
            return c
    # 「销售额」「销量」这类口语映射
    alias = {"销售额": ("金额", "销售额", "营收", "收入"), "销量": ("数量", "销量"),
             "利润": ("利润", "毛利"), "客单价": ("单价", "价格")}
    for k, names in alias.items():
        if k in q:
            for c in num_cols:
                if any(n in str(c) for n in names):
                    return c
    return default


# ---------------- 归因 ----------------
def pick_dims(df, cat_cols, exclude):
    out = []
    for c in cat_cols:
        if c in exclude:
            continue
        n = df[c].nunique()
        if 2 <= n <= 80:
            score = 2 if any(h in str(c).lower() for h in DIM_HINT) else 1
            out.append((score, -abs(n - 12), c))
    return [c for _, _, c in sorted(out, reverse=True)]


def decompose(df, dc, metric, dim, cur_mask, prev_mask):
    cur = df[cur_mask].groupby(dim)[metric].sum()
    prev = df[prev_mask].groupby(dim)[metric].sum()
    idx = cur.index.union(prev.index)
    cur = cur.reindex(idx, fill_value=0.0)
    prev = prev.reindex(idx, fill_value=0.0)
    delta = cur - prev
    return cur, prev, delta.sort_values()


def waterfall(labels, values, total_label="合计变化", title=""):
    fig = go.Figure(go.Waterfall(
        x=labels + [total_label],
        measure=["relative"] * len(labels) + ["total"],
        y=list(values) + [sum(values)],
        text=[fmt(v) for v in values] + [fmt(sum(values))],
        textposition="outside",
        connector=dict(line=dict(color=GRID)),
        increasing=dict(marker=dict(color="#4F7A55")),
        decreasing=dict(marker=dict(color="#A84A42")),
        totals=dict(marker=dict(color=BI_NAVY))))
    fig_base(fig, 380, title)
    fig.update_layout(margin=dict(l=74, r=24, t=48, b=78))
    fig.update_xaxes(tickangle=-30)
    return fig


def compare_bar(cur, prev, dim, title=""):
    idx = cur.index.union(prev.index)
    cur = cur.reindex(idx, fill_value=0.0)
    prev = prev.reindex(idx, fill_value=0.0)
    order = (cur - prev).abs().sort_values(ascending=False).index[:10]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[str(i)[:12] for i in order], y=[prev[i] for i in order],
                         name="上期", marker_color="#C6BCAF"))
    fig.add_trace(go.Bar(x=[str(i)[:12] for i in order], y=[cur[i] for i in order],
                         name="本期", marker_color=BI_BLUE))
    fig.update_layout(barmode="group")
    fig_base(fig, 360, title, legend=True)
    fig.update_layout(margin=dict(l=74, r=24, t=48, b=78))
    fig.update_xaxes(tickangle=-30)
    return fig


def analyze(df, dc, metric, cat_cols, q, num_cols, mode="环比"):
    """返回 dict：文字结论、瀑布图、对比图、明细表"""
    d = df.copy()
    filters = parse_filters(q, d, cat_cols)
    for c, v in filters.items():
        d = d[d[c].astype(str).str.strip() == str(v)]
    met = parse_metric(q, num_cols, metric)
    code = parse_period(q, df[dc].max())
    cur_lab, prev_lab, cur_m, prev_m = period_masks(d, dc, code, mode)
    cur_m = cur_m.to_numpy() if hasattr(cur_m, "to_numpy") else cur_m
    prev_m = prev_m.to_numpy() if hasattr(prev_m, "to_numpy") else prev_m

    if not cur_m.any() or not prev_m.any():
        return {"ok": False, "msg": f"{cur_lab} 或 {prev_lab} 在筛选条件下没有数据，换个问法试试。"}

    d[met] = to_num(d[met])
    cur_total = float(d.loc[cur_m, met].sum())
    prev_total = float(d.loc[prev_m, met].sum())
    delta = cur_total - prev_total
    pct = delta / prev_total * 100 if prev_total else 0.0
    cond = "、".join(f"{k}={v}" for k, v in filters.items()) or "全部"
    head = (f"【{mode}】{cur_lab}（{cond}）{met} {fmt(cur_total)}，"
            f"比 {prev_lab} 的 {fmt(prev_total)} {'增长' if delta>=0 else '下降'} "
            f"{abs(pct):.1f}%（{'+' if delta>=0 else ''}{fmt(delta)}）。")

    dims = pick_dims(d, cat_cols, exclude=set(filters.keys()))
    lines, figs, tables = [head], [], []
    main_dim = None
    for dim in dims[:2]:
        cur, prev, delta_s = decompose(d, dc, met, dim, cur_m, prev_m)
        if abs(delta_s.sum()) < 1e-9:
            continue
        if main_dim is None:
            main_dim = (dim, cur, prev, delta_s)
        total_abs = delta_s.abs().sum()
        top = delta_s.head(3)
        bottom = delta_s.tail(2).iloc[::-1]
        parts = []
        for k, v in top.items():
            share = abs(v) / total_abs * 100
            parts.append(f"「{k}」{'+' if v>=0 else ''}{fmt(v)}（占变动 {share:.0f}%）")
        txt = f"按 {dim} 拆：" + "、".join(parts)
        ups = [f"「{k}」{fmt(v)}" for k, v in bottom.items() if v > 0]
        if ups:
            txt += "；唯一逆势的是 " + "、".join(ups)
        lines.append(txt + "。")

    # 量价拆解
    qty_c = next((c for c in num_cols if any(h in str(c).lower() for h in QTY_HINT)), None)
    if qty_c and met != qty_c:
        dq = to_num(d[qty_c])
        q1, q0 = float(dq[cur_m].sum()), float(dq[prev_m].sum())
        if q0 > 0 and q1 > 0:
            p1, p0 = cur_total / q1, prev_total / q0
            eff_q = (q1 - q0) * p0
            eff_p = q0 * (p1 - p0)
            lines.append(f"量价拆解：销量从 {q0:,.0f} 到 {q1:,.0f}，贡献 {fmt(eff_q)}；"
                         f"均价从 {p0:.2f} 到 {p1:.2f}，贡献 {fmt(eff_p)}。"
                         + ("主要靠降价换量。" if eff_p < 0 and eff_q > 0 else
                            "主要是量的变化，价格影响不大。" if abs(eff_p) < abs(eff_q) * 0.3 else
                            "价格因素是主要矛盾。"))

    # 新增 / 流失（用主维度）
    if main_dim:
        dim, cur, prev, delta_s = main_dim
        lost = [k for k in delta_s.index if prev.get(k, 0) > 0 and cur.get(k, 0) <= 0]
        new = [k for k in delta_s.index if prev.get(k, 0) <= 0 and cur.get(k, 0) > 0]
        if lost:
            lines.append(f"本期完全没卖的 {dim}：{'、'.join(str(x) for x in lost[:5])}"
                         + ("等" if len(lost) > 5 else "") + f"，共 {len(lost)} 个——先查是不是断货/下架。")
        if new:
            lines.append(f"本期新出现的 {dim}：{'、'.join(str(x) for x in new[:5])}"
                         + ("等" if len(new) > 5 else "") + f"，共 {len(new)} 个。")

        top = delta_s.head(6)
        other = delta_s.iloc[6:].sum()
        labels = [str(i)[:12] for i in top.index]
        vals = [float(v) for v in top.values]
        if abs(other) > 1e-9:
            labels.append("其他")
            vals.append(float(other))
        figs.append(waterfall(labels, vals, title=f"{dim} 对{met}变化的贡献（{prev_lab} → {cur_lab}）"))
        figs.append(compare_bar(cur, prev, dim, title=f"{dim}：{prev_lab} vs {cur_lab}"))
        tb = pd.DataFrame({"本期": cur, "上期": prev, "变化": cur - prev,
                           "变化率%": ((cur - prev) / prev.replace(0, np.nan) * 100).round(1)})
        tb = tb.sort_values("变化", key=lambda s: s.abs(), ascending=False).head(15)
        tables.append((f"{dim} 明细（按变化绝对值排序）", tb))

    return {"ok": True, "lines": lines, "figs": figs, "tables": tables,
            "cur_lab": cur_lab, "prev_lab": prev_lab, "metric": met,
            "q": q, "filters": filters, "mode": mode}


# ---------------- 报告导出 ----------------
def build_report(title, kpis, summaries, analysis, sheet, caliber=None):
    def tbl(df):
        cols = [str(c) for c in df.columns]
        head = "".join(f"<th>{c}</th>" for c in cols)
        rows = ""
        for idx, r in df.iterrows():
            cells = ""
            for c in df.columns:
                v = r[c]
                if isinstance(v, (int, float, np.floating)) and not pd.isna(v):
                    cells += f"<td class='num'>{v:,.1f}</td>" if isinstance(v, float) else f"<td class='num'>{v:,}</td>"
                else:
                    cells += f"<td>{'' if pd.isna(v) else v}</td>"
            rows += f"<tr><td>{idx}</td>{cells}</tr>"
        return f"<table><thead><tr><th></th>{head}</tr></thead><tbody>{rows}</tbody></table>"

    charts = ""
    if analysis.get("ok"):
        charts = "".join(
            f.to_html(full_html=False, include_plotlyjs=False, config=dict(displayModeBar=False))
            for f in analysis["figs"])
    kpi_html = "".join(
        f"<div class='kpi'><div class='kl'>{k[0]}</div><div class='kv'>{k[1]}</div>"
        f"<div class='ks'>{k[2]}</div></div>" for k in kpis)
    sum_html = "".join(
        f"<div class='sum'><b>{s['icon']} {s['title']}</b><p>{s['text']}</p></div>" for s in summaries)
    cal_html = ("<br>".join(f"· {c}" for c in caliber) if caliber else
                "未记录口径（生成报告时未传入）")
    ana_html = ""
    if analysis.get("ok"):
        ana_html = ("<h2>问题分析</h2><div class='q'>问：" + analysis["q"] + "</div>"
                    + "".join(f"<p class='line'>{l}</p>" for l in analysis["lines"]))
        for name, t in analysis.get("tables", []):
            ana_html += f"<h3>{name}</h3>" + tbl(t)

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title><script>{get_plotlyjs()}</script>
<style>
body{{margin:0;background:#F7F4EE;font-family:{FONT};color:{TEXT};}}
.wrap{{max-width:1120px;margin:0 auto;padding:26px 22px 60px;}}
h1{{font-size:22px;margin:0 0 4px;}} h2{{font-size:17px;margin:26px 0 10px;}}
h3{{font-size:14px;margin:18px 0 8px;color:{MUTED};}}
.meta{{color:{MUTED};font-size:12px;margin-bottom:16px;}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;}}
.kpi{{background:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 1.6px 3.6px rgba(0,0,0,.1);}}
.kl{{font-size:11.5px;color:{MUTED};}} .kv{{font-size:21px;font-weight:600;}}
.ks{{font-size:11px;color:{MUTED};margin-top:4px;}}
.sum{{background:#fff;border-left:3px solid {BI_BLUE};border-radius:6px;padding:10px 14px;
      margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
.sum b{{font-size:13.5px;}} .sum p{{margin:5px 0 0;font-size:13px;line-height:1.6;color:#4A443C;}}
.q{{background:#F6EBE3;border-radius:6px;padding:9px 13px;font-size:13.5px;margin-bottom:10px;}}
.line{{font-size:13.5px;line-height:1.75;margin:6px 0;}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;background:#fff;border-radius:6px;overflow:hidden;}}
th{{text-align:left;color:{MUTED};font-size:11.5px;padding:8px;border-bottom:1px solid {GRID};}}
td{{padding:7px 8px;border-bottom:1px solid #F0EBE3;}} td.num{{text-align:right;}}
.card{{background:#fff;border-radius:8px;padding:8px 10px;margin:10px 0;
       box-shadow:0 1.6px 3.6px rgba(0,0,0,.1);}}
.foot{{color:{MUTED};font-size:11px;text-align:center;margin-top:30px;}}
.cal{{background:#fff;border-radius:6px;padding:10px 14px;font-size:12.5px;line-height:1.8;color:#4A443C;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
</style></head><body><div class="wrap">
<h1>{title}</h1>
<div class="meta">数据表：{sheet} ｜ 生成时间：{datetime.now():%Y-%m-%d %H:%M}</div>
<h2>核心指标</h2><div class="kpis">{kpi_html}</div>
<h2>本报告口径</h2><div class="cal">{cal_html}</div>
<h2>业务总结</h2>{sum_html}
{ana_html}
<h2>图表</h2>{charts}
<div class="foot">本报告由本地分析工具生成，数据未上传任何服务器。</div>
</div></body></html>"""


# ---------------- Streamlit UI ----------------
def render(df, dc, metric, num_cols, cat_cols, big, detail, sheet, kpis, summaries, mode="环比", caliber=None):
    st.markdown("<div class='sect'>问一句，出结论<small>自动找期间、找维度、做量价拆解、出瀑布图</small></div>",
                unsafe_allow_html=True)
    if not dc:
        st.info("表里没有识别到时间列，无法做期间对比。")
        return
    examples = ["上月销售额为什么下降", "上月销量为什么下降", "本季度销售额为什么上升",
                "最近三个月销售额变化原因", "今年销售额比去年怎么样"]
    c1, c2 = st.columns([3, 2])
    with c1:
        q = st.text_input("用一句话问", value="", key="qa_q",
                          placeholder="比如：上月销售额为什么下降？")
    with c2:
        pick = st.selectbox("或者选一个现成的问题", ["（自己输入）"] + examples, key="qa_pick")
    if pick != "（自己输入）":
        q = pick
    if not q:
        st.caption("👆 输入问题或从右边选一个。会在当前数据范围内做归因，并生成可下载报告。")
        return

    res = analyze(df, dc, metric, cat_cols, q, num_cols, mode)
    if not res.get("ok"):
        st.warning(res["msg"])
        return

    st.markdown("<div class='qbox'>问：" + q + "</div>", unsafe_allow_html=True)
    for line in res["lines"]:
        st.markdown(f"<div class='insight'>{line}</div>", unsafe_allow_html=True)

    figs = res["figs"]
    if figs:
        cc = st.columns(2)
        for i, f in enumerate(figs[:2]):
            with cc[i % 2]:
                if st.button("⛶ 放大", key=f"qz{i}"):
                    st.session_state["_zoom"] = (go.Figure(f), f.layout.title.text or "")
                    st.rerun()
                st.plotly_chart(f, width="stretch", config=MODEBAR)
    for name, tb in res.get("tables", []):
        with st.expander(name):
            st.dataframe(tb, width="stretch")

    html = build_report(f"经营分析报告 · {sheet}", kpis, summaries, res, sheet, caliber)
    st.download_button("📄 导出完整报告（HTML，可直接打印成 PDF）", html.encode("utf-8"),
                       file_name=f"分析报告_{datetime.now():%Y%m%d_%H%M}.html",
                       mime="text/html", key="qa_dl")
