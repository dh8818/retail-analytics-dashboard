# -*- coding: utf-8 -*-
"""
指标公式引擎：让「销售收入 / 毛利 / 毛利率 / 客单价 …」这些内置指标也能改公式。

- 默认公式按实际列名生成（金额列叫「销售额」就写 sum(销售额)）
- 公式里可以用 [指标名] 引用别的指标，例如 毛利率 = [毛利] / [销售收入]
- 支持 sum( 进货价 * 数量 ) 这种「两列相乘再求和」
- 用户改过的公式默认只存在「当前浏览器会话」里（不写服务器磁盘、不跨访客共享）；
  本地单人使用时设 DASH_PERSIST_FORMULAS=1 才会写 metric_formulas.json
"""
import json
import os
from pathlib import Path

import custom_metrics as CM

ORDER = ["销售收入", "销售数量", "订单数", "成本", "毛利", "毛利率", "客单价", "连带率", "件单价"]


def build_defaults(rev_col, qty_col, cost_col, cost_force, order_col):
    """按数据里真实存在的列，生成一套默认公式。"""
    rev = rev_col or ""
    qty = qty_col or ""
    d = {}
    d["销售收入"] = f"sum({rev})" if rev else "0"
    d["销售数量"] = f"sum({qty})" if qty and qty != rev else (f"count({rev})" if rev else "0")
    d["订单数"] = f"nunique({order_col})" if order_col else (f"count({rev})" if rev else "0")

    if cost_col and qty and cost_force != "total":
        d["成本"] = f"sum({cost_col} * {qty})"
    elif cost_col:
        d["成本"] = f"sum({cost_col})"
    else:
        d["成本"] = ""

    d["毛利"] = "[销售收入] - [成本]" if d["成本"] else ""
    d["毛利率"] = "[毛利] / [销售收入]" if d["成本"] else ""
    d["客单价"] = "[销售收入] / [订单数]"
    d["连带率"] = "[销售数量] / [订单数]"
    d["件单价"] = "[销售收入] / [销售数量]"
    return d


def resolve(df, formulas, order=None):
    """按依赖顺序求值。返回 (values, errors)。"""
    order = order or ORDER
    vals, errs = {}, {}
    cache = {}

    def calc(name, stack):
        if name in cache:
            return cache[name]
        if name in stack:
            raise ValueError(f"「{name}」的公式绕成了循环引用")
        expr = (formulas.get(name) or "").strip()
        if not expr:
            return None
        # 把 [别的指标] 换成它的数值
        for dep in order:
            if dep == name or f"[{dep}]" not in expr:
                continue
            dv = calc(dep, stack | {name})
            if dv is None:
                raise ValueError(f"「{name}」依赖的「{dep}」没有值")
            expr = expr.replace(f"[{dep}]", f"({dv!r})")
        v, err = CM.evaluate(df, expr)
        if err:
            raise ValueError(err)
        cache[name] = v
        return v

    for name in order:
        try:
            vals[name] = calc(name, frozenset())
        except ValueError as e:
            vals[name] = None
            errs[name] = str(e)
        except Exception as e:            # 兜底，绝不让单个公式拖垮整页
            vals[name] = None
            errs[name] = f"计算失败：{e}"
    return vals, errs


def sanitize(overrides, df):
    """丢掉引用了当前数据里不存在的列的公式（换了数据源时自动回退默认）。"""
    import re as _re
    cols = set(map(str, df.columns))
    out = {}
    for name, expr in (overrides or {}).items():
        tokens = set(_re.findall(r"[A-Za-z_一-龥][\w一-龥]*", str(expr)))
        refs = {t for t in tokens if t not in CM.FUNCS}
        if refs <= cols:
            out[name] = expr
    return out


def load_overrides(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except Exception:
        return {}


def persist_enabled():
    """只有本地单机场景才落盘；云端多人访问时写文件=把口径共享给陌生访客。"""
    return os.environ.get("DASH_PERSIST_FORMULAS") == "1"


def save_overrides(path, formulas):
    if not persist_enabled():
        return False
    try:
        Path(path).write_text(json.dumps(formulas, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def display(name, value, formulas=None):
    """把指标值变成页面上的文字，比率类的用百分数。"""
    if value is None:
        return "—"
    if name in ("毛利率",):
        return f"{value * 100:.1f}%"
    if abs(value) < 100 and name in ("客单价", "件单价"):
        return f"{value:,.2f}"
    a = abs(value)
    if a >= 1e8:
        return f"{value/1e8:.2f}亿"
    if a >= 1e4:
        return f"{value/1e4:.2f}万"
    return f"{value:,.2f}" if a < 100 else f"{value:,.0f}"
