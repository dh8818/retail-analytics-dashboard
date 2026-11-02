# -*- coding: utf-8 -*-
"""
零售运营指标与门店诊断引擎（纯函数，无第三方依赖，可直接被 app.py / build.py 调用）。

为什么单独一个模块：
- metric_catalog.py 管「指标定义」，metrics.py 管「在数据表上求值」，
  但这两个都不处理「固定费用、保本点、周转、动销、订货」这类**需要手工输入的门店经营参数**。
- 本模块把《零售数据运营实战手册》第 3–5 章的算法固化成可复用的函数，
  并给出「指标 → 阈值 → 动作」的诊断规则，供看板、报告、导出共用。

用法：
    from retail_ops import compute, diagnose
    m = compute({"days": 90, "sales": 230507, ...})
    for a in diagnose(m)["actions"]:
        print(a["priority"], a["title"], a["impact"])

命令行自检：
    python retail_ops.py
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------- 口径常量
# 社区便利业态经验区间，仅用于判断方向，不是考核标准
BENCH = {
    "turn_days": (7, 14, 21),        # 健康上限 / 关注 / 预警
    "gross_margin": (0.32, 0.28),    # 健康下限 / 预警
    "waste_rate": (0.015, 0.025),    # 健康 / 关注
    "active_rate": (0.80, 0.70),
    "rent_ratio": (0.10, 0.15),
    "psm": (1000, 800),              # 元/㎡/月
    "labor_eff": (10000, 8000),      # 元/人/月
    "safety": (0.15, 0.05),
}

DEFAULTS: dict[str, Any] = {
    "days": 30, "sales": 0, "cogs": 0, "orders": 0, "qty": 0,
    "open_inv": 0, "close_inv": 0, "loss": 0, "shrink": 0,
    "sku_active": 0, "sku_sold": 0, "sku_oos": 0,
    "area": 0, "staff": 0,
    "rent": 0, "labor": 0, "utility": 0, "dep": 0, "other": 0,
    "promo_spend": 0, "promo_incr": 0,
    "mom_sales": 0, "mom_traffic": 0, "mom_aov": 0,
}


def _div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute(raw: dict) -> dict:
    """输入整店流水 + 固定开销，输出全部经营指标。

    固定开销按「每月」传入，内部按统计天数折算到本期——
    这是最容易被算错的一处：90 天的店只填了一个月的房租，净利会被高估 3 倍。
    """
    x = {**DEFAULTS, **{k: v for k, v in raw.items() if v is not None}}
    days = max(1, int(x["days"]))
    months = days / 30.0

    sales, cogs, orders, qty = float(x["sales"]), float(x["cogs"]), float(x["orders"]), float(x["qty"])
    fixed_month = sum(float(x[k]) for k in ("rent", "labor", "utility", "dep", "other"))
    fixed = fixed_month * months

    gp = sales - cogs
    gm = _div(gp, sales)
    avg_inv = (float(x["open_inv"]) + float(x["close_inv"])) / 2 if float(x["open_inv"]) > 0 else float(x["close_inv"])
    cogs_daily = cogs / days
    turn_days = _div(avg_inv, cogs_daily)
    turnover = _div(cogs, avg_inv)
    turn_annual = 365 / turn_days if turn_days else 0

    op_profit = gp - fixed
    loss, shrink = float(x["loss"]), float(x["shrink"])
    net = op_profit - loss - shrink

    be_sales = fixed / gm if gm > 0 else 0
    be_daily = be_sales / days
    daily_sales = sales / days
    safety = (sales - be_sales) / sales if sales else 0
    dol = gp / op_profit if op_profit else 0

    sales_month = sales / months
    unit_cost = _div(cogs, qty)
    inv_qty = _div(float(x["close_inv"]), unit_cost)

    return {
        "days": days, "months": months,
        "sales": sales, "cogs": cogs, "orders": orders, "qty": qty,
        "sales_month": sales_month,
        "open_inv": float(x["open_inv"]), "close_inv": float(x["close_inv"]),
        "gp": gp, "gm": gm,
        "fixed_month": fixed_month, "fixed": fixed, "fixed_ratio": _div(fixed, sales),
        "op_profit": op_profit, "net": net, "net_margin": _div(net, sales),
        "avg_inv": avg_inv, "inv_known": avg_inv > 0,
        "turnover": turnover, "turn_days": turn_days, "turn_annual": turn_annual,
        "be_sales": be_sales, "be_daily": be_daily, "daily_sales": daily_sales,
        "safety": safety, "dol": dol,
        "rent_ratio": _div(float(x["rent"]), sales_month),
        "psm": _div(sales_month, float(x["area"])),
        "labor_eff": _div(sales_month, float(x["staff"])),
        "aov": _div(sales, orders), "atv": _div(sales, qty), "basket": _div(qty, orders),
        "loss": loss, "shrink": shrink, "loss_rate": _div(loss, sales),
        "waste_rate": _div(loss + shrink, sales),
        "sell_through": _div(qty, qty + inv_qty) if (qty + inv_qty) else 0,
        "oos_rate": _div(float(x["sku_oos"]), float(x["sku_active"])),
        "active_rate": _div(float(x["sku_sold"]), float(x["sku_active"])),
        "promo_roi": _div(float(x["promo_incr"]), float(x["promo_spend"])) if float(x["promo_spend"]) else None,
        "mom_sales": float(x["mom_sales"]), "mom_traffic": float(x["mom_traffic"]), "mom_aov": float(x["mom_aov"]),
    }


def promo_sim(m: dict, discount_pct: float, uplift_pct: float) -> dict:
    """促销模拟：折后毛利率用精确式（毛利率−折扣率）÷（1−折扣率）。

    常见错误是直接用「毛利率 − 折扣率」，在 45% 毛利、八折的情况下会低估 4 个百分点以上。
    """
    d = max(0.0, min(0.95, discount_pct / 100))
    lift = max(-0.9, uplift_pct / 100)
    gm, s, f = m["gm"], m["sales"] / m["months"], m["fixed_month"]

    margin_per_yuan = gm - d                      # 每 1 元原价销售额剩下的毛利
    gm_new = margin_per_yuan / (1 - d) if d < 1 else -1
    gp_base = s * gm
    gp_new = s * (1 + lift) * margin_per_yuan
    inc_gp = gp_new - gp_base
    spend = s * (1 + lift) * d
    return {
        "discount": d, "uplift": lift, "gm_new": gm_new,
        "inc_gp": inc_gp, "spend": spend,
        "roi": _div(inc_gp, spend) if spend else None,
        "need_lift_promo": d / (gm - d) if gm > d else float("inf"),
        "need_lift_store": (f / s) / (gm - d) - 1 if gm > d else float("inf"),
        "verdict": ("不可行：折扣击穿毛利" if gm_new <= 0.05 else
                    "不可行：增量补不回让利" if lift < (d / (gm - d) if gm > d else 9e9) else
                    "可行：能保本" if lift >= ((f / s) / (gm - d) - 1 if gm > d else 9e9) else
                    "有条件可行：促销不亏，但门店当月未保本"),
    }


def order_point(daily: float, lead: float, cv: float, cover: float,
                stock: float = 0, transit: float = 0) -> dict:
    """订货三件套：安全库存 / 订货点 / 订货量。"""
    safety = max(0.0, daily * cv * math.sqrt(max(0.2, lead)))
    rop = daily * max(0.0, lead) + safety
    target = daily * max(0.0, cover)
    return {"safety": safety, "rop": rop, "target": target,
            "qty": max(0.0, target - stock - transit)}


def newsboy(price: float, cost: float) -> dict:
    """鲜食报童模型：最优服务水平 = 毛利 ÷（毛利 + 成本），数值上等于毛利率。"""
    gm = (price - cost) / price if price else 0
    return {"gm": gm, "service": max(0.0, min(1.0, gm)), "unit_margin": price - cost}


# ---------------------------------------------------------------- 诊断规则
def diagnose(m: dict, ctx: dict | None = None) -> dict:
    """指标 → 结论 + 行动清单。ctx 可传 {"c_sku_count": int, "c_sku_sales_share": float}。"""
    ctx = ctx or {}
    actions: list[dict] = []
    not_do: list[dict] = []
    path: list[dict] = []

    def gate(q: str, ok: bool, val: str, note: str):
        path.append({"q": q, "pass": ok, "val": val, "note": note})

    cover = m["gp"] >= m["fixed"]
    be_ok = m["safety"] >= 0.05
    can_promo = m["safety"] >= 0.15 and m["gm"] >= 0.30
    goods_ok = m["active_rate"] >= 0.80 and (not m.get("inv_known", True) or m["turn_days"] <= 21)
    waste_ok = m["waste_rate"] <= 0.025

    cost_ok = m["cogs"] > 0 and 0.02 < m["gm"] < 0.95
    gate("毛利额为正且成本口径可信（0 < 成本 < 收入）", cost_ok, f"毛利率 {m['gm']:.1%}",
         "通过：成本口径可用" if cost_ok else "不通过：成本列缺失或口径有误")
    gate("毛利额覆盖固定费用", cover, f"毛利 {m['gp']:,.0f} / 固定费用 {m['fixed']:,.0f}",
         f"覆盖倍数 {_div(m['gp'], m['fixed']):.2f} 倍")
    gate("安全边际 ≥ 5%", be_ok, f"{m['safety']:.1%}", "通过" if be_ok else "不通过：一次促销就能打进亏损")
    gate("安全边际 ≥ 15% 且毛利率 ≥ 30%", can_promo, f"{m['safety']:.1%} · {m['gm']:.1%}",
         "通过：有让利空间" if can_promo else "不通过：先修利润结构")
    gate("动销率 ≥ 80% 且周转 ≤ 21 天", goods_ok, f"{m['active_rate']:.1%} · {m['turn_days']:.1f} 天",
         "通过" if goods_ok else "不通过：货架和资金被低效 SKU 占着")
    gate("损耗率 ≤ 2.5%", waste_ok, f"{m['waste_rate']:.1%}", "通过" if waste_ok else "不通过：订货或效期管理有问题")

    # 门槛一不过，后面的减法全是错的：先停下修数据，不要给经营建议
    if not cost_ok:
        return {
            "level": "bad",
            "headline": "先核对成本口径，再做经营判断",
            "why": ("毛利率 ≤2%：要么这份数据没接成本列，要么成本列取错了（把售价当成本、或成本单位不一致）。"
                    "在成本口径没确认之前，保本点、净利、促销 ROI 都会算错，所以这一页先不给经营建议。"
                    "到左侧「口径设置 → 成本口径」确认成本来源，或补充成本列后重新进入。"),
            "actions": [{
                "priority": "P0", "code": "D0", "title": "核对成本列与订单去重",
                "basis": [f"毛利率 {m['gm']:.1%}（便利店正常区间 30%–45%）",
                          f"销售额 {m['sales']:,.0f}，销货成本 {m['cogs']:,.0f}"],
                "actions": ["确认成本列是「进价」还是「成本金额」，单价语义需乘数量",
                            "确认订单号是否跨天重号，客单价的分母对不对",
                            "确认退款行是否冲减收入"],
                "impact": 0.0,
                "verify": ["毛利率回到 25% 以上", "净利与财务月度报表能对上"],
            }],
            "not_do": [], "path": path,
        }

    if not cover or m["net"] < 0 or m["safety"] < 0.05:
        rent_cut = m["fixed_month"] * 0.10
        gm_up = (m["sales"] / m["months"]) * 0.02
        loss_cut = (m["loss"] + m["shrink"]) / m["months"] * 0.30
        actions.append({
            "priority": "P0", "code": "B1", "title": "先保本：冻结折扣，压固定费用",
            "basis": [f"净利 {m['net']:,.0f}（净利率 {m['net_margin']:.1%}）",
                      f"保本销售额 {m['be_sales']:,.0f}，实际 {m['sales']:,.0f}",
                      f"安全边际 {m['safety']:.1%}（<5%）"],
            "actions": ["冻结全场折扣与满减", "固定费用砍 10%：房租重谈或缩面积、按客流排班",
                        "毛利率抬 2pt：高销量低毛利品换规格或供应商", "损耗压 30%：短保品按报童模型订"],
            "impact": rent_cut + gm_up + loss_cut,
            "verify": ["30 天内安全边际 ≥ 5%", "净利率转正"],
        })
        gm8 = (m["gm"] - 0.2) / 0.8
        not_do.append({"t": "不要做全场折扣",
                       "d": f"8 折后毛利率 {gm8:.1%}，保本销售额从 {m['be_sales']:,.0f} 抬到 "
                            f"{(m['fixed'] / gm8 if gm8 > 0 else 0):,.0f}"})

    if m["gm"] < 0.28:
        actions.append({
            "priority": "P1" if cover else "P0", "code": "B2", "title": "毛利率撑不起固定费用",
            "basis": [f"毛利率 {m['gm']:.1%}，低于参考下限 28%",
                      f"固定费用率 {m['fixed_ratio']:.1%}"],
            "actions": ["把毛利率抬到 28%", "用满赠替代直接折扣", "提高鲜食与自有品牌占比"],
            "impact": (m["sales"] / m["months"]) * (0.28 - m["gm"]) * 0.6,
            "verify": ["毛利率连续 30 天 ≥ 28%"],
        })

    # 售罄率 = 销量 ÷（销量 + 期末库存），库存没填时这个数恒为 100%，不能拿来判断
    sell_high = m.get("inv_known", True) and m["sell_through"] > 0.93
    if not waste_ok or sell_high or m["oos_rate"] > 0.08:
        sell_txt = (f"售罄率 {m['sell_through']:.1%}" if m.get("inv_known", True)
                    else "售罄率未计算（没填期末库存）")
        actions.append({
            "priority": "P1", "code": "B3", "title": "订货不准：短保压量、长保补断货",
            "basis": [f"损耗率 {m['waste_rate']:.1%}", sell_txt,
                      f"缺货率 {m['oos_rate']:.1%}"],
            "actions": ["短保品按报童模型订（服务水平＝毛利率）", "长保品按订货点补", "列缺货清单分清「没订」与「没送到」"],
            "impact": (m["loss"] + m["shrink"]) / m["months"] * 0.35,
            "verify": ["损耗率 < 2.5%", "缺货率 < 5%"],
        })

    if not goods_ok:
        inv_ok = m.get("inv_known", True)
        release = m["close_inv"] * (1 - 12 / m["turn_days"]) if (inv_ok and m["turn_days"] > 12) else 0
        turn_txt = f"周转 {m['turn_days']:.1f} 天" if inv_ok else "周转未计算（没填期末库存）"
        actions.append({
            "priority": "P1", "code": "B4", "title": "精简商品：砍掉不产钱的 SKU",
            "basis": [f"动销率 {m['active_rate']:.1%}", turn_txt,
                      f"C 类 SKU {ctx.get('c_sku_count', 0)} 个，贡献 {ctx.get('c_sku_sales_share', 0):.1%} 销售额"],
            "actions": ["先淘汰 90 天销量 < 10 件且有替代品的 SKU", "其余做两周端架测试", "把货架让给 A 类"],
            "impact": max(0.0, release) * 0.08 + m["loss"] / m["months"] * 0.2,
            "verify": ["动销率 ≥ 80%", "周转 ≤ 14 天"],
        })

    decline = m["mom_sales"] < -3 or m["mom_traffic"] < -3 or m["mom_aov"] < -3
    if can_promo and decline:
        d_be = 0.15 * m["gm"] / 1.15
        sim = promo_sim(m, max(1.0, min(15.0, d_be * 100 * 0.7)), 15)
        actions.append({
            "priority": "P2", "code": "B5", "title": "可以做促销，但只做保毛利的促销",
            "basis": [f"安全边际 {m['safety']:.1%}", f"销售额环比 {m['mom_sales']:.1f}%",
                      f"折扣上限约 {d_be:.1%}", f"测算 ROI {sim['roi']:.2f}" if sim["roi"] is not None else "测算 ROI —"],
            "actions": ["优先第二件半价/组合装", "折扣只对 C 类与新品开放", "毛利率跌破 30% 立即停"],
            "impact": max(0.0, sim["inc_gp"]),
            "verify": ["促销期毛利率 ≥ 30%", "促销 ROI ≥ 1"],
        })

    if 12 < m["turn_days"] <= 21 and goods_ok:
        release = m["close_inv"] * (1 - 12 / m["turn_days"])
        actions.append({
            "priority": "P2", "code": "B8", "title": "库存微调：把周转压到 12 天",
            "basis": [f"周转 {m['turn_days']:.1f} 天", f"期末库存 {m['close_inv']:,.0f}",
                      f"可释放现金 {release:,.0f}"],
            "actions": ["慢销品两周清一次", "A 类订货频次加倍、单次量减半", "与供应商谈账期或退换货"],
            "impact": 0.0,
            "verify": ["周转 ≤ 12 天", "A 类缺货率不上升"],
        })

    if m["rent_ratio"] > 0.12 or m["psm"] < 800:
        actions.append({
            "priority": "P2", "code": "B6", "title": "租效偏弱：谈租、缩面积或调品类",
            "basis": [f"租售比 {m['rent_ratio']:.1%}", f"坪效 {m['psm']:,.0f} 元/㎡/月",
                      f"人效 {m['labor_eff']:,.0f} 元/人/月"],
            "actions": ["按同商圈水平谈续租，目标降 8%–12%", "压缩仓库面积", "低坪效品类缩排面"],
            "impact": m["fixed_month"] * 0.08,
            "verify": ["租售比 ≤ 10%"],
        })

    if cover and be_ok and goods_ok and waste_ok and m["gm"] >= 0.28:
        add_aov = _div(m["orders"], m["months"]) * 1 * m["gm"]
        actions.append({
            "priority": "P3", "code": "B7", "title": "基本盘健康：把增长放在客单价上",
            "basis": [f"净利率 {m['net_margin']:.1%}", f"客单价 {m['aov']:.2f}、连带率 {m['basket']:.2f}"],
            "actions": ["收银台加 1 元换购", "A 类品组合陈列", "会员日只对会员开放"],
            "impact": add_aov,
            "verify": ["客单价环比 +3%", "连带率 +0.1"],
        })

    if not actions:
        actions.append({"priority": "P3", "code": "B0", "title": "维持现状，盯住三个先行指标",
                        "basis": ["各项指标均在区间内"], "actions": ["每周看客流、库存天数、报损率"],
                        "impact": 0.0, "verify": ["三个先行指标不恶化"]})

    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    actions.sort(key=lambda a: (order[a["priority"]], -a["impact"]))

    if not cover or m["net"] < 0 or m["safety"] < 0.05:
        level, headline = "bad", "现在不是促销的时候：先保本"
        why = (f"这家店{'净利为负' if m['net'] < 0 else '净利为正但安全边际不足 5%'}。"
               f"毛利 {m['gp']:,.0f} {'刚够' if cover else '还不够'}覆盖固定费用 {m['fixed']:,.0f}，"
               f"保本日均 {m['be_daily']:,.0f}，实际日均 {m['daily_sales']:,.0f}。"
               f"此时任何降价都会同时压低毛利率、抬高保本线——先砍固定费用和损耗，"
               f"把安全边际做到 5% 以上再谈引流。")
    elif not goods_ok:
        level, headline = "warn", "先精简商品，再谈促销"
        why = (f"店是赚钱的（净利率 {m['net_margin']:.1%}），但钱压在货上："
               f"周转 {m['turn_days']:.1f} 天、动销率 {m['active_rate']:.1%}。"
               f"这类店做促销只是把滞销品换个方式打折，毛利更薄。先把不产钱的 SKU 清出去，"
               f"把库存变成现金，再考虑拉新。")
    elif can_promo and decline:
        level, headline = "ok", "可以做促销，但要按 ROI 做"
        d_be = 0.15 * m["gm"] / 1.15
        sim = promo_sim(m, max(1.0, min(15.0, d_be * 100 * 0.7)), 15)
        why = (f"毛利率 {m['gm']:.1%}、安全边际 {m['safety']:.1%}，有让利空间；"
               f"下滑来自{'客单价' if abs(m['mom_aov']) >= abs(m['mom_traffic']) else '客流'}"
               f"（客单 {m['mom_aov']:+.1f}%、客流 {m['mom_traffic']:+.1f}%）。"
               f"按折扣上限 {d_be:.1%} 以内、增量 15% 测算 ROI {sim['roi']:.2f}——"
               f"可以做，但必须先算清增量线，不能凭感觉打折。")
    else:
        level, headline = "ok", "基本盘健康，把力气花在客单价和结构上"
        if m.get("inv_known", True):
            turn_txt = (f"周转 {m['turn_days']:.1f} 天"
                        f"{'（略高于 7–14 天的健康区间）' if m['turn_days'] > 14 else ''}")
        else:
            turn_txt = "库存还没填，周转暂时算不出来"
        why = (f"毛利覆盖固定费用，安全边际 {m['safety']:.1%}，{turn_txt}、"
               f"动销率 {m['active_rate']:.1%}。这个阶段不需要救火，需要的是把客单价和毛利结构一点点抬上去。")

    return {"level": level, "headline": headline, "why": why, "actions": actions,
            "not_do": not_do, "path": path}


# ---------------------------------------------------------------- 指标口径（补全看板所缺）
OPS_CATALOG = {
    "固定费用": ("成本", "房租+人工+水电+折旧+其他（按每月输入，折算到统计期）", "元", "促销物料、平台佣金不属于固定费用"),
    "固定费用率": ("成本", "固定费用 ÷ 销售额", "%", "越高，销售波动对利润放大越狠"),
    "经营利润": ("结果", "毛利额 − 固定费用", "元", "销售额掉 10% 时它掉得最狠"),
    "净利": ("结果", "经营利润 − 报损 − 盘亏", "元", "账面利润≠现金"),
    "净利率": ("结果", "净利 ÷ 销售额", "%", "便利店参考 3%–8%"),
    "保本销售额": ("成本", "固定费用 ÷ 毛利率", "元", "毛利率口径不同，结果差很多"),
    "保本日均": ("成本", "保本销售额 ÷ 统计天数", "元/天", "门店每天的红线"),
    "安全边际": ("先行", "（销售额 − 保本销售额）÷ 销售额", "%", "<5% 危险；≥15% 才有促销空间"),
    "经营杠杆DOL": ("先行", "毛利额 ÷ 经营利润", "倍", "销售额降 1%，经营利润降 DOL%"),
    "租售比": ("效率", "房租 ÷ 销售额（月口径）", "%", ">15% 危险"),
    "坪效": ("效率", "销售额 ÷ 营业面积，折算月", "元/㎡/月", "面积含不含仓库要固定"),
    "人效": ("效率", "销售额 ÷ 员工数，折算月", "元/人/月", "兼职要折工时"),
    "商品周转率": ("效率", "销货成本 ÷ 平均库存成本", "次/期", "与毛利率是乘法关系"),
    "周转天数": ("效率", "平均库存成本 ÷ 日均销货成本", "天", "分子分母都用成本价"),
    "年化周转次数": ("效率", "365 ÷ 周转天数", "次/年", "便利店健康 26–52 次"),
    "售罄率": ("效率", "销量 ÷（销量 + 期末库存件数）", "%", "过高＝订少了"),
    "缺货率": ("效率", "缺货 SKU 数 ÷ 在售 SKU 数", "%", "按 SKU 还是按时长差别大"),
    "动销率": ("效率", "有销量 SKU 数 ÷ 在售 SKU 数", "%", "低＝长尾太多"),
    "报损率": ("损耗", "报损金额 ÷ 销售额", "%", "鲜食店的核心指标"),
    "损耗率": ("损耗", "（报损 + 盘亏）÷ 销售额", "%", "盘亏常比报损更能说明问题"),
    "促销ROI": ("促销", "增量毛利 ÷ 活动投入", "倍", "<1 就是花钱买热闹"),
    "折后毛利率": ("促销", "（毛利率 − 折扣率）÷（1 − 折扣率）", "%", "用近似式会算错"),
    "促销打平增量": ("促销", "折扣率 ÷（毛利率 − 折扣率）", "%", "涨不到这个数就是白做"),
    "安全库存": ("订货", "日均销量 × 波动系数 × √交货天数", "件", "简化算法"),
    "订货点": ("订货", "日均销量 × 交货天数 + 安全库存", "件", "库存降到这个数下单"),
    "订货量": ("订货", "目标库存 − 现有库存 − 在途", "件", "定期订货法"),
    "最优服务水平": ("订货", "毛利 ÷（毛利 + 成本），等于毛利率", "%", "毛利率越低越该订得保守"),
}

OPS_GROUPS = {
    "盈利与保本": ["固定费用", "固定费用率", "经营利润", "净利", "净利率", "保本销售额", "保本日均", "安全边际", "经营杠杆DOL"],
    "效率": ["租售比", "坪效", "人效", "商品周转率", "周转天数", "年化周转次数", "售罄率", "缺货率", "动销率"],
    "损耗与促销": ["报损率", "损耗率", "促销ROI", "折后毛利率", "促销打平增量"],
    "订货": ["安全库存", "订货点", "订货量", "最优服务水平"],
}


def ops_dict_rows() -> list[dict]:
    """口径字典行：指标 / 分组 / 公式 / 单位 / 口径说明。供报告与页面直接渲染。"""
    gmap = {n: g for g, names in OPS_GROUPS.items() for n in names}
    return [{"指标": k, "分组": gmap.get(k, "未分组"), "层级": v[0], "公式": v[1],
             "单位": v[2], "口径说明": v[3]} for k, v in OPS_CATALOG.items()]


# ---------------------------------------------------------------- 命令行自检
if __name__ == "__main__":
    demo = {"days": 90, "sales": 230507, "cogs": 125219, "orders": 21125, "qty": 51373,
            "open_inv": 18476, "close_inv": 20082, "loss": 2958, "shrink": 620,
            "sku_active": 44, "sku_sold": 44, "sku_oos": 3,
            "area": 68, "staff": 5,
            "rent": 6000, "labor": 19000, "utility": 2200, "dep": 800, "other": 800,
            "mom_sales": -2.6, "mom_traffic": -1.5, "mom_aov": -1.1}
    m = compute(demo)
    print(f"销售额 {m['sales']:,.0f} 毛利 {m['gp']:,.0f}（{m['gm']:.2%}）净利 {m['net']:,.0f}")
    print(f"保本日均 {m['be_daily']:,.0f} 安全边际 {m['safety']:.1%} 周转 {m['turn_days']:.1f} 天")
    print(f"坪效 {m['psm']:,.0f} 人效 {m['labor_eff']:,.0f} 租售比 {m['rent_ratio']:.1%}")
    d = diagnose(m, {"c_sku_count": 14, "c_sku_sales_share": 0.103})
    print(f"\n诊断：{d['headline']}（{d['level']}）")
    for a in d["actions"]:
        print(f"  {a['priority']} {a['title']}  预计月改善 {a['impact']:,.0f}")
    print("\n口径字典条目：", len(ops_dict_rows()))
