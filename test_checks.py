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

print("\n== 目标达成 ==")
tp = AN.target_progress(pd.Series([10.0, 20.0, 30.0]), 100, elapsed=0.5)
check("达成率%", tp["rate"], 30.0)
check("推算%", tp["proj_rate"], 60.0)

print("\n" + ("全部通过 ✅" if not FAIL else f"失败 {len(FAIL)} 项 ❌：{FAIL}"))
sys.exit(0 if not FAIL else 1)
