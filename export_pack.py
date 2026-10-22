# -*- coding: utf-8 -*-
"""分析包导出：把数据、口径、结论、图表打成一个 ZIP，方便店主交给专业分析师。

包含：
  01_数据_清洗后.csv      原始（或脱敏）明细
  02_字段说明.csv         每列的类型、缺失、示例、推断含义
  03_指标与口径.csv       每个指标的值 + 公式（避免对方重算出口径不一致）
  04_分析结论.md          概况、结论、问题清单、改善建议
  05_数据体检.csv         检出的数据问题
  06_图表/*.png           四张主图（趋势、结构、帕累托、毛利率）
  07_给分析师的说明.md    包里有什么、建议先看什么、还缺什么数据
"""
import io
import os
import re
import tempfile
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd

import advice as ADV
import ppt_export as PX

PII_HINTS = ("手机", "电话", "姓名", "名字", "身份证", "地址", "邮箱", "卡号", "顾客", "会员名", "联系人")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _mask_cols(df):
    """脱敏：去掉明显含个人信息或过细的列。"""
    drop = [c for c in df.columns if any(h in str(c) for h in PII_HINTS)]
    return df.drop(columns=drop), drop


def _field_dict(df):
    rows = []
    for c in df.columns:
        s = df[c]
        nn = s.notna().sum()
        sample = ""
        try:
            vals = s.dropna().astype(str).unique()[:3]
            sample = " / ".join(v[:18] for v in vals)
        except Exception:
            pass
        uniq = s.nunique(dropna=True)
        if pd.api.types.is_numeric_dtype(s):
            kind = "数值"
        elif pd.api.types.is_datetime64_any_dtype(s):
            kind = "日期"
        elif uniq <= max(30, len(df) * 0.02):
            kind = "类别"
        else:
            kind = "文本/编号"
        rows.append({"列名": c, "类型": kind, "非空": int(nn),
                     "缺失": int(len(s) - nn), "不同取值": int(uniq), "示例": sample})
    return pd.DataFrame(rows)


def _conclusion_md(df, metric, qty_col, date_col, big_col, item_col, cost_col,
                   cost_force, margin, advice_list, issues, span):
    lines = [f"# 经营数据摘要\n", f"生成时间：{datetime.now():%Y-%m-%d %H:%M}\n"]
    lines.append(f"- 数据规模：{len(df):,} 行，{len(df.columns)} 列")
    if span:
        lines.append(f"- 数据区间：{span}")
    if metric:
        total = float(_num(df[metric]).sum())
        lines.append(f"- {metric}合计：{total:,.2f}")
    if margin is not None:
        lines.append(f"- 毛利率：{margin*100:.2f}%")
    elif cost_col:
        lines.append("- 毛利率：未计算（成本列与金额相等，或缺少进货成本；请补充真实成本后重算）")

    if date_col and metric:
        d = df.dropna(subset=[date_col])
        m = d.groupby(pd.to_datetime(d[date_col]).dt.to_period("M"))[metric].sum()
        if len(m) >= 2:
            chg = (m.iloc[-1] / m.iloc[-2] - 1) * 100 if m.iloc[-2] else float("nan")
            lines.append(f"- 最近一个月环比：{chg:+.1f}%（{m.index[-2]} → {m.index[-1]}）")

    if big_col and metric:
        share = df.groupby(big_col)[metric].sum().sort_values(ascending=False)
        share = share.head(5) / max(share.sum(), 1) * 100
        lines.append("\n## 结构\n")
        for k, v in share.items():
            lines.append(f"- {k}：{v:.1f}%")

    if item_col and metric:
        s = df.groupby(item_col)[metric].sum().sort_values(ascending=False)
        if len(s):
            top = s.head(5)
            lines.append("\n## 销量/金额前五\n")
            for k, v in top.items():
                lines.append(f"- {k}：{v:,.0f}")

    if issues:
        lines.append("\n## 数据问题（交给对方时要一并说明）\n")
        for i in issues:
            lines.append(f"- [{i['级别']}] {i['问题']}：{i['定位']}（{i['数量']}）")

    if advice_list:
        lines.append("\n## 已识别的改善方向\n")
        for a in advice_list[:6]:
            lines.append(f"### {a['title']}")
            lines.append(f"- 依据：{a['evidence']}")
            lines.append(f"- 建议：{a['action']}")
            lines.append(f"- 预期：{a['impact']}\n")
    return "\n".join(lines)


def _readme_md(df, files, mask_dropped):
    return f"""# 这份分析包里有什么

生成时间：{datetime.now():%Y-%m-%d %H:%M}　｜　数据规模：{len(df):,} 行 × {len(df.columns)} 列

## 建议的阅读顺序

1. `04_分析结论.md` —— 先看结论和已发现的问题
2. `03_指标与口径.csv` —— 每个数字是怎么算出来的，**复算时请以此为准**
3. `06_图表/` —— 四张主图，可直接放进报告
4. `01_数据_清洗后.csv` —— 需要自己动手时用它，不要再用原始导出表

## 文件清单

{chr(10).join('- `' + f + '`' for f in files)}

## 口径说明（重要）

- 金额为销售明细的**净额**（含退款冲红），不是订单实付
- 成本按列名判断是单价还是总额；单价会乘以数量
- 毛利率 =（金额 − 成本）÷ 金额
- 若与你的算法不一致，请以 `03_指标与口径.csv` 里的公式为准，不要直接改数

## 还缺什么（如果你要做更深入的分析）

- 库存快照（期初、入库、出库、在途）→ 才能算周转与缺货
- 促销/活动记录 → 才能区分销量变化是活动带来的还是趋势
- 客流数据 → 才能拆「进店人数 × 转化率 × 客单价」
- 商品成本与效期 → 才能算真实毛利与报损

{('- 注：已按要求脱敏，移除列：' + '、'.join(mask_dropped)) if mask_dropped else ''}

## 想请你回答的问题

1. 现在最影响利润的是哪三个商品/品类？依据是什么？
2. 如果只能改一件事，改哪个动作收益最大？
3. 现有数据缺什么，补齐之后能多回答什么问题？
4. 哪些结论是数据支持的，哪些只是推测？请分开写。
5. 有没有明显的口径问题或异常值？
6. 如果要做一次试点，你会选哪个门店、哪个商品、观察多久、看哪两个指标？
"""


def build_pack(df, metric=None, qty_col=None, cost_col=None, cost_force="auto",
               date_col=None, item_col=None, big_col=None, order_col=None,
               target=0.0, metric_rows=None, issues=None, mask=True,
               company="") -> bytes:
    """返回 zip 的二进制内容。任何一张图失败都只跳过那张图。"""
    d = df.copy()
    mask_dropped = []
    if mask:
        d, mask_dropped = _mask_cols(d)

    span = ""
    if date_col and date_col in d.columns:
        dts = pd.to_datetime(d[date_col], errors="coerce", format="mixed")
        d[date_col] = dts
        if dts.notna().any():
            span = f"{dts.min():%Y-%m-%d} — {dts.max():%Y-%m-%d}"

    rev_total = float(_num(d[metric]).sum()) if metric and metric in d.columns else 0.0
    cost_total, margin = None, None
    if cost_col and cost_col in d.columns and rev_total:
        c = _num(d[cost_col])
        if cost_force != "total" and qty_col and qty_col in d.columns:
            c = c * _num(d[qty_col])
        cost_total = float(c.sum())
        # 成本列如果和金额同源（比如把"售价"当成本选了进来），毛利率会算成 0，
        # 这种假数字比没有更糟，直接判为不可计算
        if rev_total and abs(cost_total - rev_total) / rev_total < 0.005:
            cost_total = None
        else:
            margin = (rev_total - cost_total) / rev_total

    try:
        adv = ADV.build_advice(d, metric, qty_col, cost_col, cost_force,
                               date_col, item_col, big_col, order_col, target)
    except Exception:
        adv = []

    tmp = tempfile.mkdtemp(prefix="pack_")
    charts = {}

    def _try(name, fn, *a, **k):
        try:
            p = os.path.join(tmp, name)
            fn(*a, path=p, **k) if "path" not in k else fn(*a, **k)
            if os.path.exists(p) and os.path.getsize(p) > 2000:
                charts[f"06_图表/{name}"] = p
        except Exception:
            pass

    if date_col and metric and date_col in d.columns:
        try:
            g = d.dropna(subset=[date_col])
            m = g.groupby(g[date_col].dt.to_period("M"))
            rev = m[metric].sum()
            prof = None
            if cost_col and cost_col in d.columns:
                cc = _num(d[cost_col]) * (_num(d[qty_col]) if cost_force != "total" and qty_col else 1)
                prof = g.assign(_c=cc).groupby(g[date_col].dt.to_period("M"))["_c"].sum()
            if len(rev) >= 2:
                profit = (rev - prof.reindex(rev.index).fillna(0)) if prof is not None else rev * 0
                _try("01_月度趋势.png", PX.chart_trend, [str(i) for i in rev.index],
                     list(rev.values), list(profit.values))
        except Exception:
            pass

    if big_col and metric and big_col in d.columns:
        try:
            s = d.groupby(big_col)[metric].sum().sort_values(ascending=False).head(8)
            if len(s):
                _try("02_品类结构.png", PX.chart_donut, [str(i) for i in s.index], list(s.values))
        except Exception:
            pass

    if item_col and metric and item_col in d.columns:
        try:
            s = d.groupby(item_col)[metric].sum()
            if len(s) >= 3:
                _try("03_商品帕累托.png", PX.chart_pareto, [str(i) for i in s.index], list(s.values))
        except Exception:
            pass

    if big_col and metric and cost_col and margin is not None:
        try:
            cc = _num(d[cost_col]) * (_num(d[qty_col]) if cost_force != "total" and qty_col else 1)
            t = d.assign(_c=cc).groupby(big_col).agg(_rev=(metric, "sum"), _cost=("_c", "sum"))
            t = t[t._rev != 0]
            ms = ((t._rev - t._cost) / t._rev).sort_values(ascending=False)
            if len(ms) >= 2:
                _try("04_品类毛利率.png", PX.chart_margin, [str(i) for i in ms.index], list(ms.values))
        except Exception:
            pass

    conclusion = _conclusion_md(d, metric, qty_col, date_col, big_col, item_col,
                                cost_col, cost_force, margin, adv, issues or [], span)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01_数据_清洗后.csv", d.to_csv(index=False).encode("utf-8-sig"))
        z.writestr("02_字段说明.csv", _field_dict(d).to_csv(index=False).encode("utf-8-sig"))
        if metric_rows:
            z.writestr("03_指标与口径.csv",
                       pd.DataFrame(metric_rows).to_csv(index=False).encode("utf-8-sig"))
        z.writestr("04_分析结论.md", conclusion.encode("utf-8"))
        if issues:
            z.writestr("05_数据体检.csv",
                       pd.DataFrame(issues).to_csv(index=False).encode("utf-8-sig"))
        names = ["01_数据_清洗后.csv", "02_字段说明.csv", "03_指标与口径.csv",
                 "04_分析结论.md", "05_数据体检.csv", "06_图表/", "07_给分析师的说明.md"]
        for n, path in charts.items():
            z.write(path, n)
            names.append(n)
        z.writestr("07_给分析师的说明.md", _readme_md(d, names, mask_dropped).encode("utf-8"))
    return buf.getvalue()
