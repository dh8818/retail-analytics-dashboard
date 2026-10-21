# -*- coding: utf-8 -*-
"""
统一样式与数字格式（原先 app.py / qa_engine.py / extra_sections.py 各抄了一份）
改配色、改数字缩写规则，只改这里。
"""
import numpy as np
# Power BI 配色
BI_BLUE, BI_NAVY = "#2E75B6", "#1F3864"
PALETTE = ["#1F3864", "#2E75B6", "#548235", "#C55A11", "#7030A0",
           "#BF8F00", "#7F7F7F", "#9DC3E6"]

CARD_BG, PAGE_BG = "#FFFFFF", "#F5F6F8"
TEXT, MUTED, GRID = "#1F2328", "#5F6672", "#E3E6EA"
FONT = "Segoe UI, Microsoft YaHei, sans-serif"
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
    if legend:
        fig.update_layout(legend=dict(orientation="h", y=1.09, x=1, xanchor="right",
                                      font=dict(size=11, color=MUTED)))
    return fig
