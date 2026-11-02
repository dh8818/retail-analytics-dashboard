# -*- coding: utf-8 -*-
"""retail_ops 的算法校验：不复用被测函数的中间量，独立重算关键指标并比对。

跑法：python test_retail_ops.py
"""
import math
import sys

import pandas as pd

import retail_ops as RO

FAIL = []


def close(a, b, tol=1e-6, label=""):
    ok = abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    print(f"  {'✓' if ok else '✗'} {label}: {a:,.4f} vs {b:,.4f}")
    if not ok:
        FAIL.append(label)


def case_demo():
    """用项目里的真实样例数据，独立算一遍再和引擎比。"""
    print("\n[1] 样例门店：独立复算")
    pos = pd.read_csv("data/pos.csv", encoding="utf-8-sig", parse_dates=["日期"])
    prod = pd.read_csv("data/products.csv", encoding="utf-8-sig")
    days = pos["日期"].nunique()
    sales = pos["金额"].sum()
    cogs = pos["成本"].sum()
    orders = pos["订单号"].nunique()
    qty = pos["数量"].sum()
    inv = float((prod["当前库存"] * prod["进价"]).sum())

    m = RO.compute({
        "days": int(days), "sales": float(sales), "cogs": float(cogs),
        "orders": int(orders), "qty": float(qty),
        "open_inv": inv, "close_inv": inv,
        "sku_active": len(prod), "sku_sold": len(prod), "sku_oos": 0,
        "area": 68, "staff": 5,
        "rent": 6000, "labor": 19000, "utility": 2200, "dep": 800, "other": 800,
    })

    close(m["gp"], sales - cogs, label="毛利额 = 销售额 − 成本")
    close(m["gm"], (sales - cogs) / sales, label="毛利率")
    close(m["fixed_month"], 28800, label="固定开销合计（月）")
    close(m["fixed"], 28800 * days / 30, label="固定开销折算到本期")
    close(m["op_profit"], (sales - cogs) - m["fixed"], label="经营利润")
    close(m["net"], m["op_profit"], label="净利（无报损时）")
    close(m["be_sales"] * m["gm"], m["fixed"], tol=1e-9, label="保本销售额 × 毛利率 = 固定费用")
    close(m["safety"], (sales - m["be_sales"]) / sales, label="安全边际")
    close(m["turn_days"], inv / (cogs / days), label="周转天数")
    close(m["turn_annual"], 365 / (inv / (cogs / days)), label="年化周转次数")
    close(m["psm"], sales / 68 / (days / 30), label="坪效")
    close(m["labor_eff"], sales / 5 / (days / 30), label="人效")
    close(m["rent_ratio"], 6000 / (sales / (days / 30)), label="租售比")
    close(m["aov"], sales / orders, label="客单价")
    close(m["basket"], qty / orders, label="连带率")
    close(m["dol"], (sales - cogs) / m["op_profit"], label="经营杠杆 DOL")

    # 五层减法必须严格闭合
    wf = sales - cogs - m["fixed"] - 0 - 0
    close(wf, m["net"], tol=1e-9, label="五层减法闭合：销售额−成本−固定费用−损耗=净利")
    return m


def case_edge():
    print("\n[2] 边界：未填库存 / 亏损 / 零销售额")
    m = RO.compute({"days": 30, "sales": 100000, "cogs": 60000, "close_inv": 0})
    assert m["inv_known"] is False, "未填库存时 inv_known 必须为 False"
    assert m["turn_days"] == 0, "未填库存时周转天数应为 0（表示未知，不是很快）"
    print("  ✓ 未填库存：inv_known=False，周转天数=0")

    m2 = RO.compute({"days": 30, "sales": 0, "cogs": 0, "rent": 10000})
    assert m2["gm"] == 0 and m2["safety"] == 0 and m2["be_sales"] == 0
    print("  ✓ 零销售额不产生除零异常")

    m3 = RO.compute({"days": 30, "sales": 66000, "cogs": 43560, "rent": 9800, "labor": 24000,
                     "utility": 3200, "dep": 1000, "other": 1000, "loss": 3100, "shrink": 900,
                     "close_inv": 30000, "open_inv": 30000, "area": 85, "staff": 6,
                     "sku_active": 72, "sku_sold": 49})
    d = RO.diagnose(m3)
    assert m3["net"] < 0 and d["level"] == "bad" and d["headline"].startswith("现在不是促销"), d
    print(f"  ✓ 亏损店判为 P0 保本：{d['headline']}")

    # 没有成本列：必须先停下修口径，不能直接给「先保本」的经营建议
    m4 = RO.compute({"days": 30, "sales": 100000, "cogs": 0, "rent": 10000})
    d4 = RO.diagnose(m4)
    assert d4["actions"][0]["code"] == "D0", d4["actions"][0]
    print(f"  ✓ 无成本列先停：{d4['headline']}")


def case_promo():
    print("\n[3] 促销公式：精确式 + 打平增量")
    m = RO.compute({"days": 30, "sales": 100000, "cogs": 55000, "rent": 10000, "labor": 15000})
    sim = RO.promo_sim(m, 10, 15)
    gm, d = m["gm"], 0.10
    close(sim["gm_new"], (gm - d) / (1 - d), label="折后毛利率 =（毛利率−折扣率）÷（1−折扣率）")
    assert abs(sim["gm_new"] - (gm - d)) > 0.01, "近似式与精确式必须有可见差异"
    close(sim["need_lift_promo"], d / (gm - d), label="促销打平增量 = 折扣率 ÷（毛利率−折扣率）")

    # 增量刚好等于打平增量时，增量毛利应约等于 0
    lift = sim["need_lift_promo"] * 100
    sim2 = RO.promo_sim(m, 10, lift)
    close(sim2["inc_gp"], 0.0, tol=1e-3, label="增量=打平增量时增量毛利≈0")

    # ROI 的分子是增量毛利，不是增量销售额
    sim3 = RO.promo_sim(m, 10, 40)
    close(sim3["roi"], sim3["inc_gp"] / sim3["spend"], label="ROI = 增量毛利 ÷ 让利投入")


def case_order():
    print("\n[4] 订货三件套与报童模型")
    o = RO.order_point(12, 2, 0.3, 7, 10, 0)
    close(o["safety"], 12 * 0.3 * math.sqrt(2), label="安全库存")
    close(o["rop"], 12 * 2 + o["safety"], label="订货点")
    close(o["qty"], max(0, 12 * 7 - 10), label="订货量")
    nb = RO.newsboy(12, 7)
    close(nb["service"], 5 / 12, label="最优服务水平 = 毛利率")
    nb2 = RO.newsboy(10, 8)
    assert nb2["service"] < nb["service"], "毛利率更低时必须订得更保守"
    print("  ✓ 毛利率越低，服务水平越低（订得更保守）")


def case_branches():
    print("\n[5] 三种结论必须能分别触发")
    base = {"days": 30, "area": 68, "staff": 5, "close_inv": 20000, "open_inv": 20000,
            "sku_active": 45, "sku_sold": 43, "rent": 6000, "labor": 19000,
            "utility": 2200, "dep": 800, "other": 800}
    # 健康 + 下滑 → 可促销
    m_ok = RO.compute({**base, "sales": 96000, "cogs": 52800, "loss": 700,
                       "mom_sales": -6, "mom_traffic": -2, "mom_aov": -4})
    d_ok = RO.diagnose(m_ok)
    assert d_ok["level"] == "ok" and "促销" in d_ok["headline"], d_ok["headline"]
    codes_ok = [a["code"] for a in d_ok["actions"]]
    assert "B5" in codes_ok, codes_ok
    print(f"  ✓ 健康店触发促销建议：{d_ok['headline']} | {codes_ok}")

    # 压货 → 先精简
    m_slow = RO.compute({**base, "sales": 108000, "cogs": 59400, "loss": 2300,
                         "sku_active": 88, "sku_sold": 54, "close_inv": 46500, "open_inv": 41000,
                         "mom_sales": -12, "mom_traffic": -1, "mom_aov": -11})
    d_slow = RO.diagnose(m_slow)
    assert d_slow["level"] == "warn" and "精简" in d_slow["headline"], d_slow["headline"]
    assert any(a["code"] == "B4" for a in d_slow["actions"])
    print(f"  ✓ 压货店触发精简建议：{d_slow['headline']}")

    # 亏损 → 先保本，且必须有「不要做折扣」
    m_bad = RO.compute({**base, "sales": 66000, "cogs": 43560, "loss": 3100, "shrink": 900,
                        "rent": 9800, "labor": 24000, "utility": 3200})
    d_bad = RO.diagnose(m_bad)
    assert d_bad["level"] == "bad" and d_bad["actions"][0]["priority"] == "P0"
    assert d_bad["not_do"], "亏损店必须给出「不要做折扣」的反向建议"
    print(f"  ✓ 亏损店触发保本建议：{d_bad['headline']} | 不建议：{d_bad['not_do'][0]['t']}")


if __name__ == "__main__":
    case_demo()
    case_edge()
    case_promo()
    case_order()
    case_branches()
    print("\n结果：", "全部通过" if not FAIL else f"失败 {len(FAIL)} 项 -> {FAIL}")
    sys.exit(0 if not FAIL else 1)
