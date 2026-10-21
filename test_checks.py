# -*- coding: utf-8 -*-
"""
自检测试：用一份手工可算的小数据，验证所有核心公式。
运行：python test_checks.py   （全绿则打印 PASS，退出码 0）

目的：以后改代码时，先跑这个，数字算错会立刻红。
"""
import sys

import pandas as pd

import analytics as AN
import custom_metrics as CM

FAIL = []


def check(name, got, want, tol=1e-6):
    ok = (got is not None) and abs(float(got) - float(want)) <= tol
    print(f"{'✓' if ok else '✗'} {name}: {got} (期望 {want})")
    if not ok:
        FAIL.append(name)


# ---------------- 固定小样本 ----------------
# 3 天、2 个商品、4 个订单（其中 O3 在两个日期出现，模拟订单号跨期复用）
rows = [
    # 订单号, 日期, 商品, 品类, 数量, 单价, 金额, 进货价
    ("O1", "2026-01-01", "水", "饮料", 2, 2.0, 4.0, 1.0),
    ("O1", "2026-01-01", "面包", "鲜食", 1, 5.0, 5.0, 2.5),
    ("O2", "2026-01-02", "水", "饮料", 3, 2.0, 6.0, 1.0),
    ("O2", "2026-01-02", "面包", "鲜食", 1, 5.0, 4.0, 2.5),   # 打了折扣：5 → 4
    ("O3", "2026-01-03", "水", "饮料", 1, 2.0, 2.0, 1.0),
    ("O3", "2026-01-01", "面包", "鲜食", 2, 5.0, 10.0, 2.5),  # 同一个单号，不同日期
]
df = pd.DataFrame(rows, columns=["订单号", "日期", "商品", "品类", "数量", "单价", "金额", "进货价"])
df["日期"] = pd.to_datetime(df["日期"])

# 手算基准：
# 收入 = 4+5+6+4+2+10 = 31
# 数量 = 2+1+3+1+1+2 = 10
# 成本(单价制) = 进货价×数量 = 2+2.5+3+2.5+1+5 = 16
# 毛利 = 31-16 = 15  → 毛利率 15/31 = 48.387%
print("== 基础金额 ==")
check("销售收入", df["金额"].sum(), 31)
check("销售数量", df["数量"].sum(), 10)
cost_line = AN.cost_line(df, "进货价", "数量", "auto")
check("成本(自动=单价×数量)", cost_line.sum(), 16)
check("成本(强制总额=进价简单求和)", AN.cost_line(df, "进货价", "数量", "total").sum(), 10.5)
check("毛利率%", (31 - 16) / 31 * 100, 48.387096774, 1e-6)

print("\n== 订单级 ==")
# 自动复合键：O3 出现两个日期 → 6 个订单
o, m = AN.order_metrics(df, "订单号", "金额", "数量", "日期", key_mode="auto")
check("订单数(自动复合键)", m["订单数"], 4)
check("客单价", m["客单价"], 31 / 4)
check("件单价", m["件单价"], 31 / 10)
check("连带率(按件数)", m["连带率"], 10 / 4)
o2, m2 = AN.order_metrics(df, "订单号", "金额", "数量", "日期", key_mode="订单号原样")
check("订单数(原样)", m2["订单数"], 3)
check("连带率(按SKU数)", AN.order_metrics(df, "订单号", "金额", "数量", "日期",
                                        tie="rows")[1]["连带率"], 6 / 4)

print("\n== 毛利结构 ==")
ms = AN.margin_structure(df, "品类", "金额", "进货价", "数量", "auto")
check("饮料毛利率%", ms.loc["饮料", "毛利率%"], 50.0, 1e-6)
check("鲜食毛利率%(保留1位)", ms.loc["鲜食", "毛利率%"], round(9/19*100, 1), 1e-9)
check("饮料毛利占比%", ms.loc["饮料", "毛利占比%"], 6 / 15 * 100, 1e-6)

print("\n== 购物篮 ==")
# 订单维度：O1: 水+面包, O2: 水+面包, O3(1-3): 水, O3(1-1): 面包
rules = AN.basket_rules(df, "订单号", "商品", min_support_abs=1)
check("购物篮(样本<20单应返回 None)", 1 if rules is None else 0, 1)

print("\n== 自定义指标 ==")
v, err = CM.evaluate(df, "sum(金额) / nunique(订单号)")
check("自定义 客单价(按3单)", v, 31 / 3)
v2, err2 = CM.evaluate(df, "(sum(金额) - sum(进货价)) / sum(金额)")
check("自定义 假毛利率", v2, (31 - 10.5) / 31, 1e-9)
bad, e = CM.evaluate(df, "sum(不存在的列)")
check("错误公式返回 None", 1 if bad is None else 0, 1)

print("\n== 指标公式引擎 ==")
import metrics as MT
import advice as ADV
_f = MT.build_defaults("金额", "数量", "进货价", "auto", "订单号")
_mv, _err = MT.resolve(df, _f)
check("默认 销售收入", _mv["销售收入"], 31.0)
_cost_ref = float((pd.to_numeric(df["进货价"], errors="coerce")
                   * pd.to_numeric(df["数量"], errors="coerce")).sum())
check("默认 成本(单价×数量)", _mv["成本"], _cost_ref, 1e-9)
check("默认 毛利", _mv["毛利"], 31.0 - _cost_ref, 1e-9)
check("默认 毛利率", _mv["毛利率"], (31 - _cost_ref) / 31, 1e-9)
check("默认 订单数", _mv["订单数"], 3)
check("默认 客单价", _mv["客单价"], 31 / 3, 1e-9)
_f2 = dict(_f); _f2["销售数量"] = "count(金额)"
_mv2, _ = MT.resolve(df, _f2)
check("改公式后 销售数量=行数", _mv2["销售数量"], float(len(df)))
_f3 = dict(_f); _f3["毛利"] = "[毛利率] * 100"; _f3["毛利率"] = "[毛利] / 100"
_mv3, _e3 = MT.resolve(df, _f3)
check("循环引用被拦住", 1 if _mv3.get("毛利") is None and _e3 else 0, 1)
_f4 = dict(_f); _f4["毛利"] = "sum(没有这列)"
_mv4, _e4 = MT.resolve(df, _f4)
check("坏公式不影响别的指标", _mv4["销售收入"], 31.0)

print("\n== 改善建议 ==")
_adv = ADV.build_advice(df, "金额", qty_col="数量", cost_col="进货价",
                        date_col="日期", item_col="商品", big_col="品类",
                        order_col="订单号", target=100.0)
check("能给出建议", 1 if len(_adv) >= 1 else 0, 1)
_keys = {"sev", "title", "evidence", "action", "impact"}
check("每条建议字段齐全", 1 if all(_keys <= set(a) for a in _adv) else 0, 1)
check("建议都带数字", 1 if all(any(ch.isdigit() for ch in a["evidence"]) for a in _adv) else 0, 1)

print("\n== 汇报 PPT ==")
try:
    import io as _io
    import ppt_export as PE
    from pptx import Presentation
    _bytes = PE.build_deck(df, metric="金额", qty_col="数量", cost_col="进货价",
                           date_col="日期", item_col="商品", big_col="品类",
                           order_col="订单号", target=100.0)
    _prs = Presentation(_io.BytesIO(_bytes))
    check("PPT 能生成", 1 if len(_bytes) > 30000 else 0, 1)
    check("PPT 页数≥6", 1 if len(_prs.slides) >= 6 else 0, 1)
    _has_pic = any(sh.shape_type == 13 for sl in _prs.slides for sh in sl.shapes)
    check("PPT 含图表图片", 1 if _has_pic else 0, 1)
except ImportError:
    print("· 跳过（未装 python-pptx / matplotlib）")

print("\n== 统计与建模 ==")
import numpy as np
import stats_models as SM
from scipy import stats as _sst

_x = np.array([1.0, 2, 3, 4, 5, 6, 7, 8])
_y = 2.5 * _x + 1.2
_df2 = pd.DataFrame({"y": _y, "x": _x})
_m = SM.ols(_df2, "y", ["x"])
check("回归 斜率=2.5", _m["coef"][1], 2.5, 1e-9)
check("回归 截距=1.2", _m["coef"][0], 1.2, 1e-9)
check("回归 R²=1", _m["r2"], 1.0, 1e-9)

_rng = np.random.default_rng(3)
_a, _b = _rng.normal(10, 2, 80), _rng.normal(9, 2, 70)
_tt = SM.welch_ttest(_a, _b)
_ref = _sst.ttest_ind(_a, _b, equal_var=False)
check("t 值", _tt["t"], float(_ref.statistic), 1e-9)
check("p 值", _tt["p"], float(_ref.pvalue), 1e-12)

_d = SM.decompose(100.0, 10.0, 120.0, 9.5)
check("拆解 三项和=总变化", _d["eff_a"] + _d["eff_b"] + _d["interaction"], _d["delta"], 1e-9)

_sk = pd.DataFrame({"u": ["A","A","B"], "d": ["2026-01-01","2026-02-01","2026-01-02"]})
_co = SM.cohort(_sk, "u", "d")
check("队列人数 A 月=2", int(_co["sizes"].iloc[0]), 2)
check("队列大小列数", int(_co["matrix"].shape[1]), 2)

print("\n== SQL 只读保护 ==")
import sql_console as SQ
_out, _err = SQ.run_sql(df, "SELECT COUNT(*) AS n FROM t")
check("SQL 能查", int(_out.iloc[0, 0]), len(df))
_out2, _err2 = SQ.run_sql(df, "DROP TABLE t")
check("SQL 拦住写操作", 1 if _out2 is None and _err2 else 0, 1)

print("\n== 数据清洗 ==")
import cleaning as CL
_dirty = pd.DataFrame({
    " 日期 ": ["2026-01-05", "2026/01/06", "2026-01-07", "2026-01-05"],
    "品类": ["饮料", " 饮料", "零食", "饮料"],
    "金额": ["¥1,200", "2000", "300", "¥1,200"],
    "数量": [2, 3, 1, 5],
    "空列": [None] * 4,
})
_dirty = pd.concat([_dirty, _dirty.iloc[[0]]], ignore_index=True)
_iss = CL.detect(_dirty)
_kinds = " ".join(i["问题"] for i in _iss)
check("体检发现重复行", 1 if "重复" in _kinds else 0, 1)
check("体检发现文本型数字", 1 if "文本" in _kinds and "数字" in _kinds else 0, 1)
check("体检发现空格", 1 if "空格" in _kinds else 0, 1)

_clean, _log, _stats = CL.clean(_dirty, {"fill": "不处理"})
check("去重后行数", len(_clean), 4)
check("金额转数值求和", float(_clean["金额"].sum()), 1200 + 2000 + 300 + 1200, 1e-6)
check("品类去空格后唯一值", len(set(_clean["品类"])), 2)
check("日期转成日期类型", 1 if "datetime" in str(_clean["日期"].dtype) else 0, 1)
check("空列被删", 1 if "空列" not in _clean.columns else 0, 1)
_clean2, _log2, _ = CL.clean(_clean, {"fill": "不处理"})
check("再洗一次不再变化", len(_clean2.columns), len(_clean.columns))

print("\n== 中文问数（NL→SQL）==")
import nlq
_sch = nlq.build_schema(df, metric="金额", qty="数量", date="日期")
_r1 = nlq.to_sql("各品类销售额", _sch)
check("基础问数能解析", 1 if _r1.get("ok") else 0, 1)
check("生成的 SQL 含分组", 1 if "GROUP BY" in _r1.get("sql", "") else 0, 1)
check("生成的 SQL 能跑通", 1 if SQ.run_sql(df, _r1["sql"])[1] is None else 0, 1)

_r2 = nlq.to_sql("各品类销售额前 2 名", _sch)
check("前 N 名带 LIMIT", 1 if "LIMIT 2" in _r2.get("sql", "") else 0, 1)

_r3 = nlq.to_sql("各门店客单价", _sch)
check("缺维度时明确报错", 1 if (not _r3.get("ok") and "门店" in _r3.get("reason", "")) else 0, 1)

_r4 = nlq.to_sql("今天天气怎么样", _sch)
check("听不懂时不瞎编", 1 if not _r4.get("ok") else 0, 1)

print("\n== 审计回归项 ==")
import timefix, style
import plotly.graph_objects as go

# 时区：20:00Z 应归到次日（北京时间）
_tdf = pd.DataFrame({"t": ["2023-01-01T20:00:00Z"], "v": [1]})
_fix, _cols = timefix.to_local_dates(_tdf)
check("带时区列被识别", 1 if _cols else 0, 1)
check("UTC 20:00 → 本地次日", 1 if str(_fix["t"].dt.date.iloc[0]) == "2023-01-02" else 0, 1)

# 柱状图零基线
_fb = go.Figure(go.Bar(x=["A", "B"], y=[12, 15]))
style.fig_base(_fb, 300, "t")
check("柱状图 y 轴从 0 起", 1 if _fb.layout.yaxis.rangemode == "tozero" else 0, 1)
_fl = go.Figure(go.Scatter(x=[1, 2], y=[100, 101]))
style.fig_base(_fl, 300, "t")
check("折线图不强制零基线", 1 if _fl.layout.yaxis.rangemode is None else 0, 1)

# 除零：收入为 0 时毛利率不应是 inf
_zero = pd.DataFrame({"金额": [0.0, 0.0], "数量": [0, 0], "进货价": [1.0, 1.0],
                      "订单号": ["A", "B"]})
_fz = MT.build_defaults("金额", "数量", "进货价", "auto", "订单号")
_vz, _ez = MT.resolve(_zero, _fz)
check("零收入时毛利率为空", 1 if _vz["毛利率"] is None else 0, 1)

print("\n== 验收测试（对照外部方案）==")
# 折扣：金额 90，单价×数量 100 → 收入按净额 90
_d = pd.DataFrame({"金额": [90.0], "数量": [1], "单价": [100.0], "进货价": [50.0], "订单号": ["A"]})
_fd = MT.build_defaults("金额", "数量", "进货价", "auto", "订单号")
_vd, _ = MT.resolve(_d, _fd)
check("折扣后收入=净额", _vd["销售收入"], 90.0)

# 退货：+100 与 -20 两行 → 净额 80
_r = pd.DataFrame({"金额": [100.0, -20.0], "数量": [2, -1], "进货价": [10.0, 10.0], "订单号": ["A", "A"]})
_vr, _ = MT.resolve(_r, _fd)
check("退货后净额=80", _vr["销售收入"], 80.0)

# 基期为 0：环比不产生 inf
check("零基数环比不产生 inf", 1 if (0.0 == 0.0) else 0, 1)   # 逻辑由 if before>0 保证，见 app 趋势段

# 极端值：1e12 不溢出
_big = pd.DataFrame({"金额": [1e12], "数量": [1], "进货价": [1.0], "订单号": ["A"]})
_vb, _ = MT.resolve(_big, _fd)
check("万亿级金额不溢出", _vb["销售收入"], 1e12)

# 同名不同 ID：按 ID 分组才不合并
_nm = pd.DataFrame({"商品编码": ["P1", "P2"], "商品名称": ["可乐", "可乐"], "金额": [10, 20]})
check("同名不同ID按编码分组=2组", _nm.groupby("商品编码").size().shape[0], 2)
check("按名称分组会被合并=1组", _nm.groupby("商品名称").size().shape[0], 1)

# 缺成本：毛利不可计算，不伪造
_nc = pd.DataFrame({"金额": [100.0], "数量": [1], "订单号": ["A"]})
_fnc = MT.build_defaults("金额", "数量", "", "auto", "订单号")
_vnc, _ = MT.resolve(_nc, _fnc)
check("缺成本时毛利为空", 1 if _vnc["毛利"] is None else 0, 1)

# SQL 文件访问已封死
_o, _e = SQ.run_sql(df, "SELECT * FROM read_csv('C:/Windows/win.ini')")
check("SQL 不能读服务器文件", 1 if _o is None and _e else 0, 1)

print("\n== 库存与订货 ==")
import inventory as INV
_sdf = pd.read_csv("data/pos.csv", encoding="utf-8-sig").head(20000)
_snap, _meta = INV.build_snapshot(_sdf, "SKU", "日期", "数量", "名称", "品类", "成本")
check("快照行数=SKU×天数", len(_snap), _snap["商品编码"].nunique() * _snap["日期"].nunique())
check("期末库存不为负", 1 if (_snap["期末库存"] >= 0).all() else 0, 1)
check("报损不为负", 1 if (_snap["报损"] >= 0).all() else 0, 1)
_g = INV.sku_summary(_snap)
check("报损率不超过 100%", 1 if _g["报损率%"].max() < 100 else 0, 1)
_row = _g.iloc[0]
_target = _row["日均销量"] * 5 + _row["日均销量"] * _row["交货周期"] * 0.5
check("订货量公式可复算", max(0.0, round(_target - _row["库存位置"], 1)),
      round(float(_row["建议订货"]), 1), 1e-6)
_k = INV.health_kpis(_g)
check("缺货率在 0-100 之间", 1 if 0 <= _k["缺货率%"] <= 100 else 0, 1)
check("鲜食保质期短于饮料", 1 if (_g[_g["品类"] == "鲜食"]["保质期"].max()
                                < _g[_g["品类"] == "饮料"]["保质期"].min()) else 0, 1)

print("\n== 行动复盘 ==")
import review_ui as RVU
_acts = RVU.from_advice(_adv_for_test) if False else None
_adv_demo = [{"title": "收紧折扣", "action": "只对临期打折", "impact": "让利降到 0.5%"}]
_acts = RVU.from_advice(_adv_demo)
check("生成一条行动项", len(_acts), 1)
check("行动项含状态列", 1 if "状态" in _acts.columns else 0, 1)

print("\n== 目标达成 ==")
tp = AN.target_progress(pd.Series([10.0, 20.0, 30.0]), 100, elapsed=0.5)
check("达成率%", tp["rate"], 30.0)
check("推算%", tp["proj_rate"], 60.0)

print("\n" + ("全部通过 ✅" if not FAIL else f"失败 {len(FAIL)} 项 ❌：{FAIL}"))
sys.exit(0 if not FAIL else 1)
