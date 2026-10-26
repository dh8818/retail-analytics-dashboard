# -*- coding: utf-8 -*-
"""
自定义指标：把「口径字典里的公式」变成可以自己写的
支持聚合函数 + 四则运算，安全求值（AST 白名单，不执行任意代码）

用法示例：
    sum(金额) / nunique(订单号)          → 客单价
    sum(金额) / sum(数量)                → 件单价
    (sum(金额) - sum(成本)) / sum(金额)  → 毛利率
    sum("销售额") / COUNT_DISTINCT("会员卡号")   → 含空格/中文括号的列用引号
"""
import ast
import math
from numbers import Real

import pandas as pd

MAX_LEN = 200
# AST 递归深度上限：防「((((((...1...))))))」这类深层嵌套把解析/求值栈打爆
MAX_DEPTH = 40
FUNCS = {
    "sum": lambda s: s.sum(),
    "mean": lambda s: s.mean(),
    "avg": lambda s: s.mean(),
    "median": lambda s: s.median(),
    "max": lambda s: s.max(),
    "min": lambda s: s.min(),
    "std": lambda s: s.std(),
    "count": lambda s: s.count(),
    "nunique": lambda s: s.nunique(),
    "count_distinct": lambda s: s.nunique(),
}


class FormulaError(ValueError):
    pass


NUM_FUNCS = {"sum", "mean", "avg", "median", "max", "min", "std"}


def _col(df, name, numeric=True):
    """取列。pandas 3 的字符串列是 str dtype 不是 object，不能靠 dtype 判断是否数值。"""
    if name not in df.columns:
        raise FormulaError(f"找不到列「{name}」")
    s = df[name]
    if numeric:
        return pd.to_numeric(s, errors="coerce")
    return s


def _numify(v):
    try:
        v = float(v)
    except Exception:
        raise FormulaError("公式结果不是数字")
    if math.isnan(v) or math.isinf(v):
        raise FormulaError("公式结果无效（可能除以 0）")
    return v


def _eval(node, df, depth=0):
    if depth > MAX_DEPTH:
        raise FormulaError("公式嵌套太深")
    if isinstance(node, ast.Expression):
        return _eval(node.body, df, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node.value, str):
            return node.value
        raise FormulaError("不支持的常量")
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, df, depth + 1), _eval(node.right, df, depth + 1)
        # 用 numbers.Real 判断，而不是 isinstance(..., (int, float))：
        # 后者会漏掉 numpy.float64 这类标量（pandas 聚合结果默认是 np.float64）
        if not (isinstance(a, Real) and isinstance(b, Real)):
            raise FormulaError("四则运算两侧必须都是数值")
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise FormulaError("除以 0")
            return a / b
        if isinstance(node.op, ast.Mod):
            if b == 0:
                raise FormulaError("除以 0")
            return a % b
        raise FormulaError("不支持的运算符")
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, df, depth + 1)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        raise FormulaError("不支持的一元运算")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id.lower()
        if fn not in FUNCS:
            raise FormulaError(f"不支持的函数「{node.func.id}」，可用：{', '.join(sorted(FUNCS))}")
        if len(node.args) != 1:
            raise FormulaError(f"{fn}() 只接受一个参数（列名）")
        argnode = node.args[0]
        # 支持 sum(进货价 * 数量)：两列相乘再聚合
        if isinstance(argnode, ast.BinOp) and isinstance(argnode.op, ast.Mult):
            if fn not in NUM_FUNCS:
                raise FormulaError(f"{fn}() 不能用在「列 * 列」上")
            left = argnode.left.id if isinstance(argnode.left, ast.Name) else None
            right = argnode.right.id if isinstance(argnode.right, ast.Name) else None
            if not (left and right):
                raise FormulaError("乘号两边必须是列名，例如 sum(进货价 * 数量)")
            prod = _col(df, left) * _col(df, right)
            return float(FUNCS[fn](prod))
        arg = _eval(argnode, df, depth + 1)
        if not isinstance(arg, str):
            raise FormulaError(f"{fn}() 的参数必须是列名，例如 sum(金额)")
        return float(FUNCS[fn](_col(df, arg, numeric=(fn in NUM_FUNCS))))
    raise FormulaError("公式里有不支持的内容（只允许聚合函数 + 数字 + 四则运算）")


def evaluate(df, expr):
    """返回 (值, 错误信息)。值可能为 None。"""
    expr = (expr or "").strip()
    if not expr:
        return None, "公式为空"
    if len(expr) > MAX_LEN:
        return None, "公式太长"
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return None, f"语法错误：{e.msg}"
    try:
        return _numify(_eval(tree, df)), None
    except FormulaError as e:
        return None, str(e)
    except Exception as e:
        return None, f"计算失败：{e}"


def fmt_value(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e8:
        return f"{v/1e8:.2f}亿"
    if a >= 1e4:
        return f"{v/1e4:.2f}万"
    if a >= 100:
        return f"{v:,.0f}"
    return f"{v:,.2f}"
