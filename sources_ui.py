# -*- coding: utf-8 -*-
"""
数据源 / 多门店管理界面：连接收银数据源、管理门店结构、跑批与订阅。

这是第 1/2/3 项功能的入口，与主看板（app.py 的上传即分析）并列，互不干扰。
- 数据接入：列出已注册连接器，一键拉取，落本地 SQLite。
- 多门店：查看门店结构、跨店对比。
- 自动跑批：手动触发一次跑批，产出异常预警与日报，落本地通知。

说明：本地 SQLite 先单机跑通；真实收银系统、企业微信推送、定时调度
是本模块预留的接口位，见 docs/分阶段落地蓝图.md。
"""
import pandas as pd
import streamlit as st

import datasources as DS
import scheduler as SC
import stores as ST
import connector_sqlite as CS
from style import MUTED, BI_NAVY


def _demo_seed():
    """首次使用时生成一套模拟门店 SQLite 数据（示例连接器的数据源）。"""
    import os
    db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "demo_pos.db")
    if not os.path.exists(db):
        with st.spinner("首次使用，正在生成示例门店数据…"):
            CS.seed_demo(db)
    return db


def render():
    st.markdown(
        f"<div style='font-size:23px;font-weight:600;color:{BI_NAVY};letter-spacing:.4px'>数据源与多门店</div>"
        f"<div style='font-size:12.5px;color:{MUTED}'>连接收银系统、管理门店、自动跑批——"
        f"让数据在交易发生时自己进来</div>"
        f"<div style='height:2px;background:{BI_NAVY};width:44px;margin:8px 0 10px'></div>",
        unsafe_allow_html=True)

    st.markdown(
        "<div class='insight' style='border-left-color:#B9812F'>"
        "<b>当前阶段</b>：数据接入走「连接器接口 + 本地 SQLite 持久化」骨架，"
        "内置一个可跑的 SQLite 示例连接器；真实收银系统（银豹/客如云/有赞/科脉）、"
        "企业微信推送、定时调度是预留接口，见蓝图文档。</div>",
        unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["① 数据接入", "② 多门店对比", "③ 自动跑批与订阅", "④ 指标中心", "⑤ 数据资产"])

    # ---------- ① 数据接入 ----------
    with tab1:
        st.markdown("<div class='sect'>连接数据源<small>销售 / 库存 / 会员，一次拉取落本地</small></div>",
                    unsafe_allow_html=True)
        sources = DS.available_sources()
        for s in sources:
            st.markdown(f"· **{s['label']}**（`{s['key']}`）")
        if not sources:
            st.caption("还没有注册任何连接器。")
        else:
            key = st.selectbox("选择数据源", [s["key"] for s in sources], format_func=lambda k: next(
                (s["label"] for s in sources if s["key"] == k), k), key="src_pick")
            if st.button("拉取数据（增量）", type="primary", key="src_fetch"):
                with st.spinner("正在拉取…"):
                    try:
                        store = DS.Store()
                        since = store.get_since(key)
                        src = DS.create_source(key, {"path": _demo_seed()})
                        fetched = src.fetch(since)
                        from datetime import datetime
                        for kind, df in fetched.items():
                            if df is not None and not df.empty:
                                store.save_snapshot(key, kind, df)
                        store.set_since(key, src.label, {"path": _demo_seed()},
                                        datetime.now().isoformat(timespec="seconds"))
                        rows = {k: (0 if v is None else len(v)) for k, v in fetched.items()}
                        st.success(f"拉取完成：销售 {rows.get('sales', 0):,} 行、"
                                   f"库存 {rows.get('inventory', 0):,} 行、会员 {rows.get('members', 0):,} 行。")
                        st.session_state["_src_fetched"] = True
                    except Exception as e:
                        st.error(f"拉取失败：{e}")
            if st.session_state.get("_src_fetched"):
                store = DS.Store()
                sales = store.load_snapshot(key, "sales")
                if not sales.empty:
                    st.markdown(f"<div style='font-size:12.5px;color:{MUTED}'>"
                                f"已落库销售明细 {len(sales):,} 行（预览）：</div>",
                                unsafe_allow_html=True)
                    st.dataframe(sales.head(50), width="stretch", hide_index=True)

    # ---------- ② 多门店对比 ----------
    with tab2:
        st.markdown("<div class='sect'>多门店结构<small>总部—区域—门店 + 数据隔离 + 跨店对比</small></div>",
                    unsafe_allow_html=True)
        if st.button("用示例数据演示多门店对比", key="store_demo"):
            db = _demo_seed()
            import sqlite3
            con = sqlite3.connect(db)
            sales = pd.read_sql_query("SELECT * FROM sales", con)
            stores_df = pd.read_sql_query(
                "SELECT DISTINCT 门店编码 AS code, 门店编码 AS name, '区域1' AS region, '' AS parent FROM sales",
                con) if "门店编码" in sales.columns else pd.DataFrame()
            con.close()

            if not sales.empty and "门店编码" in sales.columns:
                cmp = ST.cross_store_compare(sales, "门店编码", "金额")
                if not cmp.empty:
                    st.markdown("<div style='font-size:12.5px;color:#6E685E'>各门店销售额对比（总部视角）：</div>",
                                unsafe_allow_html=True)
                    st.dataframe(cmp, width="stretch", hide_index=True)
                    top = cmp.iloc[0]
                    st.markdown(f"<div class='insight'>最高「{top['门店']}」占全部销售的 {top['占比%']}%，"
                                f"最低「{cmp.iloc[-1]['门店']}」占 {cmp.iloc[-1]['占比%']}%——"
                                f"差距超过一倍的门店值得单独看。</div>", unsafe_allow_html=True)
                else:
                    st.info("示例数据里没识别到门店列。")
            else:
                st.info("请先在「① 数据接入」拉取示例数据。")

        st.markdown(
            "<div class='insight'>权限模型（`stores.py`）："
            "店长只看自己店、区域经理看本区域、老板看全部。数据隔离按门店编码过滤，"
            "不软删、可追溯。真实多租户登录需接后端认证（见蓝图）。</div>",
            unsafe_allow_html=True)

    # ---------- ③ 自动跑批与订阅 ----------
    with tab3:
        st.markdown("<div class='sect'>自动跑批与预警<small>不用主动打开，也能收到关键结论</small></div>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div class='insight'>跑批是纯函数（`scheduler.py`），可由任意调度器定时触发。"
            "这里先手动触发一次，验证「异常预警 → 结论 → 本地通知」全链路。</div>",
            unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        channel = c1.selectbox("推送渠道", list(SC.CHANNELS.keys()),
                               format_func=lambda k: SC.CHANNELS[k], key="sch_chan")
        c2.markdown(f"<div style='padding-top:30px;color:{MUTED};font-size:12px'>"
                    f"local 立即落盘；wecom 发企业微信群机器人</div>", unsafe_allow_html=True)

        # 企业微信机器人 webhook 地址（选 wecom 时显示，填一次存本地）
        if channel == "wecom":
            cur_hook = SC.get_wecom_webhook()
            hook = st.text_input(
                "企业微信群机器人 Webhook 地址",
                value=cur_hook, key="wecom_hook",
                placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
                help="在企业微信群里「添加群机器人」可拿到这个地址，形如 qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…")
            if st.button("保存地址", key="wecom_save"):
                SC.set_wecom_webhook(hook)
                st.success("已保存（存在本地 data/push_config.json）")
            st.caption("拿到地址后：企业微信 → 目标群 → 右上角「…」→ 群机器人 → 添加 → 复制 Webhook 地址粘到这里。")

        if st.button("手动跑一次批（生成今日预警）", type="primary", key="sch_run"):
            db = _demo_seed()
            import sqlite3
            con = sqlite3.connect(db)
            sales = pd.read_sql_query("SELECT * FROM sales", con)
            con.close()
            concl = SC.detect_anomalies(sales, "金额", "日期", "门店编码")
            report = SC.build_daily_report(sales, "金额", "日期", "品类", "门店编码")
            digest = SC.render_digest(concl)
            full = (report + "\n\n—— 异常预警 ——\n" + digest) if concl else report
            res = SC.deliver(channel, full)
            st.code(full, language="text")
            if res["ok"]:
                st.success(res["msg"])
            else:
                st.warning(res["msg"])

        st.markdown("<div class='sect'>订阅<small>按 topic 订阅，到点自动推送（结构已就绪）</small></div>",
                    unsafe_allow_html=True)
        st.caption("订阅模型存在本地 SQLite（subscriptions 表）：用户 + topic（异常预警/日报/周报）+ 渠道。"
                   "定时触发与真实推送通道接入后即可自动发。")

    # ---------- ④ 指标中心 ----------
    with tab4:
        import metric_catalog as MC
        st.markdown("<div class='sect'>指标中心<small>定义一次、全局复用，跨人跨报表口径一致</small></div>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div class='insight'>这 9 个指标的公式、单位、口径说明集中在这一份定义里；"
            "概览卡、口径字典、报告、分析包、推送结论都从同一处取，不会出现"
            "「页面一个数、报告另一个数」的口径漂移。</div>", unsafe_allow_html=True)
        rows = MC.catalog_rows()
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption(f"指标中心版本 {MC.CATALOG_VERSION}；公式里的 "
                   f"{{rev}}/{{qty}}/{{cost}}/{{order}} 是语义占位符，"
                   f"运行时按当前数据源的实际列名绑定（同一套口径能套到不同数据源）。")

    # ---------- ⑤ 数据资产 ----------
    with tab5:
        st.markdown("<div class='sect'>数据资产<small>我的数据长什么样——表、字段、关联、质量</small></div>",
                    unsafe_allow_html=True)
        st.markdown(
            "<div class='insight'>这是「数据中台/数仓」的轻量落地：不搞重数仓，"
            "只回答「我有哪些表、每张表有哪些字段、它们怎么关联、数据质量如何」。</div>",
            unsafe_allow_html=True)
        try:
            store = DS.Store()
            # 从快照表读出已落库的数据
            import sqlite3
            con = sqlite3.connect(str(store.path))
            snaps = pd.read_sql_query(
                "SELECT source_key, kind, fetched_at, rows FROM snapshots ORDER BY fetched_at DESC", con)
            con.close()
            if snaps.empty:
                st.info("还没有拉取过任何数据。先去「① 数据接入」拉一次，这里就能看到数据资产全景。")
            else:
                latest = snaps.drop_duplicates(subset=["source_key", "kind"], keep="first")
                st.markdown("<div style='font-size:12.5px;color:#6E685E'>已落库的表（快照）：</div>",
                            unsafe_allow_html=True)
                st.dataframe(latest, width="stretch", hide_index=True)
                # 字段清单（以最新一次 sales 快照为例）
                sales = store.load_snapshot(latest.iloc[0]["source_key"], "sales")
                if not sales.empty:
                    st.markdown("<div class='sect' style='margin-top:12px'>字段清单（销售明细示例）"
                                "<small>类型 / 非空 / 示例</small></div>", unsafe_allow_html=True)
                    finfo = []
                    for c in sales.columns:
                        s = sales[c]
                        if pd.api.types.is_numeric_dtype(s):
                            t = "数值"
                        elif pd.api.types.is_datetime64_any_dtype(s):
                            t = "日期"
                        else:
                            t = "文本"
                        finfo.append({"字段": c, "类型": t,
                                      "非空": int(s.notna().sum()),
                                      "缺失": int(s.isna().sum()),
                                      "示例": str(s.dropna().iloc[0])[:20] if s.notna().any() else ""})
                    st.dataframe(pd.DataFrame(finfo), width="stretch", hide_index=True)
        except Exception as e:
            st.info(f"数据资产暂不可用：{e}")


def render_entry():
    """在侧栏顶部放一个入口，点击进入数据源管理页。"""
    if st.sidebar.button("🔌 数据源 / 多门店（新）", key="src_entry"):
        st.session_state["_src_view"] = True
        st.rerun()


def is_active() -> bool:
    return bool(st.session_state.get("_src_view"))


def exit_active():
    if st.sidebar.button("← 返回上传分析", key="src_exit"):
        st.session_state.pop("_src_view", None)
        st.rerun()


# ---------------- 通用接口配置表单（与上传表格并列的数据来源） ----------------

# 数据源类型下拉：示例连接器 + 预留的厂商位（接真实 API 时在此加一项即可）
SOURCE_TYPES = {
    "sqlite_pos": {"label": "示例连接器（本地 SQLite，演示用）",
                   "fields": ["数据文件路径"]},
    "api_generic": {"label": "通用 HTTP 接口（预留，需厂商开放 API）",
                    "fields": ["接口地址", "AppKey / AppSecret", "门店号 / 商户号"]},
}

FIELD_HINTS = {
    "接口地址": "对方开放平台提供的拉数地址，如 https://open.xxx.com/v1/sales",
    "AppKey / AppSecret": "开放平台申请的应用密钥，用于鉴权",
    "门店号 / 商户号": "要拉哪家门店的数据；多门店可留空表示拉全部",
    "数据文件路径": "本地 SQLite 数据库文件路径（示例连接器专用）",
}


def render_source_picker(key_prefix: str = "") -> dict | None:
    """渲染「连接数据源」通用配置表单，点连接后返回 {'sheets': {...}, 'label': str}。

    返回的 sheets 与 app.py 里「上传文件」得到的 sheets 同构，
    下游分析链路完全复用，不改主流程。
    key_prefix：同一页面可能有两处入口（侧栏 + 正文）渲染这个表单，
    Streamlit 不允许 widget key 重复，必须用前缀区分。
    """
    st.markdown("<div class='sect'>连接数据源<small>填接口或选数据源，数据自动拉进来</small></div>",
                unsafe_allow_html=True)

    keys = list(SOURCE_TYPES.keys())
    stype = st.selectbox(
        "数据源类型", keys,
        format_func=lambda k: SOURCE_TYPES[k]["label"],
        key=f"{key_prefix}src_type")

    cfg = {}
    for f in SOURCE_TYPES[stype]["fields"]:
        hint = FIELD_HINTS.get(f, "")
        cfg[f] = st.text_input(f, key=f"{key_prefix}src_cfg_{f}", help=hint)

    # 通用：把「数据源类型 key」也放进 config，供 create_source 使用
    full_cfg = {"_type": stype, **cfg}

    st.caption("数据只在本机/你的数据源之间流转；真实厂商 API 需其开放平台授权。")

    if st.button("连接并拉取数据", type="primary", key=f"{key_prefix}src_connect"):
        with st.spinner("正在连接并拉取…"):
            try:
                result = _connect_and_fetch(full_cfg)
                # 存进 session_state 供主数据流消费，并刷新进入分析
                st.session_state["_conn_sheets"] = result
                st.rerun()
            except Exception as e:
                st.error(f"连接失败：{e}")
                return None
    return None


def _connect_and_fetch(cfg: dict) -> dict | None:
    """按配置拉取数据，落库并返回 sheets（与上传文件同构）。"""
    from datetime import datetime
    stype = cfg.get("_type", "")

    # 示例连接器：直接走 connector_sqlite
    if stype == "sqlite_pos":
        db = cfg.get("数据文件路径", "").strip() or _demo_seed()
        src = CS.SqlitePOSSource({"path": db})
        fetched = src.fetch()
        key = "sqlite_pos"
        label = "SQLite 示例数据源"
    else:
        # 通用 HTTP 接口：预留。当前没有真实厂商 API，明确告知。
        raise RuntimeError(
            "通用 HTTP 接口尚未接入具体厂商。请先在「数据源类型」选示例连接器体验，"
            "或提供厂商开放 API 文档后由开发接入。")

    # 落库 + 记录游标
    store = DS.Store()
    for kind, df in fetched.items():
        if df is not None and not df.empty:
            store.save_snapshot(key, kind, df)
    store.set_since(key, label, {"path": cfg.get("数据文件路径", "")},
                    datetime.now().isoformat(timespec="seconds"))

    # 合成 sheets：销售明细作为主表，库存/会员作为可关联维表（如有）
    sheets = {}
    sales = fetched.get("sales")
    if sales is not None and not sales.empty:
        sheets["销售明细"] = sales
    inv = fetched.get("inventory")
    if inv is not None and not inv.empty:
        sheets["库存"] = inv
    mem = fetched.get("members")
    if mem is not None and not mem.empty:
        sheets["会员"] = mem

    if not sheets:
        raise RuntimeError("没有拉到任何数据。")

    st.success(f"拉取完成：销售 {0 if sales is None else len(sales):,} 行、"
               f"库存 {0 if inv is None else len(inv):,} 行、会员 {0 if mem is None else len(mem):,} 行。")
    return {"sheets": sheets, "label": label}
