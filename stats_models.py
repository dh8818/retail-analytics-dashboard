# -*- coding: utf-8 -*-
"""
统计与建模：初级到中级分析师的分水岭能力。

全部是纯函数，输入 DataFrame，输出可核对的数字：
- describe      描述统计（均值/中位数/标准差/分位数/偏度/变异系数）
- welch_ttest   两组差异显著性（Welch t 检验 + Cohen's d）
- ols           多元线性回归（系数、标准误、t 值、p 值、R²、F、残差）
- kmeans        K-Means 聚类（自带实现，不依赖 sklearn）
- decompose     乘法式指标拆解（收入 = 订单数 × 客单价）
- cohort        复购/留存队列（cohort matrix）

每个函数都不吞异常以外的假设：算不出来就抛错或返回 None，由界面提示。
"""
import numpy as np
import pandas as pd
from scipy import stats as _st


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def describe(df, cols):
    """描述统计表。偏度用 Fisher 定义（正态=0）。"""
    rows = []
    for c in cols:
        x = _num(df[c]).dropna()
        if x.empty:
            continue
        sd = float(x.std(ddof=1))
        rows.append({
            "指标": c,
            "样本数": int(x.size),
            "均值": float(x.mean()),
            "中位数": float(x.median()),
            "标准差": sd,
            "最小值": float(x.min()),
            "P25": float(x.quantile(0.25)),
            "P75": float(x.quantile(0.75)),
            "最大值": float(x.max()),
            "变异系数": (sd / float(x.mean())) if x.mean() else np.nan,
            "偏度": float(_st.skew(x, bias=False)) if x.size > 2 else np.nan,
        })
    return pd.DataFrame(rows)


def welch_ttest(a, b):
    """Welch t 检验（不假设方差齐）。返回 t、df、双尾 p、均值差、Cohen's d。"""
    a = _num(pd.Series(a)).dropna().to_numpy()
    b = _num(pd.Series(b)).dropna().to_numpy()
    if a.size < 2 or b.size < 2:
        return None
    res = _st.ttest_ind(a, b, equal_var=False)
    va, vb = a.var(ddof=1), b.var(ddof=1)
    sp = np.sqrt((va + vb) / 2)          # 近似合并标准差
    d = (a.mean() - b.mean()) / sp if sp else np.nan
    return {
        "t": float(res.statistic), "df": float(res.df), "p": float(res.pvalue),
        "mean_a": float(a.mean()), "mean_b": float(b.mean()),
        "diff": float(a.mean() - b.mean()), "cohens_d": float(d),
        "n_a": int(a.size), "n_b": int(b.size),
    }


def ols(df, y, xs):
    """最小二乘回归，带截距。结果含系数、标准误、t、p、R²、调整 R²、F 与残差。"""
    yv = _num(df[y]).to_numpy(dtype=float)
    Xs = []
    used = []
    for c in xs:
        v = _num(df[c]).to_numpy(dtype=float)
        Xs.append(v)
        used.append(c)
    if not Xs:
        return None
    X = np.column_stack(Xs)
    m = np.isfinite(yv) & np.isfinite(X).all(axis=1)
    if m.sum() < len(used) + 2:
        return None
    yv, X = yv[m], X[m]
    n = len(yv)
    A = np.column_stack([np.ones(n), X])
    coef, *_ = np.linalg.lstsq(A, yv, rcond=None)
    fitted = A @ coef
    resid = yv - fitted
    k = A.shape[1]
    dof = n - k
    if dof <= 0:
        return None

    # 标准误：sigma² (X'X)^-1
    sigma2 = float(resid @ resid) / dof
    try:
        xtx_inv = np.linalg.inv(A.T @ A)
    except np.linalg.LinAlgError:
        return None
    se = np.sqrt(np.clip(np.diag(xtx_inv) * sigma2, 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        tvals = np.where(se > 0, coef / se, np.nan)
    pvals = 2 * _st.t.sf(np.abs(tvals), dof)

    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    ss_res = float((resid ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else np.nan
    adj = 1 - (1 - r2) * (n - 1) / dof if np.isfinite(r2) else np.nan
    f_stat = ((ss_tot - ss_res) / (k - 1)) / (ss_res / dof) if ss_res > 0 and k > 1 else np.nan
    f_p = float(_st.f.sf(f_stat, k - 1, dof)) if np.isfinite(f_stat) else np.nan

    names = ["截距"] + list(used)
    table = pd.DataFrame({
        "变量": names, "系数": coef, "标准误": se,
        "t 值": tvals, "p 值": pvals,
    })
    return {"table": table, "r2": float(r2), "adj_r2": float(adj),
            "f": float(f_stat), "f_p": f_p, "n": int(n), "dof": int(dof),
            "y": y, "xs": list(used), "coef": coef,
            "resid": resid, "fitted": fitted, "y_true": yv}


def predict(model, df):
    """用 OLS 结果对新数据预测。"""
    A = np.column_stack([np.ones(len(df))] + [_num(df[c]).to_numpy(dtype=float) for c in model["xs"]])
    return pd.Series(A @ model["coef"], index=df.index)


def kmeans(X, k=3, iters=100, seed=0):
    """K-Means（k-means++ 初始化）。返回标签、中心点、组内平方和。"""
    X = np.asarray(X, dtype=float)
    m = np.isfinite(X).all(axis=1)
    Xv = X[m]
    n = len(Xv)
    k = max(1, min(int(k), max(1, n - 1)))
    rng = np.random.default_rng(seed)
    centers = [Xv[rng.integers(n)]]
    for _ in range(k - 1):
        d2 = np.min(((Xv[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(axis=2), axis=1)
        tot = d2.sum()
        probs = d2 / tot if tot > 0 else np.ones(n) / n
        centers.append(Xv[rng.choice(n, p=probs)])
    C = np.array(centers)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        d = ((Xv[:, None, :] - C[None, :, :]) ** 2).sum(axis=2)
        new = d.argmin(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                C[j] = Xv[labels == j].mean(axis=0)
    inertia = float(((Xv - C[labels]) ** 2).sum())
    out = np.full(len(X), -1, dtype=int)
    out[m] = labels
    return {"labels": out, "centers": C, "inertia": inertia, "k": k, "mask": m}


def decompose(prev_a, prev_b, cur_a, cur_b, name_a="数量", name_b="单价"):
    """乘法拆解：V = A × B。把 V 的变化拆成 A 的效应、B 的效应和交互项。

    恒等式：ΔV = ΔA·B₀ + A₀·ΔB + ΔA·ΔB（三项相加严格等于 ΔV）
    """
    pa, pb, ca, cb = float(prev_a), float(prev_b), float(cur_a), float(cur_b)
    d_a, d_b = ca - pa, cb - pb
    eff_a = d_a * pb
    eff_b = pa * d_b
    inter = d_a * d_b
    d_v = ca * cb - pa * pb
    return {
        "prev": pa * pb, "cur": ca * cb, "delta": d_v,
        "eff_a": eff_a, "eff_b": eff_b, "interaction": inter,
        "share_a": eff_a / d_v if d_v else np.nan,
        "share_b": eff_b / d_v if d_v else np.nan,
        "name_a": name_a, "name_b": name_b,
        "prev_a": pa, "prev_b": pb, "cur_a": ca, "cur_b": cb,
    }


def cohort(df, user_col, date_col, value_col=None, periods=6):
    """按首次出现月份分队列，看后续每个月还有多少用户回来（留存/复购）。

    返回：cohort_matrix（行=队列月，列=第几个自然月）、sizes（队列人数）、rate（留存率矩阵）
    """
    if user_col not in df.columns or date_col not in df.columns:
        return None
    d = df[[user_col, date_col] + ([value_col] if value_col in df.columns else [])].dropna(subset=[user_col, date_col]).copy()
    if d.empty:
        return None
    d["_m"] = pd.to_datetime(d[date_col], errors="coerce").dt.to_period("M")
    d = d.dropna(subset=["_m"])
    if d.empty:
        return None
    first = d.groupby(user_col)["_m"].min().rename("_first")
    d = d.join(first, on=user_col)
    d["_idx"] = (d["_m"].astype("int64") - d["_first"].astype("int64")).astype(int)
    d = d[d["_idx"] >= 0]

    sizes = d.groupby("_first")[user_col].nunique().rename("队列人数")
    piv = d.groupby(["_first", "_idx"])[user_col].nunique().unstack(fill_value=0)
    rate = piv.div(sizes, axis=0) * 100
    return {"matrix": piv, "rate": rate, "sizes": sizes, "periods": min(periods, piv.shape[1])}
