# -*- coding: utf-8 -*-
"""经营行动与复盘：问题 → 动作 → 预期 → 实际结果，闭环留痕。

复盘要能复盘出真东西，靠三个机制：
1. 基准指标快照：生成行动项时把当时的收入/毛利率等钉死在行里，
   复盘时数据再怎么变，当时的基准不会漂；
2. 复盘质量体检：已完成但没填实际结果、没负责人、没日期的行，直接点名——
   没有这些字段，复盘就是空话；
3. 闭环率：按状态统计，导出可交接。
"""
from datetime import date

import pandas as pd
import streamlit as st

from style import MUTED, fmt

_COLS = ["日期", "问题", "采取的动作", "负责人", "预期效果", "基准指标", "实际结果", "状态"]
_STATUS = ["待开始", "进行中", "已完成", "已放弃"]

# 场景关键词：用来判断这一行属于哪类经营动作，预期就按哪套口径推。
# 顺序有讲究：越具体的场景越靠前，"促销"最宽泛（活动/折扣），放最后兜底。
_SCENE_RULES = [
    ("缺货", ("缺货", "断货", "断订", "补货", "安全库存", "物流")),
    ("调价", ("调价", "提价", "降价", "涨价", "定价")),
    ("新品", ("新品", "上架", "动销率", "新进", "试销")),
    ("滞销", ("滞销", "清货", "临期", "报损", "周转", "积压", "库存")),
    ("排班", ("排班", "人力", "高峰", "时段", "人手", "班表", "客流")),
    ("陈列", ("陈列", "货架", "连带", "关联", "捆绑", "位置", "黄金位")),
    ("促销", ("促销", "折扣", "满减", "活动", "买赠", "特价", "试吃")),
]


def _detect_scene(text):
    """按关键词判断行动类型；都不命中就走通用口径。"""
    for name, kws in _SCENE_RULES:
        if any(k in text for k in kws):
            return name
    return "通用"


def _agg(sub, metric, qty_col, cost_col):
    """一小批行的销售额 / 销量 / 毛利率。"""
    rev = 0.0
    if metric and metric in sub.columns:
        rev = float(pd.to_numeric(sub[metric], errors="coerce").sum())
    qty = float(len(sub))
    if qty_col and qty_col in sub.columns:
        qty = float(pd.to_numeric(sub[qty_col], errors="coerce").sum())
    m = None
    if cost_col and cost_col in sub.columns and rev:
        try:
            import analytics as AN
            line = AN.cost_line(sub, cost_col, qty_col, "auto")
            if line is not None:
                m = (rev - float(line.sum())) / rev * 100
        except Exception:
            pass
    return rev, qty, m


def _match_objects(text, ctx):
    """从这一行的文字里，找出数据中真实存在的商品名 / 品类名。"""
    items, cates = [], []
    for v in ctx.get("items", []):
        if len(v) >= 2 and v in text:
            items.append(v)
    for v in ctx.get("cates", []):
        if len(v) >= 2 and v in text:
            cates.append(v)
    return items, cates


def infer_row(row, ctx):
    """按一行「问题 / 采取的动作」的文字，从数据推算它的基准指标与预期效果。

    优先落到具体商品，其次品类，最后才是全店——这样每行的数字都跟着自己的
    内容走，不会几行全是同一个「全店收入 / 毛利率」。
    """
    df = ctx.get("df")
    metric = ctx.get("metric")
    qty_col = ctx.get("qty")
    cost_col = ctx.get("cost")
    big_col = ctx.get("big")
    detail_col = ctx.get("detail")

    text = (f"{row.get('问题', '')} {row.get('采取的动作', '')}").strip()
    if not text.strip():
        return row.get("基准指标", ""), row.get("预期效果", "")

    scene = _detect_scene(text)
    items, cates = _match_objects(text, ctx)

    rev = qty = None
    obj_m = ctx.get("margin")
    if df is not None and items and detail_col in df.columns:
        sub = df[df[detail_col].astype(str).isin(items)]
        rev, qty, obj_m = _agg(sub, metric, qty_col, cost_col)
        base = f"{'、'.join(items[:2])}：销售额 {fmt(rev)}，销量 {qty:,.0f} 件"
        if obj_m is not None:
            base += f"，毛利率 {obj_m:.1f}%"
    elif df is not None and cates and big_col in df.columns:
        sub = df[df[big_col].astype(str).isin(cates)]
        rev, qty, obj_m = _agg(sub, metric, qty_col, cost_col)
        share = rev / ctx["sales"] * 100 if ctx.get("sales") else 0
        base = f"{'、'.join(cates[:2])}：销售额 {fmt(rev)}，占比 {share:.1f}%"
        if obj_m is not None:
            base += f"，毛利率 {obj_m:.1f}%"
    else:
        rev = ctx.get("sales") or 0
        base = f"全店：收入 {fmt(rev)}"
        if ctx.get("margin") is not None:
            base += f"，毛利率 {ctx['margin']:.1f}%"

    gm = obj_m if obj_m is not None else ctx.get("margin")
    if scene == "促销":
        exp = (f"活动期销量提升 20%（约 {qty*1.2:,.0f} 件）" if qty
               else "活动期销量比活动前提升 20% 以上")
        if gm is not None:
            exp += f"，毛利率不低于 {gm-3:.1f}%"
    elif scene == "缺货":
        exp = "缺货天数降为 0，次月不再出现同因缺货"
    elif scene == "调价":
        exp = (f"毛利额不下降，销量波动 ±10%（约 {qty*0.9:,.0f}~{qty*1.1:,.0f} 件）" if qty
               else "毛利额不下降的前提下，销量波动在 ±10% 以内")
    elif scene == "新品":
        exp = ("上架 2 周内动销率 ≥50%" + (f"（约 {qty*0.5:,.0f} 件）" if qty else "")
               + "，周转天数不超过品类平均")
    elif scene == "滞销":
        exp = "4 周内清掉 70% 滞销库存，报损率不上升"
    elif scene == "排班":
        exp = "高峰时段客单转化不下降，人力成本下降 5%~10%"
    elif scene == "陈列":
        exp = "关联商品连带率提升 10%~20%"
    else:
        exp = "关键指标（收入 / 毛利率）不低于当前水平"
    return base, exp


def _refresh_auto(df, ctx):
    """把每一行的基准 / 预期按当前文字重算一遍（幂等，可反复调用）。"""
    if ctx is None or df is None or df.empty:
        return df
    d = df.copy()
    for i in d.index:
        if str(d.at[i, "问题"]).strip() or str(d.at[i, "采取的动作"]).strip():
            base, exp = infer_row(d.loc[i], ctx)
            d.at[i, "基准指标"] = base
            d.at[i, "预期效果"] = exp
    return d


def _build_ctx(df, metric, qty, cost, big, detail, sales, margin):
    """提前把商品 / 品类清单抽出来，避免每行都去重扫全表。"""
    items = []
    cates = []
    if df is not None:
        if detail and detail in df.columns:
            items = [str(v).strip() for v in df[detail].dropna().astype(str).unique()]
        if big and big in df.columns:
            cates = [str(v).strip() for v in df[big].dropna().astype(str).unique()]
    return {"df": df, "metric": metric, "qty": qty, "cost": cost,
            "big": big, "detail": detail, "sales": sales, "margin": margin,
            "items": items, "cates": cates}


def _nonempty(df):
    """data_editor 新增的空行是空字符串，不是 NaN，dropna 抓不到。"""
    d = df.copy()
    for c in d.columns:
        d[c] = d[c].astype("object").where(d[c].notna(), "")
        d[c] = d[c].apply(lambda v: v.strip() if isinstance(v, str) else v)
    return d.replace("", pd.NA).dropna(how="all")


def _store():
    if "_actions" not in st.session_state:
        st.session_state["_actions"] = pd.DataFrame(columns=_COLS)
    return st.session_state["_actions"]


def from_advice(adv_list, base_text="", ctx=None):
    """把改善建议转成行动项（问题 + 预期 + 基准指标自动填好）。"""
    rows = []
    for a in adv_list[:5]:
        if ctx:
            base, exp = infer_row({"问题": a["title"], "采取的动作": a["action"]}, ctx)
        else:
            base, exp = base_text, a["impact"]
        rows.append({"日期": str(date.today()), "问题": a["title"],
                     "采取的动作": a["action"], "负责人": "",
                     "预期效果": exp,
                     "基准指标": base,
                     "实际结果": "", "状态": "待开始"})
    return pd.DataFrame(rows, columns=_COLS)


# 场景模板：常见经营动作的复盘骨架，一键预填、改数字就能用
SCENARIOS = {
    "促销活动复盘": {
        "问题": "促销活动效果待验证",
        "采取的动作": "活动期间对【商品】做满减/折扣（填写：商品、力度、档期）",
        "预期效果": "活动期销量比活动前提升 20% 以上，且毛利率下滑不超过 3 个点",
    },
    "缺货复盘": {
        "问题": "商品缺货导致销售损失",
        "采取的动作": "排查缺货原因（断订/物流/供应商），补货并把安全库存上调",
        "预期效果": "该商品缺货天数降为 0，次月不再出现同因缺货",
    },
    "调价复盘": {
        "问题": "调价对销量和毛利的影响待验证",
        "采取的动作": "对【商品】提价/降价 X%（填写：商品与幅度），观察两周",
        "预期效果": "毛利额不下降的前提下，销量波动在 ±10% 以内",
    },
    "新品上架复盘": {
        "问题": "新品动销情况待验证",
        "采取的动作": "新品上架，给到收银台/黄金位陈列，配合试吃/推荐话术",
        "预期效果": "上架 2 周内动销率 ≥50%，周转天数不超过品类平均",
    },
    "滞销清货复盘": {
        "问题": "滞销商品占用库存资金",
        "采取的动作": "对 30 天未动销商品做临期折扣/捆绑销售/退供",
        "预期效果": "4 周内清掉 70% 滞销库存，报损率不上升",
    },
    "排班调整复盘": {
        "问题": "高峰时段人手不足 / 低峰人力浪费",
        "采取的动作": "按星期×时段热力图重排班表（高峰加人、低谷减人）",
        "预期效果": "高峰时段客单转化不下降，人力成本下降 5%~10%",
    },
    "陈列调整复盘": {
        "问题": "关联商品分开摆放，连带率低",
        "采取的动作": "把强关联商品对（购物篮提升度最高）调到相邻货架",
        "预期效果": "这对商品的连带率提升 10%~20%",
    },
}


def from_scenario(name, base_text="", ctx=None):
    """把场景模板转成一条行动项。"""
    s = SCENARIOS[name]
    if ctx:
        base, exp = infer_row({"问题": s["问题"], "采取的动作": s["采取的动作"]}, ctx)
    else:
        base, exp = base_text, s["预期效果"]
    return pd.DataFrame([{"日期": str(date.today()), "问题": s["问题"],
                          "采取的动作": s["采取的动作"], "负责人": "",
                          "预期效果": exp, "基准指标": base,
                          "实际结果": "", "状态": "待开始"}], columns=_COLS)


def _next_step_hint(row):
    """按当前状态给一句「下一步该干什么」。"""
    st_ = str(row.get("状态", ""))
    if st_ == "待开始":
        return "定了负责人和日期就动手——没有负责人的行动项不会自己发生"
    if st_ == "进行中":
        return "动作跑到预期周期的一半时，先看一次中间数据，别等结束才发现方向错了"
    if st_ == "已完成":
        has_result = str(row.get("实际结果", "")).strip()
        return ("结果已记录 ✓" if has_result
                else "已标记完成但还没填实际结果——拿同口径数据再算一次，填进来才算闭环")
    if st_ == "已放弃":
        return "写一句放弃原因（数据不支持/成本超预期/方向变了），放弃也是结论"
    return ""


def _quality_check(df):
    """复盘质量体检：找「复盘不出来」的行。返回 (问题清单, 合格行数)。"""
    issues = []
    if df.empty:
        return issues, 0
    done = df[df["状态"] == "已完成"]
    if len(done) and "实际结果" in done:
        n = int((done["实际结果"].isna() | (done["实际结果"].astype(str).str.strip() == "")).sum())
        if n:
            issues.append(f"{n} 项已标记「已完成」但**没填实际结果**——没有实际数字，复盘等于没做")
    n_owner = int((df["负责人"].isna() | (df["负责人"].astype(str).str.strip() == "")).sum())
    if n_owner:
        issues.append(f"{n_owner} 项没写负责人——没人背的动作不会被执行")
    n_date = 0
    if "日期" in df:
        dd = pd.to_datetime(df["日期"], errors="coerce")
        n_date = int(dd.isna().sum())
        if n_date:
            issues.append(f"{n_date} 项日期为空或格式不对（要 YYYY-MM-DD）——没有时间就没法对周期")
    n_expected = int((df["预期效果"].isna() | (df["预期效果"].astype(str).str.strip() == "")).sum())
    if n_expected:
        issues.append(f"{n_expected} 项没有预期效果——没有预期，实际结果好坏都无法判断")
    return issues, len(df)


def render(adv_list, base_text="", ctx=None):
    st.markdown("<div class='sect'>经营行动与复盘<small>做了什么、效果如何——把分析变成闭环</small></div>",
                unsafe_allow_html=True)
    st.caption("报表回答「发生了什么」，这一页回答「改了什么、结果如何」。"
               "每条行动都有负责人、时间、预期与实际，效果可回溯、可交接。"
               "「基准指标」和「预期效果」会按每行写到的商品 / 品类和动作类型自动推算，改了「问题 / 动作」就跟着实时变。")

    cur = _store()
    c1, c2, c3 = st.columns([1.2, 1.2, 3])
    if c1.button("从改善建议生成", key="rv_seed", disabled=not adv_list):
        new = from_advice(adv_list, base_text, ctx)
        st.session_state["_actions"] = pd.concat([cur, new], ignore_index=True).drop_duplicates(
            subset=["问题", "采取的动作"], keep="last")
        st.rerun()
    if c2.button("清空", key="rv_clear", disabled=cur.empty):
        st.session_state["_actions"] = pd.DataFrame(columns=_COLS)
        st.rerun()

    # ---- 场景模板：常见经营动作一键预填，改数字就能用 ----
    with st.expander("📋 按场景快速新建（促销 / 缺货 / 调价 / 新品 / 滞销 / 排班 / 陈列）", expanded=False):
        st.caption("选一个场景点「填入」，会预填问题、动作、预期——把【】里的占位改成你的实际商品和数字即可。")
        sc_cols = st.columns(4)
        scen_names = list(SCENARIOS.keys())
        _picked_scene = None
        for i, name in enumerate(scen_names):
            with sc_cols[i % 4]:
                if st.button(name, key=f"sc_{i}", use_container_width=True):
                    _picked_scene = name
        if _picked_scene:
            new = from_scenario(_picked_scene, base_text, ctx)
            st.session_state["_actions"] = pd.concat([_store(), new], ignore_index=True)
            st.rerun()

    cur = _store()
    # 实时推算：每行的「基准指标 / 预期效果」按它自己的问题与动作重算，
    # 这样几行不会共用同一个「全店收入 / 毛利率」。
    if ctx and not cur.empty and len(cur) <= 30:
        cur = _refresh_auto(cur, ctx)
        st.session_state["_actions"] = cur.fillna("")
    if cur.empty:
        st.info("还没有行动项。点「从改善建议生成」，或直接在下面新增一行。")
        empty = pd.DataFrame([{c: "" for c in _COLS}])
        edited = st.data_editor(empty, num_rows="dynamic", width="stretch",
                                column_config={
                                    "状态": st.column_config.SelectboxColumn(options=_STATUS),
                                    "日期": st.column_config.TextColumn(help="YYYY-MM-DD"),
                                    "基准指标": st.column_config.TextColumn(help="生成时的经营数字快照"),
                                }, key="rv_editor_empty")
        _filled = _nonempty(edited)
        if len(_filled):
            st.session_state["_actions"] = _filled.fillna("")
            st.rerun()
        return

    edited = st.data_editor(cur, num_rows="dynamic", width="stretch", key="rv_editor",
                            column_config={
                                "状态": st.column_config.SelectboxColumn(options=_STATUS),
                                "问题": st.column_config.TextColumn(width="medium"),
                                "采取的动作": st.column_config.TextColumn(width="large"),
                                "预期效果": st.column_config.TextColumn(
                                    width="medium", help="按本行的问题 / 动作类型自动推算"),
                                "基准指标": st.column_config.TextColumn(
                                    width="medium", help="按本行提到的商品 / 品类自动取值"),
                                "实际结果": st.column_config.TextColumn(width="large"),
                            })
    edited = _nonempty(edited).reset_index(drop=True)      # 丢掉空行，只留真实行动

    # 「问题 / 动作」一改，基准与预期立刻按新内容重算（实时），并刷新表格
    if ctx and not edited.empty and len(edited) <= 30:
        _recalc = _refresh_auto(edited, ctx).fillna("")
        if not _recalc[["基准指标", "预期效果"]].equals(
                edited[["基准指标", "预期效果"]].fillna("")):
            st.session_state["_actions"] = _recalc
            st.rerun()

    if not edited.equals(cur):
        st.session_state["_actions"] = edited.fillna("")

    done = (edited["状态"] == "已完成").sum() if "状态" in edited else 0
    total = len(edited)
    st.markdown(
        f"<div class='insight'>共 <b>{total}</b> 项行动：已完成 {done}，"
        f"进行中 {(edited['状态'] == '进行中').sum()}，待开始 {(edited['状态'] == '待开始').sum()}。"
        + ("　闭环率 {:.0f}%".format(done / total * 100) if total else "")
        + "</div>", unsafe_allow_html=True)

    # ---- 每条行动的「下一步」提示：让复盘活起来，告诉用户此刻该干什么 ----
    with st.expander("👉 每条行动下一步该干什么（按状态自动提示）", expanded=bool(total) and total <= 6):
        for _, r in edited.iterrows():
            hint = _next_step_hint(r)
            icon = {"待开始": "🕐", "进行中": "🚀", "已完成": "✅", "已放弃": "⛔"}.get(
                str(r.get("状态", "")), "•")
            st.markdown(
                f"<div style='font-size:13px;margin:4px 0;line-height:1.6'>{icon} "
                f"<b>{str(r.get('问题',''))[:40]}</b> —— {hint}</div>",
                unsafe_allow_html=True)

    # ---- 复盘质量体检：点名复盘不成立的行 ----
    issues, _n = _quality_check(edited)
    if issues:
        rows_html = "".join(f"<li style='margin:2px 0'>{t}</li>" for t in issues)
        st.markdown(
            "<div class='insight' style='border-left-color:#B9812F'>"
            f"<b>复盘质量体检（{len(issues)} 处不成立，改了才算复盘）</b><ul style='margin:4px 0 0 18px;padding:0'>{rows_html}</ul></div>",
            unsafe_allow_html=True)
    else:
        st.markdown("<div class='insight' style='border-left-color:#6F8A63'>"
                    "<b>复盘质量体检通过</b>：每项都有负责人、日期、预期和实际结果。</div>",
                    unsafe_allow_html=True)

    with st.expander("复盘怎么写才有说服力", expanded=False):
        st.markdown(f"""
- **问题**：写具体数字，不写"销售不好"（例：鲜食报损率 24%，集中在酸奶）
- **动作**：写可执行的事，带参数（例：酸奶订货量从日均 1.5 天降到 1 天）
- **预期**：写清方向和量级（例：报损率降到 15% 以内）
- **基准**：生成时已自动记录当时的收入/毛利率（「基准指标」列）；复盘时换一批数据
  （比如下个月再导一次），就能拿实际结果和基准对——差多少、是不是动作起了作用
- **实际**：实施后同样口径再算一次，**不要美化**；没效果也是结论
- **归因**：期间的促销、天气、缺货要一起写，否则无法判断是不是动作起了作用
        """)
    st.download_button("导出行动清单 CSV",
                       _nonempty(edited).to_csv(index=False).encode("utf-8-sig"),
                       file_name="经营行动清单.csv", mime="text/csv", key="rv_dl")
