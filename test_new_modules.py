# -*- coding: utf-8 -*-
"""
新功能模块自检：数据源 / 多门店 / 跑批推送 / 语义层 / 安全库存 / 规模优化。
运行：python test_new_modules.py
"""
import os
import tempfile

import numpy as np
import pandas as pd

FAIL = []


def check(name, got, want=None, predicate=None):
    ok = predicate(got) if predicate else (got == want)
    print(f"{'✓' if ok else '✗'} {name}: {got}")
    if not ok:
        FAIL.append(name)


print("== 指标语义层 ==")
import metric_catalog as MC
_b = MC.bind_columns("金额", "数量", "进货价", "订单号")
check("销售收入公式", _b["销售收入"], "sum(金额)")
check("成本公式(单价×数量)", _b["成本"], "sum(进货价 * 数量)")
check("毛利率公式(引用)", _b["毛利率"], "[毛利] / [销售收入]")
_b2 = MC.bind_columns("金额", "数量", "", "订单号")
check("缺成本列时成本公式为空", _b2["成本"], "")

print("\n== 数据源抽象层 + 示例连接器 ==")
import connector_sqlite as CS
import datasources as DS
db = os.path.join(tempfile.gettempdir(), "demo_pos_test2.db")
CS.seed_demo(db, days=30, stores=3)
src = CS.SqlitePOSSource({"path": db})
fetched = src.fetch()
check("销售明细有数据", len(fetched["sales"]) > 0, predicate=lambda v: v)
check("销售表含标准门店列", "门店编码" in fetched["sales"].columns, True)
check("增量拉取比全量少", len(src.fetch(fetched["sales"]["日期"].min())["sales"]) < len(fetched["sales"]), True)

store = DS.Store(os.path.join(tempfile.gettempdir(), "test_stores.db"))
store.save_snapshot("sqlite_pos", "sales", fetched["sales"])
back = store.load_snapshot("sqlite_pos", "sales")
check("快照落库可读回", len(back), len(fetched["sales"]))
store.close()

print("\n== 多门店 ==")
import stores as ST
cmp = ST.cross_store_compare(fetched["sales"], "门店编码", "金额")
check("跨店对比行数=门店数", len(cmp), fetched["sales"]["门店编码"].nunique())
check("占比合计≈100", round(cmp["占比%"].sum()), 100)

tree = ST.StoreTree.build_from(pd.DataFrame([
    {"code": "A", "region": "R1"}, {"code": "B", "region": "R1"}, {"code": "C", "region": "R2"}]))
check("店长只看自己店", ST.StoreTree.visible_codes(tree, "store_manager", "A"), ["A"])
check("区域经理看本区域", ST.StoreTree.visible_codes(tree, "region_manager", "R1"), ["A", "B"])
check("老板看全部", len(ST.StoreTree.visible_codes(tree, "boss", None)), 3)

print("\n== 跑批与预警 ==")
import scheduler as SC
sales = fetched["sales"].copy()
# 人为制造最近一天暴跌，应能触发预警
sales["日期"] = pd.to_datetime(sales["日期"])
dmax = sales["日期"].max()
sales.loc[sales["日期"] == dmax, "金额"] *= 0.5
concl = SC.detect_anomalies(sales, "金额", "日期", "门店编码")
check("暴跌能触发预警", len(concl) > 0, predicate=lambda v: v)
rep = SC.build_daily_report(sales, "金额", "日期", "品类", "门店编码")
check("日报含销售额", "销售额" in rep, True)
res = SC.deliver("local", rep, "test")
check("本地推送落盘", res["ok"], True)

print("\n== 动态安全库存 ==")
import inventory as INV
flat = np.array([10, 11, 10, 11, 10, 11, 10, 11])
volatile = np.array([5, 20, 8, 30, 6, 25, 9, 28])
ss1, _ = INV.safety_stock(flat, 3)
ss2, _ = INV.safety_stock(volatile, 3)
check("波动大→安全库存更高", ss2 > ss1, True)
outlier = np.array([10, 11, 10, 500, 11, 10, 11, 10])
ss3, avg3 = INV.safety_stock(outlier, 3)
check("500大单不拉爆安全库存", ss3 < 20, True)
check("稳健日均接近中位数", 9 < avg3 < 15, True)

print("\n== 规模优化 ==")
import scale
# 造足够多的订单（>20 单），覆盖购物篮的样本门槛
_rng = np.random.default_rng(0)
_items = ["水", "面包", "可乐", "牛奶", "薯片"]
_rows = []
for o in range(30):
    pick = _rng.choice(_items, size=2, replace=False)
    for it in pick:
        _rows.append({"订单号": f"o{o}", "商品": it})
d = pd.DataFrame(_rows)
rules = scale.basket_vectorized(d, "订单号", "商品", min_support=1, top_n=5)
check("向量化购物篮能出结果", rules is not None and len(rules) > 0, True)
dd = pd.DataFrame({"a": np.arange(100, dtype=np.int64), "b": np.arange(100, dtype=np.float64)})
dd2 = scale.downcast(dd)
check("整数列降精度", dd2["a"].dtype in (np.int16, np.int32), True)
check("浮点列降精度", dd2["b"].dtype == np.float32, True)

print("\n" + ("全部通过 ✅" if not FAIL else f"失败 {len(FAIL)} 项 ❌：{FAIL}"))
import sys
sys.exit(0 if not FAIL else 1)
