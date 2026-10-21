# -*- coding: utf-8 -*-
"""
便利店经营分析看板（Power BI 风格单文件 HTML）
用法：python build.py
输出：output/便利店经营看板.html —— 双击即可在浏览器打开，无需联网
"""
import math
from itertools import combinations
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

BASE = Path(__file__).parent
DATA = BASE / "data"
OUT = BASE / "output"
OUT.mkdir(exist_ok=True)

# ---------------- Power BI 配色 ----------------
BI_BLUE, BI_NAVY = "#118DFF", "#12239E"
PALETTE = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7",
           "#744EC2", "#D9B300", "#D64550"]
CARD_BG, PAGE_BG, TEXT, MUTED, GRID = "#FFFFFF", "#F3F2F1", "#252423", "#605E5C", "#EDEBE9"
FONT = "Segoe UI, Microsoft YaHei, sans-serif"

# ---------------- 数据 ----------------
pos = pd.read_csv(DATA / "pos.csv", encoding="utf-8-sig")
prod = pd.read_csv(DATA / "products.csv", encoding="utf-8-sig")
pos["日期"] = pd.to_datetime(pos["日期"])
pos["小时"] = pos["时间"].str.slice(0, 2).astype(int)
pos["星期"] = pos["日期"].dt.dayofweek.map(
    {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"})
pos["毛利"] = pos["金额"] - pos["成本"]

D_START, D_END = pos["日期"].min(), pos["日期"].max()
SPAN = (D_END - D_START).days + 1

# ---------------- 核心指标 ----------------
sales = pos["金额"].sum()
cost = pos["成本"].sum()
profit = sales - cost
orders = pos["订单号"].nunique()
items = pos["数量"].sum()
aov = sales / orders
margin = profit / sales
daily_avg = sales / SPAN

# 同比环比的替代：最近 7 天 vs 前 7 天（没有跨年数据，用周环比更诚实）
last7 = pos[pos["日期"] > D_END - pd.Timedelta(days=7)]["金额"].sum()
prev7 = pos[(pos["日期"] <= D_END - pd.Timedelta(days=7)) &
            (pos["日期"] > D_END - pd.Timedelta(days=14))]["金额"].sum()
wow = (last7 - prev7) / prev7 * 100 if prev7 else 0.0


def fig_base(fig, height=300, title=None):
    fig.update_layout(
        height=height,
        margin=dict(l=16, r=16, t=48 if title else 22, b=16),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(family=FONT, size=12, color=TEXT),
        title=dict(text=title, font=dict(size=14, color=MUTED), x=0.02, y=0.96) if title else None,
        hoverlabel=dict(bgcolor="white", font_size=12, font_family=FONT),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID,
                     tickfont=dict(color=MUTED, size=11))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED, size=11))
    return fig


# 1) 日销售额趋势 + 7日均线
daily = pos.groupby("日期")["金额"].sum().reset_index()
daily["7日均线"] = daily["金额"].rolling(7, min_periods=1).mean()

f_trend = go.Figure()
f_trend.add_trace(go.Scatter(x=daily["日期"], y=daily["金额"], name="日销售额",
                             mode="lines", line=dict(color=BI_BLUE, width=1.2),
                             fill="tozeroy", fillcolor="rgba(17,141,255,0.10)"))
f_trend.add_trace(go.Scatter(x=daily["日期"], y=daily["7日均线"], name="7日均线",
                             mode="lines", line=dict(color="#E66C37", width=2.6, dash="solid")))
fig_base(f_trend, 320, f"日销售额与 7 日均线（{D_START:%m-%d} ~ {D_END:%m-%d}）")
f_trend.update_layout(showlegend=True,
                      legend=dict(orientation="h", y=1.06, x=1, xanchor="right",
                                  font=dict(size=11, color=MUTED)))

# 2) 品类销售额占比（环形）
cat = pos.groupby("品类").agg(销售额=("金额", "sum"), 毛利=("毛利", "sum")).reset_index()
cat = cat.sort_values("销售额", ascending=False)
cat["占比"] = cat["销售额"] / cat["销售额"].sum()
f_cat = go.Figure(go.Pie(labels=cat["品类"], values=cat["销售额"], hole=0.62,
                         marker=dict(colors=PALETTE, line=dict(color="white", width=2)),
                         textinfo="label+percent", textfont=dict(size=11),
                         hovertemplate="%{label}<br>销售额 ¥%{value:,.0f}<br>占比 %{percent}<extra></extra>"))
f_cat.add_annotation(text=f"¥{cat['销售额'].sum()/10000:.1f}万<br><span style='font-size:11px;color:{MUTED}'>总销售额</span>",
                     showarrow=False, font=dict(size=17, color=TEXT))
fig_base(f_cat, 320, "品类销售额结构")
f_cat.update_layout(showlegend=True,
                    legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center", font=dict(size=11)))

# 3) 星期 × 小时 销售热力图
pivot = pos.pivot_table(index="星期", columns="小时", values="金额", aggfunc="sum").fillna(0)
week_order = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
pivot = pivot.reindex([w for w in week_order if w in pivot.index])
f_heat = go.Figure(go.Heatmap(z=pivot.values, x=[f"{h}时" for h in pivot.columns], y=pivot.index,
                              colorscale=[[0, "#F3F9FF"], [0.35, "#9CC9FF"],
                                          [0.7, "#118DFF"], [1, "#12239E"]],
                              hovertemplate="%{y} %{x}<br>销售额 ¥%{z:,.0f}<extra></extra>",
                              colorbar=dict(thickness=8, len=0.8, tickfont=dict(size=10, color=MUTED))))
f_heat.update_xaxes(showgrid=False)
fig_base(f_heat, 320, "销售高峰热力图（星期 × 时段）")

# 4) SKU ABC 帕累托
sku = pos.groupby(["SKU", "名称"])["金额"].sum().reset_index().sort_values("金额", ascending=False)
sku["累计占比"] = sku["金额"].cumsum() / sku["金额"].sum()
sku["等级"] = sku["累计占比"].apply(lambda x: "A" if x <= 0.7 else ("B" if x <= 0.9 else "C"))
top = sku.head(18)
f_abc = go.Figure()
color_map = {"A": BI_BLUE, "B": "#744EC2", "C": "#C8C6C4"}
f_abc.add_trace(go.Bar(x=top["名称"], y=top["金额"], name="销售额",
                       marker=dict(color=[color_map[c] for c in top["等级"]]),
                       hovertemplate="%{x}<br>销售额 ¥%{y:,.0f}<extra></extra>"))
f_abc.add_trace(go.Scatter(x=top["名称"], y=top["累计占比"] * 100, name="累计占比",
                           mode="lines+markers", yaxis="y2",
                           line=dict(color="#E66C37", width=2.2), marker=dict(size=4)))
f_abc.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105],
                                showgrid=False, ticksuffix="%",
                                tickfont=dict(size=11, color=MUTED)),
                    showlegend=True, legend=dict(orientation="h", y=1.08, x=1, xanchor="right",
                                                 font=dict(size=11)))
fig_base(f_abc, 340, "SKU 帕累托（A 类贡献 70% 销售额）")
f_abc.update_xaxes(tickangle=-38, tickfont=dict(size=9.5))

# 5) 关联购买 Top 10
basket = pos.groupby("订单号")["名称"].apply(lambda s: sorted(set(s)))
pair_count = {}
for items_list in basket:
    for a, b in combinations(items_list, 2):
        pair_count[(a, b)] = pair_count.get((a, b), 0) + 1
single_count = pos.groupby("名称")["订单号"].nunique().to_dict()
n_basket = basket.shape[0]
pairs = []
for (a, b), c in pair_count.items():
    if c < 10:
        continue
    conf_ab = c / single_count[a]
    support = c / n_basket
    lift = conf_ab / (single_count[b] / n_basket)
    pairs.append((f"{a} + {b}", support, conf_ab, lift))
pairs = sorted(pairs, key=lambda x: -x[3])[:10]
f_pair = go.Figure(go.Bar(
    x=[p[3] for p in pairs], y=[p[0] for p in pairs], orientation="h",
    marker=dict(color=BI_BLUE),
    text=[f"{p[3]:.1f}×" for p in pairs],
    textposition="outside", textfont=dict(size=10, color=MUTED),
    hovertemplate="%{y}<br>提升度 %{x:.2f}<extra></extra>"))
f_pair.update_yaxes(autorange="reversed")
fig_base(f_pair, 340, "关联购买 Top 10（可用于套餐与陈列）")
f_pair.update_xaxes(showgrid=True, gridcolor=GRID, range=[0, max([p[3] for p in pairs]) * 1.45])

# 6) 风险清单：滞销 / 临期
recent14 = pos[pos["日期"] > D_END - pd.Timedelta(days=14)].groupby("SKU")["数量"].sum()
recent7_q = pos[pos["日期"] > D_END - pd.Timedelta(days=7)].groupby("SKU")["数量"].sum()
risk_rows = []
for _, r in prod.iterrows():
    q14 = recent14.get(r["SKU"], 0)
    v7 = recent7_q.get(r["SKU"], 0) / 7
    sell_days = r["当前库存"] / v7 if v7 > 0 else 999
    if q14 == 0:
        risk_rows.append(["滞销", r["SKU"], r["名称"], r["品类"], r["当前库存"], 0.0,
                          "14 天零动销", f"下架或做 ¥{max(1, r['进价']):.1f} 清仓"])
    elif r["保质期天"] <= 21 and sell_days > r["保质期天"] * (1.0 if r["保质期天"] >= 4 else 1.6):
        risk_rows.append(["临期", r["SKU"], r["名称"], r["品类"], r["当前库存"], round(v7, 1),
                          f"可售 {sell_days:.1f} 天 > 保质期 {int(r['保质期天'])} 天",
                          "今日起打折或调整订货量"])
    elif sell_days > 45:
        risk_rows.append(["积压", r["SKU"], r["名称"], r["品类"], r["当前库存"], round(v7, 1),
                          f"可售 {sell_days:.0f} 天", "暂停补货，优先陈列"])
risk = pd.DataFrame(risk_rows, columns=["类型", "SKU", "名称", "品类", "库存", "日均", "判断依据", "建议"])
risk = risk.sort_values("库存", ascending=False).head(10)

# 7) 补货建议
reco = []
for _, r in prod.iterrows():
    v7 = recent7_q.get(r["SKU"], 0) / 7
    target = v7 * 7 * 1.15
    need = math.ceil(max(0, target - r["当前库存"]))
    if need <= 0 or v7 < 0.2:
        continue
    reco.append([r["名称"], r["品类"], round(v7, 1), int(r["当前库存"]),
                 int(round(target)), need, round(need * r["进价"], 2)])
reco = pd.DataFrame(reco, columns=["商品", "品类", "近7日日均", "当前库存", "目标库存", "建议补货", "占用资金"])
reco = reco.sort_values("建议补货", ascending=False).head(12)


def kpi_card(label, value, sub="", color=TEXT):
    return f"""<div class="kpi">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value" style="color:{color}">{value}</div>
      <div class="kpi-sub">{sub}</div>
    </div>"""


def table_html(df, badge_col=None):
    head = "".join(f"<th>{c}</th>" for c in df.columns)
    body = ""
    for _, row in df.iterrows():
        tds = ""
        for i, c in enumerate(df.columns):
            v = row[c]
            if badge_col and c == badge_col:
                cls = {"滞销": "b-red", "临期": "b-orange", "积压": "b-yellow"}.get(str(v), "b-blue")
                tds += f'<td><span class="badge {cls}">{v}</span></td>'
            elif isinstance(v, float):
                tds += f"<td class='num'>{v:,.1f}</td>"
            elif isinstance(v, int):
                tds += f"<td class='num'>{v:,}</td>"
            else:
                tds += f"<td>{v}</td>"
        body += f"<tr>{tds}</tr>"
    return f'<table class="bi-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def chart(fig, cls="c6"):
    body = pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config=dict(displayModeBar=False))
    return f'<div class="card {cls}">{body}</div>'


html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>便利店经营分析看板</title>
<script>{get_plotlyjs()}</script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:{PAGE_BG}; font-family:{FONT}; color:{TEXT}; }}
  .topbar {{ background:#fff; padding:14px 22px; display:flex; align-items:center;
            justify-content:space-between; box-shadow:0 1.6px 3.6px rgba(0,0,0,.10); }}
  .topbar h1 {{ font-size:17px; margin:0; font-weight:600; letter-spacing:.2px; }}
  .topbar .meta {{ font-size:12px; color:{MUTED}; }}
  .dot {{ width:9px; height:9px; border-radius:50%; background:{BI_BLUE};
         display:inline-block; margin-right:8px; }}
  .wrap {{ padding:16px 18px 40px; max-width:1500px; margin:0 auto; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:12px; }}
  .kpi {{ background:{CARD_BG}; border-radius:8px; padding:14px 16px;
         box-shadow:0 1.6px 3.6px rgba(0,0,0,.10), 0 0 2px rgba(0,0,0,.06); }}
  .kpi-label {{ font-size:12px; color:{MUTED}; margin-bottom:6px; }}
  .kpi-value {{ font-size:26px; font-weight:600; line-height:1.15; }}
  .kpi-sub {{ font-size:11px; color:{MUTED}; margin-top:6px; }}
  .grid {{ display:grid; grid-template-columns:repeat(12,1fr); gap:12px; margin-top:12px; }}
  .card {{ background:{CARD_BG}; border-radius:8px; padding:10px 12px;
          box-shadow:0 1.6px 3.6px rgba(0,0,0,.10), 0 0 2px rgba(0,0,0,.06); min-width:0; }}
  .c8 {{ grid-column:span 8; }} .c6 {{ grid-column:span 6; }}
  .c4 {{ grid-column:span 4; }} .c12 {{ grid-column:span 12; }}
  .card-title {{ font-size:13px; font-weight:600; color:{TEXT}; margin:4px 4px 10px; }}
  .bi-table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  .bi-table th {{ text-align:left; color:{MUTED}; font-weight:600; font-size:11.5px;
                 padding:8px 8px; border-bottom:1px solid {GRID}; white-space:nowrap; }}
  .bi-table td {{ padding:7px 8px; border-bottom:1px solid #F7F6F5; }}
  .bi-table td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .bi-table tr:hover td {{ background:#F8FBFF; }}
  .badge {{ display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; }}
  .b-red {{ background:#FDE7E9; color:#A4262C; }}
  .b-orange {{ background:#FEE9E1; color:#8A3707; }}
  .b-yellow {{ background:#FFF4CE; color:#6A5400; }}
  .b-blue {{ background:#EAF3FF; color:#0B5CAB; }}
  @media (max-width:900px) {{ .c8,.c6,.c4 {{ grid-column:span 12; }} }}
  .foot {{ text-align:center; color:{MUTED}; font-size:11px; margin-top:22px; }}
</style></head>
<body>
<div class="topbar">
  <h1><span class="dot"></span>门店经营分析看板 · 便利店</h1>
  <div class="meta">数据范围 {D_START:%Y-%m-%d} ~ {D_END:%Y-%m-%d} ｜ {SPAN} 天 ｜ {orders:,} 单 ｜ {items:,} 件</div>
</div>
<div class="wrap">
  <div class="kpis">
    {kpi_card("总销售额", f"¥{sales/10000:.2f}万", f"日均 ¥{daily_avg:,.0f}")}
    {kpi_card("毛利额", f"¥{profit/10000:.2f}万", f"毛利率 {margin*100:.1f}%", "#107C10")}
    {kpi_card("订单数", f"{orders:,}", f"件单价 ¥{sales/items:.2f}")}
    {kpi_card("客单价", f"¥{aov:.2f}", "行业参考 8~12 元")}
    {kpi_card("周环比", f"{wow:+.1f}%", f"近7天 ¥{last7/10000:.2f}万",
              "#107C10" if wow >= 0 else "#A4262C")}
    {kpi_card("在售 SKU", f"{prod.shape[0]}", f"A 类 {int((sku['等级']=='A').sum())} 个贡献 70%")}
  </div>

  <div class="grid">
    {chart(f_trend, "c8")}
    {chart(f_cat, "c4")}
    {chart(f_heat, "c6")}
    {chart(f_abc, "c6")}
    {chart(f_pair, "c6")}
    <div class="card c6">
      <div class="card-title">风险清单：滞销 / 临期 / 积压（当前库存视角）</div>
      {table_html(risk, badge_col="类型")}
    </div>
    <div class="card c12">
      <div class="card-title">未来 7 天补货建议（近 7 日日均 × 7 天 × 1.15 安全系数 − 当前库存）</div>
      {table_html(reco)}
    </div>
  </div>
  <div class="foot">模拟数据演示 ｜ 换成门店真实 POS 明细后，指标、图表、建议全部自动重算</div>
</div>
</body></html>"""

out_file = OUT / "便利店经营看板.html"
out_file.write_text(html, encoding="utf-8")
print(f"看板已生成：{out_file}")
print(f"销售额 ¥{sales:,.0f} ｜ 毛利 ¥{profit:,.0f}（{margin*100:.1f}%）｜ 订单 {orders:,} ｜ 客单价 ¥{aov:.2f}")
print(f"风险条目 {len(risk)} 条 ｜ 补货建议 {len(reco)} 条 ｜ 关联规则 {len(pairs)} 条")
