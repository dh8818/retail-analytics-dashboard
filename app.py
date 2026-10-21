# -*- coding: utf-8 -*-
"""
网页版智能分析 v2：上传 Excel/CSV → 自动识别表结构与表关系 → 多维度图表

图表选择依据 Financial Times Visual Vocabulary / Abela Chart Chooser：
  变化趋势 → 折线/柱      项目对比 → 排序条形
  构成占比 → 环形/矩形树图  构成随时间 → 堆叠柱
  分布     → 直方图/箱线   关系     → 散点/相关矩阵
  部分与整体 → 帕累托       地理     → 省域气泡图
  期间对比 → 仪表盘

启动：双击 网页版看板.bat
"""
import io
import os
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import qa_engine
import analytics as AN
import extra_sections as XS
import custom_metrics as CM
import metrics as MT
import advice as ADV
import sql_console as SQ
import nlq
import perf
import timefix
import privacy_ui as PV
import cleaning_ui as CU
import cleaning as CL
import advanced_ui as AU
try:
    import ppt_export as PE
except Exception:
    PE = None
from datetime import datetime

MT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metric_formulas.json")

from style import (BI_BLUE, BI_NAVY, PALETTE, CARD_BG, PAGE_BG, TEXT, MUTED, GRID,
                   FONT, fmt, fig_base, MODEBAR)

st.set_page_config(page_title="智能数据分析", layout="wide", page_icon="📊")

# 可选访问密码：设了环境变量 DASH_PASSWORD 才会启用
_DASH_PWD = os.environ.get("DASH_PASSWORD", "").strip()
if _DASH_PWD:
    _entered = st.text_input("访问密码", type="password", key="_dash_pwd")
    if _entered != _DASH_PWD:
        st.caption("需要密码才能查看数据。")
        st.stop()

_UI_TOKENS = {
    "PAGE_BG": PAGE_BG, "CARD_BG": CARD_BG, "TEXT": TEXT, "MUTED": MUTED,
    "GRID": GRID, "NAVY": BI_NAVY, "BLUE": BI_BLUE, "FONT": FONT,
}
try:
    _css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.css"),
                encoding="utf-8").read()
    for _k, _v in _UI_TOKENS.items():
        _css = _css.replace(f"__{_k}__", _v)
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)
except Exception:
    pass

# ============================================================
# 基础工具
# ============================================================
DATE_HINT = ("日期", "date", "时间", "月份", "年月", "day", "month")
ID_HINT = ("id", "编码", "代码", "编号", "货号", "条码", "单号", "序号", "code", "sku")
METRIC_PRIORITY = ["销售额", "金额", "营收", "收入", "成交额", "amount", "sales", "revenue",
                   "gmv", "total", "利润", "毛利", "profit", "数量", "销量", "qty",
                   "quantity", "件数", "单价", "price"]
BIG_HINT = ("大类", "类别", "品类", "分类", "category", "class", "type", "系列")
DETAIL_HINT = ("名称", "品名", "name", "商品", "product", "款", "title")
GRAN = {"年": "YS", "季度": "QS", "月": "MS", "周": "W-MON", "日": "D"}


def to_datetime_col(s):
    return pd.to_datetime(s, errors="coerce")


def to_numeric_col(s):
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(s.astype(str).str.replace(r"[¥$,\s]", "", regex=True), errors="coerce")


def try_datetime(s):
    sample = s.dropna().astype(str).head(400)
    if sample.empty:
        return 0.0
    ok = 0
    for v in sample:
        if not re.search(r"[-/年月:]", v):
            continue
        try:
            pd.to_datetime(v)
            ok += 1
        except Exception:
            pass
    return ok / len(sample)


def try_numeric(s):
    sample = s.dropna().astype(str).head(400)
    if sample.empty:
        return 0.0
    cleaned = sample.str.replace(r"[¥$,\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").notna().mean()


def profile(df):
    kinds = {}
    n = max(len(df), 1)
    for c in df.columns:
        s = df[c]
        nn = s.dropna()
        name = str(c).lower()
        if pd.api.types.is_datetime64_any_dtype(s):
            kinds[c] = "date"
            continue
        if pd.api.types.is_bool_dtype(s):
            kinds[c] = "cat"
            continue
        if pd.api.types.is_numeric_dtype(s):
            uniq_ratio = nn.nunique() / max(len(nn), 1)
            if any(h in name for h in ID_HINT) and uniq_ratio > 0.9 and len(nn) > 20:
                kinds[c] = "id"
            else:
                kinds[c] = "num"
            continue
        if try_datetime(s) > 0.8:
            kinds[c] = "date"
            continue
        if try_numeric(s) > 0.85 and not any(h in name for h in ("电话", "手机", "身份证", "编号", "编码")):
            kinds[c] = "num"
            continue
        uniq = nn.nunique()
        if any(h in name for h in ID_HINT) and uniq / max(len(nn), 1) > 0.9:
            kinds[c] = "id"
        elif uniq <= max(2, min(60, 0.35 * n)):
            kinds[c] = "cat"
        else:
            kinds[c] = "text"
    return kinds


def pick_metric(num_cols):
    for key in METRIC_PRIORITY:
        for c in num_cols:
            if key in str(c).lower():
                return c
    return num_cols[0] if num_cols else None


def clean_sheet(df):
    d = df.copy()
    d.columns = [str(c).strip() for c in d.columns]
    return d.dropna(how="all").dropna(axis=1, how="all")


@st.cache_data(show_spinner="正在读取并解析文件…", max_entries=3)
def _load_cached(name: str, raw: bytes):
    """Excel 解析很贵（十几万行要好几秒），缓存住，改设置时不用重读。"""
    return load_any(name, raw)


def _as_key(s):
    return s.dropna().astype(str).str.strip()


def load_any(name, raw):
    low = name.lower()
    if low.endswith((".xlsx", ".xlsm", ".xls")):
        xls = pd.ExcelFile(io.BytesIO(raw))
        return {s: pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names}
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV 编码认不出来")
    for sep in (",", "\t", ";"):
        try:
            df = pd.read_csv(io.StringIO(txt), sep=sep)
            if df.shape[1] > 1:
                return {"CSV": df}
        except Exception:
            pass
    return {"CSV": pd.read_csv(io.StringIO(txt))}


# ---------- 表关系 ----------
def detect_join(fact, dim):
    best = None
    for pk in dim.columns:
        dv = _as_key(dim[pk])
        if dv.empty or dv.nunique() < 2:
            continue
        uniq_ratio = dv.nunique() / len(dv)
        pk_hint = any(h in str(pk).lower() for h in ID_HINT)
        if uniq_ratio < 0.9 and not pk_hint:
            continue
        vals = set(dv)
        if not [c for c in dim.columns if c != pk and c not in fact.columns]:
            continue
        for fk in fact.columns:
            fv = _as_key(fact[fk])
            if fv.empty:
                continue
            match = float(fv.isin(vals).mean())
            if match < 0.3:
                continue
            score = match * 3 + uniq_ratio + (0.4 if str(fk) == str(pk) else 0) + (0.3 if pk_hint else 0)
            if best is None or score > best["score"]:
                best = {"fk": fk, "pk": pk, "match": match, "score": score}
    return best


def apply_join(fact, dim, fk, pk, dim_name, resolve="数值平均"):
    """返回 (合并后表, 新增列名, 键冲突条数)。键有重复时必须显式选择处理方式。"""
    d = dim.copy()
    dup = int(d[pk].duplicated().sum())
    if dup:
        if resolve in ("数值求和", "数值平均"):
            numc = [c for c in d.columns if c != pk and pd.api.types.is_numeric_dtype(d[c])]
            others = [c for c in d.columns if c != pk and c not in numc]
            agg = {c: "first" for c in others}
            agg.update({c: ("sum" if resolve == "数值求和" else "mean") for c in numc})
            d = d.groupby(pk, as_index=False).agg(agg)
        else:
            d = d.drop_duplicates(subset=[pk], keep="last" if resolve == "取最新" else "first")
    rename = {c: (c if c not in fact.columns else f"{dim_name}_{c}") for c in d.columns}
    d = d.rename(columns=rename)
    pk2 = rename[pk]
    added = [rename[c] for c in dim.columns if c != pk and c not in fact.columns]
    # 兜底：万一维表没去干净，merge 会扇出、金额成倍放大。这里强制一行对一行
    fact = fact.reset_index(drop=True)
    fact["__row__"] = range(len(fact))
    out = fact.merge(d, left_on=fk, right_on=pk2, how="left")
    if len(out) != len(fact):
        extra = len(out) - len(fact)
        out = out.drop_duplicates(subset="__row__", keep="first")
        dup = dup + extra
    out = out.drop(columns=["__row__"])
    if pk2 in out.columns and fk != pk2:
        out = out.drop(columns=[pk2])
    return out, added, dup


# ============================================================
# 时间维度：年 / 季度 / 月 / 周 / 日
# ============================================================
def time_key(dt, gran):
    if gran == "年":
        return dt.dt.year.astype(str)
    if gran == "季度":
        return dt.dt.year.astype(str) + "Q" + dt.dt.quarter.astype(str)
    if gran == "月":
        return dt.dt.strftime("%Y-%m")
    if gran == "周":
        return dt.dt.strftime("%Y-W%W")
    return dt.dt.strftime("%Y-%m-%d")


def series_by(df, dc, metric, gran):
    d = df.dropna(subset=[dc]).copy()
    if d.empty:
        return None
    key = time_key(d[dc], gran)
    d["_k"] = key
    g = d.groupby("_k")[metric].sum()
    g = g[g.index.notna()].sort_index()
    return g if len(g) else None


# ============================================================
# 图表工厂
# ============================================================
def chart_trend(df, dc, metric, gran):
    g = series_by(df, dc, metric, gran)
    if g is None or len(g) < 2:
        return None
    win = {"日": 7, "周": 4, "月": 3, "季度": 2, "年": 2}[gran]
    ma = g.rolling(win, min_periods=1).mean() if win > 1 else g
    f = go.Figure()
    f.add_trace(go.Bar(x=list(g.index), y=list(g.values), name=gran + "值",
                       marker=dict(color="rgba(17,141,255,0.35)"),
                       hovertemplate="%{x}<br>" + str(metric) + " %{y:,.0f}<extra></extra>"))
    f.add_trace(go.Scatter(x=list(g.index), y=list(ma.values), name=f"{win}期移动平均",
                           mode="lines", line=dict(color="#E66C37", width=2.6)))
    fig_base(f, 340, f"按{gran}看{metric}变化（柱＝当期，线＝移动平均）", legend=True)
    f.update_xaxes(tickangle=-35 if len(g) > 12 else 0)
    return f


def chart_year_month_heat(df, dc, metric):
    d = df.dropna(subset=[dc]).copy()
    if d.empty:
        return None
    d["_y"] = d[dc].dt.year
    d["_m"] = d[dc].dt.month
    pv = d.pivot_table(index="_y", columns="_m", values=metric, aggfunc="sum")
    if pv.empty or len(pv) < 1:
        return None
    pv = pv.reindex(columns=range(1, 13))
    f = go.Figure(go.Heatmap(z=pv.values, x=[f"{m}月" for m in range(1, 13)],
                             y=[f"{int(y)}年" for y in pv.index],
                             colorscale=[[0, "#F5F9FF"], [0.35, "#9CC9FF"],
                                         [0.7, "#118DFF"], [1, "#12239E"]],
                             hovertemplate="%{y} %{x}<br>%{z:,.0f}<extra></extra>",
                             colorbar=dict(thickness=8, len=0.85,
                                           tickfont=dict(size=10, color=MUTED))))
    fig_base(f, 300, "季节分布：年 × 月热力图（哪个月是旺季一眼看出来）")
    f.update_xaxes(showgrid=False)
    return f


def chart_quarter(df, dc, metric):
    d = df.dropna(subset=[dc]).copy()
    if d.empty:
        return None
    d["_q"] = "Q" + d[dc].dt.quarter.astype(str)
    g = d.groupby("_q")[metric].sum()
    if len(g) < 2:
        return None
    peak = g.idxmax()
    colors = [BI_BLUE if i != peak else "#E66C37" for i in g.index]
    f = go.Figure(go.Bar(x=list(g.index), y=list(g.values), marker=dict(color=colors),
                         text=[fmt(v) for v in g.values], textposition="outside",
                         textfont=dict(size=11, color=MUTED)))
    fig_base(f, 300, f"季度对比（1-3月为Q1…10-12月为Q4；橙色＝最高 {peak}）")
    f.update_yaxes(range=[0, float(g.max()) * 1.18])
    return f


def chart_year_compare(df, dc, metric):
    d = df.dropna(subset=[dc]).copy()
    if d.empty:
        return None
    d["_y"] = d[dc].dt.year.astype(str)
    d["_m"] = d[dc].dt.month
    pv = d.pivot_table(index="_m", columns="_y", values=metric, aggfunc="sum")
    if pv.shape[1] < 2:
        return None
    f = go.Figure()
    for i, y in enumerate(pv.columns):
        f.add_trace(go.Scatter(x=list(range(1, 13)), y=list(pv[y].values), name=f"{y}年",
                               mode="lines+markers",
                               line=dict(color=PALETTE[i % len(PALETTE)], width=2.4),
                               marker=dict(size=5)))
    fig_base(f, 300, "年度对比：同一个月份放在一起比（找同比差在哪）", legend=True)
    f.update_xaxes(tickmode="array", tickvals=list(range(1, 13)),
                   ticktext=[f"{m}月" for m in range(1, 13)], range=[0.5, 12.5])
    return f


def chart_stacked_time_cat(df, dc, cat, metric, gran="月"):
    d = df.dropna(subset=[dc, cat]).copy()
    if d.empty:
        return None
    top = d.groupby(cat)[metric].sum().nlargest(4 if _LITE else 6).index
    d = d[d[cat].isin(top)]
    d["_k"] = time_key(d[dc], gran)
    pv = d.pivot_table(index="_k", columns=cat, values=metric, aggfunc="sum").fillna(0)
    if pv.empty:
        return None
    f = go.Figure()
    for i, c in enumerate(pv.columns):
        f.add_trace(go.Bar(x=list(pv.index), y=list(pv[c].values), name=str(c),
                           marker=dict(color=PALETTE[i % len(PALETTE)])))
    f.update_layout(barmode="stack")
    fig_base(f, 340, f"构成随时间变化：按{gran} × {cat} 堆叠（谁在增长、谁在萎缩）", legend=True)
    f.update_xaxes(tickangle=-35 if len(pv) > 10 else 0)
    return f


def chart_donut(df, cat, metric):
    g = df.groupby(cat)[metric].sum().sort_values(ascending=False)
    g = g[g != 0]
    if g.empty:
        return None
    if len(g) > 8:
        g = pd.concat([g.head(7), pd.Series({"其他": g.iloc[7:].sum()})])
    f = go.Figure(go.Pie(labels=[str(i) for i in g.index], values=list(g.values), hole=0.62,
                         marker=dict(colors=PALETTE, line=dict(color="white", width=2)),
                         textinfo="label+percent", textfont=dict(size=11)))
    f.add_annotation(text=f"{fmt(g.sum())}<br><span style='font-size:10px;color:{MUTED}'>合计</span>",
                     showarrow=False, font=dict(size=15, color=TEXT))
    fig_base(f, 320, f"{cat} 构成占比（看钱从哪来）")
    return f


def chart_treemap(df, big, detail, metric):
    if not detail or detail == big:
        return None
    d = df.dropna(subset=[big, detail])
    if d.empty:
        return None
    g = d.groupby([big, detail])[metric].sum().reset_index()
    g = g[g[metric] > 0]
    if g.empty:
        return None
    b = g.groupby(big)[metric].sum()
    big_labels = [str(x) for x in b.index]
    det_labels = [f"{str(x)} " for x in g[detail]]
    f = go.Figure(go.Treemap(
        labels=big_labels + det_labels,
        parents=[""] * len(big_labels) + [str(x) for x in g[big]],
        values=list(b.values) + list(g[metric]),
        branchvalues="total",
        marker=dict(colors=PALETTE * 4, line=dict(color="white", width=1.5)),
        textinfo="label+percent parent", textfont=dict(size=11),
        hovertemplate="%{label}<br>" + str(metric) + " %{value:,.0f}<extra></extra>"))
    fig_base(f, 340, f"层级结构：{big} → {detail}（面积＝{metric}）")
    return f


def chart_pareto(df, dim, metric):
    g = df.groupby(dim)[metric].sum().sort_values(ascending=False)
    g = g[g > 0]
    if len(g) < 4:
        return None
    cum = g.cumsum() / g.sum() * 100
    top = g.head(15)
    f = go.Figure()
    f.add_trace(go.Bar(x=[str(i)[:12] for i in top.index], y=list(top.values),
                       marker=dict(color=BI_BLUE), hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>"))
    f.add_trace(go.Scatter(x=[str(i)[:12] for i in top.index], y=list(cum.head(15).values),
                           mode="lines+markers", yaxis="y2",
                           line=dict(color="#E66C37", width=2.4), marker=dict(size=4)))
    fig_base(f, 340, f"帕累托：{dim} 中少数贡献多少（柱＝值，线＝累计占比）")
    f.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], ticksuffix="%",
                                showgrid=False, tickfont=dict(size=10, color=MUTED)))
    f.update_xaxes(tickangle=-40, tickfont=dict(size=9.5))
    return f


def chart_top_bar(df, cat, metric, n=12, desc=True):
    g = df.groupby(cat)[metric].sum().sort_values(ascending=False).head(n)
    g = g.iloc[::-1] if desc else g.sort_values(ascending=True)
    if g.empty:
        return None
    f = go.Figure(go.Bar(x=list(g.values), y=[str(i)[:16] for i in g.index], orientation="h",
                         marker=dict(color=BI_BLUE), text=[fmt(v) for v in g.values],
                         textposition="outside", textfont=dict(size=10, color=MUTED)))
    fig_base(f, 340, f"{cat} Top {n}（排序条形最适合比大小）")
    f.update_xaxes(range=[0, float(g.max()) * 1.3], showgrid=True, gridcolor=GRID)
    return f


def chart_hist(df, metric):
    s = to_numeric_col(df[metric]).dropna()
    if len(s) < 5:
        return None
    if _LITE and len(s) > 20000:
        s = s.sample(20000, random_state=0)
    f = go.Figure(go.Histogram(x=s, nbinsx=20 if _LITE else 30,
                               marker=dict(color=BI_BLUE, line=dict(width=0))))
    fig_base(f, 300, f"{metric} 分布（中位数 {fmt(s.median())}，看集中在哪个区间）")
    return f


def chart_box(df, cat, metric):
    if not cat:
        return None
    d = df.dropna(subset=[cat]).copy()
    top = d.groupby(cat)[metric].sum().nlargest(6).index
    d = d[d[cat].isin(top)]
    if d.empty:
        return None
    f = go.Figure()
    for i, c in enumerate(top):
        f.add_trace(go.Box(y=to_numeric_col(d[d[cat] == c][metric]).dropna(),
                           name=str(c)[:10], marker_color=PALETTE[i % len(PALETTE)],
                           boxpoints="outliers"))
    fig_base(f, 300, f"各 {cat} 的{metric}分布（箱线图看波动和离群，比平均值诚实）")
    return f


def chart_heat_cat(df, dc, cat, metric):
    d = df.dropna(subset=[dc, cat]).copy()
    if d.empty:
        return None
    d["_m"] = d[dc].dt.strftime("%Y-%m")
    top = d.groupby(cat)[metric].sum().nlargest(8).index
    d = d[d[cat].isin(top)]
    pv = d.pivot_table(index=cat, columns="_m", values=metric, aggfunc="sum").fillna(0)
    if pv.empty or pv.shape[0] < 2:
        return None
    f = go.Figure(go.Heatmap(z=pv.values, x=list(pv.columns),
                             y=[str(i)[:14] for i in pv.index],
                             colorscale=[[0, "#F5F9FF"], [0.35, "#9CC9FF"],
                                         [0.7, "#118DFF"], [1, "#12239E"]],
                             colorbar=dict(thickness=8, len=0.85,
                                           tickfont=dict(size=10, color=MUTED))))
    fig_base(f, 330, f"{cat} × 月份 热力（谁在哪个时间段发力）")
    f.update_xaxes(showgrid=False)
    return f


def chart_scatter(df, x, y, color=None):
    a, b = to_numeric_col(df[x]), to_numeric_col(df[y])
    m = a.notna() & b.notna()
    if m.sum() < 5:
        return None
    # 有一列是常数时相关系数无意义，也不该让 numpy 报 RuntimeWarning
    if a[m].nunique() < 2 or b[m].nunique() < 2:
        return None
    if _LITE:
        idx = np.flatnonzero(m.to_numpy())[:800]
        a = a.iloc[idx]; b = b.iloc[idx]
        m = pd.Series(True, index=a.index)
    try:
        corr = float(np.corrcoef(a[m], b[m])[0, 1])
    except Exception:
        corr = 0.0
    f = go.Figure(go.Scattergl(x=a[m], y=b[m], mode="markers",
                               marker=dict(color=BI_BLUE, size=6, opacity=0.5)))
    fig_base(f, 300, f"关系：{x} vs {y}（相关系数 {corr:.2f}）")
    return f


def chart_corr(df, nums):
    nums = [c for c in nums if df[c].notna().sum() > 10][:6 if _LITE else 8]
    # 去掉常量列，否则相关系数会算出 NaN 并刷警告
    nums = [c for c in nums if to_numeric_col(df[c]).nunique() > 1]
    if len(nums) < 3:
        return None
    corr = df[nums].apply(to_numeric_col).corr()
    labels = [str(c)[:10] for c in nums]
    f = go.Figure(go.Heatmap(z=corr.values, x=labels, y=labels, zmin=-1, zmax=1,
                             colorscale=[[0, "#D64550"], [0.5, "#F3F2F1"], [1, "#118DFF"]],
                             text=np.round(corr.values, 2), texttemplate="%{text}",
                             textfont=dict(size=9),
                             colorbar=dict(thickness=8, len=0.85,
                                           tickfont=dict(size=10, color=MUTED))))
    fig_base(f, 330, "指标相关性矩阵（>0.7 说明两个指标在说同一件事）")
    f.update_xaxes(showgrid=False, tickangle=-35)
    f.update_yaxes(autorange="reversed")
    return f


def _shift_key(k, gran):
    """把时间标签往前推一年（用于同比）。"""
    try:
        if gran == "月":
            y, m = str(k).split("-")
            return f"{int(y)-1:04d}-{m}"
        if gran == "季度":
            y, q = str(k).split("Q")
            return f"{int(y)-1}Q{q}"
        if gran == "年":
            return str(int(k) - 1)
    except Exception:
        return None
    return None


def chart_gauge(df, dc, metric, gran, mode="环比"):
    g = series_by(df, dc, metric, gran)
    if g is None or len(g) < 2:
        return None
    cur = float(g.iloc[-1])
    prev = float(g.iloc[-2])
    cmp_label = f"上一个{gran}"
    if mode == "同比":
        sk = _shift_key(g.index[-1], gran)
        if sk is not None and sk in list(g.index):
            prev = float(g.loc[sk])
            cmp_label = f"去年同{gran}"
    if prev <= 0:
        return None
    ratio = cur / prev
    f = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(ratio * 100, 1),
        number={"suffix": "%", "font": {"size": 30}},
        delta={"reference": 100, "increasing": {"color": "#107C10"},
               "decreasing": {"color": "#A4262C"}},
        gauge={"axis": {"range": [0, 200], "tickwidth": 1, "tickcolor": MUTED},
               "bar": {"color": BI_BLUE, "thickness": 0.28},
               "bgcolor": "white", "borderwidth": 0,
               "steps": [{"range": [0, 80], "color": "#FDE7E9"},
                         {"range": [80, 120], "color": "#FFF4CE"},
                         {"range": [120, 200], "color": "#E7F4E4"}],
               "threshold": {"line": {"color": "#E66C37", "width": 3},
                             "thickness": 0.8, "value": 100}}))
    fig_base(f, 250, f"最近一个{gran} vs {cmp_label}（100%＝持平，{fmt(cur)} vs {fmt(prev)}）")
    return f


PROV = {"北京": (116.4, 39.9), "天津": (117.2, 39.1), "河北": (114.5, 38.0), "山西": (112.5, 37.9),
        "内蒙古": (111.7, 40.8), "辽宁": (123.4, 41.8), "吉林": (125.3, 43.9), "黑龙江": (126.6, 45.8),
        "上海": (121.5, 31.2), "江苏": (118.8, 32.1), "浙江": (120.2, 30.3), "安徽": (117.3, 31.9),
        "福建": (119.3, 26.1), "江西": (115.9, 28.7), "山东": (117.0, 36.7), "河南": (113.6, 34.8),
        "湖北": (114.3, 30.6), "湖南": (113.0, 28.2), "广东": (113.3, 23.1), "广西": (108.3, 22.8),
        "海南": (110.3, 20.0), "重庆": (106.5, 29.6), "四川": (104.1, 30.7), "贵州": (106.7, 26.6),
        "云南": (102.7, 25.0), "西藏": (91.1, 29.6), "陕西": (108.9, 34.3), "甘肃": (103.8, 36.1),
        "青海": (101.8, 36.6), "宁夏": (106.3, 38.5), "新疆": (87.6, 43.8), "台湾": (121.5, 25.0),
        "香港": (114.2, 22.3), "澳门": (113.5, 22.2)}


def norm_prov(v):
    s = str(v).strip()
    for suf in ("特别行政区", "自治区", "省", "市", "壮族", "回族", "维吾尔", "自治州"):
        s = s.replace(suf, "")
    return s


def find_geo(df, kinds):
    for c, k in kinds.items():
        if k not in ("cat", "text"):
            continue
        vals = df[c].dropna().astype(str).map(norm_prov)
        if vals.empty:
            continue
        hit = vals.isin(PROV.keys()).mean()
        if hit > 0.7 and vals.nunique() >= 2:
            return c
    return None


def chart_map(df, geo, metric):
    d = df.dropna(subset=[geo]).copy()
    d["_p"] = d[geo].astype(str).map(norm_prov)
    d = d[d["_p"].isin(PROV.keys())]
    if d.empty:
        return None
    g = d.groupby("_p")[metric].sum().sort_values(ascending=False)
    xs = [PROV[p][0] for p in g.index]
    ys = [PROV[p][1] for p in g.index]
    mx = float(g.max())
    smax = 46 if len(g) > 8 else 30
    sizes = [10 + smax * (v / mx) for v in g.values]
    # 视野贴合数据：点少时自动放大，避免全国范围里挤成一点
    pad = 5.0
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    if x1 - x0 < 16:
        cx = (x0 + x1) / 2
        x0, x1 = cx - 8, cx + 8
    if y1 - y0 < 12:
        cy = (y0 + y1) / 2
        y0, y1 = cy - 6, cy + 6
    f = go.Figure(go.Scatter(x=xs, y=ys, mode="markers+text", text=list(g.index),
                             textposition="top center", textfont=dict(size=10, color=MUTED),
                             marker=dict(size=sizes, color=list(g.values),
                                         colorscale=[[0, "#9CC9FF"], [1, "#12239E"]],
                                         line=dict(color="white", width=1),
                                         showscale=True,
                                         colorbar=dict(thickness=8, len=0.8,
                                                       tickfont=dict(size=10, color=MUTED))),
                             hovertemplate="%{text}<br>" + str(metric) + " %{customdata:,.0f}<extra></extra>",
                             customdata=list(g.values)))
    f.update_layout(
        height=420, margin=dict(l=10, r=10, t=48, b=10),
        paper_bgcolor=CARD_BG, plot_bgcolor="#F7FBFF",
        font=dict(family=FONT, size=12, color=TEXT),
        title=dict(text=f"省域分布：{metric}（气泡大小＝数值）",
                   font=dict(size=13.5, color=MUTED), x=0.015, y=0.97),
        xaxis=dict(visible=False, range=[x0, x1]),
        yaxis=dict(visible=False, range=[y0, y1], scaleanchor="x", scaleratio=1),
        showlegend=False)
    return f


# ============================================================
# 自动结论
# ============================================================
def make_insights(df, kinds, metric, dc, cat, detail):
    out = []
    d = df.copy()
    if dc:
        d[dc] = to_datetime_col(d[dc])
    if metric:
        d[metric] = to_numeric_col(d[metric])
    out.append(f"共 {len(d):,} 行、{d.shape[1]} 列；数值列 {sum(v=='num' for v in kinds.values())} 个，"
               f"类别列 {sum(v=='cat' for v in kinds.values())} 个。")

    if cat and metric:
        g = d.groupby(cat)[metric].sum().sort_values(ascending=False)
        g = g[g > 0]
        if len(g) >= 5:
            k = max(1, int(len(g) * 0.2))
            out.append(f"**集中度**：{cat} 前 20% 的取值贡献 {g.head(k).sum()/g.sum()*100:.0f}% 的 {metric}，"
                       f"头部「{g.index[0]}」占 {g.iloc[0]/g.sum()*100:.0f}%。")

    if dc and metric:
        s = d.dropna(subset=[dc])
        if len(s) > 20:
            m = s.groupby(s[dc].dt.to_period("M"))[metric].sum()
            m = m[m.index.notna()].sort_index()
            rec = before = 0.0
            lab = ""
            if len(m) >= 6:
                pm = list(m.index[-6:-3])
                contiguous = len(pm) == 3 and (pm[-1] - pm[0]).n == 2
                rec, before, lab = m.iloc[-3:].sum(), m.iloc[-6:-3].sum(), "最近 3 个月"
                if not contiguous:
                    out.append(f"**趋势**：上一个 3 个月数据不连续"
                               f"（只有 {'、'.join(str(x) for x in pm)}），环比不可比——补数据或改看同比。")
                    before = 0.0
            elif len(m) >= 2:
                rec, before, lab = float(m.iloc[-1]), float(m.iloc[-2]), "最近 1 个月"
            if before > 0:
                chg = (rec - before) / before * 100
                _note = ""
                # 基数过小时百分比会被放大，必须提示，否则 900% 这种数字会误导
                if before < float(m.mean()) * 0.2 or before < 100:
                    _note = "（基数偏小，百分比会被放大，建议同时看绝对值）"
                out.append(f"**趋势**：{lab}比上一个周期"
                           f"{'上升' if chg>0 else '下降'} {abs(chg):.1f}%"
                           f"（{fmt(rec)} vs {fmt(before)}）{_note}。")

        q = s.copy()
        q["_q"] = "Q" + q[dc].dt.quarter.astype(str)
        gq = q.groupby("_q")[metric].sum()
        if len(gq) >= 3:
            out.append(f"**季度规律**：最高是 {gq.idxmax()}（{fmt(gq.max())}），"
                       f"最低是 {gq.idxmin()}（{fmt(gq.min())}），相差 {gq.max()/max(gq.min(),1e-9):.1f} 倍。")

        yy = s[dc].dt.year.nunique()
        if yy >= 2:
            gy = s.groupby(s[dc].dt.year)[metric].sum()
            last, prev_y = gy.index[-1], gy.index[-2]
            if gy[prev_y] > 0:
                yoy = (gy[last] - gy[prev_y]) / gy[prev_y] * 100
                out.append(f"**同比**：{last} 年比 {prev_y} 年{'增长' if yoy>0 else '下滑'} {abs(yoy):.1f}%"
                           f"（{fmt(gy[last])} vs {fmt(gy[prev_y])}）。")

    if metric:
        v = to_numeric_col(d[metric]).dropna()
        if len(v) > 20:
            q1, q3 = v.quantile(0.25), v.quantile(0.75)
            iqr = q3 - q1
            hi = int((v > q3 + 1.5 * iqr).sum())
            lo = int((v < q1 - 1.5 * iqr).sum())
            if hi or lo:
                out.append(f"**异常值**：{metric} 有 {hi} 个偏高点、{lo} 个偏低点，"
                           f"占 {(hi+lo)/len(v)*100:.1f}%（可能是大单/退款，值得单独看）。")

    miss = d.isna().sum()
    miss = miss[miss > 0].sort_values(ascending=False)
    dup = int(d.duplicated().sum())
    if len(miss):
        out.append("**质量**：" + "；".join(f"「{c}」缺 {int(v)} 行" for c, v in miss.head(3).items())
                   + (f"；整行重复 {dup} 条" if dup else "") + "。")
    elif dup:
        out.append(f"**质量**：无缺失，但有 {dup} 条整行重复。")

    nums = [c for c, k in kinds.items() if k == "num" and d[c].notna().sum() > 10]
    if len(nums) >= 2:
        corr = d[nums].apply(to_numeric_col).corr()
        arr = corr.to_numpy(dtype=float).copy()
        np.fill_diagonal(arr, 0.0)
        arr = np.nan_to_num(arr, nan=0.0)
        i, j = np.unravel_index(np.argmax(arr), arr.shape)
        if arr[i, j] >= 0.5:
            out.append(f"**相关性**：「{nums[i]}」与「{nums[j]}」相关度 {arr[i,j]:.2f}，"
                       f"做归因时要小心共线性（可能一个由另一个直接算出）。")
    return out


# ============================================================
# 页面
# ============================================================
st.markdown(
    "<div style='display:flex;align-items:baseline;gap:14px;flex-wrap:wrap'>"
    f"<div style='font-size:23px;font-weight:600;color:{BI_NAVY};letter-spacing:.4px'>智能数据分析</div>"
    f"<div style='font-size:12.5px;color:{MUTED}'>上传 Excel / CSV → 自动识别结构 → 多维分析</div></div>"
    f"<div style='height:2px;background:{BI_NAVY};width:44px;margin:8px 0 10px'></div>",
    unsafe_allow_html=True)
PV.badge()

with st.sidebar:
    st.markdown("#### 1. 上传数据")
    ups = st.file_uploader("选择 Excel 或 CSV（可多选，自动按列名纵向合并）",
                           type=["xlsx", "xlsm", "xls", "csv"], accept_multiple_files=True)
    st.caption("数据只在本机内存里处理，不上传任何服务器。")

# 未上传时：主区直接给上传入口（手机端侧栏是收起的，入口必须放在正文里）
_DEMO_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pos.csv")

if not ups:
    st.markdown(
        "<div style='background:#fff;border:1px solid #E3E6EA;border-left:4px solid #1F3864;"
        "border-radius:3px;padding:18px 20px 6px;margin:6px 0 10px'>"
        "<div style='font-size:16px;font-weight:600;color:#1F2328;margin-bottom:4px'>上传你的销售数据</div>"
        "<div style='font-size:12.5px;color:#5F6672;margin-bottom:10px'>"
        "支持 Excel（.xlsx / .xlsm / .xls）与 CSV，可多选；文件只在你自己的浏览器里解析。</div></div>",
        unsafe_allow_html=True)
    _main_up = st.file_uploader(
        "选择文件（可多选）", type=["xlsx", "xlsm", "xls", "csv"],
        accept_multiple_files=True, key="main_up", label_visibility="collapsed")
    if _main_up:
        ups = _main_up

    if not ups and os.path.exists(_DEMO_CSV):
        st.markdown("<div style='font-size:12.5px;color:#5F6672;margin:10px 0 4px'>"
                    "还没有数据？先用示例数据看看能出什么：</div>", unsafe_allow_html=True)
        if st.button("加载示例数据（便利店 3 个月 POS，约 4 万行）", key="demo_load", type="primary"):
            st.session_state["_demo"] = True
            st.rerun()

    if not ups and not st.session_state.get("_demo"):
        st.markdown("""
        **会自动做的事**
        - 认出日期、数值、类别、编号列，不用改列名
        - 多张表自动建关系（销售表只有商品编码，也能补出商品名称和品类）
        - 时间自动拆成 **年 / 季度 / 月 / 周 / 日**
        - 按数据形态自动选图：趋势用折线、对比用排序条形、构成用环形/树图、
          分布用直方图/箱线、关系用散点/相关矩阵、地理用气泡地图、期间对比用仪表盘
        """)
        st.caption("手机上更多设置（主表、口径、筛选）在左上角 ☰ 里。")
        st.stop()

try:
    sheets = {}
    if not ups and st.session_state.get("_demo"):
        sheets["示例数据"] = pd.read_csv(_DEMO_CSV, encoding="utf-8-sig")
    for f in (ups or []):
        one = _load_cached(f.name, f.getvalue())
        for k, v in one.items():
            if k in sheets:
                common = [c for c in sheets[k].columns if c in v.columns]
                sheets[k] = pd.concat([sheets[k][common], v[common]], ignore_index=True) \
                    if len(common) >= 2 else pd.concat([sheets[k], v], ignore_index=True)
            else:
                sheets[k] = v
    up_name = " + ".join(f.name for f in ups) if ups else "内置示例数据"
except Exception as e:
    st.error(f"文件读不出来：{e}")
    st.stop()

# ---------- 主表 ----------
sheet_names = list(sheets.keys())
if len(sheet_names) > 1:
    default_idx = max(range(len(sheet_names)), key=lambda i: len(sheets[sheet_names[i]]))
    with st.sidebar:
        st.markdown("#### 2. 主表（明细表）")
        sheet = st.selectbox("Sheet", sheet_names, index=default_idx, label_visibility="collapsed")
else:
    sheet = sheet_names[0]

fact = clean_sheet(sheets[sheet])
others = [s for s in sheet_names if s != sheet]

# ---------- 表关系 ----------
join_cfgs = []
if others:
    with st.sidebar:
        st.markdown("#### 3. 表关系")
        for name in others:
            dim = clean_sheet(sheets[name])
            if dim.empty:
                continue
            auto = detect_join(fact, dim)
            use = st.checkbox(f"用「{name}」补全主表",
                              value=bool(auto and auto["match"] >= 0.85), key=f"use_{name}")
            fk_cols, pk_cols = list(fact.columns), list(dim.columns)
            fk0 = auto["fk"] if (auto and auto["fk"] in fk_cols) else fk_cols[0]
            pk0 = auto["pk"] if (auto and auto["pk"] in pk_cols) else pk_cols[0]
            fk = st.selectbox(f"{name} → 主表字段", fk_cols, index=fk_cols.index(fk0),
                              key=f"fk_{name}", disabled=not use)
            pk = st.selectbox(f"{name} → 对方字段", pk_cols, index=pk_cols.index(pk0),
                              key=f"pk_{name}", disabled=not use)
            if use:
                fv = _as_key(fact[fk])
                rate = float(fv.isin(set(_as_key(dim[pk]))).mean()) if len(fv) else 0.0
                extra_n = len([c for c in dim.columns if c != pk and c not in fact.columns])
                st.caption(f"匹配率 {rate*100:.0f}% ｜ 新增 {extra_n} 列")
                dup_n = int(dim[pk].duplicated().sum())
                resolve = "取第一条"
                if dup_n:
                    st.caption(f"⚠ 「{pk}」有 {dup_n} 行重复键，必须选怎么处理，否则会静默丢数据")
                    resolve = st.selectbox(
                        f"{name} · 重复键处理", ["数值平均（推荐）", "数值求和", "取第一条", "取最新"],
                        key=f"rs_{name}").replace("（推荐）", "")
                join_cfgs.append((name, dim, fk, pk, rate, resolve))

df0 = fact
joined_note = []
join_conflicts = []
for name, dim, fk, pk, rate, resolve in join_cfgs:
    df0, added, dup = apply_join(df0, dim, fk, pk, name, resolve)
    joined_note.append(f"{name}.{pk} → {fk}（匹配 {rate*100:.0f}%，新增 {len(added)} 列）")
    if dup:
        join_conflicts.append(f"「{name}」的 {pk} 有 {dup} 行重复，按「{resolve}」合并")

if df0.empty:
    st.warning("这个表是空的。")
    st.stop()

kinds = profile(df0)
date_cols = [c for c, k in kinds.items() if k == "date"]
num_cols = [c for c, k in kinds.items() if k == "num"]
cat_cols = [c for c, k in kinds.items() if k == "cat"]
auto_metric = pick_metric(num_cols)


def best_big():
    cand = [c for c in cat_cols if any(h in str(c).lower() for h in BIG_HINT)]
    cand = [c for c in cand if 2 <= df0[c].nunique() <= 20] or cand
    if cand:
        return cand[0]
    small = [c for c in cat_cols if 2 <= df0[c].nunique() <= 12]
    return max(small, key=lambda c: df0[c].nunique()) if small else (cat_cols[0] if cat_cols else None)


def best_detail(big):
    def id_like(c):
        s = str(c).lower()
        return any(h in s for h in ID_HINT) and not any(h in s for h in ("名称", "name"))

    cand = [c for c in cat_cols if c != big and any(h in str(c).lower() for h in DETAIL_HINT)
            and not id_like(c)]
    cand = [c for c in cand if 3 <= df0[c].nunique() <= 300] or cand
    if cand:
        return max(cand, key=lambda c: df0[c].nunique())
    others = [c for c in cat_cols if c != big and not id_like(c) and 3 <= df0[c].nunique() <= 300]
    return max(others, key=lambda c: df0[c].nunique()) if others else None


big_default = best_big()
detail_default = best_detail(big_default)

with st.sidebar:
    st.markdown("#### 4. 分析设置")
    _LITE = st.checkbox("省流模式（手机建议开启）", value=False, key="lite_mode",
                        help="图表降采样、关闭悬停交互，手机上滑动更顺畅；分析结果不变")
    metric = (st.selectbox("主指标", num_cols,
                           index=num_cols.index(auto_metric) if auto_metric in num_cols else 0)
              if num_cols else None)
    dc = (st.selectbox("时间列", ["（不使用）"] + date_cols, index=1 if date_cols else 0)
          if date_cols else "（不使用）")
    dc = None if dc == "（不使用）" else dc
    gran = st.selectbox("时间粒度", list(GRAN.keys()), index=2) if dc else "月"

    big_idx = (cat_cols.index(big_default) + 1) if (big_default in cat_cols) else 0
    big = st.selectbox("大类维度", ["（不使用）"] + cat_cols, index=big_idx) if cat_cols else "（不使用）"
    big = None if big == "（不使用）" else big
    det_opts = [c for c in cat_cols if c != big]
    det_idx = (det_opts.index(detail_default) + 1) if (detail_default in det_opts) else 0
    detail = st.selectbox("明细维度", ["（不使用）"] + det_opts, index=det_idx) if det_opts else "（不使用）"
    detail = None if detail == "（不使用）" else detail
    sort_desc = st.radio("条形图排序", ["从大到小", "从小到大"], horizontal=True) == "从大到小"
    cmp_mode = st.radio("对比口径", ["环比（上一期）", "同比（去年同期）"], horizontal=False)
    cmp_mode = "同比" if cmp_mode.startswith("同比") else "环比"
    refund_mode = st.radio("退款/负值行",
                           ["计入（净额）", "剔除（只看正向销售）"],
                           horizontal=False,
                           help="POS 里的退货常见为负金额。计入＝净销售额（财务口径）；剔除＝毛销售额（运营口径）")
    refund_mode = "剔除" if refund_mode.startswith("剔除") else "计入"
    target_amount = st.number_input("本期目标金额（0＝不启用）", min_value=0.0,
                                    value=0.0, step=1000.0,
                                    help="填了就会算达成率和预计能否完成")

    with st.expander("口径设置（有争议的算法）", expanded=False):
        st.caption("同一份数据，口径不同结论就不同。这里选完，全页跟着变。")
        order_key_mode = st.selectbox("订单数怎么数", ["自动（推荐）", "订单号+日期", "订单号原样"],
                                      help="订单号在多期导出里被复用时要加日期")
        tie_mode = st.selectbox("连带率怎么算", ["按件数（数量合计）", "按SKU数（明细行数）"])
        aov_mode = st.selectbox("客单价含不含退款单", ["仅正向订单（推荐）", "含退款订单"])
        cost_force = st.selectbox("成本口径", ["自动判断（推荐）", "按单价×数量", "按成本列直取"],
                                  help="列名像单价就要乘数量，像总额就直接求和")
        dict_at_top = st.checkbox("顶部显示口径字典", value=True)

    if dc:
        dta = to_datetime_col(df0[dc])
        if dta.notna().any() and dta.min() < dta.max():
            rng = st.date_input("日期范围", value=(dta.min().date(), dta.max().date()))
            if isinstance(rng, tuple) and len(rng) == 2:
                mask = (dta >= pd.Timestamp(rng[0])) & (dta <= pd.Timestamp(rng[1]) + pd.Timedelta(days=1))
                df0 = df0[mask.to_numpy()]

    st.markdown("#### 5. 筛选")
    _pre_filter_df = df0.copy()          # 下钻选项永远从这里取，不受当前筛选影响
    _drill = st.session_state.get("_drill")
    if _drill:
        _dc_d, _dv_d = _drill
        st.markdown(f"<div class='caliber' style='margin:0 0 8px;padding:7px 10px;font-size:12px'>"
                    f"下钻中：{_dc_d} ＝ {_dv_d}</div>", unsafe_allow_html=True)
        if st.button("✕ 退出下钻", key="drill_clear"):
            st.session_state.pop("_drill", None)
            st.rerun()
        df0 = df0[df0[_dc_d].astype(str) == str(_dv_d)]
    _filter_cols = st.multiselect("按维度筛选（可多条件）", cat_cols, default=[], key="flt_cols")
    for _fc in _filter_cols[:3]:
        _vals = sorted(df0[_fc].dropna().astype(str).unique())[:200]
        _pick = st.multiselect(f"{_fc} 取值", _vals, key=f"flt_val_{_fc}")
        if _pick:
            df0 = df0[df0[_fc].astype(str).isin(_pick)]

sampled_from = len(df0) if len(df0) > 200000 else 0
if sampled_from:
    df0 = df0.sample(200000, random_state=0)

# ---------- 口径选择落到内部代码 ----------
_order_key = {"自动（推荐）": "auto", "订单号+日期": "订单号+日期", "订单号原样": "订单号原样"}[order_key_mode]
_tie = "qty" if tie_mode.startswith("按件数") else "rows"
_include_refunds = aov_mode.startswith("含退款")
_cost_force = {"自动判断（推荐）": "auto", "按单价×数量": "unit", "按成本列直取": "total"}[cost_force]

df = df0.copy()
if dc:
    df[dc] = to_datetime_col(df[dc])
if metric:
    df[metric] = to_numeric_col(df[metric])

geo = find_geo(df, kinds)

# ---------- 退款 / 负值行处理 ----------
refund_info = {"n": 0, "sum": 0.0, "removed": 0}
if metric:
    neg_mask = (df[metric] < 0).to_numpy()
    refund_info["n"] = int(neg_mask.sum())
    refund_info["sum"] = float(df.loc[neg_mask, metric].sum())
    if refund_mode == "剔除" and refund_info["n"]:
        refund_info["removed"] = refund_info["n"]
        df = df[~neg_mask].copy()

# ---------- 顶部信息 ----------
st.markdown(
    f"<div style='font-size:12.5px;color:{MUTED};margin-bottom:6px'>"
    f"文件：{up_name} ｜ 主表：{sheet} ｜ {len(df):,} 行 × {df.shape[1]} 列 ｜ "
    f"识别出 {len(date_cols)} 个时间列、{len(num_cols)} 个数值列、{len(cat_cols)} 个类别列"
    + (f"、地理列「{geo}」" if geo else "") + "</div>", unsafe_allow_html=True)
if joined_note:
    st.markdown(f"<div style='font-size:12px;color:#107C10;margin-bottom:6px'>🔗 已关联："
                + "；".join(joined_note) + "</div>", unsafe_allow_html=True)
if dc:
    yrs = df[dc].dt.year.nunique()
    qs = df[dc].dt.to_period("Q").nunique()
    st.markdown(
        f"<div style='font-size:12px;color:{MUTED};margin-bottom:8px'>"
        f"时间跨度：{df[dc].min():%Y-%m-%d} ~ {df[dc].max():%Y-%m-%d} ｜ 覆盖 {yrs} 个年度、{qs} 个季度"
        f"</div>", unsafe_allow_html=True)




def data_health(df, dc, metric, num_cols, refund_info, join_conflicts, sampled_from):
    items = []
    if dc and len(df):
        days = df[dc].dropna().dt.normalize()
        if len(days):
            full = pd.date_range(days.min(), days.max(), freq="D")
            missing = full.difference(pd.DatetimeIndex(days.unique()))
            if len(missing):
                gap = "、".join(d.strftime("%m-%d") for d in list(missing)[:6])
                items.append({"level": "warn", "title": f"时间断档 {len(missing)} 天",
                              "text": f"缺 {gap}{'…' if len(missing) > 6 else ''}。"
                                      f"断档会让环比和趋势失真，先确认是当天没营业还是导出漏了。"})
            else:
                items.append({"level": "ok", "title": "时间连续",
                              "text": "所选范围内每天都有数据，趋势可信。"})

    if refund_info["n"]:
        removed = refund_info["removed"]
        items.append({"level": "ok" if removed else "warn",
                      "title": f"退款/负值 {refund_info['n']:,} 行",
                      "text": f"合计 {fmt(refund_info['sum'])}，当前"
                              + ("已剔除（毛销售口径）" if removed else "计入（净额口径）")
                              + ("。此时不要跟财务的净销售额直接对账。" if not removed
                                 else "。跟财务对账时记得把退款加回去。")})
    elif metric:
        items.append({"level": "ok", "title": "无负值行", "text": "没检测到退款/冲红记录。"})

    price_c = next((c for c in num_cols if any(h in str(c).lower() for h in ("单价", "price", "售价"))), None)
    qty_c = next((c for c in num_cols if any(h in str(c).lower() for h in ("数量", "销量", "qty", "quantity"))), None)
    if metric and price_c and qty_c and price_c != metric and qty_c != metric:
        calc = to_numeric_col(df[qty_c]) * to_numeric_col(df[price_c])
        bad = int(((to_numeric_col(df[metric]) - calc).abs() > 0.02).sum())
        if bad:
            items.append({"level": "warn", "title": f"金额校验不通过 {bad:,} 行",
                          "text": f"「{metric}」≠ 数量×单价 的有 {bad:,} 条（{bad/len(df)*100:.1f}%）。"
                                  f"多半是折扣/满减，也可能是错单——做毛利和价格分析前要确认。"})
        else:
            items.append({"level": "ok", "title": "金额校验通过",
                          "text": f"{metric} 与 数量×单价 全部一致。"})

    dup = int(df.duplicated().sum())
    if dup:
        items.append({"level": "warn", "title": f"整行重复 {dup:,} 条",
                      "text": "可能是重复导出，先去重，否则总额被放大。"})

    cost_c0 = next((c for c in num_cols
                    if any(h in str(c).lower() for h in ("成本", "进价", "cost", "进货"))), None)
    if cost_c0:
        kind = AN.cost_kind(cost_c0)
        items.append({"level": "info", "title": f"毛利口径：「{cost_c0}」按{kind}算",
                      "text": ("已按 单价 × 数量 换算成本；如果这列其实是每行总成本，毛利会被高估，请核对。"
                               if kind == "单价" else
                               "这列当作每行成本总额直接求和；如果其实是单价，毛利会被严重低估。")})

    miss = df.isna().mean()
    heavy = miss[miss > 0.2].sort_values(ascending=False)
    if len(heavy):
        items.append({"level": "warn", "title": f"{len(heavy)} 列缺失严重",
                      "text": "；".join(f"「{c}」缺 {v*100:.0f}%" for c, v in heavy.head(4).items())
                              + "。用这些列做维度会掉数据。"})

    for t in join_conflicts:
        items.append({"level": "warn", "title": "关联键冲突", "text": t + "，核对一下总额。"})

    if sampled_from:
        items.append({"level": "info", "title": f"已抽样 {len(df):,} / {sampled_from:,} 行",
                      "text": "图表和结论都基于抽样，绝对数会偏小，比例仍可用。"})

    const = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    if const:
        items.append({"level": "info", "title": f"{len(const)} 个常量列",
                      "text": "、".join(str(c) for c in const[:5]) + " 只有一个取值，做维度没意义。"})
    return items


WK_CN = {"Monday": "周一", "Tuesday": "周二", "Wednesday": "周三", "Thursday": "周四",
         "Friday": "周五", "Saturday": "周六", "Sunday": "周日"}


def _cost_col(num_cols):
    for c in num_cols:
        s = str(c).lower()
        if any(h in s for h in ("成本", "进价", "cost", "进货")):
            return c
    return None


def business_summary(df, kinds, metric, dc, big, detail, num_cols, cost_force="auto"):
    """返回一组「一句话结论 + 支撑数据」的业务发现。"""
    out = []
    if not metric or df.empty:
        return out
    d = df.copy()
    if dc:
        d[dc] = to_datetime_col(d[dc])
    d[metric] = to_numeric_col(d[metric])
    cost_c = _cost_col(num_cols)
    dim = detail or big
    rev = float(d[metric].sum())

    if cost_c and d[cost_c].notna().mean() > 0.5:
        qty_c_bs = next((c for c in num_cols if c != metric and
                         any(h in str(c).lower() for h in ("数量", "销量", "件数", "qty", "quantity"))), None)
        d["_cost"] = AN.cost_line(d, cost_c, qty_c_bs, cost_force)
        if d["_cost"] is None:
            d["_cost"] = to_numeric_col(d[cost_c]).fillna(0)
        profit = rev - float(d["_cost"].sum())
        margin = profit / rev * 100 if rev else 0
        hi = "；属于高毛利结构，促销空间大" if margin >= 40 else (
            "；毛利率偏低，主要靠走量" if margin < 20 else "")
        out.append({"icon": "💰", "title": "整体赚钱能力",
                    "text": f"{metric}合计 {fmt(rev)}，毛利 {fmt(profit)}，毛利率 {margin:.1f}%{hi}。"})
        g = d.groupby(dim).agg(rev=(metric, "sum"), cost=("_cost", "sum"))
        g = g[g["rev"] > rev * 0.005]
        if len(g) >= 3:
            g["profit"] = g["rev"] - g["cost"]
            g["margin"] = g["profit"] / g["rev"] * 100
            top_p = g.sort_values("profit", ascending=False).iloc[0]
            out.append({"icon": "🏆", "title": f"最赚钱的{dim}",
                        "text": f"「{top_p.name}」毛利 {fmt(top_p['profit'])}（毛利率 {top_p['margin']:.1f}%），"
                                f"贡献全部毛利的 {top_p['profit']/max(g['profit'].sum(),1e-9)*100:.0f}%。"})
            rich = g[(g["margin"] >= 40) & (g["rev"] >= rev * 0.01)].sort_values("margin", ascending=False)
            if len(rich):
                names = "、".join(f"{i}({r['margin']:.0f}%)" for i, r in rich.head(3).iterrows())
                out.append({"icon": "📈", "title": "高毛利商品（值得主推）",
                            "text": f"{names}。提利润比拉销量见效更快，优先给好位置。"})
            if big and detail and big != detail:
                gb = d.groupby(big).agg(rev=(metric, "sum"), cost=("_cost", "sum"))
                gb = gb[gb["rev"] > rev * 0.02]
                gb["margin"] = (gb["rev"] - gb["cost"]) / gb["rev"] * 100
                if len(gb) >= 2:
                    best, worst = gb["margin"].idxmax(), gb["margin"].idxmin()
                    out.append({"icon": "⚖️", "title": f"{big}之间的利润差",
                                "text": f"「{best}」毛利率最高 {gb.loc[best,'margin']:.1f}%，"
                                        f"「{worst}」最低 {gb.loc[worst,'margin']:.1f}%，"
                                        f"差 {gb.loc[best,'margin']-gb.loc[worst,'margin']:.1f} 个百分点。"})
    else:
        out.append({"icon": "💰", "title": "整体规模",
                    "text": f"{metric}合计 {fmt(rev)}。表里没有成本/进价字段，算不出毛利——"
                            f"补一列成本就能看谁真正赚钱。"})

    if dim:
        g = d.groupby(dim)[metric].sum().sort_values(ascending=False)
        if len(g) >= 3:
            out.append({"icon": "🥇", "title": f"卖得最好的{dim}",
                        "text": f"「{g.index[0]}」{fmt(g.iloc[0])}，占全部 {g.iloc[0]/g.sum()*100:.1f}%；"
                                f"前三名合计占 {g.head(3).sum()/g.sum()*100:.1f}%。"})

    if dc:
        m = d.groupby(d[dc].dt.to_period("M"))[metric].sum()
        m = m[m.index.notna()].sort_index()
        if len(m) >= 3:
            b, w = m.idxmax(), m.idxmin()
            out.append({"icon": "📅", "title": "整体最好 / 最差的月份",
                        "text": f"{b} 最好（{fmt(m[b])}），{w} 最差（{fmt(m[w])}），"
                                f"相差 {m[b]/max(m[w],1e-9):.1f} 倍。"})
        if big:
            pv = d.dropna(subset=[dc]).pivot_table(index=d[dc].dt.month, columns=big,
                                                   values=metric, aggfunc="sum")
            if pv.shape[1] >= 1 and pv.shape[0] >= 3:
                tops = d.groupby(big)[metric].sum().nlargest(3).index
                parts = []
                for c in tops:
                    if c not in pv.columns or pv[c].isna().all():
                        continue
                    parts.append(f"{c} 在 {int(pv[c].idxmax())} 月最好、{int(pv[c].idxmin())} 月最差")
                if parts:
                    out.append({"icon": "🌡️", "title": "各大类的旺淡季", "text": "；".join(parts) + "。"})
        wk = d.dropna(subset=[dc]).groupby(d[dc].dt.day_name())[metric].sum()
        if len(wk) >= 5:
            wk.index = [WK_CN.get(x, x) for x in wk.index]
            out.append({"icon": "🗓️", "title": "一周里的规律",
                        "text": f"{wk.idxmax()}最好（{fmt(wk.max())}），{wk.idxmin()}最差（{fmt(wk.min())}），"
                                f"差距 {wk.max()/max(wk.min(),1e-9):.1f} 倍。"})
        if dim:
            mm = d.dropna(subset=[dc]).copy()
            mm["_m"] = mm[dc].dt.to_period("M")
            months = sorted(mm["_m"].unique())
            if len(months) >= 6:
                last3, prev3 = months[-3:], months[-6:-3]
                basis = "上月比"
                pv2 = mm.pivot_table(index=dim, columns="_m", values=metric, aggfunc="sum").fillna(0)
                # 数据有断档时，"前 3 个月"可能跨年，改成去年同期更可比
                contiguous = ((prev3[-1] - prev3[0]).n == 2 and (last3[0] - prev3[-1]).n == 1)
                if not contiguous:
                    alt = [m - 12 for m in last3]
                    if all(c in pv2.columns for c in list(last3) + alt):
                        prev3 = alt
                        basis = "去年同期"
                if all(c in pv2.columns for c in list(last3) + list(prev3)):
                    a = pv2[last3].sum(axis=1)
                    b2 = pv2[prev3].sum(axis=1)
                    base = pv2.sum(axis=1)
                    ok = base[base > base.sum() * 0.005].index
                    chg = ((a - b2) / b2.replace(0, np.nan) * 100).reindex(ok).dropna()
                    if len(chg) >= 3:
                        up, down = chg.idxmax(), chg.idxmin()
                        out.append({"icon": "🚀", "title": f"增长最快 / 下滑最快（{basis}）",
                                    "text": f"「{up}」近 3 个月 {chg[up]:+.0f}%，"
                                            f"「{down}」{chg[down]:+.0f}%——前者加订，后者查原因。"})
        if dim:
            cut = d[dc].max() - pd.Timedelta(days=30)
            recent = d[d[dc] > cut].groupby(dim)[metric].sum()
            ever = d.groupby(dim)[metric].sum()
            dead = [x for x in ever.index if recent.get(x, 0) <= ever[x] * 0.02]
            if 0 < len(dead) <= max(2, len(ever) // 2):
                out.append({"icon": "📦", "title": "最近 30 天基本没动销",
                            "text": "、".join(str(x) for x in dead[:6])
                                    + ("等 " if len(dead) > 6 else " ") + f"共 {len(dead)} 个，考虑清库存或下架。"})

    price_c = next((c for c in num_cols if any(h in str(c).lower() for h in ("单价", "price", "售价"))), None)
    if price_c:
        p = to_numeric_col(d[price_c]).dropna()
        p = p[(p > 0) & (p < p.quantile(0.99))]
        if len(p) > 50:
            bins = pd.cut(p, bins=[0, 3, 5, 8, 12, 20, 1e9],
                          labels=["3元以下", "3-5元", "5-8元", "8-12元", "12-20元", "20元以上"])
            share = bins.value_counts(normalize=True).sort_index()
            top2 = share.nlargest(2).index.tolist()
            out.append({"icon": "💵", "title": "价格带集中在哪",
                        "text": f"「{share.idxmax()}」占 {share.max()*100:.0f}%，"
                                f"成交主要集中在 {'、'.join(str(x) for x in top2)}。"})
    return out


CHART_H = 330
_LITE = False          # 省流模式：图表降采样、关交互，手机上更顺


def _chart_config():
    return {"displayModeBar": False, "staticPlot": True} if _LITE else MODEBAR


def chart_card(fig, key, height=CHART_H):
    if fig is None:
        return
    title = ""
    try:
        title = fig.layout.title.text or ""
    except Exception:
        pass
    is_gauge = bool(fig.data) and getattr(fig.data[0], "type", "") == "indicator"
    margin = dict(l=44, r=44, t=16, b=8) if is_gauge else dict(l=16, r=16, t=16, b=12)
    fig.update_layout(title=None, height=height, margin=margin)
    with st.container(border=True):
        c1, c2 = st.columns([0.88, 0.12], vertical_alignment="center")
        with c1:
            st.markdown(f"<div class='ctitle'>{title}</div>", unsafe_allow_html=True)
        with c2:
            if st.button("⛶", key=f"z_{key}"):
                st.session_state["_zoom"] = (go.Figure(fig), title)
                st.rerun()
        st.plotly_chart(fig, width="stretch", config=_chart_config())



# ---------- 放大视图面板 ----------
_zoom = st.session_state.get("_zoom")
if _zoom:
    _zfig, _ztitle = _zoom
    with st.container(border=True):
        zc1, zc2 = st.columns([0.88, 0.12], vertical_alignment="center")
        with zc1:
            st.markdown(f"<div class='ctitle'>🔍 {_ztitle}（放大视图）</div>",
                        unsafe_allow_html=True)
        with zc2:
            if st.button("✕ 关闭", key="zoom_close"):
                st.session_state.pop("_zoom", None)
                st.rerun()
        _zbig = go.Figure(_zfig)
        _zbig.update_layout(height=720, title=None, margin=dict(l=30, r=30, t=10, b=30))
        st.plotly_chart(_zbig, width="stretch", config=_chart_config())


# ---------- 清洗层：清洗后的数据会被全站使用 ----------
df, _tz_fixed = timefix.to_local_dates(df)      # 带时区的时间戳先换算成本地时间
_RAW_DF = df.copy()
_DF_SIG = f"{len(_RAW_DF)}x{len(_RAW_DF.columns)}:" + ",".join(map(str, _RAW_DF.columns))
_clean_state = st.session_state.get("_clean")
_clean_on = bool(_clean_state and _clean_state.get("sig") == _DF_SIG)
if _clean_on:
    df = _clean_state["df"]
# 缓存签名要区分「原始 / 清洗后」，否则清洗完还在用旧缓存
perf.set_sig(f"{_DF_SIG}|clean={int(_clean_on)}|rows={len(df)}")

# ---------- 核心四指标（单独一行） ----------
_qty_c0 = next((c for c in num_cols
                if c != metric and any(h in str(c).lower() for h in ("数量", "销量", "件数", "qty", "quantity"))), None)
_cost_c0 = next((c for c in num_cols
                 if any(h in str(c).lower() for h in ("成本", "进价", "cost", "进货"))), None)

_sales = float(to_numeric_col(df[metric]).sum()) if metric else 0.0
_cost_line = AN.cost_line(df, _cost_c0, _qty_c0, _cost_force) if _cost_c0 else None
_cost = float(_cost_line.sum()) if _cost_line is not None else None
_profit = (_sales - _cost) if _cost is not None else None
_margin = (_profit / _sales * 100) if (_profit is not None and _sales) else None
_qty = float(to_numeric_col(df[_qty_c0]).sum()) if _qty_c0 else float(len(df))

# 指标公式：默认按真实列名生成，用户改过的存 session_state + metric_formulas.json
_oc0 = AN.pick_order_col(df)
# 成本先按统一口径算成一行一列（单价×数量 / 总额），公式里直接引用，保证与体检、报告同源
_COST_TMP = "成本额_计算"
if _cost_c0 and _cost_line is not None:
    df[_COST_TMP] = _cost_line.fillna(0)
    kinds[_COST_TMP] = "calc"          # 登记类型，免得后面的列信息表找不到
# 订单键也按当前口径生成一列，公式里用它才算得出和页面一致的订单数
_ORDER_TMP = "订单键_计算"
if _oc0:
    _key0 = df[_oc0].astype(str)
    _plus_date = False
    if dc and dc in df.columns and str(_order_key) != "订单号原样":
        _dts = pd.to_datetime(df[dc], errors="coerce")
        if str(_order_key).startswith("订单号+日期"):
            _plus_date = True
        else:      # auto：订单号跨期重复时自动加上日期，和 analytics 同一套判断
            try:
                _multi = df.assign(_k=_key0, _d=_dts.dt.normalize()).groupby("_k")["_d"].nunique()
                _plus_date = bool((_multi > 1).mean() > 0.01)
            except Exception:
                _plus_date = False
        if _plus_date:
            _key0 = _key0 + "|" + _dts.dt.strftime("%Y-%m-%d").fillna("")
    # 整单金额 ≤0 的是纯退款单，不进订单数（和订单级口径一致）
    try:
        _ord_total = pd.to_numeric(df[metric], errors="coerce").groupby(_key0).transform("sum")
        _key0 = _key0.where(_ord_total > 0)
    except Exception:
        pass
    df[_ORDER_TMP] = _key0
    kinds[_ORDER_TMP] = "calc"

_FM_DEFAULT = MT.build_defaults(metric, _qty_c0, _COST_TMP if _cost_line is not None else _cost_c0,
                                "total" if _cost_line is not None else _cost_force,
                                _ORDER_TMP if _oc0 else None)
_fm_sig = "|".join(f"{k}={v}" for k, v in _FM_DEFAULT.items())
if st.session_state.get("_fm_sig") != _fm_sig:
    _saved_fm = MT.sanitize(MT.load_overrides(MT_FILE), df)
    for _k, _v in _FM_DEFAULT.items():
        st.session_state[f"fm_{_k}"] = _saved_fm.get(_k) or _v
    st.session_state["_fm_sig"] = _fm_sig
_fm_cur = {k: st.session_state.get(f"fm_{k}", v) for k, v in _FM_DEFAULT.items()}
MV, MVERR = MT.resolve(df, _fm_cur)

if MV.get("销售收入") is not None:
    _sales = float(MV["销售收入"])
if MV.get("销售数量") is not None:
    _qty = float(MV["销售数量"])
if MV.get("成本") is not None:
    _cost = float(MV["成本"])
if MV.get("毛利") is not None:
    _profit = float(MV["毛利"])
if MV.get("毛利率") is not None:
    _margin = float(MV["毛利率"]) * 100


def _fm_custom(name, default_sub):
    return "自定义公式" if (_fm_cur.get(name) or "").strip() != (_FM_DEFAULT.get(name) or "").strip() else default_sub


_hero = [
    ("销售收入", fmt(_sales), _fm_custom("销售收入", "净额（含退款）" if refund_mode == "计入" else "毛销售（已剔除退款）"), BI_NAVY),
    ("毛利", fmt(_profit) if _profit is not None else "—",
     _fm_custom("毛利", "收入 − 成本") if _profit is not None else "表里没有成本/进价列", "#2E75B6"),
    ("毛利率", f"{_margin:.1f}%" if _margin is not None else "—",
     _fm_custom("毛利率", "毛利 ÷ 收入") if _margin is not None else "需要成本列才能算", "#548235"),
    ("销售数量", f"{_qty:,.0f}", _fm_custom("销售数量", f"来自「{_qty_c0}」" if _qty_c0 else "行数（无数量列）"), "#7F8A99"),
]
_hc = st.columns(4)
for _i, (_lab, _val, _sub, _color) in enumerate(_hero):
    with _hc[_i]:
        st.markdown(
            f"<div class='kpi hero' style='border-left:4px solid {_color}'>"
            f"<div class='kpi-label'>{_lab}</div>"
            f"<div class='kpi-value hero-val'>{_val}</div>"
            f"<div class='kpi-sub'>{_sub}</div></div>", unsafe_allow_html=True)

# ---------- 公共计算 ----------
_k = f"{metric}:{dc}:{big}:{detail}:{_cost_force}:{len(df)}"
sums = perf.get("sums:" + _k, lambda: business_summary(df, kinds, metric, dc, big, detail, num_cols, _cost_force))
health = perf.get("health:" + _k, lambda: data_health(df, dc, metric, num_cols, refund_info,
                                                     join_conflicts, sampled_from))
ins = perf.get("ins:" + _k, lambda: make_insights(df, kinds, metric, dc, big, detail))
oc = AN.pick_order_col(df)
cust_col = AN.find_col(df.columns, AN.CUST_HINT)
cost_c = AN.find_col(df.columns, AN.COST_HINT, exclude={metric})
qty_c = AN.find_col(df.columns, AN.QTY_HINT, exclude={metric})
_price_c0 = next((c for c in num_cols
                  if c != metric and any(h in str(c).lower() for h in ("单价", "售价", "price"))), None)
_warn_n = sum(1 for h in health if h["level"] == "warn")

if _warn_n:
    st.markdown(f"<div style='font-size:12px;color:#E66C37;margin:2px 0 6px'>"
                f"⚠ 数据体检发现 {_warn_n} 处需要注意，详见「数据与口径」页</div>",
                unsafe_allow_html=True)

items = [("数据行数", f"{len(df):,}", sheet), ("列数", f"{df.shape[1]}", "已忽略空列")]
if dc:
    items.append(("覆盖天数", f"{(df[dc].max()-df[dc].min()).days}", "min~max"))
if big:
    items.append((str(big)[:6] + " 数", f"{df[big].nunique()}", "distinct"))
if metric:
    items.append(("单行均值", fmt(df[metric].mean()), "每行商品，非客单价"))


# ============================================================
# 口径字典
# ============================================================
def render_metric_dict(metric, qty_c, cost_c, order_col, dc, refund_mode, gran,
                       order_key="自动（推荐）", tie="按件数（数量合计）",
                       aov="仅正向订单（推荐）", cost_mode="自动判断（推荐）", *,
                       with_editor=True):
    """口径字典：所有公式都按当前选择动态生成，选了什么就显示什么。"""
    if cost_mode.startswith("按单价"):
        cost_formula = f"Σ({cost_c} × {qty_c or '数量'})"
    elif cost_mode.startswith("按成本"):
        cost_formula = f"Σ「{cost_c}」"
    else:
        cost_formula = (f"Σ({cost_c} × {qty_c or '数量'})" if cost_c and AN.cost_kind(cost_c) == "单价"
                        else f"Σ「{cost_c}」" if cost_c else "—")
    order_formula = {"自动（推荐）": "去重订单号（跨期重复时自动 +日期）",
                     "订单号+日期": "去重 订单号+日期",
                     "订单号原样": "去重订单号"}[order_key]
    tie_formula = ("Σ数量 ÷ 订单数" if tie.startswith("按件数") else "明细行数 ÷ 订单数")
    aov_note = ("只统计金额>0 的订单" if aov.startswith("仅正向") else "退款单也进分母，客单价会被拉低")

    rows = [
        ("销售收入", f"Σ「{metric}」", "全部行的金额求和",
         "退款行（负金额）默认计入 → 净销售额；切成「剔除」就是毛销售额，两者能差几个点"),
        ("销售数量", f"Σ「{qty_c}」" if qty_c else "无数量列，用行数", qty_c or "行数",
         "和收入同口径；退货行的负数量会冲减"),
        ("成本", cost_formula, cost_c or "无成本列",
         f"当前口径：{cost_mode}。列名像单价要乘数量，像总额直接求和——这条最容易算错"),
        ("毛利", "销售收入 − 成本", "上面两行", "不含人工、房租、平台佣金，是商品毛利不是净利"),
        ("毛利率", "毛利 ÷ 销售收入", "毛利 / 收入", "低毛利靠走量的生意，别用毛利率做唯一考核"),
        ("订单数", order_formula, order_col or "无订单号列",
         f"当前口径：{order_key}。订单号跨期复用时不加日期，连带率会虚高"),
        ("客单价", "Σ订单金额 ÷ 订单数", f"{metric} / 订单号", aov_note),
        ("件单价", "Σ金额 ÷ Σ数量", f"{metric} / {qty_c or '数量'}", "反映每件商品卖多少钱"),
        ("连带率", tie_formula, "数量 / 订单号", f"当前口径：{tie}"),
        ("客单价中位数", "订单金额的中位数", f"{metric}", "抗极端大单，看「典型顾客」花多少"),
        ("金额校验", "金额 vs 数量×单价", f"{metric} / {qty_c or '—'} / 单价", "不一致多半是折扣满减，也可能是错单"),
        ("构成占比", "某维度金额 ÷ 总金额", f"{metric} / 维度列", "环形图、树图都用这个"),
        ("毛利占比", "某维度毛利 ÷ 总毛利", "毛利 / 维度列", "和金额占比对比，能看出「谁真正赚钱」"),
        ("帕累托累计", "按金额降序的累计占比", f"{metric}", "ABC 分层阈值 70% / 90%"),
        ("支持度", "同时含 A、B 的订单 ÷ 总订单", "订单号 + 商品", "购物篮用的基础频次"),
        ("置信度", "含 A 的订单里也含 B 的比例", "订单号 + 商品", "做套餐命中率估算"),
        ("提升度", "置信度 ÷ B 的基础购买率", "订单号 + 商品", ">1 才有正的连带关系；只看置信度会误判畅销品"),
        ("环比", f"本期 vs 上一个{gran}", dc or "—", "看短期波动，受促销和断档影响大"),
        ("同比", "本期 vs 去年同期", dc or "—", "剔掉季节性，判断趋势真假用这个"),
        ("RFM", "R 最近一次距今 / F 购买频次 / M 累计金额，各做五分位", "会员列 + 日期 + 金额",
         "快照式分层，不反映「新客留存到第 3 个月还剩多少」"),
        ("目标达成率", "本期实际 ÷ 目标", f"{metric}", "目标是整期口径，月中查看时结合按速度推算值"),
        ("预测", "移动平均 + 阻尼趋势 + 星期季节性偏移", dc or "—",
         "区间用残差标准差算，不是置信区间推导；只适合短期"),
        ("异常点", "滚动中位数 + MAD（|z|>3.5）", dc or "—", "比 3σ 抗极端值；先排查缺货/系统故障再剔除"),
    ]
    if with_editor:
        st.markdown("<div class='sect'>指标公式<small>直接改，改完立即生效；图表仍按列聚合，不受影响</small></div>",
                    unsafe_allow_html=True)
        st.caption("写法：sum(列名) / nunique(列名) / sum(进价 * 数量)；也能用 [毛利] / [销售收入] 引用别的指标。"
                   "改的是「指标数值」，图形还是用原始列画。")
        for _m in MT.ORDER:
            _c1, _c2, _c3 = st.columns([1.1, 3.0, 1.7])
            _c1.markdown(f"<div style='padding-top:7px;font-weight:600;font-size:13px'>{_m}</div>",
                         unsafe_allow_html=True)
            _c2.text_input(_m, key=f"fm_{_m}", label_visibility="collapsed",
                           placeholder=_FM_DEFAULT.get(_m) or "（无此指标）")
            if MVERR.get(_m):
                _c3.markdown(f"<div style='color:#D64550;font-size:12px;padding-top:9px'>⚠ {MVERR[_m][:38]}</div>",
                             unsafe_allow_html=True)
            else:
                _c3.markdown(f"<div style='color:{MUTED};font-size:13px;padding-top:9px'>"
                             f"= {MT.display(_m, MV.get(_m))}</div>", unsafe_allow_html=True)
        _b1, _b2, _ = st.columns([1.1, 1.1, 2.2])
        if _b1.button("💾 保存公式", key="fm_save"):
            MT.save_overrides(MT_FILE, {k: st.session_state.get(f"fm_{k}", v) for k, v in _FM_DEFAULT.items()})
            st.success("已保存到 metric_formulas.json，下次打开还是这套")
        if _b2.button("↺ 恢复默认", key="fm_reset"):
            MT.save_overrides(MT_FILE, {})
            # 只赋值没用（widget 自己的 state 会盖掉），要删 key 再重跑
            for k in _FM_DEFAULT:
                st.session_state.pop(f"fm_{k}", None)
            st.session_state["_fm_sig"] = None
            st.rerun()

    head = "".join(f"<th>{h}</th>" for h in ["指标", "计算公式", "取数", "口径提醒"])
    body = ""
    for r in rows:
        body += ("<tr>" + f"<td>{r[0]}</td><td class='mono'>{r[1]}</td>"
                 f"<td>{r[2]}</td><td class='note'>{r[3]}</td>" + "</tr>")
    st.markdown(f"<table class='mdict'><thead><tr>{head}</tr></thead>"
                f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)

    st.markdown(
        "<div class='insight'>上面每一条都是本工具<b>当前实际执行</b>的逻辑，会随左侧「口径设置」变化。"
        "跟财务/老板对数之前，先把这张表对一遍——口径不一致时，数字差多少都能解释得通。</div>",
        unsafe_allow_html=True)


# ---------- 当前口径条 + 顶部字典 ----------
_caliber_bits = [
    f"收入＝{'净额（含退款）' if refund_mode == '计入' else '毛销售（剔除退款）'}",
    f"订单数＝{order_key_mode}",
    f"连带率＝{tie_mode}",
    f"客单价＝{aov_mode}",
    f"成本＝{cost_force}",
]
st.markdown(
    "<div class='caliber'><span>" + " ｜ ".join(_caliber_bits) + "</span>"
    "<span class='caliber-hint'>在左侧「口径设置」里改，全页跟着变</span></div>",
    unsafe_allow_html=True)

if dict_at_top:
    with st.expander("📖 指标口径字典｜每个数字是怎么算出来的", expanded=False):
        render_metric_dict(metric, qty_c, cost_c, oc, dc, refund_mode, gran,
                           order_key_mode, tie_mode, aov_mode, cost_force, with_editor=False)


# ============================================================
# 分页
# ============================================================
# ---------- 本期要点（一句话结论，汇报时直接念） ----------
_issues_n = 0
if not (_clean_state and _clean_state.get("sig") == _DF_SIG):
    _issues_n = len(perf.get("clean_issues", lambda: CL.detect(_RAW_DF)))
if _issues_n:
    st.markdown(f"<div class='brief' style='border-left-color:#C55A11'>"
                f"检测到 <b>{_issues_n} 类</b>数据问题（重复行 / 文本型数字 / 缺失等），"
                f"建议先到「数据清洗」处理，否则统计结果会有偏差。</div>", unsafe_allow_html=True)

_lead = ""
if sums:
    _lead = str(sums[0].get("text", ""))
elif ins:
    _lead = str(ins[0])
if _lead:
    _lead = re.sub(r"\*\*(.+?)\*\*", r"<b></b>", _lead)
    st.markdown(f"<div class='brief'>{_lead}</div>", unsafe_allow_html=True)

# 分段选择器：只渲染当前模块。手机上如果 6 个 tab 全渲染，25 张 Plotly 图会把浏览器拖垮
_SECTIONS = ["概览", "数据清洗", "趋势", "结构", "经营", "客户与归因", "SQL 查询", "统计建模", "数据与口径"]
try:
    _sec = st.segmented_control("模块", _SECTIONS, default=_SECTIONS[0],
                                key="sec_pick", label_visibility="collapsed")
except Exception:
    _sec = st.radio("模块", _SECTIONS, horizontal=True, key="sec_pick",
                    label_visibility="collapsed")
_sec = _sec or _SECTIONS[0]

# ---------------- 概览 ----------------
if _sec == "概览":
    if sums:
        st.markdown("<div class='sect'>业务总结<small>谁卖得好、什么时候好卖、谁真正赚钱</small></div>",
                    unsafe_allow_html=True)
        for i in range(0, len(sums), 2):
            pair = sums[i:i + 2]
            cols2 = st.columns(2)
            for j, it in enumerate(pair):
                with cols2[j]:
                    st.markdown(
                        f"<div class='sumcard'><div class='sumhead'>{it['icon']} {it['title']}</div>"
                        f"<div class='sumtext'>{it['text']}</div></div>", unsafe_allow_html=True)
    _adv = perf.get(f"advice:{metric}:{qty_c}:{_cost_c0}:{dc}:{detail}:{big}:{oc}:{target_amount}:{len(df)}",
                    lambda: ADV.build_advice(df, metric, qty_c, _cost_c0, _cost_force, dc,
                                             detail or big, big, oc, float(target_amount or 0)))
    if _adv:
        st.markdown("<div class='sect'>改善建议<small>按你这份数据算的，每条都带依据；预期是粗估，不是承诺</small></div>",
                    unsafe_allow_html=True)
        for _a in _adv:
            _col = {"高": "#D64550", "中": "#E66C37", "低": "#107C10"}.get(_a["sev"], MUTED)
            st.markdown(
                f"<div class='sumcard' style='border-left:4px solid {_col}'>"
                f"<div class='sumhead'><span style='color:{_col};font-weight:700'>{_a['sev']}</span> · {_a['title']}</div>"
                f"<div class='sumtext'><b>依据</b>：{_a['evidence']}<br>"
                f"<b>怎么做</b>：{_a['action']}<br>"
                f"<b>预期</b>：{_a['impact']}</div></div>", unsafe_allow_html=True)

    # 汇报话术：把结论组织成能直接念的一段话
    if metric:
        _period, _mom_txt, _top_cat, _top_share = "本期", "", "", ""
        if dc:
            _dts = pd.to_datetime(df[dc], errors="coerce")
            _gg = pd.to_numeric(df[metric], errors="coerce").groupby(_dts.dt.to_period("M")).sum()
            _gg = _gg[_gg.index.notna()]
            if len(_gg) >= 2 and _gg.iloc[-2]:
                _period = str(_gg.index[-1])
                _mom_txt = f"{(_gg.iloc[-1] - _gg.iloc[-2]) / _gg.iloc[-2] * 100:+.1f}%"
        if big and big in df.columns:
            _sc = df.groupby(big)[metric].sum().sort_values(ascending=False)
            if len(_sc):
                _top_cat = str(_sc.index[0])
                _top_share = f"{_sc.iloc[0] / _sc.sum() * 100:.0f}%"
        _facts = {"period": _period, "rev": fmt(_sales),
                  "margin": f"{_margin:.1f}%" if _margin is not None else "",
                  "mom": _mom_txt, "top_cat": _top_cat, "top_share": _top_share,
                  "concern": (_adv[0]["title"] if _adv else ""),
                  "advice": _adv[:3] if _adv else []}
        with st.expander("汇报话术｜照着念就行", expanded=False):
            st.code(ADV.speech_script(_facts), language="text")
            st.caption("数字全部来自当前这份数据；口径改了，话术也跟着变。")

    if oc and metric:
        _o_tab, _om = perf.get(f"om:{oc}:{metric}:{qty_c}:{dc}:{_order_key}:{_tie}:{_include_refunds}:{len(df)}",
                               lambda: AN.order_metrics(df, oc, metric, qty_c, dc, _order_key, _tie, _include_refunds))
        if _om:
            st.markdown("<div class='sect'>关键指标<small>订单级口径，和上面的行级指标不是一回事</small></div>",
                        unsafe_allow_html=True)
            XS.kpi_row([("订单数", f"{_om['订单数']:,}", "订单号去重"),
                        ("客单价", fmt(_om["客单价"]), "金额 ÷ 订单数"),
                        ("连带率", f"{_om['连带率']:.2f}", "件数 ÷ 订单数"),
                        ("件单价", fmt(_om["件单价"]), "金额 ÷ 件数")], cols=4)

    if ins:
        with st.expander("数据层面的自动结论（集中度 / 趋势 / 异常 / 质量）", expanded=False):
            for t in ins:
                t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
                st.markdown(f"<div class='insight'>{t}</div>", unsafe_allow_html=True)

# ---------------- 趋势 ----------------
if _sec == "数据清洗":
    CU.render(_RAW_DF, _DF_SIG)

if _sec == "趋势":
    if metric and dc:
        r1 = st.columns([3, 2])
        with r1[0]:
            chart_card(chart_trend(df, dc, metric, gran), "trend", 340)
        with r1[1]:
            chart_card(chart_gauge(df, dc, metric, gran, cmp_mode), "gauge", 340)
        r2 = st.columns(3)
        with r2[0]:
            chart_card(chart_quarter(df, dc, metric), "quarter")
        with r2[1]:
            chart_card(chart_year_month_heat(df, dc, metric), "ymheat")
        with r2[2]:
            chart_card(chart_year_compare(df, dc, metric), "yoy")
        if target_amount:
            XS.section_target(df, dc, metric, gran, target_amount, chart_card)
        XS.section_forecast(df, dc, metric, gran, chart_card)
    else:
        st.info("没有识别到时间列，趋势分析不可用。")

# ---------------- 结构 ----------------
if _sec == "结构":
    if metric and (big or detail):
        r3 = st.columns([2, 3])
        with r3[0]:
            _dn = chart_donut(df, big, metric) if big else None
            if _dn is not None:
                _dn.update_layout(height=330, title=None, margin=dict(l=16, r=16, t=12, b=12))
                with st.container(border=True):
                    st.markdown(f"<div class='ctitle'>{big} 构成（下方选值可下钻）</div>",
                                unsafe_allow_html=True)
                    try:
                        _ev = st.plotly_chart(_dn, key="dn_drill", on_select="rerun",
                                              selection_mode="points", width="stretch",
                                              config=_chart_config())
                        _pts = (_ev or {}).get("selection", {}).get("points", [])                             if isinstance(_ev, dict) else []
                        if _pts:
                            _lab = _pts[0].get("label") or _pts[0].get("legendgroup")
                            if _lab and st.session_state.get("_drill") != (big, _lab):
                                st.session_state["_drill"] = (big, _lab)
                                st.rerun()
                    except Exception:
                        st.plotly_chart(_dn, width="stretch", config=_chart_config())
                if big:
                    _src = _pre_filter_df if big in _pre_filter_df.columns else df
                    _dv_opts = _src[big].dropna().astype(str).value_counts().head(30).index.tolist()
                    _opts = ["（全部）"] + _dv_opts
                    _cur = st.session_state.get("_drill")
                    _cur_val = _cur[1] if (_cur and _cur[0] == big and _cur[1] in _opts) else "（全部）"
                    _sel = st.selectbox(f"下钻到（{big}）", _opts, index=_opts.index(_cur_val),
                                        key="drill_pick")
                    if _sel != _cur_val:
                        if _sel == "（全部）":
                            st.session_state.pop("_drill", None)
                        else:
                            st.session_state["_drill"] = (big, _sel)
                        st.rerun()
        with r3[1]:
            chart_card(chart_treemap(df, big, detail, metric), "treemap")
        r4 = st.columns(2)
        with r4[0]:
            chart_card(chart_top_bar(df, detail or big, metric, desc=sort_desc), "topbar")
        with r4[1]:
            chart_card(chart_pareto(df, detail or big, metric), "pareto")
        if dc and big:
            r5 = st.columns(2)
            with r5[0]:
                chart_card(chart_heat_cat(df, dc, big, metric), "catheat")
            with r5[1]:
                chart_card(chart_stacked_time_cat(df, dc, big, metric, "月"), "stack")
    if geo and metric:
        chart_card(chart_map(df, geo, metric), "map", 430)

# ---------------- 经营 ----------------
if _sec == "经营":
    if oc and metric:
        XS.section_orders(df, oc, metric, qty_c, dc, chart_card, _order_key, _tie, _include_refunds)
    if oc and (detail or big):
        XS.section_basket(df, oc, detail or big, chart_card)
    if cost_c and big and metric:
        XS.section_margin(df, big, metric, cost_c, chart_card, qty_c, _cost_force)
    XS.section_discount(df, metric, qty_c, _price_c0, big, chart_card)
    if metric:
        r6 = st.columns(3)
        with r6[0]:
            chart_card(chart_hist(df, metric), "hist")
        with r6[1]:
            chart_card(chart_box(df, big, metric), "box")
        others = sorted([c for c in num_cols if c != metric],
                        key=lambda c: df[c].nunique(), reverse=True)
        with r6[2]:
            chart_card(chart_scatter(df, metric, others[0]) if others else None, "scatter")
        chart_card(chart_corr(df, num_cols), "corr", 340)

# ---------------- 客户与归因 ----------------
if _sec == "客户与归因":
    if cust_col and dc and metric:
        XS.section_rfm(df, cust_col, dc, metric, chart_card)
    else:
        st.info("没有识别到会员/客户列（如会员卡号、customer id），客户分层需要这类字段。")
    if metric and dc:
        qa_engine.render(df, dc, metric, num_cols, cat_cols, big, detail, sheet, items, sums, cmp_mode, _caliber_bits)
        XS.section_compare(df, dc, metric, cat_cols, chart_card)

# ---------------- 数据与口径 ----------------
if _sec == "SQL 查询":
    _nlq_schema = nlq.build_schema(df, metric=metric, qty=qty_c, date=dc,
                                   cost=cost_c, cat=big, item=detail)
    SQ.render_ask(df, _nlq_schema)
    st.divider()
    SQ.render_sql(df)

if _sec == "统计建模":
    AU.render_stats(df, metric, qty_c, cost_c, dc, big, detail, cust_col, oc)

if _sec == "数据与口径":
    PV.render()
    st.markdown("<div class='sect'>数据概况</div>", unsafe_allow_html=True)
    kcols = st.columns(len(items[:5]))
    for i, (lab, val, sub) in enumerate(items[:5]):
        with kcols[i]:
            st.markdown(f"<div class='kpi'><div class='kpi-label'>{lab}</div>"
                        f"<div class='kpi-value'>{val}</div><div class='kpi-sub'>{sub}</div></div>",
                        unsafe_allow_html=True)

    if health:
        st.markdown(f"<div class='sect'>数据体检<small>{'发现 ' + str(_warn_n) + ' 处需要注意' if _warn_n else '没有明显问题'}</small></div>",
                    unsafe_allow_html=True)
        for i in range(0, len(health), 3):
            row = health[i:i + 3]
            hc = st.columns(3)
            for j, it in enumerate(row):
                color = {"warn": "#E66C37", "ok": "#107C10", "info": BI_BLUE}[it["level"]]
                icon = {"warn": "⚠", "ok": "✓", "info": "ⓘ"}[it["level"]]
                with hc[j]:
                    st.markdown(
                        f"<div class='hcard' style='border-left-color:{color}'>"
                        f"<div class='hhead' style='color:{color}'>{icon} {it['title']}</div>"
                        f"<div class='htext'>{it['text']}</div></div>", unsafe_allow_html=True)

    st.markdown("<div class='sect'>自定义指标<small>公式自己写，口径自己定</small></div>",
                unsafe_allow_html=True)
    if "_custom" not in st.session_state:
        st.session_state["_custom"] = []
    with st.form("cm_form"):
        fc1, fc2, fc3 = st.columns([1.1, 3, 0.7])
        cm_name = fc1.text_input("指标名", placeholder="毛利占比")
        cm_expr = fc2.text_input("公式", placeholder="(sum(金额) - sum(成本)) / sum(金额)")
        cm_ok = fc3.form_submit_button("添加")
    st.caption("可用：sum / mean / median / min / max / std / nunique / count；"
               "列名直接写，含空格或括号的用引号，例如 sum(\"销售额(元)\")")
    if cm_ok:
        if not cm_name.strip():
            st.error("指标名不能为空")
        else:
            _v, _err = CM.evaluate(df, cm_expr)
            if _err:
                st.error(f"公式有误：{_err}")
            else:
                st.session_state["_custom"] = [
                    c for c in st.session_state["_custom"] if c["name"] != cm_name.strip()
                ] + [{"name": cm_name.strip(), "expr": cm_expr}]
                st.success(f"「{cm_name.strip()}」= {CM.fmt_value(_v)}")
    if st.session_state["_custom"]:
        _rows = []
        for _it in st.session_state["_custom"]:
            _v, _err = CM.evaluate(df, _it["expr"])
            _rows.append((_it, _v, _err))
        _cols = st.columns(min(4, len(_rows)))
        for _i, (_it, _v, _err) in enumerate(_rows):
            with _cols[_i % len(_cols)]:
                _shown = CM.fmt_value(_v) if not _err else "—"
                _sub = _it["expr"][:40] if not _err else _err[:32]
                st.markdown(f"<div class='kpi'><div class='kpi-label'>{_it['name']}</div>"
                            f"<div class='kpi-value'>{_shown}</div>"
                            f"<div class='kpi-sub'>{_sub}</div></div>", unsafe_allow_html=True)
        _del_cols = st.columns(min(4, len(_rows)))
        for _i, (_it, _v, _err) in enumerate(_rows):
            with _del_cols[_i % len(_del_cols)]:
                if st.button(f"删除「{_it['name']}」", key=f"cm_del_{_i}"):
                    st.session_state["_custom"] = [c for c in st.session_state["_custom"]
                                                   if c["name"] != _it["name"]]
                    st.rerun()

    st.markdown("<div class='sect'>指标口径字典<small>每个数字是怎么算出来的</small></div>",
                unsafe_allow_html=True)
    render_metric_dict(metric, qty_c, cost_c, oc, dc, refund_mode, gran,
                       order_key_mode, tie_mode, aov_mode, cost_force)

    with st.expander("查看列信息（自动识别的类型）"):
        kind_name = {"date": "日期", "num": "数值", "cat": "类别", "text": "文本", "id": "编号/ID",
                     "calc": "计算列"}
        st.dataframe(pd.DataFrame([{
            "列名": c, "识别类型": kind_name.get(kinds.get(c, "text"), kinds.get(c, "text")),
            "非空": int(df[c].notna().sum()), "缺失": int(df[c].isna().sum()),
            "唯一值": int(df[c].nunique()),
            "示例": str(df[c].dropna().iloc[0])[:24] if df[c].notna().any() else ""
        } for c in df.columns]), width="stretch", hide_index=True)

    with st.expander("查看数据明细（前 200 行）"):
        st.dataframe(df.head(200), width="stretch")
        st.download_button("下载当前数据 CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"分析数据_{sheet}.csv", mime="text/csv")

    with st.expander("导出汇报 PPT（含图表与解读）", expanded=False):
        st.caption("按公司汇报格式生成：封面 / 执行摘要 / 核心指标 / 趋势 / 品类结构 / 毛利率 / "
                   "Top 商品 / 改善建议 / 附录口径，每张图配解读。图表为图片，可直接投屏。")
        if PE is not None:
            st.caption(f"图表中文字体：{getattr(PE, '_FONT', '未知')}"
                       + ("（未找到中文字体，图表里的中文会变成方框）" if getattr(PE, "_FONT", "") == "DejaVu Sans" else ""))
        if st.button("生成 PPT", key="mk_ppt"):
            with st.spinner("正在生成 PPT…"):
                try:
                    st.session_state["_ppt_bytes"] = PE.build_deck(
                        df, metric=metric, qty_col=qty_c, cost_col=cost_c,
                        cost_force=_cost_force, date_col=dc, item_col=detail,
                        big_col=big, order_col=oc, gran=gran,
                        target=float(target_amount or 0),
                        title="经营分析报告",
                        company=f"{sheet or '销售'} · 经营数据分析")
                except Exception as _e:
                    st.error(f"生成失败：{_e}")
        if st.session_state.get("_ppt_bytes"):
            st.download_button(
                "⬇ 下载 PPT", st.session_state["_ppt_bytes"],
                file_name=f"经营分析报告_{datetime.now():%Y%m%d_%H%M}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key="dl_ppt")

    with st.expander("导出 Excel（多工作表）"):
        st.caption("包含：核心指标、数据体检、业务总结、数据明细（前 5000 行）。")
        if st.button("生成 Excel", key="mk_xlsx"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                pd.DataFrame(items, columns=["指标", "值", "说明"]).to_excel(
                    w, sheet_name="核心指标", index=False)
                if health:
                    pd.DataFrame(health).rename(
                        columns={"level": "级别", "title": "项目", "text": "说明"}
                    )[["级别", "项目", "说明"]].to_excel(w, sheet_name="数据体检", index=False)
                if sums:
                    pd.DataFrame([{"标题": s["title"], "内容": s["text"]} for s in sums]).to_excel(
                        w, sheet_name="业务总结", index=False)
                _cust = st.session_state.get("_custom") or []
                if _cust:
                    _cr = []
                    for _it in _cust:
                        _v, _err = CM.evaluate(df, _it["expr"])
                        _cr.append({"指标": _it["name"], "公式": _it["expr"],
                                    "值": round(_v, 4) if _v is not None else None,
                                    "错误": _err or ""})
                    pd.DataFrame(_cr).to_excel(w, sheet_name="自定义指标", index=False)
                df.head(5000).to_excel(w, sheet_name="数据明细", index=False)
            st.session_state["_xlsx"] = buf.getvalue()
        if st.session_state.get("_xlsx"):
            st.download_button(
                "⬇ 下载 Excel",
                st.session_state["_xlsx"],
                file_name=f"分析结果_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
