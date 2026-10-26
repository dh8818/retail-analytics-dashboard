# -*- coding: utf-8 -*-
"""
统一样式与数字格式（原先 app.py / qa_engine.py / extra_sections.py 各抄了一份）
改配色、改数字缩写规则，只改这里。

设计基调：暖「陶土 / 奶白」风 —— 参考 Claude 官网的视觉语言：
奶白底色、陶土主色、柔和阴影、克制的动效、清晰的排版层级与充足留白。
"""
import numpy as np

# ---------- 主色：陶土（主强调）+ 深墨（中性强调） ----------
BI_BLUE = "#C9744F"   # 浅陶土：次级强调（insight / sumcard 左边框、hover）
BI_NAVY = "#B85532"   # 深陶土：主强调（主按钮、KPI 数值、区块标记、激活态）

# 分类色板：暖色为主，掺少量冷色保证多系列图表可区分
PALETTE = ["#B85532", "#3F382D", "#6F8A63", "#C08A3E",
           "#5F7A96", "#8E6B7C", "#4E7E7A", "#9A9084"]

# ---------- 语义色：好 / 坏 / 警示（保留红=负、绿=正的业务语义） ----------
GOOD = "#4F7A55"       # 正向（低风险 / 盈利 / 达成）
BAD = "#A84A42"        # 负向（高风险 / 亏损 / 未达成）
WARN = "#B9812F"       # 警示（中等 / 提醒）

# ---------- 背景与文本 ----------
CARD_BG, PAGE_BG = "#FFFFFF", "#F7F4EE"
TEXT, MUTED, GRID = "#2A2723", "#6E685E", "#E8E2D8"
ACCENT_SOFT = "#F6EBE3"   # 陶土淡底（提示条 / 高亮）
FONT = ('system-ui, -apple-system, "Segoe UI", "PingFang SC", '
        '"Microsoft YaHei", "Hiragino Sans GB", sans-serif')
MODEBAR = {"displayModeBar": False}


def fmt(v):
    """数字缩写：亿 / 万 / 千分位，None 和 NaN 返回破折号。"""
    try:
        v = float(v)
    except Exception:
        return "—"
    if np.isnan(v) or np.isinf(v):
        return "—"
    a = abs(v)
    if a >= 1e8:
        return f"{v/1e8:.2f}亿"
    if a >= 1e4:
        return f"{v/1e4:.2f}万"
    if a >= 100:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def fig_base(fig, height=330, title=None, legend=False):
    """统一图表底样式：白底、去网格、标题左上、图例置顶。"""
    fig.update_layout(
        height=height,
        margin=dict(l=16, r=16, t=48 if title else 16, b=14),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(family=FONT, size=12, color=TEXT),
        title=dict(text=title, font=dict(size=13.5, color=MUTED), x=0.015, y=0.97) if title else None,
        hoverlabel=dict(bgcolor="white", font_size=12, font_family=FONT),
        showlegend=legend,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID,
                     tickfont=dict(color=MUTED, size=11))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED, size=11))

    # 柱状图必须零基线：否则 12 和 15 看起来差 3 倍（视觉误导）
    bars = [t for t in fig.data if getattr(t, "type", "") == "bar"]
    if bars:
        horizontal = [getattr(t, "orientation", None) for t in bars]
        if all(o == "h" for o in horizontal):
            fig.update_xaxes(rangemode="tozero")
        else:
            fig.update_yaxes(rangemode="tozero")
    if legend:
        fig.update_layout(legend=dict(orientation="h", y=1.09, x=1, xanchor="right",
                                      font=dict(size=11, color=MUTED)))
    return fig
