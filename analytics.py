# -*- coding: utf-8 -*-
"""
销售分析的核心模型层（纯 pandas，不依赖 Streamlit，方便单独测试）
- 订单级指标：客单价、连带率、单均件数
- 购物篮：支持度 / 置信度 / 提升度
- 毛利结构：金额占比 vs 毛利占比
- 客户 RFM 分层
- 时间序列预测（移动平均 + 阻尼趋势）
- 异常点检测（滚动中位数 + MAD）
- 任意两期对比
"""
import numpy as np
import pandas as pd


# ---------------- 列识别 ----------------
ORDER_HINT = ("订单号", "单号", "小票", "交易号", "orderid", "orderno", "billno", "invoice")
CUST_HINT = ("会员", "客户", "顾客", "手机号", "手机", "customer", "member", "vip", "userid")
COST_HINT = ("成本", "进价", "cost", "进货价")
QTY_HINT = ("数量", "销量", "件数", "qty", "quantity")
PRICE_HINT = ("单价", "售价", "价格", "price")


def _num(s):
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    return pd.to_numeric(s.astype(str).str.replace(r"[¥$,\s]", "", regex=True), errors="coerce")


def find_col(cols, hints, exclude=None):
    exclude = exclude or set()
    for c in cols:
        if c in exclude:
            continue
        s = str(c).lower()
        if any(h in s for h in hints):
            return c
    return None


def pick_order_col(df):
    c = find_col(df.columns, ORDER_HINT)
    if c and df[c].nunique() < len(df) * 0.95 and df[c].nunique() > 1:
        return c
    return None


# ---------------- 订单级 ----------------
def order_metrics(df, order_col, metric, qty_col=None, date_col=None,
                  key_mode="auto", tie="qty", include_refunds=False):
    """订单级指标。key_mode: auto/订单号+日期/订单号原样；tie: qty(件数)/rows(SKU数)"""
    if not order_col or order_col not in df.columns:
        return None, None
    key = df[order_col].astype(str)
    composite = False
    if key_mode == "订单号+日期" and date_col and date_col in df.columns:
        key = key + "|" + pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
        composite = True
    elif key_mode != "订单号原样" and date_col and date_col in df.columns:
        dts = pd.to_datetime(df[date_col], errors="coerce")
        try:
            multi = df.assign(_k=key, _d=dts.dt.normalize()).groupby("_k")["_d"].nunique()
            if (multi > 1).mean() > 0.01:
                key = key + "|" + dts.dt.strftime("%Y-%m-%d").fillna("")
                composite = True
        except Exception:
            pass
    tmp = pd.DataFrame({"_o": key, "_amt": _num(df[metric])})
    tmp["_qty"] = _num(df[qty_col]).fillna(0) if (tie == "qty" and qty_col and qty_col in df.columns) else 1.0
    if date_col and date_col in df.columns:
        tmp["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
    g = tmp.groupby("_o").agg(金额=("_amt", "sum"), 件数=("_qty", "sum"))
    if date_col and date_col in df.columns:
        g["日期"] = tmp.groupby("_o")["_dt"].min()
    if not include_refunds:
        g = g[g["金额"] > 0]
    if g.empty:
        return None, None
    n = len(g)
    metrics = {
        "订单数": int(n),
        "客单价": float(g["金额"].mean()),
        "件单价": float(g["金额"].sum() / max(g["件数"].sum(), 1e-9)),
        "连带率": float(g["件数"].sum() / n),
        "单均件数": float(g["件数"].mean()),
        "客单价中位数": float(g["金额"].median()),
        "最高单笔": float(g["金额"].max()),
        "复合键": composite,
    }
    return g, metrics


# ---------------- 购物篮 ----------------
def basket_rules(df, order_col, item_col, min_support_abs=8, top_n=12):
    """A→B 的 support / confidence / lift"""
    if not order_col or not item_col or order_col not in df or item_col not in df:
        return None
    d = df[[order_col, item_col]].dropna()
    d = d[d[item_col].astype(str).str.strip() != ""]
    if d.empty:
        return None
    baskets = d.groupby(order_col)[item_col].apply(lambda s: sorted(set(s.astype(str))))
    n_basket = len(baskets)
    if n_basket < 20:
        return None
    item_count = {}
    pair_count = {}
    for items in baskets:
        for it in items:
            item_count[it] = item_count.get(it, 0) + 1
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                key = (items[i], items[j])
                pair_count[key] = pair_count.get(key, 0) + 1
    rows = []
    for (a, b), c in pair_count.items():
        if c < min_support_abs:
            continue
        sup = c / n_basket
        ca, cb = item_count[a], item_count[b]
        conf_ab = c / ca
        lift = conf_ab / (cb / n_basket)
        rows.append({"商品A": a, "商品B": b, "同单次数": c, "支持度%": round(sup * 100, 2),
                     "置信度%": round(conf_ab * 100, 1), "提升度": round(lift, 2)})
    if not rows:
        return None
    out = pd.DataFrame(rows)
    # 双向合并，保留提升度更高的一条
    out = out.sort_values("提升度", ascending=False).drop_duplicates(subset=["商品A", "商品B"])
    return out.head(top_n).reset_index(drop=True)


def cost_line(df, cost_col, qty_col=None, force="auto"):
    """把成本列换算成「每行成本总额」。
    force: auto（按列名判断）/ unit（强制当单价×数量）/ total（强制当总额）
    """
    if not cost_col or cost_col not in df.columns:
        return None
    c = _num(df[cost_col]).fillna(0)
    name = str(cost_col)
    unit_like = any(h in name for h in ("进价", "进货价", "单价", "unit", "price"))
    total_like = any(h in name for h in ("成本", "成本额", "cost"))
    if force == "total":
        return c
    if force == "unit":
        return c * _num(df[qty_col]).fillna(0) if qty_col and qty_col in df.columns else c
    if total_like and not unit_like:
        return c
    if unit_like and qty_col and qty_col in df.columns:
        return c * _num(df[qty_col]).fillna(0)
    return c


def cost_kind(cost_col):
    name = str(cost_col)
    if any(h in name for h in ("进价", "进货价", "单价", "unit", "price")):
        return "单价"
    return "总额"


# ---------------- 毛利结构 ----------------
def margin_structure(df, cat_col, metric, cost_col, qty_col=None, force="auto"):
    if not cat_col or not cost_col or cost_col not in df.columns:
        return None
    d = df.dropna(subset=[cat_col]).copy()
    if d.empty:
        return None
    line = cost_line(d, cost_col, qty_col, force)
    if line is None:
        return None
    d["_cost"] = line
    g = d.groupby(cat_col).agg(金额=(metric, "sum"), 成本=("_cost", "sum"))
    g["毛利"] = g["金额"] - g["成本"]
    g = g[g["金额"] > 0]
    if g.empty:
        return None
    g["金额占比%"] = (g["金额"] / g["金额"].sum() * 100).round(1)
    g["毛利占比%"] = (g["毛利"] / g["毛利"].sum() * 100).round(1)
    g["毛利率%"] = (g["毛利"] / g["金额"] * 100).round(1)
    g["占比差"] = (g["毛利占比%"] - g["金额占比%"]).round(1)
    return g.sort_values("金额", ascending=False)


# ---------------- RFM ----------------
def rfm_table(df, cust_col, date_col, metric):
    if not cust_col or not date_col:
        return None
    d = df[[cust_col, date_col, metric]].dropna(subset=[cust_col, date_col]).copy()
    if not pd.api.types.is_datetime64_any_dtype(d[date_col]):
        d[date_col] = pd.to_datetime(d[date_col], errors="coerce", format="mixed")
        d = d.dropna(subset=[date_col])
    d[metric] = _num(d[metric])
    d = d[d[metric] > 0]
    if d.empty or d[cust_col].nunique() < 10:
        return None
    ref = d[date_col].max() + pd.Timedelta(days=1)
    g = d.groupby(cust_col).agg(
        最近购买=(date_col, "max"), 频次=(date_col, lambda s: s.dt.normalize().nunique()),
        金额=(metric, "sum"), 订单数=(date_col, "size"))
    g["R天"] = (ref - g["最近购买"]).dt.days
    g["F"] = g["频次"]
    g["M"] = g["金额"]

    def score(s, asc):
        try:
            r = s.rank(method="first", ascending=asc)
            return pd.qcut(r, 5, labels=[1, 2, 3, 4, 5]).astype(int)
        except Exception:
            return pd.Series(3, index=s.index)

    g["R"] = score(g["R天"], True)      # 越近分越高
    g["Fs"] = score(g["F"], False)
    g["Ms"] = score(g["M"], False)

    def seg(r):
        if r["R"] >= 4 and r["Fs"] >= 4:
            return "重要价值客户"
        if r["R"] >= 4 and r["Fs"] <= 2:
            return "新客/待培养"
        if r["R"] <= 2 and r["Fs"] >= 4:
            return "重要挽留（流失预警）"
        if r["R"] <= 2 and r["Fs"] <= 2:
            return "流失客户"
        return "一般客户"

    g["分层"] = g.apply(seg, axis=1)
    g = g[(g["R天"] >= 0)]
    return g


def rfm_summary(rfm):
    if rfm is None or rfm.empty:
        return None
    s = rfm.groupby("分层").agg(人数=("M", "size"), 金额=("M", "sum"), 客单价=("M", "mean"))
    s["人数占比%"] = (s["人数"] / s["人数"].sum() * 100).round(1)
    s["金额占比%"] = (s["金额"] / s["金额"].sum() * 100).round(1)
    s["客单价"] = s["客单价"].round(1)
    return s.sort_values("金额", ascending=False).reset_index()


# ---------------- 目标达成 ----------------
def target_progress(series, target, elapsed=1.0):
    """series: 按时间排序的数值序列（已聚合）。elapsed: 本期已过比例（0~1）。"""
    if series is None or len(series) == 0 or not target or target <= 0:
        return None
    actual = float(series.iloc[-1])
    elapsed = min(max(float(elapsed), 0.03), 1.0)
    run_rate = actual / elapsed
    return {"actual_y": actual, "target": float(target), "rate": actual / target * 100,
            "gap": float(target) - actual, "run_rate": run_rate,
            "proj_rate": run_rate / float(target) * 100, "elapsed": elapsed}


# ---------------- 预测 ----------------
def forecast(series, periods=14, window=7, season=None):
    """移动平均 + 阻尼趋势 + 残差上下界。返回 DataFrame(index=未来标签, yhat/lo/hi)"""
    s = pd.Series(series).dropna()
    if len(s) < max(window * 2, 8):
        return None, None
    y = s.astype(float).values
    w = min(window, max(3, len(y) // 3))
    ma = pd.Series(y).rolling(w, min_periods=1).mean().values
    resid = y - ma
    sigma = float(np.std(resid, ddof=1)) if len(resid) > 2 else 0.0
    # 阻尼趋势：最近半段 vs 前一段的斜率
    k = min(len(y) // 2, 30)
    if k >= 2:
        slope = (y[-k:].mean() - y[-2 * k:-k].mean()) / max(k, 1)
    else:
        slope = 0.0
    damp = 0.85
    base = float(ma[-1])
    last_idx = s.index[-1]
    fut_idx = []
    step = None
    if isinstance(last_idx, pd.Timestamp):
        freq = pd.infer_freq(pd.DatetimeIndex(s.index[-10:])) or "D"
        try:
            rng = pd.date_range(last_idx, periods=periods + 1, freq=freq)[1:]
        except Exception:
            rng = pd.date_range(last_idx, periods=periods + 1, freq="D")[1:]
        fut_idx = list(rng)
        step = (rng[0] - last_idx) / pd.Timedelta(days=1)
    else:
        fut_idx = [f"T+{i+1}" for i in range(periods)]
        step = 1
    # 周季节性（日粒度）：按星期几的均值偏移
    offsets = []
    if isinstance(last_idx, pd.Timestamp) and step and 0.9 < float(step) < 1.1:
        dow = pd.Series(y, index=pd.DatetimeIndex(s.index)).groupby(pd.DatetimeIndex(s.index).dayofweek).mean()
        gm = float(np.mean(dow.values)) if len(dow) else 0.0
        for f in fut_idx:
            offsets.append(float(dow.get(f.dayofweek, gm)) - gm if gm else 0.0)
    else:
        offsets = [0.0] * len(fut_idx)
    yhat, lo, hi = [], [], []
    for i in range(periods):
        trend_add = slope * (i + 1) * step ** 0
        v = base + trend_add * (damp ** i) + offsets[i]
        yhat.append(max(v, 0.0))
        band = 1.96 * sigma * (1 + 0.12 * i) ** 0.5
        lo.append(max(v - band, 0.0))
        hi.append(v + band)
    out = pd.DataFrame({"预测": yhat, "下界": lo, "上界": hi}, index=fut_idx)
    fit = pd.Series(ma, index=s.index)
    return out, fit


# ---------------- 异常 ----------------
def detect_anomalies(series, threshold=3.5):
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 10:
        return None
    med = s.rolling(min(len(s), 7), center=True, min_periods=3).median()
    mad = (s - med).abs().rolling(min(len(s), 7), center=True, min_periods=3).median()
    mad = mad.replace(0, np.nan)
    z = 0.6745 * (s - med) / mad
    flag = z.abs() > threshold
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    flag = flag | (s > q3 + 3 * iqr) | (s < q1 - 3 * iqr)
    out = pd.DataFrame({"值": s, "异常": flag.fillna(False), "z": z.fillna(0)})
    return out


# ---------------- 两期对比 ----------------
def compare_periods(df, date_col, metric, cur, base, dim=None):
    """cur/base = (start, end) 元组。返回 dict"""
    d = df.dropna(subset=[date_col]).copy()
    d[metric] = _num(d[metric])
    cm = (d[date_col] >= pd.Timestamp(cur[0])) & (d[date_col] < pd.Timestamp(cur[1]) + pd.Timedelta(days=1))
    bm = (d[date_col] >= pd.Timestamp(base[0])) & (d[date_col] < pd.Timestamp(base[1]) + pd.Timedelta(days=1))
    if not cm.any() or not bm.any():
        return None
    cur_v = float(d.loc[cm, metric].sum())
    base_v = float(d.loc[bm, metric].sum())
    delta = cur_v - base_v
    pct = delta / base_v * 100 if base_v else 0.0
    res = {"cur": cur_v, "base": base_v, "delta": delta, "pct": pct,
           "cur_days": int(cm.sum()), "base_days": int(bm.sum()), "figs": [], "lines": []}
    lines = [f"本期 {cur_v:,.0f} vs 对比期 {base_v:,.0f}，{'增长' if delta>=0 else '下降'} "
             f"{abs(pct):.1f}%（{delta:+,.0f}）。"]
    if dim and dim in d.columns:
        c = d.loc[cm].groupby(dim)[metric].sum()
        b = d.loc[bm].groupby(dim)[metric].sum()
        idx = c.index.union(b.index)
        c = c.reindex(idx, fill_value=0.0)
        b = b.reindex(idx, fill_value=0.0)
        dl = (c - b).sort_values()
        total_abs = dl.abs().sum()
        if total_abs > 0:
            parts = [f"「{k}」{v:+,.0f}（占变动 {abs(v)/total_abs*100:.0f}%）" for k, v in dl.head(3).items()]
            lines.append(f"按 {dim} 拆：" + "、".join(parts) + "。")
        res["table"] = pd.DataFrame({"本期": c, "对比期": b, "变化": c - b,
                                     "变化率%": ((c - b) / b.replace(0, np.nan) * 100).round(1)}
                                    ).sort_values("变化", key=lambda s: s.abs(), ascending=False).head(20)
        res["delta_series"] = dl
    res["lines"] = lines
    return res
