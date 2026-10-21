# -*- coding: utf-8 -*-
"""把模型结果翻译成人话：每个数字什么意思、说明了什么、能拿它做什么。"""


def _sig(p):
    if p != p:            # NaN
        return "无法判断"
    if p < 0.01:
        return "很显著"
    if p < 0.05:
        return "显著"
    if p < 0.10:
        return "边缘显著"
    return "不显著"


def coef_sentences(m, y_name):
    """回归系数逐条翻译。"""
    out = []
    names = ["截距"] + list(m["xs"])
    for i, name in enumerate(names):
        b = float(m["coef"][i])
        p = float(m["table"]["p 值"][i]) if i < len(m["table"]) else float("nan")
        if name == "截距":
            out.append(f"<b>截距</b> = {b:,.2f}：所有自变量为 0 时 {y_name} 的基准值，通常没有业务含义，看方向就行。")
            continue
        direction = "增加" if b > 0 else "减少"
        out.append(
            f"<b>{name}</b> 每多 1 个单位，{y_name} 平均{direction} <b>{abs(b):,.2f}</b>"
            f"（{_sig(p)}，p={p:.3f}）"
            + ("" if _sig(p) in ("显著", "很显著") else "——这条证据不够，别据此下结论"))
    return out


def model_readout(m, y_name):
    """模型整体结论：3–4 句。"""
    r2 = m["r2"]
    if r2 >= 0.7:
        strength = "很强"
        meaning = "这些变量基本能解释结果的大部分波动，可以拿来做事前判断"
    elif r2 >= 0.4:
        strength = "中等"
        meaning = "能看出主要方向，但还有相当一部分波动来自没进模型的因素"
    elif r2 >= 0.15:
        strength = "偏弱"
        meaning = "只能当作线索，不能当预测工具；更可能是漏了关键变量"
    else:
        strength = "很弱"
        meaning = "这些变量几乎解释不了结果，先别用这个模型做决策"

    lines = [f"模型解释了 {r2*100:.1f}% 的波动（R² = {r2:.3f}），解释力{strength}：{meaning}。"]

    sig_cols = [(n, float(m["coef"][i + 1]))
                for i, n in enumerate(m["xs"])
                if i + 1 < len(m["table"]) and float(m["table"]["p 值"][i + 1]) < 0.05]
    if sig_cols:
        top = max(sig_cols, key=lambda x: abs(x[1]))
        lines.append(f"其中影响最大的是「{top[0]}」（系数 {top[1]:,.2f}，方向"
                     f"{'正' if top[1] > 0 else '负'}），它是最值得先动的杠杆。")
    else:
        lines.append("没有任何一个自变量的系数显著——这份数据里还看不出稳定的影响因素。")

    lines.append("注意：这是相关关系，不是因果关系。系数大不代表「改它就能带来变化」，"
                 "真正的因果要靠对照实验或时间上的先后顺序来验证。")
    return lines


def cluster_profiles(tmp, feats, label_col="群"):
    """聚类画像：每一群里，各特征相对整体是偏高还是偏低。"""
    import pandas as pd

    agg = tmp.groupby(label_col)[feats].mean()
    overall = tmp[feats].mean()
    out = []
    for g in sorted(agg.index):
        desc = []
        for f in feats:
            v = agg.loc[g, f]
            avg = overall[f]
            if pd.isna(v) or not avg:
                continue
            ratio = v / avg
            tag = "偏高" if ratio > 1.15 else ("偏低" if ratio < 0.85 else "持平")
            desc.append(f"{f}{tag}（{v:,.2f}，整体均值 {avg:,.2f}）")
        out.append({"群": int(g), "样本数": int((tmp[label_col] == g).sum()),
                    "画像": "；".join(desc) or "没有明显特征"})
    return out
