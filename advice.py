# -*- coding: utf-8 -*-
"""
改善建议：从数据里算出「该动哪里」，每条都带数字依据，不写空话。

输出是纯数据（list[dict]），UI 和报告都能复用；每条建议都给
severity（高/中/低）、依据、动作、预期影响（粗估，不是承诺）。
"""
import numpy as np
import pandas as pd

import analytics as AN


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _pct(a, b):
    return (a / b * 100) if b else 0.0


def _top_pairs(df, order_col, item_col, min_support=5, n=3):
    """轻量购物篮：同订单出现次数最多的商品对（提升度优先）。"""
    if not order_col or not item_col:
        return []
    try:
        d = df[[order_col, item_col]].dropna()
        d = d.drop_duplicates()
        cnt = d[item_col].value_counts()
        orders = d[order_col].nunique()
        from itertools import combinations
        pair_cnt = {}
        for _, g in d.groupby(order_col)[item_col]:
            items = sorted(set(g))
            if 2 <= len(items) <= 12:
                for a, b in combinations(items, 2):
                    pair_cnt[(a, b)] = pair_cnt.get((a, b), 0) + 1
        out = []
        for (a, b), c in pair_cnt.items():
            if c < min_support:
                continue
            support = c / orders if orders else 0
            lift = (c / orders) / ((cnt[a] / orders) * (cnt[b] / orders)) if orders and cnt[a] and cnt[b] else 0
            conf = c / cnt[a]
            if lift > 1.2:
                out.append({"a": a, "b": b, "lift": lift, "support": support, "conf": conf, "n": c})
        out.sort(key=lambda x: x["lift"], reverse=True)
        return out[:n]
    except Exception:
        return []


def build_advice(df, metric, qty_col=None, cost_col=None, cost_force="auto",
                 date_col=None, item_col=None, big_col=None, order_col=None,
                 target=0.0, weekend_gap=True):
    """返回建议列表，按严重程度排序。任何一条算不出来就跳过，不影响别的。"""
    if df is None or df.empty or not metric or metric not in df.columns:
        return []

    rev = float(_num(df[metric]).sum())
    qty = float(_num(df[qty_col]).sum()) if qty_col and qty_col in df.columns else float(len(df))
    out = []

    def add(sev, title, evidence, action, impact):
        out.append({"sev": sev, "title": title, "evidence": evidence,
                    "action": action, "impact": impact})

    # ---------- 1. 毛利率 ----------
    margin = None
    if cost_col and cost_col in df.columns:
        # 统一走 analytics.cost_line：口径判断（单价/总额）与全站同源，
        # 避免「销售单位成本」这类列名被当总额直接求和、毛利错一个数量级
        line = AN.cost_line(df, cost_col, qty_col, cost_force)
        cost = float(line.sum()) if line is not None else None
        if cost is not None and rev:
            margin = (rev - cost) / rev
    if margin is not None:
        if margin < 0.25:
            add("高", f"整体毛利率只有 {margin*100:.1f}%，低于便利店常见水平（25%~35%）",
                f"收入 {rev:,.0f}、成本 {cost:,.0f}，毛利 {rev-cost:,.0f}。",
                "先查最不赚钱的 3 个品类：是进货价偏高、还是折扣打太多；再考虑调价 1%~3% 或换供应商。",
                "毛利率每提高 1 个点，按当前收入约多赚 {:.0f}。".format(rev * 0.01))
        elif margin > 0.55:
            add("低", f"毛利率 {margin*100:.1f}%，偏高，说明定价有余量",
                f"收入 {rev:,.0f}，毛利 {rev-cost:,.0f}。",
                "重点不该再压价，而该看「有多少顾客来了却没买」——补品类、加组合，比提毛利更划算。",
                "客单价提升 5% 对利润的贡献，通常大于毛利率再提 2 个点。")

    # ---------- 2. 折扣 ----------
    price_col = next((c for c in df.columns if any(h in str(c) for h in ("单价", "售价", "零售价", "price"))), None)
    if price_col and qty_col and qty_col in df.columns:
        try:
            line = _num(df[price_col]) * _num(df[qty_col])
            cut = line - _num(df[metric])
            disc = (cut > 0.01) & (line > 0)
            n_disc, n_all = int(disc.sum()), len(df)
            if n_all and n_disc / n_all > 0.10:
                lost = float(cut[disc].sum())
                add("中", f"{n_disc/n_all*100:.0f}% 的销售行在打折，合计让利 {lost:,.0f}",
                    f"让利金额相当于收入的 {_pct(lost, rev):.1f}%。",
                    "把折扣从「随手打」改成「只对临期/滞销打」，并设一个让利上限（例如收入的 1%）。",
                    f"让利压到收入 0.5%，大约能多留 {max(lost - rev*0.005, 0):,.0f}。")
        except Exception:
            pass

    # ---------- 3. 退货 ----------
    try:
        neg = _num(df[metric]) < 0
        pos = _num(df[metric]) > 0
        if neg.sum() >= 3:
            rate = _pct(abs(float(_num(df.loc[neg, metric]).sum())), float(_num(df.loc[pos, metric]).sum()))
            if rate > 2:
                where = ""
                if big_col and big_col in df.columns:
                    g = df[neg].groupby(big_col)[metric].sum().abs().sort_values(ascending=False)
                    if len(g):
                        where = f"退货最多的品类是「{g.index[0]}」（{g.iloc[0]:,.0f}）。"
                add("高", f"退货率 {rate:.1f}%（{int(neg.sum())} 行负金额）",
                    f"负金额合计 {abs(float(_num(df.loc[neg, metric]).sum())):,.0f}。" + where,
                    "抽查退货最多的品类：是质量问题、临期，还是收银错单；临期商品提前 2 天打折清。",
                    "退货率压到 1% 以内，等于白拿回约 {:.0f} 的收入。".format(
                        abs(float(_num(df.loc[neg, metric]).sum())) * 0.5))
    except Exception:
        pass

    # ---------- 4. 商品集中度 / 长尾 ----------
    if item_col and item_col in df.columns:
        try:
            s = df.groupby(item_col)[metric].sum().sort_values(ascending=False)
            s = s[s > 0]
            if len(s) >= 10:
                k = max(int(len(s) * 0.2), 1)
                top_share = _pct(float(s.head(k).sum()), float(s.sum()))
                tail_n = int((s.cumsum() / s.sum() <= 0.9).sum())
                add("中", f"{k} 个商品（前 20%）贡献了 {top_share:.0f}% 的收入",
                    f"共 {len(s)} 个有销量的商品，贡献 90% 收入的是前 {tail_n} 个。",
                    "前 20% 必须保证不断货（每天看一眼库存）；后 30% 逐个评估：能清就清，腾出货架给新品。",
                    "把长尾 SKU 砍掉 20%，通常能少压 10%~15% 的库存资金。")
        except Exception:
            pass

    # ---------- 5. 时段 / 星期 ----------
    if date_col and date_col in df.columns:
        try:
            d = pd.to_datetime(df[date_col], errors="coerce")
            ok = d.notna()
            if ok.sum() > 20:
                wd = d[ok].dt.dayofweek
                g = _num(df.loc[ok, metric]).groupby(wd).sum()
                g = g[g.index < 7]
                if len(g) >= 5:
                    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                    best, worst = g.idxmax(), g.idxmin()
                    avg = g.mean()
                    if g[worst] < avg * 0.75:
                        add("中", f"{names[worst]}是明显低谷（只有均值的 {_pct(g[worst], avg):.0f}%）",
                            f"{names[worst]} {g[worst]:,.0f}，{names[best]} {g[best]:,.0f}。",
                            f"{names[worst]}把促销/上新压到这天，或者减少排班；把主力活动放在{names[best]}前一天预热。",
                            f"低谷日做到均值，一周大约多 {max(avg - g[worst], 0):,.0f}。")
        except Exception:
            pass

    # ---------- 6. 客单价 / 连带率 ----------
    if order_col and order_col in df.columns:
        try:
            n_ord = df[order_col].nunique()
            if n_ord:
                aov = rev / n_ord
                tie = qty / n_ord
                if tie < 1.6:
                    add("中", f"连带率只有 {tie:.2f} 件/单，顾客基本只买一件",
                        f"客单价 {aov:,.2f}，共 {n_ord:,} 单。",
                        "把收银台 3 米内的商品换成「高频 + 低单价」组合，并设一个「满 X 减 Y」门槛在客单价上方 20%。",
                        "连带率提到 2.0，客单价大约能涨 {:.0f}%。".format((2.0 / max(tie, 0.1) - 1) * 100))
        except Exception:
            pass

    # ---------- 7. 关联商品 ----------
    pairs = _top_pairs(df, order_col, item_col)
    if pairs:
        p = pairs[0]
        add("低", f"「{p['a']}」和「{p['b']}」经常一起买（提升度 {p['lift']:.1f} 倍）",
            f"同时出现在 {p['n']} 单里，占全部订单 {p['support']*100:.1f}%。",
            "把这两个摆在一起，或者做成一个组合价（比单买省 5%~8%）。",
            "组合销售通常能把这对商品的连带率再抬 10%~20%，属于几乎零成本的改动。")

    # ---------- 8. 目标缺口 ----------
    if target and target > 0:
        try:
            gap = target - rev
            if gap > 0:
                days = None
                if date_col and date_col in df.columns:
                    dd = pd.to_datetime(df[date_col], errors="coerce").dropna()
                    if len(dd):
                        days = max((dd.max() - dd.min()).days + 1, 1)
                per_day = target / days if days else None
                add("高" if gap / target > 0.1 else "中",
                    f"距目标还差 {gap:,.0f}（完成 {_pct(rev, target):.1f}%）",
                    f"目标 {target:,.0f}，实际 {rev:,.0f}。" + (f"剩余 {days} 天。" if days else ""),
                    (f"剩下每天要做到 {target/days:,.0f}（现在日均 {rev/days:,.0f}，要高 {_pct(target, rev)-100:.0f}%）——"
                     "要么加大活动，要么把目标按品类拆下去" if per_day else "把缺口按品类拆下去，别平均摊"),
                    "靠临期折扣冲量会吃掉毛利，优先用组合装和高毛利品做增量。")
        except Exception:
            pass

    # ---------- 8.5 库存周转 ----------
    stock_col = next((c for c in df.columns if any(h in str(c) for h in ("库存", "结存", "stock"))), None)
    if stock_col and date_col and date_col in df.columns and item_col and item_col in df.columns:
        try:
            dd = pd.to_datetime(df[date_col], errors="coerce").dropna()
            span = max((dd.max() - dd.min()).days + 1, 1) if len(dd) else 0
            if span:
                sold = df.groupby(item_col)[metric].sum()
                stock = df.groupby(item_col)[stock_col].max()
                daily_qty = (df.groupby(item_col)[qty_col].sum() / span) if qty_col and qty_col in df.columns else None
                if daily_qty is not None:
                    turn = (stock / daily_qty.replace(0, np.nan)).dropna()
                    slow = turn[turn > 45].sort_values(ascending=False)
                    if len(slow) >= 2:
                        top = slow.head(3)
                        names = "、".join(f"「{i}」{v:.0f} 天" for i, v in top.items())
                        _price_col = next((c for c in df.columns
                                           if any(h in str(c) for h in ("售价", "单价", "零售价", "price"))), None)
                        if _price_col:
                            _avg_price = df.groupby(item_col)[_price_col].mean()
                            _val = float((stock[slow.index] * _avg_price.reindex(slow.index).fillna(0)).sum())
                            _impact = f"这 {len(slow)} 个商品压着的库存按售价算约 {_val:,.0f}，清掉能直接换回现金。"
                        else:
                            _impact = f"这 {len(slow)} 个商品合计库存 {float(stock[slow.index].sum()):,.0f} 件。"
                        add("中", f"{len(slow)} 个商品的库存要卖 45 天以上（按当前速度）",
                            f"最慢的是 {names}。",
                            "保质期短的先打折清，保质期长的暂停进货一个周期；采购按「日均销量 × 补货周期 × 1.2」下单。",
                            _impact)
        except Exception:
            pass

    # ---------- 9. 品类结构 ----------
    if big_col and big_col in df.columns and cost_col:
        try:
            # 成本口径与全站同源（单价×数量 / 总额），不用内联判断
            _cline = AN.cost_line(df, cost_col, qty_col, cost_force)
            if _cline is not None:
                g = df.groupby(big_col).apply(
                    lambda x: pd.Series({"rev": _num(x[metric]).sum(),
                                         "cost": _cline.loc[x.index].sum()}),
                    include_groups=False)
                g["margin"] = (g["rev"] - g["cost"]) / g["rev"].replace(0, np.nan)
                g = g.dropna().sort_values("rev", ascending=False)
                if len(g) >= 2:
                    worst = g["margin"].idxmin()
                    share = _pct(float(g.loc[worst, "rev"]), float(g["rev"].sum()))
                    if g.loc[worst, "margin"] < 0.2 and share > 0.1:
                        add("中", f"「{worst}」占了 {share:.0f}% 的收入，但毛利率只有 {g.loc[worst,'margin']*100:.1f}%",
                            f"这一块毛利 {g.loc[worst,'rev']-g.loc[worst,'cost']:,.0f}。",
                            "它拉量但不赚钱：要么提价 2%~3% 试水，要么把它当引流品、把利润压在高毛利品类上。",
                            f"这块毛利率提到 25%，大约多赚 {(g.loc[worst,'rev']*0.25 - (g.loc[worst,'rev']-g.loc[worst,'cost'])):,.0f}。")
        except Exception:
            pass

    # ---------- 10. 兜底：数据健康时给「增量方向」参考 ----------
    if len(out) < 3 and order_col and order_col in df.columns:
        try:
            n_ord = df[order_col].nunique()
            if n_ord:
                aov = rev / n_ord
                add("低", f"整体没有明显问题，增强方向在客单价（当前 {aov:,.2f}）",
                    f"{n_ord:,} 单、收入 {rev:,.0f}，连带率 {qty/n_ord:.2f} 件/单。",
                    "三件事按性价比排：①收银台放高频小件做冲动购买 ②满减门槛设在客单价上方 20% ③把两个爆款做成组合价。",
                    f"客单价提 10%（{aov:,.2f} → {aov*1.1:,.2f}），收入大约多 {rev*0.1:,.0f}。")
            if len(out) < 3:
                add("低", "下一步值得先补的数据",
                    "现在的表能算销量和毛利，但缺少「进店人数 / 时段客流」。",
                    "如果能导出按小时的小票，就能看到「人来了不买」和「人没来」的区别——这两种问题的解法完全相反。",
                    "补上客流数据后，转化率、坪效、排班建议才站得住。")
        except Exception:
            pass

    sev_rank = {"高": 0, "中": 1, "低": 2}
    out.sort(key=lambda x: sev_rank.get(x["sev"], 3))
    return out


def speech_script(facts):
    """把结论组织成一段可以直接照着念的汇报话术。facts 里没有的项自动跳过。"""
    period = facts.get("period") or "本期"
    parts = []

    head = f"{period}，"
    if facts.get("rev"):
        head += f"销售收入 {facts['rev']}"
    if facts.get("margin"):
        head += f"，毛利率 {facts['margin']}"
    if facts.get("mom"):
        head += f"，环比 {facts['mom']}"
    parts.append(head.rstrip("，") + "。")

    if facts.get("top_cat"):
        seg = f"结构上，{facts['top_cat']}"
        if facts.get("top_share"):
            seg += f"贡献 {facts['top_share']} 的收入"
        if facts.get("top_margin"):
            seg += f"，是当前利润的主要来源" if facts.get("is_best") else f"，但毛利率只有 {facts['top_margin']}"
        parts.append(seg + "。")

    if facts.get("concern"):
        parts.append(f"需要重点关注的是：{facts['concern']}。")

    advs = [a["title"] for a in (facts.get("advice") or [])][:3]
    if advs:
        parts.append("接下来建议做三件事：" +
                     "；".join(f"{i+1}）{t}" for i, t in enumerate(advs)) + "。")

    if facts.get("ask"):
        parts.append(f"需要支持：{facts['ask']}。")

    return chr(10).join(parts)
