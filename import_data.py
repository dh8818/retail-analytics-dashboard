# -*- coding: utf-8 -*-
"""
把门店真实数据导成看板能用的格式。

用法：
1. 把 POS 导出的 Excel（或 CSV）丢进 data/ 目录，文件名随便，比如 data/原始数据.xlsx
2. 双击运行本脚本（或命令行 python import_data.py）
3. 再双击 一键运行.bat，看板就换成你的真实数据了

脚本会自动认列名（常见叫法都能认出来），认不出来的会明确提示你，
不会静默算错。原有 data/pos.csv 会备份成 pos.csv.bak。
"""
import shutil
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
DATA = BASE / "data"

# 目标列 -> 常见别名（小写、去空格后做包含匹配）
ALIASES = {
    "订单号": ["订单号", "单号", "销售单号", "小票号", "流水号", "交易号", "票据号",
               "orderid", "orderno", "billno", "ticket"],
    "日期": ["日期", "交易日期", "销售日期", "发生日期", "业务日期", "date", "riqi"],
    "时间": ["时间", "交易时间", "销售时间", "时分", "时刻", "time", "shijian"],
    "SKU": ["sku", "商品编码", "商品代码", "货号", "条码", "编码", "商品编号",
            "barcode", "itemcode", "productcode"],
    "名称": ["名称", "商品名称", "品名", "商品", "货品名称", "productname", "itemname"],
    "品类": ["品类", "分类", "类别", "商品类别", "大类", "中类", "category", "class"],
    "数量": ["数量", "销量", "销售数量", "件数", "个数", "qty", "quantity", "num"],
    "单价": ["单价", "售价", "零售价", "价格", "销售价", "price", "unitprice"],
    "金额": ["金额", "销售额", "小计", "实收", "应收", "合计", "成交金额",
             "amount", "total", "sales"],
    "成本": ["成本", "进价", "成本额", "进货价", "成本价", "cost"],
    "日类型": ["日类型", "工作日", "是否周末", "daytype"],
    "天气": ["天气", "weather"],
}
REQUIRED = ["订单号", "日期", "SKU", "数量", "金额"]


def norm(s):
    return str(s).strip().lower().replace(" ", "").replace("　", "").replace("(", "（").replace(")", "）")


def match_columns(cols):
    """返回 {目标列: 原始列名}，按优先级从精确到模糊匹配，一个原始列只用一次。"""
    mapping, used = {}, set()
    normed = {c: norm(c) for c in cols}
    # 第一轮：精确匹配
    for target, keys in ALIASES.items():
        for c in cols:
            if c in used:
                continue
            if normed[c] in keys:
                mapping[target] = c
                used.add(c)
                break
    # 第二轮：包含匹配（长的别名优先，避免"金额"抢走"成本金额"）
    for target, keys in ALIASES.items():
        if target in mapping:
            continue
        for k in sorted(keys, key=len, reverse=True):
            hit = None
            for c in cols:
                if c in used:
                    continue
                if k in normed[c]:
                    hit = c
                    break
            if hit:
                mapping[target] = hit
                used.add(hit)
                break
    return mapping


def find_source():
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            return p
        print(f"找不到文件：{p}")
        sys.exit(1)
    files = [f for f in DATA.glob("*")
             if f.suffix.lower() in (".xlsx", ".xls", ".csv")
             and f.name not in ("pos.csv", "products.csv")
             and not f.name.endswith(".bak")]
    if not files:
        print("data/ 里没找到原始数据文件。请把 POS 导出的 Excel 放进 data/ 目录再运行。")
        print("例如：data/原始数据.xlsx")
        sys.exit(1)
    return max(files, key=lambda f: f.stat().st_mtime)


def main():
    src = find_source()
    print(f"读取：{src.name}")
    if src.suffix.lower() == ".csv":
        raw = None
        for enc in ("utf-8-sig", "gbk", "utf-8"):
            try:
                raw = pd.read_csv(src, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if raw is None:
            print("CSV 编码认不出来，请用 Excel 另存为 utf-8 再试。")
            sys.exit(1)
    else:
        raw = pd.read_excel(src)

    raw.columns = [str(c).strip() for c in raw.columns]
    print(f"共 {len(raw):,} 行，{len(raw.columns)} 列：{list(raw.columns)}")

    m = match_columns(raw.columns)
    missing = [c for c in REQUIRED if c not in m]
    if missing:
        print(f"\n❌ 缺少必需的列：{missing}")
        print(f"   认出来的列：{m}")
        print("   解决办法：在 Excel 里把对应列改名为标准名，或打开 import_data.py 在 ALIASES 里加一个别名。")
        sys.exit(1)

    df = pd.DataFrame()
    for target in ["订单号", "日期", "时间", "SKU", "名称", "品类", "数量", "单价", "金额", "成本", "日类型", "天气"]:
        df[target] = raw[m[target]] if target in m else pd.NA

    # ---- 类型清洗 ----
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    bad_date = df["日期"].isna().sum()
    if bad_date:
        print(f"⚠ 有 {bad_date} 行日期解析失败，已丢弃")
        df = df[df["日期"].notna()]

    for c in ("数量", "单价", "金额", "成本"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace("¥", "").str.replace(",", ""),
                              errors="coerce")

    # 时间：从任意写法里抽出 HH:MM（兼容 "12:35"、"2026-09-01 12:35:00"）
    hhmm = df["时间"].astype(str).str.extract(r"(\d{1,2}:\d{2})")[0]
    lost = int(hhmm.isna().sum() - df["时间"].isna().sum())
    df["时间"] = hhmm.fillna("00:00")
    if lost > 0:
        print(f"⚠ 有 {lost} 行没能识别出时间，已记为 00:00（时段热力图会受影响）")

    # 订单号缺失：退化处理，并警告
    if df["订单号"].isna().all():
        df["订单号"] = [f"R{i:07d}" for i in range(len(df))]
        print("⚠ 没有订单号列：每行当成一单，关联购买分析会失真")

    df["数量"] = df["数量"].fillna(1).clip(lower=1)
    if df["金额"].isna().all() and df["单价"].notna().any():
        df["金额"] = df["数量"] * df["单价"]
        print("· 金额缺失，已按 数量×单价 计算")

    # 用商品主数据补 名称/品类/成本
    pk = DATA / "products.csv"
    if pk.exists():
        prod = pd.read_csv(pk, encoding="utf-8-sig")
        p_map = prod.set_index("SKU")
        df["SKU"] = df["SKU"].astype(str).str.strip()
        p_map.index = p_map.index.astype(str).str.strip()

        fill_name = df["名称"].isna() | (df["名称"].astype(str).str.strip() == "")
        fill_cat = df["品类"].isna() | (df["品类"].astype(str).str.strip() == "")
        if fill_name.any() or fill_cat.any():
            df.loc[fill_name, "名称"] = df.loc[fill_name, "SKU"].map(p_map["名称"])
            df.loc[fill_cat, "品类"] = df.loc[fill_cat, "SKU"].map(p_map["品类"])
            print("· 名称/品类缺失部分已从 products.csv 补齐")

        if df["成本"].isna().all() or (df["成本"].notna().sum() < len(df) * 0.5):
            df["成本"] = df["数量"] * df["SKU"].map(p_map["进价"])
            print("· 成本缺失，已按 products.csv 的进价×数量 计算（务必核对进价表）")

    df["品类"] = df["品类"].fillna("未分类")
    df["名称"] = df["名称"].fillna(df["SKU"])
    df["单价"] = df["单价"].fillna(df["金额"] / df["数量"])
    df["成本"] = df["成本"].fillna(0)
    df["日类型"] = df["日类型"].fillna(
        df["日期"].dt.weekday.map(lambda x: "周末" if x >= 5 else "工作日"))
    df["天气"] = df["天气"].fillna("未知")

    df = df.dropna(subset=["SKU", "金额"])
    out = df[["订单号", "日期", "时间", "日类型", "天气", "SKU", "名称",
              "品类", "数量", "单价", "金额", "成本"]].copy()
    out["日期"] = out["日期"].dt.strftime("%Y-%m-%d")
    out["时间"] = out["时间"].fillna("00:00")
    out["订单号"] = out["订单号"].astype(str)
    for c in ("单价", "金额", "成本"):
        out[c] = out[c].round(2)
    out["数量"] = out["数量"].astype(int)

    target = DATA / "pos.csv"
    if target.exists():
        shutil.copy(target, DATA / "pos.csv.bak")
        print(f"· 旧文件已备份为 data/pos.csv.bak")

    out.to_csv(target, index=False, encoding="utf-8-sig")

    print("\n✅ 导入完成")
    print(f"   行数：{len(out):,} ｜ 订单数：{out['订单号'].nunique():,} ｜ SKU 数：{out['SKU'].nunique()}")
    print(f"   日期范围：{out['日期'].min()} ~ {out['日期'].max()}")
    print(f"   销售额：¥{out['金额'].sum():,.0f} ｜ 成本：¥{out['成本'].sum():,.0f}")
    if out["成本"].sum() == 0:
        print("   ⚠ 成本全是 0，毛利率会显示 100%，请检查 products.csv 的进价列")
    print(f"   输出：{target}")
    print("\n下一步：双击 一键运行.bat 重新生成看板")
    unmapped = [c for c in raw.columns if c not in m.values()]
    if unmapped:
        print(f"\n（这些列没被用到，不影响：{unmapped}）")


if __name__ == "__main__":
    main()
