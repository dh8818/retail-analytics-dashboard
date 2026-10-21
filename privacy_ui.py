# -*- coding: utf-8 -*-
"""数据与隐私：把「你的数据去了哪」讲清楚，而不是一句「放心」。"""
import streamlit as st

from style import MUTED, TEXT

_GUARANTEES = [
    ("不写磁盘", "上传的文件只在内存里解析，不生成任何数据文件；只有你点「下载」时才会生成文件给你自己"),
    ("不外发", "本项目没有任何第三方统计、埋点、外部 API 调用；自然语言问数用的是本地规则解析，不调用大模型"),
    ("不留副本", "关闭页面 / 会话结束即释放；清洗结果、公式设置只存在当前浏览器会话里"),
]


def _host():
    try:
        h = st.context.headers.get("host", "") or ""
    except Exception:
        h = ""
    return h


def where_am_i(host=None):
    h = (host if host is not None else _host()).lower()
    if not h:
        return "unknown"
    if h.startswith("localhost") or h.startswith("127.0.0.1") or h.startswith("0.0.0.0"):
        return "local"
    return "cloud"


def render(compact=False):
    mode = where_am_i()
    st.markdown("<div class='sect'>数据与隐私<small>你的文件到底去了哪</small></div>",
                unsafe_allow_html=True)

    if mode == "local":
        st.markdown(
            "<div class='insight' style='border-left-color:#548235'>"
            "<b>当前是本地运行</b>：数据只在你自己的电脑内存里，<b>没有离开过这台机器</b>，"
            "关掉页面就释放。断网也能用。</div>", unsafe_allow_html=True)
    elif mode == "cloud":
        st.markdown(
            "<div class='insight' style='border-left-color:#C55A11'>"
            "<b>当前是云端运行</b>（*.streamlit.app）：文件会通过 HTTPS 上传到 Streamlit 的服务器，"
            "在那台服务器的内存里完成计算，再把图表传回你的浏览器。<br>"
            "本应用不落盘、不外发、不调用外部 API，但<b>「数据没有离开服务器」这一点取决于托管平台</b>。"
            "<br>→ 真实客户数据（手机号、会员卡号、身份证）建议用<b>本地版</b>，或先脱敏再上传。</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='insight'>无法判断运行位置。判断依据：地址栏是 <b>localhost</b> 就是本地；"
            "是 <b>*.streamlit.app</b> 就是云端。</div>", unsafe_allow_html=True)

    rows = ""
    for t, d in _GUARANTEES:
        rows += f"<tr><td style='white-space:nowrap'>✓ {t}</td><td class='note'>{d}</td></tr>"
    st.markdown(f"<table class='mdict'><thead><tr><th>本应用的保证</th><th>具体含义</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>", unsafe_allow_html=True)

    if not compact:
        st.caption("已关闭 Streamlit 使用统计（gatherUsageStats=false）。"
                   "需要绝对隔离时，双击「网页版看板.bat」用本地版即可，功能完全一样。")


def badge():
    """标题旁边的小标签，一眼看到当前是本地还是云端。"""
    mode = where_am_i()
    text, color = {"local": ("本地运行 · 数据不出机器", "#548235"),
                   "cloud": ("云端运行 · 见「数据与口径」隐私说明", "#C55A11")}.get(
        mode, ("运行位置未知", MUTED))
    st.markdown(f"<span style='display:inline-block;font-size:11.5px;color:#fff;background:{color};"
                f"padding:3px 9px;border-radius:2px'>{text}</span>", unsafe_allow_html=True)
