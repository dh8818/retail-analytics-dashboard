# -*- coding: utf-8 -*-
"""
示例连接器：从一个本地 SQLite 数据库（模拟某收银/进销存系统的导库）拉数据。

作用：
- 演示 DataSource 协议怎么实现，作为「接入真实收银系统」的模板。
- 自带一个 seed_demo() 生成一套模拟门店数据，开箱即用、真实可跑。
- 真实系统（银豹/客如云/有赞/科脉）的对接：照着这个类的 fetch 结构，
  把「读本地 SQLite」换成「调对方 HTTP API + 鉴权」即可，协议不变。

支持的增量：fetch(since) 只拉日期 > since 的销售行；库存/会员按全量快照。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from datasources import DataSource, register_source


def seed_demo(path: Path | str, days: int = 60, stores: int = 3, seed: int = 7):
    """生成一套模拟门店数据（销售明细/库存/会员），写入 SQLite。

    这是示例连接器的数据来源，不代表真实门店数据。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    cats = ["饮料", "零食", "鲜食", "乳品", "日用"]
    skus = [f"SKU{i:03d}" for i in range(1, 41)]
    sku_cat = {s: cats[i % len(cats)] for i, s in enumerate(skus)}
    sku_price = {s: round(float(rng.uniform(2, 25)), 1) for s in skus}
    sku_cost = {s: round(sku_price[s] * rng.uniform(0.55, 0.8), 2) for s in skus}
    shelf = {s: (3 if sku_cat[s] == "鲜食" else 15 if sku_cat[s] == "乳品"
                 else 180) for s in skus}

    store_codes = [f"T{1001 + i}" for i in range(stores)]
    store_region = {c: f"区域{i // 2 + 1}" for i, c in enumerate(store_codes)}

    end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sales_rows = []
    for d in range(days):
        day = end - timedelta(days=days - 1 - d)
        for code in store_codes:
            n_orders = int(rng.integers(60, 160))
            for _ in range(n_orders):
                order = f"{code}-{day:%Y%m%d}-{rng.integers(1, 99999):05d}"
                n_items = int(rng.integers(1, 4))
                for _ in range(n_items):
                    s = skus[int(rng.integers(0, len(skus)))]
                    qty = int(rng.integers(1, 3))
                    price = sku_price[s]
                    disc = rng.random() < 0.08
                    unit = round(price * rng.uniform(0.9, 1.0), 1) if disc else price
                    sales_rows.append({
                        "订单号": order,
                        "日期": day.strftime("%Y-%m-%d"),
                        "时间": f"{rng.integers(6, 23):02d}:{rng.integers(0, 59):02d}",
                        "SKU": s, "名称": s, "品类": sku_cat[s],
                        "数量": qty, "单价": unit, "金额": round(unit * qty, 2),
                        "成本": round(sku_cost[s] * qty, 2),
                        "会员编号": f"M{rng.integers(1, 500):04d}" if rng.random() < 0.4 else None,
                        "门店编码": code,
                    })
    sales = pd.DataFrame(sales_rows)

    inv_rows = []
    for code in store_codes:
        for s in skus:
            inv_rows.append({
                "SKU": s, "名称": s, "品类": sku_cat[s],
                "期末库存": int(rng.integers(0, 200)),
                "在途": int(rng.integers(0, 20)),
                "保质期天": shelf[s], "单位成本": sku_cost[s],
                "门店编码": code, "日期": end.strftime("%Y-%m-%d"),
            })
    inventory = pd.DataFrame(inv_rows)

    mem_rows = []
    for code in store_codes:
        for i in range(1, 501):
            mem_rows.append({
                "会员编号": f"M{i:04d}", "最近购买": end.strftime("%Y-%m-%d"),
                "购买频次": int(rng.integers(1, 30)), "累计金额": round(float(rng.uniform(10, 3000)), 2),
                "门店编码": code,
            })
    members = pd.DataFrame(mem_rows)

    con = sqlite3.connect(str(path))
    sales.to_sql("sales", con, if_exists="replace", index=False)
    inventory.to_sql("inventory", con, if_exists="replace", index=False)
    members.to_sql("members", con, if_exists="replace", index=False)
    con.close()
    return {"sales": len(sales), "inventory": len(inventory), "members": len(members)}


@register_source
class SqlitePOSSource(DataSource):
    key = "sqlite_pos"
    label = "SQLite 收银导库（示例连接器）"

    def fetch(self, since: str | None = None) -> dict[str, pd.DataFrame | None]:
        db = self.config.get("path") or str(Path(__file__).resolve().parent / "data" / "demo_pos.db")
        con = sqlite3.connect(db)

        sales = pd.read_sql_query(
            "SELECT * FROM sales WHERE 日期 > ? ORDER BY 日期",
            con, params=[since or "0000-00-00"])
        inventory = pd.read_sql_query("SELECT * FROM inventory", con)
        members = pd.read_sql_query("SELECT * FROM members", con)
        con.close()

        return self.normalize({
            "sales": sales,
            "inventory": inventory,
            "members": members,
        })
