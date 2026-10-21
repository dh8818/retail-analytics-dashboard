# -*- coding: utf-8 -*-
"""经营行动与复盘：问题 → 动作 → 预期 → 实际结果，闭环留痕。"""
from datetime import date

import pandas as pd
import streamlit as st

from style import MUTED

_COLS = ["日期", "问题", "采取的动作", "负责人", "预期效果", "实际结果", "状态"]
_STATUS = ["待开始", "进行中", "已完成", "已放弃"]


def _store():
    if "_actions" not in st.session_state:
        st.session_state["_actions"] = pd.DataFrame(columns=_COLS)
    return st.session_state["_actions"]


def from_advice(adv_list):
    """把改善建议转成行动项（问题 + 预期自动填好）。"""
    rows = []
    for a in adv_list[:5]:
        rows.append({"日期": str(date.today()), "问题": a["title"],
                     "采取的动作": a["action"], "负责人": "",
                     "预期效果": a["impact"], "实际结果": "", "状态": "待开始"})
    return pd.DataFrame(rows, columns=_COLS)


def render(adv_list):
    st.markdown("<div class='sect'>经营行动与复盘<small>做了什么、效果如何——把分析变成闭环</small></div>",
                unsafe_allow_html=True)
    st.caption("报表回答「发生了什么」，这一页回答「改了什么、结果如何」。"
               "每条行动都有负责人、时间、预期与实际，效果可回溯、可交接。")

    cur = _store()
    c1, c2, c3 = st.columns([1.2, 1.2, 3])
    if c1.button("从改善建议生成", key="rv_seed", disabled=not adv_list):
        new = from_advice(adv_list)
        st.session_state["_actions"] = pd.concat([cur, new], ignore_index=True).drop_duplicates(
            subset=["问题", "采取的动作"], keep="last")
        st.rerun()
    if c2.button("清空", key="rv_clear", disabled=cur.empty):
        st.session_state["_actions"] = pd.DataFrame(columns=_COLS)
        st.rerun()

    cur = _store()
    if cur.empty:
        st.info("还没有行动项。点「从改善建议生成」，或直接在下面新增一行。")
        empty = pd.DataFrame([{c: "" for c in _COLS}])
        edited = st.data_editor(empty, num_rows="dynamic", width="stretch",
                                column_config={
                                    "状态": st.column_config.SelectboxColumn(options=_STATUS),
                                    "日期": st.column_config.TextColumn(help="YYYY-MM-DD"),
                                }, key="rv_editor_empty")
        if edited.dropna(how="all").shape[0]:
            st.session_state["_actions"] = edited.dropna(how="all").fillna("")
            st.rerun()
        return

    edited = st.data_editor(cur, num_rows="dynamic", width="stretch", key="rv_editor",
                            column_config={
                                "状态": st.column_config.SelectboxColumn(options=_STATUS),
                                "问题": st.column_config.TextColumn(width="medium"),
                                "采取的动作": st.column_config.TextColumn(width="large"),
                                "实际结果": st.column_config.TextColumn(width="large"),
                            })
    if not edited.equals(cur):
        st.session_state["_actions"] = edited.fillna("")

    done = (edited["状态"] == "已完成").sum() if "状态" in edited else 0
    total = len(edited)
    st.markdown(
        f"<div class='insight'>共 <b>{total}</b> 项行动：已完成 {done}，"
        f"进行中 {(edited['状态'] == '进行中').sum()}，待开始 {(edited['状态'] == '待开始').sum()}。"
        + ("　闭环率 {:.0f}%".format(done / total * 100) if total else "")
        + "</div>", unsafe_allow_html=True)

    with st.expander("复盘怎么写才有说服力", expanded=False):
        st.markdown(f"""
- **问题**：写具体数字，不写"销售不好"（例：鲜食报损率 24%，集中在酸奶）
- **动作**：写可执行的事，带参数（例：酸奶订货量从日均 1.5 天降到 1 天）
- **预期**：写清方向和量级（例：报损率降到 15% 以内）
- **实际**：实施后同样口径再算一次，**不要美化**；没效果也是结论
- **归因**：期间的促销、天气、缺货要一起写，否则无法判断是不是动作起了作用
        """)
    st.download_button("导出行动清单 CSV",
                       edited.to_csv(index=False).encode("utf-8-sig"),
                       file_name="经营行动清单.csv", mime="text/csv", key="rv_dl")
