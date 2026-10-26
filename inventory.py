# -*- coding: utf-8 -*-
"""
库存与订货：从销售明细模拟出门店库存日快照，再算周转、缺货、报损、订货建议。

⚠️ 库存部分是**模拟数据**（真实库存快照需要门店系统导出）：
   - 销量、金额来自你上传的真实销售明细
   - 期初库存、进货、在途、交期、保质期、报损由下面的策略仿真生成
   - 每一次订货都记录：为什么订、订多少、依据是哪几个数

订货公式：
    库存位置 = 期末库存 + 在途
    目标库存 = 日均销量 × 覆盖天数 + 安全库存
    建议订货 = max(0, 目标库存 − 库存位置)，鲜食再按保质期封顶
"""
import numpy as np
import pandas as pd


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _robust_std(x, drop_outliers=True):
    """稳健标准差：先按 MAD 剔掉极端日（缺货日/大促单），再算样本标准差。

    生鲜这类波动大的品类，直接用普通 std 会被个别大单拉爆，导致安全库存
    虚高、多订货；用 MAD 剔除后再估，波动估计更稳。
    """
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return 0.0, float(np.median(v)) if len(v) else 0.0
    med = np.median(v)
    mad = np.median(np.abs(v - med))
    if mad > 0 and drop_outliers:
        z = 0.6745 * (v - med) / mad
        v = v[np.abs(z) <= 3.5]           # 只剔真极端，不伤正常波动
    if len(v) < 2:
        return 0.0, float(med)
    return float(np.std(v, ddof=1)), float(np.mean(v))


def safety_stock(daily_sales, lead_days, z=1.65, cap_ratio=2.0):
    """动态安全库存：SS = z × σ_daily × √lead。

    - daily_sales: 该 SKU 的日销量序列（一维数组）
    - lead_days: 交货周期（天）
    - z: 服务水平系数（1.65 ≈ 95% 不缺货；2.33 ≈ 99%）
    - cap_ratio: 安全库存上限，按「日均×覆盖」的倍数封顶，防生鲜波动大时订过头
    返回 (safety_stock 值, 日均销量稳健估计)。
    """
    sigma, avg = _robust_std(daily_sales)
    ss = z * sigma * np.sqrt(max(lead_days, 1))
    # 生鲜波动再大，安全库存也别超过「覆盖期内平均需求」的一定倍数，避免压货
    cap = max(avg, 1e-9) * max(lead_days, 1) * cap_ratio
    return float(min(ss, cap)), float(avg)


def _shelf_for(cat, rng):
    """保质期按品类推断：鲜食 2-3 天、乳品 7-15 天、饮料 半年以上。"""
    c = str(cat)
    if any(k in c for k in ("鲜食", "便当", "饭团", "面包", "关东煮", "熟食")):
        return int(rng.choice([2, 3]))
    if any(k in c for k in ("乳", "酸奶", "牛奶", "烘焙", "蛋糕", "三明治")):
        return int(rng.choice([7, 10, 15]))
    if "零食" in c:
        return int(rng.choice([30, 60, 90]))
    if "饮料" in c:
        return int(rng.choice([180, 270, 365]))
    return int(rng.choice([180, 365, 540]))


def build_snapshot(df, sku_col, date_col, qty_col, name_col=None, cat_col=None,
                   cost_col=None, seed=7, cover_days=None):
    """按「补货点 + 目标库存」策略逐日仿真，返回日快照表。"""
    if not all([sku_col, date_col, qty_col]) or sku_col not in df.columns:
        return None, None
    d = df[[c for c in [sku_col, date_col, qty_col, name_col, cat_col, cost_col] if c and c in df.columns]].copy()
    d["_date"] = pd.to_datetime(d[date_col], errors="coerce").dt.normalize()
    d["_qty"] = _num(d[qty_col]).fillna(0)
    d = d.dropna(subset=["_date"])
    if d.empty:
        return None, None

    daily = d.groupby([sku_col, "_date"])["_qty"].sum().rename("销量").reset_index()
    days = pd.date_range(daily["_date"].min(), daily["_date"].max(), freq="D")

    # 每个 SKU 的属性（确定性随机，便于复现）
    rng = np.random.default_rng(seed)
    meta_rows = []
    for sku, g in d.groupby(sku_col):
        name = str(g[name_col].dropna().iloc[0]) if name_col and g[name_col].notna().any() else str(sku)
        cat = str(g[cat_col].dropna().iloc[0]) if cat_col and g[cat_col].notna().any() else "未分类"
        cost = float(_num(g[cost_col]).median()) if cost_col and cost_col in g.columns and _num(g[cost_col]).notna().any() else np.nan
        shelf = _shelf_for(cat, rng)                                                        # 保质期（天，按品类）
        lead = int(rng.choice([1, 2, 3], p=[0.5, 0.35, 0.15]))                              # 交货周期
        cover = int(cover_days or rng.choice([4, 5, 6, 8], p=[0.3, 0.3, 0.25, 0.15]))        # 目标覆盖天数
        if shelf <= 3:                    # 鲜食不能按 5 天备货，否则一半报损
            cover = max(2, shelf - 1)
        meta_rows.append({"sku": sku, "name": name, "cat": cat, "cost": cost,
                          "shelf": shelf, "lead": lead, "cover": cover})
    meta = pd.DataFrame(meta_rows).set_index("sku")

    rows = []
    for sku, g in daily.groupby(sku_col):
        m = meta.loc[sku]
        s = g.set_index("_date")["销量"].reindex(days, fill_value=0.0)
        avg = float(s.mean()) if s.mean() > 0 else 1.0
        shelf = int(m["shelf"])
        lead = int(m["lead"])
        cover = int(m["cover"])

        # 批次库存：[[到期日, 数量], ...]（先进先出，过期即报损）
        batches = []
        def on_hand():
            return round(sum(q for _, q in batches), 2)

        start_qty = round(avg * cover * rng.uniform(0.9, 1.3), 1)
        if start_qty > 0:
            batches.append([days[0] + pd.Timedelta(days=shelf), start_qty])
        pipeline = {}

        for day in days:
            arriving = pipeline.pop(day, 0.0)
            if arriving > 0:
                batches.append([day + pd.Timedelta(days=shelf), arriving])

            # 1) 过期报损（FIFO：到期日早于今天）
            loss = 0.0
            keep = []
            for exp, q in batches:
                if exp <= day:
                    loss += q
                else:
                    keep.append([exp, q])
            batches = keep

            # 2) 按先进先出扣销量
            sold = float(s.loc[day])
            available = on_hand()
            stockout = 1 if sold > available + 1e-9 else 0
            need = min(sold, available)
            sold = need
            for b in batches:
                if need <= 0:
                    break
                take = min(b[1], need)
                b[1] = round(b[1] - take, 4)
                need = round(need - take, 4)
            batches = [[e, q] for e, q in batches if q > 1e-6]

            in_transit = sum(pipeline.values())
            position = round(on_hand() + in_transit, 2)
            target = avg * cover + avg * lead * 0.5
            order = max(0.0, target - position)
            if shelf <= 3:
                order = min(order, avg * shelf * 0.8)     # 鲜食不能压货
            order = round(order, 1)
            if order > 0:
                arrive = day + pd.Timedelta(days=lead)
                pipeline[arrive] = pipeline.get(arrive, 0.0) + order

            rows.append({
                "日期": day, "商品编码": sku, "商品名称": m["name"], "品类": m["cat"],
                "销量": round(sold, 2), "到货": arriving, "报损": round(loss, 2),
                "期末库存": on_hand(), "在途": round(in_transit, 2), "库存位置": position,
                "缺货": stockout, "订货量": order, "交货周期": lead, "保质期": shelf,
                "覆盖天数": cover,
                "单位成本": m["cost"], "日均销量": round(avg, 2),
            })

    snap = pd.DataFrame(rows)
    return snap, meta.reset_index()


def sku_summary(snap):
    """按 SKU 汇总：周转天数、缺货率、报损率、订货建议。"""
    g = snap.groupby(["商品编码", "商品名称", "品类"], as_index=False).agg(
        销量=("销量", "sum"), 报损=("报损", "sum"), 到货=("到货", "sum"),
        期末库存=("期末库存", "last"), 在途=("在途", "last"),
        库存位置=("库存位置", "last"), 缺货天数=("缺货", "sum"), 天数=("日期", "count"),
        日均销量=("日均销量", "last"), 交货周期=("交货周期", "last"),
        保质期=("保质期", "last"), 单位成本=("单位成本", "last"),
        覆盖天数=("覆盖天数", "last"), 建议订货=("订货量", "last"))
    g["平均库存"] = snap.groupby("商品编码")["期末库存"].mean().reindex(g["商品编码"]).to_numpy()
    safe = g["日均销量"].replace(0, np.nan)
    g["周转天数"] = (g["平均库存"] / safe).round(1)
    g["缺货率%"] = (g["缺货天数"] / g["天数"].replace(0, np.nan) * 100).round(1)
    g["报损率%"] = (g["报损"] / g["销量"].replace(0, np.nan) * 100).round(1)
    g["库存金额"] = (g["期末库存"] * g["单位成本"]).round(2)

    # ---- 动态安全库存（增强）：用每个 SKU 的日销量波动算 SS = z·σ·√lead ----
    # 比固定「交期×0.5」更贴近真实：波动大的 SKU 安全库存更高，波动小的更低。
    ss_map = {}
    for sku, sub in snap.groupby("商品编码"):
        ss, _avg = safety_stock(sub["销量"].to_numpy(), float(sub["交货周期"].iloc[-1]))
        ss_map[sku] = ss
    g["安全库存"] = g["商品编码"].map(ss_map).fillna(0.0)

    # 建议订货再按最新库存位置复核一次，保证公式可核对：
    # 目标库存 = 日均 × 覆盖天数 + 交期需求 + 动态安全库存；鲜食按保质期封顶
    cover = (g["覆盖天数"].fillna(5) if "覆盖天数" in g
             else pd.Series(5.0, index=g.index))
    target = (g["日均销量"] * cover
              + g["日均销量"] * g["交货周期"] * 0.5
              + g["安全库存"])
    order = (target - g["库存位置"]).clip(lower=0)
    fresh = g["保质期"] <= 3
    if fresh.any():
        cap = g["日均销量"] * g["保质期"] * 0.8
        order = order.mask(fresh, np.minimum(order, cap))
    g["建议订货"] = order.round(1)
    return g.sort_values(["缺货率%", "周转天数"], ascending=False)


def reorder_explain(row):
    """把一只 SKU 的订货计算摊开成文字。"""
    _cover = int(row.get("覆盖天数", 5) or 5)
    ss = float(row.get("安全库存", 0.0) or 0.0)
    target = round(row["日均销量"] * _cover + row["日均销量"] * row["交货周期"] * 0.5 + ss, 1)
    ss_txt = f" + 安全库存 {ss:.1f}" if ss > 0 else ""
    return (f"日均销量 {row['日均销量']:.1f} × 覆盖 {_cover} 天 + 交期 {row['日均销量']*row['交货周期']*0.5:.1f}"
            f"{ss_txt} = 目标库存 {target:.1f}；现有库存位置 {row['库存位置']:.1f}"
            f"（期末 {row['期末库存']:.1f} + 在途 {row['在途']:.1f}）；"
            f"建议订货 {row['建议订货']:.1f}" + (f"（保质期 {row['保质期']} 天，不能多订）" if row["保质期"] <= 3 else ""))


def health_kpis(g):
    total_sku = len(g)
    stockout_sku = int((g["缺货率%"] > 0).sum())
    return {
        "SKU 数": total_sku,
        "缺货 SKU": stockout_sku,
        "缺货率%": round(stockout_sku / total_sku * 100, 1) if total_sku else 0.0,
        "平均周转天数": round(float(g["周转天数"].replace([np.inf, -np.inf], np.nan).dropna().mean()), 1)
        if total_sku else 0.0,
        "报损率%": round(float(g["报损"].sum() / g["销量"].sum() * 100), 2) if g["销量"].sum() else 0.0,
        "待补货 SKU": int((g["建议订货"] > 0).sum()),
        "库存金额": round(float(g["库存金额"].fillna(0).sum()), 2),
    }
