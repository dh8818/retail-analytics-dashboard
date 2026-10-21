# -*- coding: utf-8 -*-
"""SQL 查询台：把上传的表变成 DuckDB 表，直接写 SQL（支持窗口函数、CTE、子查询）。

只允许 SELECT / WITH，DDL、DML、ATTACH 等一律拦掉；结果行数封顶，避免把浏览器拖死。
"""
import re

import duckdb
import pandas as pd
import streamlit as st

import nlq

from style import MUTED, TEXT, BI_NAVY

TABLE = "t"
MAX_ROWS = 5000
_BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|copy|export|import|install|load|pragma)\b",
    re.I)


def run_sql(df, sql, limit=MAX_ROWS):
    """执行一条只读 SQL，返回 (结果 DataFrame, 错误信息)。"""
    q = (sql or "").strip().rstrip(";").strip()
    if not q:
        return None, "SQL 是空的"
    if not re.match(r"^(select|with)\b", q, re.I):
        return None, "只允许 SELECT / WITH 查询"
    if _BLOCKED.search(q):
        return None, "检测到写操作关键字，这里只接受只读查询"
    con = duckdb.connect()
    try:
        # 关键：禁用本地文件系统，防止 SELECT read_csv('任意路径') 读到服务器文件
        # （这个设置必须在连接建立之后、查询之前执行）
        con.execute("SET disabled_filesystems='LocalFileSystem'")
        con.register(TABLE, df)
        out = con.execute(q).fetchdf()
    except Exception as e:
        return None, str(e).split("\n")[0][:300]
    finally:
        con.close()
    if out is None:
        return None, "没有结果"
    return out.head(limit), None


def _examples(cols):
    """按实际列名生成示例，保证复制粘贴就能跑。"""
    num = next((c for c in cols if any(h in str(c) for h in ("金额", "销售额", "收入"))), None)
    cat = next((c for c in cols if any(h in str(c) for h in ("品类", "分类", "类别"))), None)
    dt = next((c for c in cols if any(h in str(c) for h in ("日期", "时间"))), None)
    ex = [f'SELECT * FROM t LIMIT 20']
    if cat and num:
        ex.append(f'SELECT "{cat}", SUM("{num}") AS 收入, COUNT(*) AS 行数\n'
                  f'FROM t GROUP BY 1 ORDER BY 2 DESC')
    if cat and num and dt:
        ex.append(f'-- 窗口函数：每个品类按月排名\n'
                  f'SELECT * FROM (\n'
                  f'  SELECT "{cat}", strftime("{dt}", \'%Y-%m\') AS 月份, SUM("{num}") AS 收入,\n'
                  f'         ROW_NUMBER() OVER (PARTITION BY 月份 ORDER BY SUM("{num}") DESC) AS 排名\n'
                  f'  FROM t GROUP BY 1, 2\n) WHERE 排名 <= 3 ORDER BY 月份, 排名')
    if num:
        ex.append(f'-- 占比与累计（CTE + 累计窗口）\n'
                  f'WITH s AS (SELECT "{cat or "品类"}" AS 维度, SUM("{num}") AS 收入 FROM t GROUP BY 1)\n'
                  f'SELECT 维度, 收入, ROUND(100.0*收入/SUM(收入) OVER (), 1) AS 占比,\n'
                  f'       ROUND(100.0*SUM(收入) OVER (ORDER BY 收入 DESC)/SUM(收入) OVER (), 1) AS 累计占比\n'
                  f'FROM s ORDER BY 收入 DESC')
    return ex


def render_sql(df):
    st.markdown("<div class='sect'>SQL 查询台<small>上传的表 = 表名 t，支持窗口函数、CTE、子查询</small></div>",
                unsafe_allow_html=True)
    st.caption("只读：只接受 SELECT / WITH；结果最多 5000 行。列名含中文或空格时用双引号包起来。")

    with st.expander("查看可用列名", expanded=False):
        st.markdown("　".join(f"`{c}`" for c in df.columns))

    exs = _examples(list(df.columns))
    pick = st.selectbox("示例查询", ["（自己写）"] + [f"示例 {i+1}" for i in range(len(exs))],
                        key="sql_example")
    default = exs[int(pick.split()[-1]) - 1] if pick != "（自己写）" else st.session_state.get("sql_text", exs[0])
    sql = st.text_area("SQL", value=default, height=170, key="sql_text")

    c1, c2 = st.columns([1, 3])
    if c1.button("执行查询", key="sql_run", type="primary"):
        st.session_state["sql_result"] = run_sql(df, sql)

    res, err = st.session_state.get("sql_result", (None, None))
    if err:
        st.error(f"查询失败：{err}")
    elif res is not None:
        st.markdown(f"<div style='font-size:12.5px;color:{MUTED}'>结果 {len(res):,} 行 × {len(res.columns)} 列</div>",
                    unsafe_allow_html=True)
        st.dataframe(res, width="stretch", hide_index=True)
        nums = [c for c in res.columns if pd.api.types.is_numeric_dtype(res[c])]
        if nums and len(res) <= 200:
            try:
                import plotly.express as px
                x = next((c for c in res.columns if c not in nums), res.columns[0])
                fig = px.bar(res.head(30), x=x, y=nums[0], color_discrete_sequence=["#1F3864"])
                fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                                  paper_bgcolor="#fff", plot_bgcolor="#fff",
                                  font=dict(family="Microsoft YaHei, sans-serif", size=12))
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            except Exception:
                pass
        st.download_button("下载结果 CSV", res.to_csv(index=False).encode("utf-8-sig"),
                           file_name="query_result.csv", mime="text/csv", key="sql_dl")


def render_ask(df, schema):
    """用一句话问数据：中文 → SQL → 结果 → 导出。"""
    st.markdown("<div class='sect'>用一句话问数据<small>说人话，自动写 SQL 并出结果</small></div>",
                unsafe_allow_html=True)
    st.caption("比如：上个月各品类销售额 / 最近 30 天销量最高的商品 / 8 月饮料卖了多少 / 各品类毛利率")

    examples = ["上个月各品类销售额", "最近 30 天销量最高的商品",
                "8 月各品类销售额前 5", "各品类毛利率", "各月份收入"]
    try:
        picked = st.pills("示例", examples, key="ask_pills", label_visibility="collapsed")
    except Exception:
        picked = st.selectbox("示例", ["（自己输入）"] + examples, key="ask_sel",
                              label_visibility="collapsed")

    # 点了示例就把问题写进输入框（widget 已有 value 时会被忽略，必须写 session_state）
    if isinstance(picked, str) and picked in examples and st.session_state.get("_ask_pill") != picked:
        st.session_state["_ask_pill"] = picked
        st.session_state["ask_q"] = picked
        st.rerun()

    c1, c2 = st.columns([4, 1])
    q = c1.text_input("问题", key="ask_q", label_visibility="collapsed",
                      placeholder="输入你的问题，例如：上个月各品类销售额前 5")
    if c2.button("查询", key="ask_go", type="primary"):
        parsed = nlq.to_sql(q, schema)
        if not parsed.get("ok"):
            st.session_state["ask_res"] = (parsed, None, None)
        else:
            out, err = run_sql(df, parsed["sql"])
            st.session_state["ask_res"] = (parsed, out, err)

    res = st.session_state.get("ask_res")
    if not res:
        return
    parsed, out, err = res
    if not parsed.get("ok"):
        st.warning("没听懂这个问题：" + str(parsed.get("reason")))
        st.caption("换个说法试试：带上「哪个维度（品类/商品/月份）」+「什么指标（销售额/数量/订单数/客单价/毛利率）」"
                   "+「时间（上个月/近 30 天/8 月）」。")
        return

    st.markdown(f"<div class='insight'>我的理解：{parsed['explain']}</div>", unsafe_allow_html=True)
    with st.expander("查看生成的 SQL", expanded=False):
        st.code(parsed["sql"], language="sql")
    if err:
        st.error(f"执行出错：{err}")
        return
    if out is None or out.empty:
        st.info("查询没有返回数据：可能是这个时间范围内没有记录，或筛选条件太严。")
        return

    st.markdown(f"<div style='font-size:12.5px;color:{MUTED}'>结果 {len(out):,} 行</div>",
                unsafe_allow_html=True)
    st.dataframe(out, width="stretch", hide_index=True)

    nums = [c for c in out.columns if pd.api.types.is_numeric_dtype(out[c])]
    if nums and len(out) <= 100:
        try:
            import plotly.express as px
            x = next((c for c in out.columns if c not in nums), out.columns[0])
            fig = px.bar(out.head(30), x=x, y=nums[0], color_discrete_sequence=["#1F3864"],
                         text=nums[0])
            fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=20, b=10),
                              paper_bgcolor="#fff", plot_bgcolor="#fff",
                              font=dict(family="Microsoft YaHei, sans-serif", size=12))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        except Exception:
            pass

    st.download_button("下载结果 CSV", out.to_csv(index=False).encode("utf-8-sig"),
                       file_name="问数结果.csv", mime="text/csv", key="ask_dl")
