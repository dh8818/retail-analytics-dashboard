# -*- coding: utf-8 -*-
"""数据清洗界面：体检 → 选动作 → 清洗 → 看前后对比与日志。"""
import pandas as pd
import streamlit as st

import cleaning as CL
from style import MUTED, TEXT

_LEVEL_COLOR = {"高": "#D64550", "中": "#C55A11", "低": "#548235"}


def render(df_raw, sig):
    applied = st.session_state.get("_clean")
    has_applied = bool(applied and applied.get("sig") == sig)
    cur = applied["df"] if has_applied else df_raw

    st.markdown("<div class='sect'>数据体检<small>先看清哪里脏，再决定怎么处理</small></div>",
                unsafe_allow_html=True)

    issues = CL.detect(df_raw)
    if not issues:
        st.markdown("<div class='insight'>没有发现结构性问题：无重复行、无文本型数字、无空列。"
                    "仍建议看一眼业务口径（退款、赠品、测试单）。</div>", unsafe_allow_html=True)
    else:
        rows = ""
        for i in issues:
            c = _LEVEL_COLOR.get(i["级别"], MUTED)
            rows += (f"<tr><td style='color:{c};font-weight:600'>{i['级别']}</td>"
                     f"<td>{i['问题']}</td><td class='mono'>{i['定位']}</td>"
                     f"<td style='text-align:right'>{i['数量']:,}</td>"
                     f"<td class='note'>{i['建议']}</td></tr>")
        st.markdown(
            "<table class='mdict'><thead><tr><th>级别</th><th>问题</th><th>定位</th>"
            f"<th style='text-align:right'>数量</th><th>建议</th></tr></thead><tbody>{rows}</tbody></table>",
            unsafe_allow_html=True)

    st.markdown("<div class='sect'>清洗动作<small>默认只做安全动作，勾选后立即重算全站</small></div>",
                unsafe_allow_html=True)
    st.caption("清洗范围 = 当前筛选后的数据集（时间范围、筛选条件在左侧「4. 分析设置 / 5. 筛选」里调）。")
    c1, c2, c3 = st.columns(3)
    o_dupes = c1.checkbox("删除完全重复的行", True, key="cl_dupes")
    o_strip = c1.checkbox("文本去首尾空格", True, key="cl_strip")
    o_num = c1.checkbox("文本型数字转数值", True, key="cl_num")
    o_date = c2.checkbox("文本型日期转日期", True, key="cl_date")
    o_empty = c2.checkbox("删除全空列", True, key="cl_empty")
    o_const = c2.checkbox("删除常量列", False, key="cl_const")
    o_out = c3.checkbox("剔除异常值（MAD）", False, key="cl_out")
    k = c3.slider("异常值阈值", 2.5, 5.0, 3.5, 0.5, key="cl_k", disabled=not o_out)
    fill = c3.selectbox("缺失值处理", ["不处理", "数值填 0", "数值填中位数", "删除含缺失的行"], key="cl_fill")

    b1, b2, _sp = st.columns([1, 1, 2])
    if b1.button("应用清洗", key="cl_apply", type="primary"):
        new_df, log, stats = CL.clean(df_raw, {
            "drop_dupes": o_dupes, "strip_text": o_strip, "to_number": o_num,
            "to_date": o_date, "drop_empty": o_empty, "drop_constant": o_const,
            "drop_outliers": o_out, "mad_k": k, "fill": fill})
        st.session_state["_clean"] = {"sig": sig, "df": new_df, "log": log, "stats": stats}
        st.rerun()
    if b2.button("恢复原始数据", key="cl_reset", disabled=not has_applied):
        st.session_state.pop("_clean", None)
        st.rerun()

    if has_applied:
        stats = applied["stats"]
        b, a = stats["before"], stats["after"]
        st.markdown(
            f"<div class='insight'>已应用清洗：{b['行数']:,} 行 → <b>{a['行数']:,} 行</b>，"
            f"{b['列数']} 列 → {a['列数']} 列；缺失 {b['缺失单元格']:,} → {a['缺失单元格']:,} 格；"
            f"重复 {b['重复行']:,} → {a['重复行']:,} 行。<br>"
            f"下面全站所有分析（KPI、图表、统计、PPT）都基于清洗后的数据。</div>",
            unsafe_allow_html=True)
        log = applied.get("log") or []
        if log:
            st.markdown("<div class='sect'>清洗日志<small>每一步做了什么、影响到哪</small></div>",
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(log), width="stretch", hide_index=True)
        st.download_button("下载清洗后的数据 CSV", cur.to_csv(index=False).encode("utf-8-sig"),
                           file_name="cleaned.csv", mime="text/csv", key="cl_dl")

    with st.expander("查看数据预览（前 30 行）", expanded=False):
        st.dataframe(cur.head(30), width="stretch")
