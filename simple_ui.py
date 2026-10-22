# -*- coding: utf-8 -*-
"""老板视角：一屏说清「赚没赚、漏在哪、改什么」。

设计原则：
1. 只回答三个问题，不出现任何需要解释才能懂的词
2. 数字后面必须跟一句人话（比上月多/少、占比多少）
3. 每条动作都有「做什么 + 能省多少/多赚多少」
4. 全部结论可以一键复制成微信消息，老板直接转发
"""
from datetime import timedelta

import pandas as pd
import streamlit as st

from style import MUTED

# 术语翻译：出现专业词时，旁边永远有一句人话
TERMS = {
    "销售收入": "卖了多少钱（含退款冲减后的净额）",
    "毛利": "卖价减去进货成本，还没扣房租和人工",
    "毛利率": "每卖 100 块，能剩下多少毛利",
    "客单价": "平均每个顾客一次花多少钱",
    "连带率": "平均一单买几件",
    "订单数": "做了多少单生意",
    "动销": "这个商品这段时间有没有卖出去过",
    "滞销": "很久没卖动的货，占着钱",
    "报损": "过期或破损只能扔掉的货",
    "周转天数": "按现在的卖法，这批货要多少天才能卖完",
}

_LEVEL = {"高": "#B42318", "中": "#B54708", "低": "#067647"}


def _money(v):
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 10000:
        return f"{v/10000:.1f} 万"
    return f"{v:,.0f}"


def _pct(v, digits=1):
    return "—" if v is None or pd.isna(v) else f"{v:.{digits}f}%"


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _period(df, dc):
    """把数据切成「最近一段时间」和「上一段同样长的时间」。"""
    d = df.dropna(subset=[dc]).copy()
    if d.empty:
        return None
    dmax = d[dc].max()
    # 按数据实际跨度取：不足 45 天就按半月比，否则按月
    span_days = (dmax - d[dc].min()).days + 1
    if span_days <= 45:
        cur_start = dmax - pd.Timedelta(days=14)
    else:
        cur_start = dmax - pd.Timedelta(days=29)
    cur = d[d[dc] >= cur_start]
    prev_start = cur_start - (dmax - cur_start) - pd.Timedelta(days=1)
    prev = d[(d[dc] >= prev_start) & (d[dc] < cur_start)]
    return {"cur": cur, "prev": prev, "dmax": dmax, "cur_start": cur_start,
            "days": (dmax - cur_start).days + 1,
            "prev_days": (cur_start - prev_start).days}


def _wechat_text(head, metrics, blocks, advice):
    lines = [f"【{head}】", ""]
    lines += [f"· {k}：{v}" for k, v in metrics]
    for title, body in blocks:
        lines.append(f"\n{title}：{body}")
    if advice:
        lines.append("\n建议动作：")
        for i, a in enumerate(advice[:3], 1):
            lines.append(f"{i}. {a['title']} —— {a['action']}")
    lines.append("\n（数据来自门店销售明细，口径见工具内说明）")
    return "\n".join(lines)


def _period_cost(d, cost_col, qty_col, force="auto"):
    """同一区间的成本：单价要乘数量，总额直接加。返回 None 表示算不了。"""
    if not cost_col or cost_col not in d.columns:
        return None
    c = _num(d[cost_col])
    if force != "total" and qty_col and qty_col in d.columns:
        c = c * _num(d[qty_col])
    v = float(c.sum())
    return v if pd.notna(v) else None


def render(df, metric, date_col, big_col, detail_col, qty_col, cost_col,
           sales, profit, margin, advice_list, order_col=None, cost_force="auto"):
    if not date_col or date_col not in df.columns:
        st.info("这份数据里没有日期列，做不了「这个月比上个月」。请确认导入的明细里有下单日期。")
        return

    per = _period(df, date_col)
    if per is None:
        st.info("没有可用的日期，无法生成经营快报。")
        return

    cur, prev = per["cur"], per["prev"]
    cur_rev = float(_num(cur[metric]).sum()) if metric in cur else 0.0
    prev_rev = float(_num(prev[metric]).sum()) if metric in prev else 0.0
    chg = (cur_rev / prev_rev - 1) * 100 if prev_rev else None

    orders = int(cur[order_col].nunique()) if order_col and order_col in cur else 0
    aov = cur_rev / orders if orders else None

    # 毛利必须和收入是同一段时间，否则会出现「毛利比收入还大」
    cur_cost = _period_cost(cur, cost_col, qty_col, cost_force)
    cur_profit = (cur_rev - cur_cost) if cur_cost is not None else None
    if cur_cost is not None and cur_rev and abs(cur_cost - cur_rev) / cur_rev < 0.005:
        cur_profit = None                     # 成本列与金额同源，算不出真毛利
    cur_margin = (cur_profit / cur_rev * 100) if (cur_profit is not None and cur_rev) else None
    profit, margin = cur_profit, cur_margin

    # ---- 钱从哪来 ----
    cat_txt, cat_more = "", ""
    if big_col and big_col in cur.columns:
        s = cur.groupby(big_col)[metric].sum().sort_values(ascending=False)
        top = s.head(3)
        cat_txt = "、".join(f"{k} {v/max(s.sum(),1)*100:.0f}%" for k, v in top.items())
        cat_more = f"前 3 个品类占了全部收入的 {top.sum()/max(s.sum(),1)*100:.0f}%"

    # 下滑归因：哪个品类掉得最多
    drop_txt = ""
    if big_col and big_col in cur.columns and prev_rev:
        cs = cur.groupby(big_col)[metric].sum()
        ps = prev.groupby(big_col)[metric].sum()
        diff = (cs - ps.reindex(cs.index).fillna(0)).sort_values()
        if len(diff) and diff.iloc[0] < 0:
            total_drop = diff[diff < 0].sum()
            worst = diff.index[0]
            share = diff.iloc[0] / total_drop * 100 if total_drop else 0
            drop_txt = f"下滑最多的是「{worst}」，少了 {_money(-diff.iloc[0])}，占全部下滑的 {share:.0f}%"

    # ---- 漏在哪 ----
    leaks = []
    if detail_col and detail_col in cur.columns and metric in cur.columns:
        cs = cur.groupby(detail_col)[metric].sum()
        prev_s = prev.groupby(detail_col)[metric].sum() if prev_rev else None
        if prev_s is not None and len(prev_s) >= 5:
            both = pd.concat([cs.rename("cur"), prev_s.rename("prev")], axis=1).fillna(0)
            both = both[both["prev"] > 0]
            both["chg"] = both["cur"] / both["prev"] - 1
            falling = both.sort_values("chg").head(3)
            if len(falling) and falling["chg"].iloc[0] < -0.3:
                names = "、".join(f"{k}（{v*100:+.0f}%）" for k, v in falling["chg"].items())
                leaks.append(("卖得突然变差的商品", names + "，先确认是不是缺货或下架了"))

    for a in (advice_list or [])[:3]:
        if a.get("sev") == "高":
            leaks.append((a.get("title", ""), a.get("evidence", "")))
    if not leaks and advice_list:
        for a in advice_list[:2]:
            leaks.append((a.get("title", ""), a.get("evidence", "")))

    # ---- 页面 ----
    st.markdown("<div class='sect'>这个月的经营情况<small>一屏看完，不用懂数据</small></div>",
                unsafe_allow_html=True)

    head_line = (
        f"这段时间卖了 <b>{_money(cur_rev)}</b>"
        + (f"，比上一段{'多' if chg and chg > 0 else '少'} <b>{abs(chg):.0f}%</b>" if chg is not None else "")
        + (f"，主要少在「{drop_txt.split('「')[1].split('」')[0]}」" if (chg is not None and chg < 0 and "「" in drop_txt) else "")
        + "。"
    )
    st.markdown(f"<div class='insight' style='font-size:15px;line-height:1.8'>{head_line}"
                + (f"<br><span style='color:{MUTED};font-size:13px'>{drop_txt}</span>" if drop_txt else "")
                + "</div>", unsafe_allow_html=True)

    # 四个大数字：宽屏 4 列、手机 2 列（用 CSS 网格，不靠 Streamlit 的列）
    cards = [
        ("卖了多少钱", _money(cur_rev), f"近 {per['days']} 天"),
        ("赚了多少（毛利）", _money(profit) if profit is not None else "算不了",
         "卖价减进货价，未扣房租人工" if profit is not None else "缺少进货成本列"),
        ("每卖 100 块赚", _pct(margin) if margin is not None else "—", "毛利率"),
        ("平均每单", _money(aov), f"共 {orders:,} 单" if orders else ""),
    ]
    st.markdown(
        "<style>.kpi4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:6px 0 4px}"
        "@media (max-width:820px){.kpi4{grid-template-columns:repeat(2,1fr);gap:8px}}"
        "@media (max-width:360px){.kpi4{grid-template-columns:1fr}}"
        "</style>"
        "<div class='kpi4'>"
        + "".join(
            f"<div class='kpi' style='margin:0'><div class='kpi-label'>{lab}</div>"
            f"<div class='kpi-value'>{val}</div>"
            f"<div class='kpi-sub'>{sub}</div></div>"
            for lab, val, sub in cards)
        + "</div>", unsafe_allow_html=True)

    # 每天卖多少：一张图看懂走势（轻量原生图，手机不卡）
    if metric in cur.columns:
        _d = cur.dropna(subset=[date_col])
        _daily = _d.groupby(_d[date_col].dt.date)[metric].sum()
        if len(_daily) >= 3:
            st.markdown("<div class='sect'>这段时间每天卖多少<small>柱子高＝那天卖得多</small></div>",
                        unsafe_allow_html=True)
            _ser = pd.Series(_daily.values, index=[str(d)[5:] for d in _daily.index],
                             name="每天销售额")   # 用 10-01 这种短标签，避免英文月份
            st.bar_chart(_ser, height=210, color="#118DFF")
            _best = _daily.idxmax()
            _worst = _daily.idxmin()
            st.caption(f"最好的一天是 {str(_best)}（{_money(float(_daily.max()))}），"
                       f"最差是 {str(_worst)}（{_money(float(_daily.min()))}）。"
                       + ("跌幅明显的那几天，先排除是不是缺货/下雨/停业。" if _daily.min() < _daily.mean() * 0.5 else ""))

    left, right = st.columns([1, 1])
    with left:
        st.markdown("<div class='sect'>钱从哪来<small>哪几个品类在撑这家店</small></div>",
                    unsafe_allow_html=True)
        if cat_txt:
            st.markdown(f"<div class='sumcard'><div style='font-size:20px;font-weight:600'>{cat_txt}</div>"
                        f"<div style='color:{MUTED};font-size:12.5px;margin-top:6px'>{cat_more}</div></div>",
                        unsafe_allow_html=True)
            if cat_more and "前 3" in cat_more:
                st.caption("含义：生意不要只靠一个品类。前 3 个超过 70%，说明这家店很依赖少数几个品类。")

    with right:
        st.markdown("<div class='sect'>哪里要注意<small>不用看全部数据，只看这三条</small></div>",
                    unsafe_allow_html=True)
        if leaks:
            for title, body in leaks[:3]:
                st.markdown(
                    f"<div class='sumcard' style='margin-bottom:8px'>"
                    f"<div style='font-weight:600;font-size:13px;color:#B42318'>{title}</div>"
                    f"<div style='font-size:12.5px;margin-top:4px'>{body}</div></div>",
                    unsafe_allow_html=True)
        else:
            st.success("这段时间没发现明显问题：没有大幅下滑的商品，也没有高优先级的异常。")

    st.markdown("<div class='sect'>下一步做什么<small>照着做就行，每条都能算出好处</small></div>",
                unsafe_allow_html=True)
    if advice_list:
        for i, a in enumerate(advice_list[:3], 1):
            st.markdown(
                f"<div class='sumcard' style='margin-bottom:8px;border-left:3px solid {_LEVEL.get(a.get('sev'), '#888')}'>"
                f"<div style='font-weight:600;font-size:13.5px'>{i}. {a['title']}</div>"
                f"<div style='font-size:12.5px;margin-top:4px'><b>怎么做：</b>{a['action']}</div>"
                f"<div style='font-size:12.5px;color:{MUTED};margin-top:2px'><b>能带来什么：</b>{a['impact']}</div></div>",
                unsafe_allow_html=True)
    else:
        st.info("数据量还太少，暂时给不出动作建议。至少导入一个月的明细。")

    # 复制成微信消息
    txt = _wechat_text(
        f"{(per['dmax'] - pd.Timedelta(days=per['days']-1)):%m月%d日}—{per['dmax']:%m月%d日} 经营快报",
        [("卖了", _money(cur_rev) + (f"（比上一段{'+' if chg and chg>0 else ''}{chg:.0f}%）" if chg is not None else "")),
         ("毛利", _money(profit) + (f"（{margin:.1f}%）" if margin is not None else "")),
         ("订单", f"{orders:,} 单" if orders else "—")],
        [("钱从哪来", cat_txt), ("哪里要注意", leaks[0][1] if leaks else "未发现明显问题")],
        advice_list or [])
    with st.expander("复制成微信消息（直接发给老板/店员）"):
        st.code(txt, language="text")

    with st.expander("看不懂的词，点这里"):
        rows = "".join(f"<tr><td style='white-space:nowrap'>{k}</td><td>{v}</td></tr>"
                       for k, v in TERMS.items())
        st.markdown(f"<table class='mdict'><tbody>{rows}</tbody></table>", unsafe_allow_html=True)

    st.caption("这份快报用的是你上传的真实明细；要更细的分析（渠道、客户分层、预测），切到右上角「专业分析」。")
