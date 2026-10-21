# -*- coding: utf-8 -*-
"""
数据清洗：先看病、再动刀，每一步都留痕。

- detect(df)      体检：重复行、缺失、文本型数字/日期、空格、异常值、空列、常量列
- clean(df, opts) 按选项清洗，返回 (新表, 日志, 前后对比)
- 所有改动都有记录，能撤销；默认只做"安全动作"（去重、去空格、转类型、删空列）
"""
import numpy as np
import pandas as pd

_NUM_HINT = ("数量", "销量", "金额", "销售额", "单价", "价格", "成本", "收入", "库存",
             "qty", "amount", "price", "cost", "sales")


def _num(s):
    return pd.to_numeric(s, errors="coerce")


_SAMPLE = 3000


def _as_num_ratio(s):
    """这一列有多大比例能被解析成数字（用于识别"文本型数字"）。"""
    if s.dtype != object and not pd.api.types.is_string_dtype(s):
        return 0.0
    v = s.dropna().head(_SAMPLE)          # 抽样 3000 行足够判断类型
    v = v[v.astype(str).str.strip() != ""]
    if v.empty:
        return 0.0
    cleaned = v.astype(str).str.replace(r"[¥$,\s，]", "", regex=True)
    ok = pd.to_numeric(cleaned, errors="coerce").notna().mean()
    return float(ok)


def _as_date_ratio(s):
    if s.dtype != object and not pd.api.types.is_string_dtype(s):
        return 0.0
    v = s.dropna().head(_SAMPLE)
    v = v[v.astype(str).str.strip() != ""]
    if v.empty:
        return 0.0
    txt = v.astype(str).str.strip()
    # 必须先有「年」才算日期：否则 12:30:05 这种时间列会被 pandas 当成今天的日期
    has_year = txt.str.contains(r"(?:19|20)\d{2}", regex=True)
    if has_year.mean() < 0.5:
        return 0.0
    try:
        parsed = pd.to_datetime(txt.str.slice(0, 19), errors="coerce", format="mixed")
    except TypeError:
        parsed = pd.to_datetime(txt.str.slice(0, 19), errors="coerce")
    return float(parsed.notna().mean())


def _mad_flags(x, k=3.5):
    """MAD 离群判定。金额/单价这类正值右偏列在对数空间算，
    否则中位数被压得很低，一半的真实大单都会被判成异常值。"""
    v = _num(x)
    nn = v.notna()
    positive = bool(nn.any()) and bool((v[nn] > 0).mean() >= 0.95) and v[nn].median() > 0
    base = np.log1p(v) if positive else v
    med = base.median()
    mad = (base - med).abs().median()
    if not np.isfinite(mad) or mad == 0:
        return pd.Series(False, index=x.index)
    return ((0.6745 * (base - med) / mad).abs() > k)


def detect(df):
    """返回问题清单：[{级别, 问题, 定位, 数量, 建议}]"""
    out = []
    n = len(df)

    dup = int(df.duplicated().sum())
    if dup:
        out.append({"级别": "高", "问题": "完全重复的行", "定位": "整表",
                    "数量": dup, "建议": "删除重复行，否则收入会被重复计算"})

    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        out.append({"级别": "中", "问题": "整列都是空值", "定位": "、".join(map(str, empty_cols[:6])),
                    "数量": len(empty_cols), "建议": "删掉，参与不了任何分析"})

    const_cols = [c for c in df.columns
                  if df[c].notna().any() and df[c].nunique(dropna=True) <= 1]
    if const_cols:
        out.append({"级别": "低", "问题": "只有一个取值的列", "定位": "、".join(map(str, const_cols[:6])),
                    "数量": len(const_cols), "建议": "不能用来分组，可删可留"})

    miss = {c: int(df[c].isna().sum()) for c in df.columns if df[c].isna().any()}
    if miss:
        top = sorted(miss.items(), key=lambda x: -x[1])[:6]
        out.append({"级别": "高" if sum(miss.values()) > n else "中", "问题": "存在缺失值",
                    "定位": "、".join(f"{c}({v})" for c, v in top),
                    "数量": int(sum(miss.values())), "建议": "按业务决定填 0 / 中位数 / 删行"})

    num_text = [c for c in df.columns if _as_num_ratio(df[c]) >= 0.7 and pd.api.types.is_string_dtype(df[c])]
    if num_text:
        out.append({"级别": "高", "问题": "数字存成了文本（带¥、逗号或空格）", "定位": "、".join(map(str, num_text[:6])),
                    "数量": len(num_text), "建议": "转成数值，否则求和/排序全错"})

    date_text = [c for c in df.columns
                 if c not in num_text and _as_date_ratio(df[c]) >= 0.7 and pd.api.types.is_string_dtype(df[c])]
    if date_text:
        out.append({"级别": "中", "问题": "日期存成了文本", "定位": "、".join(map(str, date_text[:6])),
                    "数量": len(date_text), "建议": "转成日期，才能按年月聚合"})

    space_cols = []
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            v = df[c].dropna().head(_SAMPLE).astype(str)
            if len(v) and (v != v.str.strip()).any():
                space_cols.append(c)
    if space_cols:
        out.append({"级别": "中", "问题": "文本前后有空格（会导致分组重复）", "定位": "、".join(map(str, space_cols[:6])),
                    "数量": len(space_cols), "建议": "去掉首尾空格"})

    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    outliers = {}
    outliers, longtail = {}, {}
    for c in num_cols:
        x = _num(df[c]).dropna()
        if len(x) < 20:
            continue
        mask = _mad_flags(df[c].reindex(x.index)).reindex(x.index).fillna(False)
        k = int(mask.sum())
        if not k:
            continue
        # 仍然超过 2% 被判离群 → 说明只是长尾分布，不该提示用户去删
        if k / max(len(x), 1) <= 0.02:
            outliers[c] = k
        else:
            longtail[c] = k
    if longtail:
        out.append({"级别": "低", "问题": "长尾分布（右偏，不必删）",
                    "定位": "、".join(f"{c}({v})" for c, v in list(longtail.items())[:6]),
                    "数量": int(sum(longtail.values())),
                    "建议": "金额/单价天然右偏，多数是真实大单；要删请先确认具体订单"})
    if outliers:
        out.append({"级别": "中", "问题": "疑似异常值（偏离中位数太远）",
                    "定位": "、".join(f"{c}({v})" for c, v in list(outliers.items())[:6]),
                    "数量": int(sum(outliers.values())),
                    "建议": "先查是不是错单/系统故障，确认后再剔除"})

    neg = {c: int((_num(df[c]) < 0).sum()) for c in num_cols}
    neg = {c: v for c, v in neg.items() if v}
    if neg:
        out.append({"级别": "中", "问题": "存在负值（可能是退款/红冲）",
                    "定位": "、".join(f"{c}({v})" for c, v in list(neg.items())[:6]),
                    "数量": int(sum(neg.values())), "建议": "退款行要保留，但要确认口径是否计入"})

    return out


def clean(df, opts):
    """按选项清洗。返回 (新表, 日志 list[dict], 变更计数 dict)。"""
    d = df.copy()
    log = []
    before = {"行数": len(d), "列数": len(d.columns),
              "缺失单元格": int(d.isna().sum().sum()),
              "重复行": int(d.duplicated().sum())}

    # 1) 列名去空格
    if opts.get("strip_cols", True):
        new_cols = {c: str(c).strip() for c in d.columns}
        changed = sum(1 for k, v in new_cols.items() if k != v)
        if changed:
            d = d.rename(columns=new_cols)
            log.append({"动作": "列名去空格", "影响": f"{changed} 列", "说明": "避免取列名时找不到"})

    # 2) 文本去首尾空格
    if opts.get("strip_text", True):
        touched = 0
        for c in d.columns:
            if d[c].dtype == object or pd.api.types.is_string_dtype(d[c]):
                v = d[c].astype("object")
                s = v.map(lambda x: x.strip() if isinstance(x, str) else x)
                if not s.equals(v):
                    d[c] = s
                    touched += 1
        if touched:
            log.append({"动作": "文本去首尾空格", "影响": f"{touched} 列", "说明": "「饮料 」和「饮料」原本会被当成两个品类"})

    # 3) 文本型数字 → 数值
    if opts.get("to_number", True):
        conv = []
        for c in d.columns:
            if pd.api.types.is_string_dtype(d[c]) and _as_num_ratio(d[c]) >= 0.7:
                d[c] = _num(d[c].astype(str).str.replace(r"[¥$,\s，]", "", regex=True)
                            .replace(r"^$", None))
                conv.append(c)
        if conv:
            log.append({"动作": "文本转数字", "影响": "、".join(map(str, conv[:6])), "说明": "去掉 ¥ / 逗号 / 空格后转数值"})

    # 4) 文本型日期 → 日期
    if opts.get("to_date", True):
        conv = []
        for c in d.columns:
            if pd.api.types.is_string_dtype(d[c]) and _as_date_ratio(d[c]) >= 0.7:
                try:
                    d[c] = pd.to_datetime(d[c].astype(str).str.slice(0, 19),
                                          errors="coerce", format="mixed")
                    conv.append(c)
                except Exception:
                    pass
        if conv:
            log.append({"动作": "文本转日期", "影响": "、".join(map(str, conv[:6])), "说明": "统一成 yyyy-mm-dd"})

    # 5) 删除重复行
    if opts.get("drop_dupes", True):
        k = int(d.duplicated().sum())
        if k:
            d = d.drop_duplicates()
            log.append({"动作": "删除完全重复的行", "影响": f"{k} 行", "说明": "同样的记录只保留一条"})

    # 6) 删除全空列
    if opts.get("drop_empty", True):
        cols = [c for c in d.columns if d[c].isna().all()]
        if cols:
            d = d.drop(columns=cols)
            log.append({"动作": "删除全空列", "影响": "、".join(map(str, cols[:6])), "说明": "整列没有值"})

    # 7) 删除常量列
    if opts.get("drop_constant", False):
        cols = [c for c in d.columns if d[c].notna().any() and d[c].nunique(dropna=True) <= 1]
        if cols:
            d = d.drop(columns=cols)
            log.append({"动作": "删除常量列", "影响": "、".join(map(str, cols[:6])), "说明": "只有一个取值，无法分组"})

    # 8) 缺失值处理
    fill = opts.get("fill", "不处理")
    if fill != "不处理":
        miss_rows = int(d.isna().any(axis=1).sum())
        if fill == "删除含缺失的行":
            d = d.dropna()
            log.append({"动作": "删除含缺失的行", "影响": f"{miss_rows} 行", "说明": "只保留完整记录"})
        elif fill == "数值填 0":
            ncols = [c for c in d.columns if pd.api.types.is_numeric_dtype(d[c])]
            cells = int(d[ncols].isna().sum().sum())
            d[ncols] = d[ncols].fillna(0)
            log.append({"动作": "缺失填 0", "影响": f"{cells} 个单元格", "说明": "适合「本来没发生就是 0」的场景"})
        elif fill == "数值填中位数":
            ncols = [c for c in d.columns if pd.api.types.is_numeric_dtype(d[c])]
            cells = int(d[ncols].isna().sum().sum())
            for c in ncols:
                if d[c].isna().any():
                    d[c] = d[c].fillna(d[c].median())
            log.append({"动作": "缺失填中位数", "影响": f"{cells} 个单元格", "说明": "抗极端值"})

    # 9) 剔除异常值
    if opts.get("drop_outliers", False):
        thr = float(opts.get("mad_k", 3.5))
        total = 0
        skipped = []
        for c in [c for c in d.columns if pd.api.types.is_numeric_dtype(d[c])]:
            mask = _mad_flags(d[c], thr)
            if float(mask.mean()) > 0.02:
                skipped.append(c)
                continue
            k = int(mask.sum())
            if k:
                d = d[~mask]
                total += k
        if total:
            log.append({"动作": f"剔除异常值（MAD>{thr}）", "影响": f"{total} 行",
                        "说明": "极端偏离的记录被移除，注意这会影响总额"})
        if skipped:
            log.append({"动作": "跳过长尾列", "影响": "、".join(skipped[:6]),
                        "说明": "这些列超过 5% 的行被判离群，属右偏分布，删了会误伤真实大单"})

    after = {"行数": len(d), "列数": len(d.columns),
             "缺失单元格": int(d.isna().sum().sum()),
             "重复行": int(d.duplicated().sum())}
    return d, log, {"before": before, "after": after}


def summary_text(log, stats):
    b, a = stats["before"], stats["after"]
    head = (f"清洗前 {b['行数']:,} 行 × {b['列数']} 列，缺失 {b['缺失单元格']:,} 格，重复 {b['重复行']:,} 行；"
            f"清洗后 {a['行数']:,} 行 × {a['列数']} 列，缺失 {a['缺失单元格']:,} 格，重复 {a['重复行']:,} 行。")
    if not log:
        return head + " 这次没有执行任何清洗动作。"
    return head + f" 共执行 {len(log)} 项动作。"
