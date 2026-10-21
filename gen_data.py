# -*- coding: utf-8 -*-
"""
便利店模拟数据生成器
真实使用时：把门店 POS 导出的销售明细按同样列名存成 data/pos.csv，
并手工维护 data/products.csv（含进价、保质期、当前库存），其余脚本不用改。
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)
BASE = Path(__file__).parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

# sku, 名称, 品类, 进价, 售价, 保质期天, 动销热度(1=很慢,10=很快)
PRODUCTS = [
    ("D001", "农夫山泉550ml", "饮料", 1.10, 2.00, 365, 10),
    ("D002", "可口可乐500ml", "饮料", 2.10, 3.50, 270, 9),
    ("D003", "东方树叶500ml", "饮料", 2.80, 5.00, 270, 7),
    ("D004", "元气森林340ml", "饮料", 3.00, 6.00, 270, 6),
    ("D005", "康师傅冰红茶", "饮料", 2.20, 4.00, 270, 7),
    ("D006", "红牛250ml", "饮料", 4.20, 6.50, 540, 4),
    ("D007", "雀巢咖啡罐装", "饮料", 3.60, 6.00, 365, 5),
    ("D008", "美年达600ml", "饮料", 2.00, 3.50, 270, 3),
    ("D009", "矿泉水大瓶1.5L", "饮料", 1.60, 3.00, 365, 5),
    ("D010", "冰露纯净水", "饮料", 0.80, 1.50, 365, 6),

    ("R001", "伊利纯牛奶250ml", "乳品烘焙", 2.00, 3.50, 180, 9),
    ("R002", "蒙牛酸酸乳", "乳品烘焙", 2.30, 4.00, 21, 5),
    ("R003", "光明酸奶100g", "乳品烘焙", 2.40, 4.50, 21, 6),
    ("R004", "达利园面包", "乳品烘焙", 2.60, 4.50, 30, 6),
    ("R005", "桃李吐司切片", "乳品烘焙", 4.80, 8.00, 7, 4),
    ("R006", "三明治(冷藏)", "乳品烘焙", 5.00, 9.00, 2, 6),
    ("R007", "冷藏饭团", "乳品烘焙", 3.40, 6.00, 2, 5),
    ("R008", "安慕希酸奶", "乳品烘焙", 4.50, 7.50, 180, 4),

    ("S001", "乐事薯片原味", "零食", 3.80, 6.50, 180, 7),
    ("S002", "上好佳虾片", "零食", 2.40, 4.00, 180, 2),
    ("S003", "奥利奥饼干", "零食", 3.20, 5.50, 240, 5),
    ("S004", "卫龙辣条", "零食", 1.80, 3.50, 150, 8),
    ("S005", "士力架", "零食", 2.60, 4.50, 240, 6),
    ("S006", "德芙巧克力", "零食", 4.20, 7.00, 300, 4),
    ("S007", "洽洽瓜子", "零食", 3.40, 6.00, 270, 4),
    ("S008", "徐福记沙琪玛", "零食", 2.60, 4.50, 180, 1),
    ("S009", "口香糖", "零食", 1.40, 3.00, 400, 5),
    ("S010", "坚果小包装", "零食", 3.60, 6.50, 240, 3),

    ("F001", "关东煮(单品)", "鲜食", 1.20, 3.00, 1, 9),
    ("F002", "茶叶蛋", "鲜食", 0.80, 2.00, 1, 8),
    ("F003", "包子(肉)", "鲜食", 1.00, 2.50, 1, 8),
    ("F004", "手抓饼", "鲜食", 2.00, 5.00, 1, 4),
    ("F005", "热狗肠", "鲜食", 1.50, 3.50, 3, 6),
    ("F006", "便当(加热)", "鲜食", 6.50, 12.00, 1, 5),
    ("F007", "玉米(热食)", "鲜食", 1.50, 4.00, 1, 4),
    ("F008", "烤肠机香肠", "鲜食", 1.80, 4.00, 2, 7),

    ("M001", "抽纸(小包)", "日用", 3.20, 6.00, 999, 4),
    ("M002", "湿巾", "日用", 2.20, 4.00, 999, 3),
    ("M003", "一次性口罩", "日用", 0.50, 2.00, 999, 5),
    ("M004", "打火机", "日用", 0.60, 2.00, 999, 5),
    ("M005", "充电宝租借券", "日用", 1.00, 3.00, 999, 2),
    ("M006", "洗面奶小样", "日用", 4.00, 8.00, 720, 1),
    ("M007", "雨伞(一次性)", "日用", 4.00, 10.00, 999, 1),
    ("M008", "卫生巾应急包", "日用", 5.00, 10.00, 720, 1),
]

POP = {p[0]: p[6] for p in PRODUCTS}
INFO = {p[0]: p for p in PRODUCTS}

# 真实的连带购买习惯（便利店实际存在的组合）
COMBOS = [
    ("D001", "F001", 0.55), ("D002", "S001", 0.45), ("F001", "F002", 0.60),
    ("R006", "D007", 0.50), ("F003", "R002", 0.35), ("S004", "D001", 0.40),
    ("R001", "R004", 0.30), ("F005", "D005", 0.45), ("S009", "D002", 0.25),
    ("F008", "D009", 0.40), ("R007", "D003", 0.35), ("S005", "D006", 0.30),
]
COMBO_MAP = {}
for a, b, pr in COMBOS:
    COMBO_MAP.setdefault(a, []).append((b, pr))
    COMBO_MAP.setdefault(b, []).append((a, pr))

CAT_WEIGHT = {"饮料": 0.34, "乳品烘焙": 0.20, "零食": 0.26, "鲜食": 0.13, "日用": 0.07}
HOUR_PREF = {
    8: {"乳品烘焙": 2.2, "鲜食": 2.0}, 9: {"乳品烘焙": 1.6, "鲜食": 1.4},
    12: {"鲜食": 2.6, "饮料": 1.6}, 13: {"鲜食": 2.0, "饮料": 1.5},
    18: {"饮料": 1.5, "零食": 1.4, "鲜食": 1.3}, 19: {"饮料": 1.4, "零食": 1.5},
    20: {"零食": 1.6, "饮料": 1.3},
}
HOUR_TRAFFIC = {7: 4, 8: 12, 9: 8, 10: 5, 11: 7, 12: 13, 13: 9, 14: 5, 15: 4,
                16: 5, 17: 8, 18: 12, 19: 11, 20: 9, 21: 7, 22: 4, 23: 2}

start = date(2026, 7, 24)
days = 90
rows = []
order_seq = 0
by_cat = {}
for p in PRODUCTS:
    by_cat.setdefault(p[2], []).append(p)

for d in range(days):
    cur = start + timedelta(days=d)
    is_weekend = cur.weekday() >= 5
    weather = random.choices(["晴", "阴", "雨"], weights=[0.55, 0.28, 0.17])[0]
    base_orders = 250 if is_weekend else 230
    if weather == "雨":
        base_orders = int(base_orders * 0.78)
    elif weather == "晴":
        base_orders = int(base_orders * 1.05)
    n_orders = max(60, int(random.gauss(base_orders, 28)))

    hours = list(HOUR_TRAFFIC.keys())
    hw = [HOUR_TRAFFIC[h] for h in hours]

    for _ in range(n_orders):
        order_seq += 1
        h = random.choices(hours, weights=hw)[0]
        mm = random.randint(0, 59)
        n_items = random.choices([1, 2, 3], weights=[0.45, 0.38, 0.17])[0]

        cats = list(CAT_WEIGHT.keys())
        cw = []
        for c in cats:
            w_c = CAT_WEIGHT[c]
            if weather == "雨" and c == "鲜食":
                w_c *= 1.35
            if h in HOUR_PREF and c in HOUR_PREF[h]:
                w_c *= HOUR_PREF[h][c]
            cw.append(w_c)

        chosen = []
        for _i in range(n_items):
            cat = random.choices(cats, weights=cw)[0]
            pool = [p for p in by_cat[cat] if p[0] not in chosen]
            if not pool:
                continue
            p = random.choices(pool, weights=[POP[x[0]] for x in pool])[0]
            chosen.append(p[0])
            # 连带购买：按概率带上一件搭配商品
            for partner, pr in COMBO_MAP.get(p[0], []):
                if partner not in chosen and random.random() < pr * 0.55:
                    chosen.append(partner)
                    break

        for sku in chosen:
            p = INFO[sku]
            qty = random.choices([1, 2, 3], weights=[0.82, 0.14, 0.04])[0]
            _, name, cat2, cost, price, shelf, _pop = p
            rows.append([f"O{order_seq:07d}", cur.isoformat(), f"{h:02d}:{mm:02d}",
                         "周末" if is_weekend else "工作日", weather,
                         sku, name, cat2, qty, price, round(price * qty, 2), round(cost * qty, 2)])

# ---- 按近期销量反推"当前库存"，让库存水平贴近真实补货周期 ----
CYCLE = {"鲜食": 1.5, "乳品烘焙": 4, "饮料": 12, "零食": 18, "日用": 40}
recent = {}
cut = (start + timedelta(days=days - 14)).isoformat()
for r in rows:
    if r[1] >= cut:
        recent[r[5]] = recent.get(r[5], 0) + r[8]

stock_rows = []
for sku, name, cat, cost, price, shelf, pop in PRODUCTS:
    v = recent.get(sku, 0) / 14
    if cat == "鲜食":
        inv = max(2, round(v * CYCLE[cat] * random.uniform(0.5, 1.0)))
    else:
        inv = max(3, round(v * CYCLE[cat] * random.uniform(0.4, 2.2)))
    stock_rows.append([sku, name, cat, cost, price, shelf, inv])

with open(DATA / "products.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["SKU", "名称", "品类", "进价", "售价", "保质期天", "当前库存"])
    w.writerows(stock_rows)

with open(DATA / "pos.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["订单号", "日期", "时间", "日类型", "天气", "SKU", "名称",
                "品类", "数量", "单价", "金额", "成本"])
    w.writerows(rows)

print(f"已生成 {len(rows)} 条销售明细，覆盖 {days} 天，{len(PRODUCTS)} 个 SKU")
print(f"文件：{DATA / 'pos.csv'} / {DATA / 'products.csv'}")
