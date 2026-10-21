# -*- coding: utf-8 -*-
"""
导出「可直接汇报」的 PPT：16:9、公司汇报格式，每张图表配解读。

用法（在 Streamlit 里点按钮，或直接跑）：
    python ppt_export.py 数据.xlsx 报告.pptx
"""
import io
import os
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

import advice as ADV

# ---------------- 视觉规范 ----------------
NAVY = RGBColor(0x12, 0x23, 0x9E)
BLUE = RGBColor(0x11, 0x8D, 0xFF)
DARK = RGBColor(0x25, 0x24, 0x23)
GRAY = RGBColor(0x60, 0x5E, 0x5C)
LIGHT = RGBColor(0xF3, 0xF2, 0xF1)
RULE = RGBColor(0xDD, 0xDB, 0xDA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x10, 0x7C, 0x10)
RED = RGBColor(0xD6, 0x45, 0x50)
ORANGE = RGBColor(0xE6, 0x6C, 0x37)

HEX = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2", "#D9B300", "#D64550"]
FONT = "Microsoft YaHei"

W, H = 13.333, 7.5


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _fmt(v, unit="元"):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    a = abs(v)
    if a >= 1e8:
        return f"{v/1e8:.2f} 亿"
    if a >= 1e4:
        return f"{v/1e4:.2f} 万"
    return f"{v:,.0f}" if a >= 100 else f"{v:,.2f}"


# ---------------- 图表（matplotlib → PNG） ----------------
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _save(fig, path):
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def chart_trend(x, rev, profit, path):
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.bar(x, rev, color="#CFE4FF", width=0.62, label="销售收入")
    ax2 = ax.twinx()
    ax2.plot(x, profit, color="#12239E", lw=2.2, marker="o", ms=3.5, label="毛利")
    ax.set_ylabel("销售收入（元）", color="#605E5C", fontsize=9)
    ax2.set_ylabel("毛利（元）", color="#12239E", fontsize=9)
    ax.tick_params(colors="#605E5C", labelsize=8)
    ax2.tick_params(colors="#12239E", labelsize=8)
    for s in ["top"]:
        ax.spines[s].set_visible(False); ax2.spines[s].set_visible(False)
    ax.spines["left"].set_color("#DDDBDA"); ax.spines["bottom"].set_color("#DDDBDA")
    ax2.spines["right"].set_color("#DDDBDA")
    ax.grid(axis="y", color="#EDEBE9", lw=0.8)
    ax.set_axisbelow(True)
    step = max(len(x) // 7, 1)
    idx = list(range(0, len(x), step))
    labs = [str(v).replace("-", "/")[2:] for v in x]
    ax.set_xticks(idx)
    ax.set_xticklabels([labs[i] for i in idx], rotation=40, ha="right", fontsize=7.6)
    return _save(fig, path)


def chart_donut(labels, values, path):
    fig, ax = plt.subplots(figsize=(3.9, 3.6))
    wedges, _ = ax.pie(values, colors=HEX[:len(labels)], startangle=90,
                       wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5))
    total = sum(values) or 1
    ax.text(0, 0.08, "合计", ha="center", va="center", fontsize=9, color="#605E5C")
    ax.text(0, -0.12, _fmt(total), ha="center", va="center", fontsize=13, color="#252423", weight="bold")
    ax.legend(wedges, [f"{l}  {v/total*100:.0f}%" for l, v in zip(labels, values)],
              loc="center left", bbox_to_anchor=(0.98, 0.5), fontsize=8.5, frameon=False)
    return _save(fig, path)


def chart_pareto(labels, values, path, top=10):
    s = pd.Series(values, index=labels).sort_values(ascending=False).head(top)
    cum = s.cumsum() / s.sum() * 100
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.bar(range(len(s)), s.values, color="#118DFF", width=0.62)
    ax2 = ax.twinx()
    ax2.plot(range(len(s)), cum.values, color="#E66C37", lw=2, marker="o", ms=3.5)
    ax2.axhline(80, color="#D9B300", ls="--", lw=1)
    ax2.set_ylim(0, 105)
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([str(v)[:6] for v in s.index], rotation=35, ha="right", fontsize=8)
    ax.tick_params(colors="#605E5C", labelsize=8)
    ax2.tick_params(colors="#E66C37", labelsize=8)
    ax.spines["top"].set_visible(False); ax2.spines["top"].set_visible(False)
    ax.grid(axis="y", color="#EDEBE9", lw=0.8); ax.set_axisbelow(True)
    return _save(fig, path)


def chart_hbar(labels, values, path, color="#118DFF", height=3.4, title_unit="元"):
    fig, ax = plt.subplots(figsize=(7.2, height))
    order = np.argsort(values)
    labs = [str(labels[i])[:12] for i in order]
    vals = [values[i] for i in order]
    bars = ax.barh(range(len(vals)), vals, color=color, height=0.62)
    ax.set_yticks(range(len(vals)))
    ax.set_yticklabels(labs, fontsize=8.5)
    for b, v in zip(bars, vals):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {_fmt(v)}", va="center", fontsize=7.5, color="#605E5C")
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDDBDA"); ax.spines["bottom"].set_color("#DDDBDA")
    ax.grid(axis="x", color="#EDEBE9", lw=0.8); ax.set_axisbelow(True)
    ax.tick_params(colors="#605E5C", labelsize=8)
    return _save(fig, path)


def chart_margin(labels, margins, path):
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    order = np.argsort(margins)[::-1]
    labs = [str(labels[i])[:10] for i in order]
    vals = [margins[i] * 100 for i in order]
    colors = ["#118DFF" if v >= 0 else "#D64550" for v in vals]
    bars = ax.bar(range(len(vals)), vals, color=colors, width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}%",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8, color="#605E5C")
    ax.set_xticks(range(len(vals))); ax.set_xticklabels(labs, fontsize=8.5)
    ax.axhline(0, color="#DDDBDA", lw=1)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#EDEBE9", lw=0.8); ax.set_axisbelow(True)
    ax.tick_params(colors="#605E5C", labelsize=8)
    return _save(fig, path)


# ---------------- 版式助手 ----------------
def _text(slide, left, top, width, height, text, size=12, bold=False, color=DARK,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.15):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.bold = bold
        r.font.color.rgb = color; r.font.name = FONT
    return box


def _rect(slide, left, top, width, height, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top),
                                 Inches(width), Inches(height))
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


def _header(slide, title, kicker=None):
    _rect(slide, 0, 0, W, 0.06, NAVY)
    if kicker:
        _text(slide, 0.6, 0.34, 8, 0.28, kicker, size=10, color=GRAY)
    _text(slide, 0.6, 0.62 if kicker else 0.42, 11.5, 0.5, title, size=21, bold=True, color=DARK)
    line = slide.shapes.add_connector(1, Inches(0.6), Inches(1.22), Inches(W - 0.6), Inches(1.22))
    line.line.color.rgb = RULE; line.line.width = Pt(0.75)


def _footer(slide, page, note="数据来源：本表销售明细"):
    _text(slide, 0.6, H - 0.45, 8, 0.25, note, size=8.5, color=GRAY)
    _text(slide, W - 1.4, H - 0.45, 0.8, 0.25, f"{page:02d}", size=9, color=GRAY, align=PP_ALIGN.RIGHT)


def _insight_panel(slide, bullets, left=9.35, top=1.55, width=3.35, height=4.6,
                   title="解读"):
    _rect(slide, left, top, width, height, LIGHT)
    _rect(slide, left, top, 0.05, height, BLUE)
    _text(slide, left + 0.28, top + 0.22, width - 0.5, 0.3, title, size=11.5, bold=True, color=NAVY)
    y = top + 0.66
    usable = width - 0.5
    size = 9.8
    for b in bullets[:5]:
        # 中文按 1 个字宽 ≈ 字号，估算折成几行
        per_line = max(int(usable / (size / 72)), 8)
        lines = max(1, int(np.ceil(len(b) / per_line)))
        h = lines * size * 1.35 / 72 + 0.12
        _text(slide, left + 0.28, y, usable, h, "· " + b, size=size, color=DARK, spacing=1.28)
        y += h + 0.12


def _kpi_block(slide, left, top, width, label, value, sub, color=NAVY):
    _rect(slide, left, top, width, 1.5, WHITE, line=RULE)
    _rect(slide, left, top, 0.055, 1.5, color)
    _text(slide, left + 0.22, top + 0.16, width - 0.4, 0.25, label, size=10, color=GRAY)
    _text(slide, left + 0.22, top + 0.46, width - 0.4, 0.55, value, size=25, bold=True, color=DARK)
    _text(slide, left + 0.22, top + 1.08, width - 0.4, 0.28, sub, size=9, color=GRAY)


def _chart_slide(prs, title, kicker, page, png, bullets, caption="", note="",
                 img_width=8.4, img_top=1.45):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _header(slide, title, kicker)
    if png and os.path.exists(png):
        slide.shapes.add_picture(png, Inches(0.6), Inches(img_top), width=Inches(img_width))
    if caption:
        _text(slide, 0.6, 6.45, 8.4, 0.3, caption, size=9, color=GRAY)
    _insight_panel(slide, bullets)
    _footer(slide, page, note or "数据来源：本表销售明细")
    return slide


# ---------------- 主流程 ----------------
def build_deck(df, metric="金额", qty_col=None, cost_col=None, cost_force="auto",
               date_col=None, item_col=None, big_col=None, order_col=None,
               gran="月", target=0.0, title="经营分析报告", company="", deck_note="") -> bytes:
    """返回 pptx 的二进制内容。任何一段算不出来就跳过那一页，不会整份失败。"""
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)

    tmp = tempfile.mkdtemp(prefix="deck_")
    rev_total = float(_num(df[metric]).sum()) if metric in df.columns else 0.0
    qty_total = float(_num(df[qty_col]).sum()) if qty_col and qty_col in df.columns else float(len(df))

    cost_total = None
    margin = None
    if cost_col and cost_col in df.columns:
        c = _num(df[cost_col])
        if cost_force != "total" and qty_col and qty_col in df.columns:
            c = c * _num(df[qty_col])
        cost_total = float(c.sum())
        if rev_total:
            margin = (rev_total - cost_total) / rev_total

    # ---- 期间 ----
    span = ""
    if date_col and date_col in df.columns:
        d = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if len(d):
            span = f"{d.min():%Y-%m-%d} — {d.max():%Y-%m-%d}"

    # ================= 1. 封面 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(s, 0, 0, W, H, RGBColor(0xF7, 0xF9, 0xFC))
    _rect(s, 0, 0, 0.28, H, NAVY)
    _text(s, 1.0, 1.55, 10.5, 0.35, company or "月度经营回顾 · 数据分析", size=12, color=GRAY)
    _text(s, 1.0, 2.0, 10.8, 1.0, title, size=38, bold=True, color=DARK)
    _rect(s, 1.0, 3.06, 1.6, 0.05, BLUE)
    _text(s, 1.0, 3.32, 10.5, 0.75,
          f"数据区间：{span or '见明细'}\n分析口径：行级销售明细，金额口径为净额（含退款）",
          size=12.5, color=GRAY, spacing=1.5)
    _text(s, 1.0, 6.42, 10.5, 0.6,
          f"数据规模：{len(df):,} 行 ｜ 生成时间：{datetime.now():%Y-%m-%d %H:%M}" +
          (f"\n{deck_note}" if deck_note else ""),
          size=10, color=GRAY, spacing=1.4)

    # ---- 数据准备 ----
    adv_list = ADV.build_advice(df, metric, qty_col, cost_col, cost_force, date_col,
                               item_col, big_col, order_col, target)
    # 月度
    trend = None
    period_col = None
    if date_col and date_col in df.columns:
        dts = pd.to_datetime(df[date_col], errors="coerce")
        if dts.notna().sum() > 10:
            period_col = dts.dt.to_period("M").astype(str)
            g = df.assign(_p=period_col)
            trend = g.groupby("_p")[metric].sum()
            if cost_col and cost_col in df.columns:
                cc = _num(df[cost_col])
                if cost_force != "total" and qty_col and qty_col in df.columns:
                    cc = cc * _num(df[qty_col])
                trend_profit = trend - cc.groupby(g["_p"]).sum()   # trend 是按期汇总的序列，不能再用 .sum()
            else:
                trend_profit = None

    # 品类
    cat = None
    if big_col and big_col in df.columns:
        cat = df.groupby(big_col)[metric].sum().sort_values(ascending=False)
        cat = cat[cat > 0].head(8)
    cat_margin = None
    if big_col and big_col in df.columns and cost_col and cost_col in df.columns:
        try:
            cc = _num(df[cost_col])
            if cost_force != "total" and qty_col and qty_col in df.columns:
                cc = cc * _num(df[qty_col])
            g = df.assign(_c=cc).groupby(big_col).agg(rev=(metric, "sum"), cost=("_c", "sum"))
            g = g[g["rev"] > 0]
            cat_margin = (g["rev"] - g["cost"]) / g["rev"]
        except Exception:
            pass

    # 商品
    item = None
    if item_col and item_col in df.columns:
        item = df.groupby(item_col)[metric].sum().sort_values(ascending=False)
        item = item[item > 0]

    # ================= 2. 执行摘要 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, "执行摘要", "EXECUTIVE SUMMARY")
    summary = []
    line1 = f"本期销售收入 {_fmt(rev_total)}，销售数量 {_fmt(qty_total)} 件"
    if margin is not None:
        line1 += f"，毛利 {_fmt(rev_total - cost_total)}，毛利率 {margin*100:.1f}%"
    summary.append(line1)
    if trend is not None and len(trend) >= 2:
        last, prev = trend.iloc[-1], trend.iloc[-2]
        chg = (last - prev) / prev * 100 if prev else 0
        summary.append(f"最近一期（{trend.index[-1]}）收入 {_fmt(last)}，环比 {chg:+.1f}%；"
                       f"期间最高为 {trend.idxmax()}（{_fmt(trend.max())}）")
    if cat is not None and len(cat):
        share = cat.iloc[0] / cat.sum() * 100
        summary.append(f"品类结构上「{cat.index[0]}」贡献 {share:.0f}% 收入，前 3 类合计 "
                       f"{cat.head(3).sum()/cat.sum()*100:.0f}%")
    if cat_margin is not None and len(cat_margin):
        best = cat_margin.idxmax(); worst = cat_margin.idxmin()
        summary.append(f"毛利最高的是「{best}」（{cat_margin[best]*100:.1f}%），"
                       f"最低的是「{worst}」（{cat_margin[worst]*100:.1f}%）")
    if adv_list:
        summary.append(f"优先处理：{adv_list[0]['title']}")

    y = 1.55
    for i, t in enumerate(summary[:5], 1):
        _text(s, 0.6, y, 0.42, 0.4, f"{i}", size=14, bold=True, color=BLUE)
        _text(s, 1.05, y, 11.4, 0.75, t, size=13, color=DARK, spacing=1.3)
        y += 0.95
    _footer(s, 2)

    # ================= 3. 核心指标 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, "核心指标", "KEY METRICS")
    gap = 0.28
    cw = (W - 1.2 - gap * 3) / 4
    vals = [("销售收入", _fmt(rev_total), "净额（含退款）", BLUE),
            ("毛利", _fmt(rev_total - cost_total) if cost_total is not None else "—",
             "收入 − 成本", NAVY),
            ("毛利率", f"{margin*100:.1f}%" if margin is not None else "—",
             "毛利 ÷ 收入", RGBColor(0x10, 0x7C, 0x10)),
            ("销售数量", f"{qty_total:,.0f}", "件", ORANGE)]
    for i, (lab, v, sub, color) in enumerate(vals):
        _kpi_block(s, 0.6 + i * (cw + gap), 1.6, cw, lab, v, sub, color)

    _text(s, 0.6, 3.55, 12.1, 0.35, "指标说明", size=12, bold=True, color=NAVY)
    notes = [
        f"销售收入 = 金额列求和（含退款负额），本期 {_fmt(rev_total)}",
        f"成本 = {'单价 × 数量' if cost_force != 'total' else '成本列求和'}，合计 {_fmt(cost_total) if cost_total is not None else '—'}",
        f"毛利率 = 毛利 ÷ 收入 = {f'{margin*100:.2f}%' if margin is not None else '—'}（商品毛利，未扣人工房租）",
        f"销售数量 = 数量列求和 = {qty_total:,.0f} 件；订单数按订单号去重",
    ]
    yy = 3.98
    for n in notes:
        _text(s, 0.75, yy, 11.8, 0.32, "· " + n, size=11, color=DARK)
        yy += 0.42
    _footer(s, 3)

    # ================= 4. 趋势 =================
    page = 4
    if trend is not None and len(trend) >= 3:
        png = chart_trend(list(trend.index), list(trend.values),
                          list(trend_profit.values) if trend_profit is not None else [0] * len(trend),
                          os.path.join(tmp, "trend.png"))
        peak, low = trend.idxmax(), trend.idxmin()
        amp = (trend.max() - trend.min()) / trend.mean() * 100 if trend.mean() else 0
        bl = [f"峰值在 {peak}，{_fmt(trend.max())}；谷值在 {low}，{_fmt(trend.min())}",
              f"波动幅度为均值的 {amp:.0f}%，" + ("季节性明显" if amp > 40 else "整体较平稳"),
              f"最近一期 {trend.index[-1]} 为 {_fmt(trend.iloc[-1])}"]
        if trend_profit is not None and len(trend_profit):
            m_last = trend_profit.iloc[-1] / trend.iloc[-1] * 100 if trend.iloc[-1] else 0
            bl.append(f"最近一期毛利率 {m_last:.1f}%，与整体 {margin*100:.1f}% "
                      f"{'基本一致' if abs(m_last - (margin*100 if margin else 0)) < 3 else '存在偏离'}" if margin else
                      f"最近一期毛利 {_fmt(trend_profit.iloc[-1])}")
        _chart_slide(prs, "销售收入与毛利趋势", "TREND", page, png, bl,
                     caption="柱：销售收入　线：毛利", note="数据来源：销售明细按自然月汇总")
        page += 1

    # ================= 5. 品类结构 =================
    if cat is not None and len(cat) >= 2:
        png = chart_donut(list(cat.index), list(cat.values), os.path.join(tmp, "donut.png"))
        share1 = cat.iloc[0] / cat.sum() * 100
        share3 = cat.head(3).sum() / cat.sum() * 100
        cres = df.groupby(item_col)[metric].sum() if item_col and item_col in df.columns else None
        bl = [f"「{cat.index[0]}」占收入 {share1:.0f}%，为第一大品类",
              f"前 3 类合计 {share3:.0f}%，" + ("集中度偏高，需关注单一品类风险" if share3 > 75 else "结构相对分散"),
              f"共 {len(df[big_col].dropna().unique())} 个品类在售" if big_col else ""]
        if cres is not None and len(cres) >= 5:
            k = max(int(len(cres) * 0.2), 1)
            bl.append(f"{k} 个商品贡献 {cres.head(k).sum()/cres.sum()*100:.0f}% 收入（头部集中度）")
        _chart_slide(prs, "品类收入结构", "STRUCTURE", page, png, [b for b in bl if b],
                     caption="按销售收入占比排序，仅显示前 8 个品类",
                     img_width=6.6, img_top=1.55)
        page += 1

        if cat_margin is not None and len(cat_margin) >= 2:
            png2 = chart_margin(list(cat_margin.index), list(cat_margin.values),
                                os.path.join(tmp, "margin.png"))
            best, worst = cat_margin.idxmax(), cat_margin.idxmin()
            bl2 = [f"「{best}」毛利率最高（{cat_margin[best]*100:.1f}%），是利润主力",
                   f"「{worst}」最低（{cat_margin[worst]*100:.1f}%），"
                   + ("低于 20%，属于引流品而非利润品" if cat_margin[worst] < 0.2 else "仍有改善空间"),
                   f"整体毛利率 {margin*100:.1f}%" if margin is not None else ""]
            _chart_slide(prs, "各品类毛利率", "PROFITABILITY", page, png2, [b for b in bl2 if b],
                         caption="毛利率 = （收入 − 成本）÷ 收入")
            page += 1

    # ================= 6. 商品表现 =================
    if item is not None and len(item) >= 5:
        top = item.head(10)
        png = chart_hbar(list(top.index), list(top.values), os.path.join(tmp, "top.png"))
        share_top = top.sum() / item.sum() * 100
        bl = [f"销量第一是「{top.index[0]}」，{_fmt(top.iloc[0])}",
              f"前 10 个商品合计占收入 {share_top:.0f}%",
              f"在售商品 {len(item)} 个，" + ("头部依赖明显，需保证 A 类不断货"
                                          if share_top > 50 else "长尾较多，可考虑精简 SKU")]
        _chart_slide(prs, "畅销商品 Top 10", "PRODUCTS", page, png, bl,
                     caption="按销售收入排序")
        page += 1

    # ================= 7. 改善建议 =================
    if adv_list:
        s = prs.slides.add_slide(prs.slide_layouts[6])
        _header(s, "改善建议", "RECOMMENDATIONS")
        show = adv_list[:4]
        col_w = (W - 1.2 - 0.3 * (len(show) - 1)) / len(show)
        for i, a in enumerate(show):
            x = 0.6 + i * (col_w + 0.3)
            color = {"高": RED, "中": ORANGE, "低": GREEN}.get(a["sev"], GRAY)
            _rect(s, x, 1.5, col_w, 4.95, WHITE, line=RULE)
            _rect(s, x, 1.5, col_w, 0.075, color)
            _text(s, x + 0.2, 1.68, col_w - 0.4, 0.26, f"优先级 {a['sev']}", size=9, color=color, bold=True)
            _text(s, x + 0.2, 1.98, col_w - 0.4, 0.9, a["title"], size=11.5, bold=True, color=DARK,
                  spacing=1.2)
            _text(s, x + 0.2, 3.0, col_w - 0.4, 0.26, "依据", size=8.5, color=GRAY, bold=True)
            _text(s, x + 0.2, 3.26, col_w - 0.4, 1.05, a["evidence"], size=8.8, color=DARK, spacing=1.2)
            _text(s, x + 0.2, 4.36, col_w - 0.4, 0.26, "怎么做", size=8.5, color=GRAY, bold=True)
            _text(s, x + 0.2, 4.62, col_w - 0.4, 1.1, a["action"], size=8.8, color=DARK, spacing=1.2)
            _text(s, x + 0.2, 5.86, col_w - 0.4, 0.5, a["impact"], size=8.5, color=GRAY, spacing=1.15)
        _footer(s, page)
        page += 1

    # ================= 8. 附录：口径 =================
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _header(s, "附录：口径与方法", "APPENDIX")
    rows = [("指标", "计算方式", "说明"),
            ("销售收入", f"Σ「{metric}」", "退款行（负额）计入，为净销售额"),
            ("成本", "Σ(单价 × 数量) 或 Σ 成本列", "不含人工、房租、平台佣金"),
            ("毛利 / 毛利率", "收入 − 成本；毛利 ÷ 收入", "商品毛利，非净利"),
            ("销售数量", f"Σ「{qty_col}」" if qty_col else "无数量列", "退货负数量冲减"),
            ("订单数", "订单号去重（跨期重复时加日期）", "纯退款单不计入"),
            ("结构占比", "某维度金额 ÷ 总金额", "环形图、帕累托同口径")]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.5),
                             Inches(W - 1.2), Inches(0.42 * len(rows))).table
    tbl.columns[0].width = Inches(2.2)
    tbl.columns[1].width = Inches(5.4)
    tbl.columns[2].width = Inches(4.5)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = str(val)
            cell.margin_left = Inches(0.08)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9.5 if r else 10)
                    run.font.name = FONT
                    run.font.bold = (r == 0)
                    run.font.color.rgb = WHITE if r == 0 else DARK
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r == 0 else (WHITE if r % 2 else RGBColor(0xF7, 0xF9, 0xFC))

    q = [f"数据行数：{len(df):,}", f"时间范围：{span or '—'}",
         f"字段数：{len(df.columns)}", f"重复行：{int(df.duplicated().sum()):,}"]
    _text(s, 0.6, 5.35, 12.1, 0.3, "数据质量", size=12, bold=True, color=NAVY)
    _text(s, 0.6, 5.7, 12.1, 0.9, "　｜　".join(q), size=10, color=GRAY)
    _footer(s, page)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "data/pos.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "output/经营分析报告.pptx"
    d = pd.read_csv(src) if src.endswith(".csv") else pd.read_excel(src)
    cols = list(d.columns)
    pick = lambda hs, ex=None: next((c for c in cols if any(h in str(c) for h in hs)), ex)
    _metric = next((c for c in cols if any(h in str(c) for h in ("金额", "销售额", "实收", "收入"))),
                   cols[-1])
    data = build_deck(d, metric=_metric,
                      qty_col="数量", cost_col="成本", cost_force="total",
                      date_col="日期", item_col="名称" if "名称" in cols else pick(["商品"]),
                      big_col="品类", order_col="订单号")
    open(out, "wb").write(data)
    print("已生成", out, len(data), "bytes")
