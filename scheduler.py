# -*- coding: utf-8 -*-
"""
自动跑批、异常预警、订阅推送：让用户不用主动打开也能收到关键结论。

对应第 2 项需求。设计（与现有产品哲学一致——「老板看结论，不主动操作」）：
- 订阅（Subscription）：用户订阅一个 topic（异常预警 / 日报 / 周报），
  指定推送渠道（wecom / email / local）。
- 预警规则（Rule）：声明式的异常条件，跑批时逐条求值，命中就产出结论。
- 结论（Conclusion）：一句话 + 一条动作，格式与简单版「一键复制微信」一致。
- 推送通道（Channel）：先实现 local（写文件/落消息表，可单测），
  预留 wecom/email 接口位——接真实企业微信时只需补一个 adapter。

跑批本身不在这里「定时」——Streamlit 无后台常驻，定时由外部 cron /
Streamlit 的 schedule 或操作系统的计划任务触发，跑批函数是纯函数可被任何调度器调用。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

# 推送渠道：local 落地文件；wecom 走企业微信群机器人；email 预留
CHANNELS = {
    "local": "本地（写入文件/消息表）",
    "wecom": "企业微信群机器人",
    "email": "邮件（预留）",
}


def detect_anomalies(df: pd.DataFrame, metric: str, date_col: str,
                     store_col: str | None = None) -> list[dict]:
    """异常预警规则：环比大幅下滑 / 连续下滑 / 负毛利等，产出结论列表。

    每条结论 = {severity, title, detail, action}，可直接喂给推送。
    """
    if metric not in df.columns or date_col not in df.columns:
        return []
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col])
    d[metric] = pd.to_numeric(d[metric], errors="coerce")
    if d.empty:
        return []

    out = []
    # 按日聚合（如有门店则按门店×日）
    group_cols = [store_col] if (store_col and store_col in d.columns) else []
    daily = d.groupby(group_cols + [d[date_col].dt.date])[metric].sum().reset_index()
    daily = daily.rename(columns={list(daily.columns)[-1]: "销售额"})
    date_key = list(daily.columns)[-2] if group_cols else list(daily.columns)[0]
    # 简化：整体按最近两天环比
    series = d.groupby(d[date_col].dt.date)[metric].sum().sort_index()
    if len(series) < 3:
        return out
    cur = float(series.iloc[-1])
    prev = float(series.iloc[-2])
    scope = f"门店 {d[store_col].iloc[0]}" if (store_col and store_col in d.columns) else "整体"

    if prev > 0:
        chg = (cur - prev) / prev * 100
        if chg <= -20:
            out.append({
                "severity": "高",
                "title": f"{scope}销售额环比大跌 {abs(chg):.0f}%",
                "detail": f"最近一天 {cur:,.0f} vs 前一天 {prev:,.0f}",
                "action": "先查是否缺货/停业/系统漏单，再决定是否补促销。",
            })
        elif chg <= -10:
            out.append({
                "severity": "中",
                "title": f"{scope}销售额环比下滑 {abs(chg):.0f}%",
                "detail": f"最近一天 {cur:,.0f} vs 前一天 {prev:,.0f}",
                "action": "关注连续两天下滑趋势，提前排查。",
            })

    # 连续下滑：最近 3 天逐日下降
    last3 = list(series.values[-3:])
    if len(last3) == 3 and last3[0] > last3[1] > last3[2]:
        out.append({
            "severity": "中",
            "title": f"{scope}连续 3 天下滑",
            "detail": f"{last3[0]:,.0f} → {last3[1]:,.0f} → {last3[2]:,.0f}",
            "action": "连续下滑往往不是偶然，建议当天到店看现场。",
        })
    return out


def build_daily_report(df: pd.DataFrame, metric: str, date_col: str,
                       big_col: str | None = None,
                       store_col: str | None = None) -> str:
    """生成一段可直接转发的经营快报文字（格式对齐 simple_ui 的微信文案）。"""
    if metric not in df.columns or date_col not in df.columns:
        return ""
    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=[date_col])
    if d.empty:
        return ""
    dmax = d[date_col].max()
    cur = d[d[date_col] >= dmax - pd.Timedelta(days=1)]
    rev = float(pd.to_numeric(cur[metric], errors="coerce").sum())
    lines = [f"【{dmax:%m月%d日} 经营快报】", f"· 销售额：{rev:,.0f} 元"]
    if big_col and big_col in d.columns:
        top = cur.groupby(big_col)[metric].sum().sort_values(ascending=False).head(2)
        lines.append("· 卖得最好：" + "、".join(f"{k}({v:,.0f})" for k, v in top.items()))
    if store_col and store_col in d.columns:
        worst = cur.groupby(store_col)[metric].sum().sort_values().head(1)
        lines.append(f"· 最需关注门店：{worst.index[0]}（{worst.values[0]:,.0f}）")
    lines.append("（数据来自自动跑批，口径见工具内说明）")
    return "\n".join(lines)


def render_digest(conclusions: list[dict]) -> str:
    """把一组结论拼成一段可转发的摘要。"""
    if not conclusions:
        return "今日无明显异常。"
    parts = []
    for c in conclusions:
        parts.append(f"[{c['severity']}] {c['title']} —— {c['action']}")
    return "\n".join(parts)


def _load_config() -> dict:
    """加载推送配置（本地 JSON，单机先跑通；上云后换成 DB）。"""
    from pathlib import Path
    import json
    p = Path(__file__).resolve().parent / "data" / "push_config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict):
    from pathlib import Path
    import json
    p = Path(__file__).resolve().parent / "data" / "push_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_wecom_webhook() -> str:
    """读企业微信机器人 webhook 地址；未配置返回空串。"""
    return (_load_config().get("wecom_webhook") or "").strip()


def set_wecom_webhook(url: str):
    """保存企业微信机器人 webhook 地址。"""
    cfg = _load_config()
    cfg["wecom_webhook"] = (url or "").strip()
    _save_config(cfg)


def send_wecom(webhook: str, content: str) -> dict:
    """真正调用企业微信群机器人 webhook 发一条文本消息。

    企业微信机器人接口：POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
    body: {"msgtype":"text","text":{"content":"..."}}
    返回 {'ok': bool, 'msg': str}。
    """
    import json
    import urllib.request
    if not webhook:
        return {"ok": False, "msg": "未配置企业微信机器人地址，无法发送。"}
    payload = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read() or b"{}")
        if resp.get("errcode") == 0:
            return {"ok": True, "msg": "已推送到企业微信群。"}
        return {"ok": False, "msg": f"企业微信返回错误 {resp.get('errcode')}: {resp.get('errmsg')}"}
    except Exception as e:
        return {"ok": False, "msg": f"推送失败：{e}"}


def deliver(channel: str, content: str, target: str = "") -> dict:
    """把内容推送到指定渠道。local 落地文件；wecom 走群机器人；email 预留。

    返回 {'ok': bool, 'msg': str}。
    """
    if channel == "local":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 本地落盘到 output/ 下的通知目录，便于验证与后续接真推送
        from pathlib import Path
        out_dir = Path(__file__).resolve().parent / "output" / "notifications"
        out_dir.mkdir(parents=True, exist_ok=True)
        f = out_dir / f"{ts}_{target or 'all'}.txt"
        f.write_text(content, encoding="utf-8")
        return {"ok": True, "msg": f"已写入本地通知：{f.name}"}
    if channel == "wecom":
        return send_wecom(get_wecom_webhook(), content)
    # email：预留接口位
    return {"ok": False, "msg": f"渠道「{channel}」尚未接入，内容已生成但未发送。"
                                 f"接入时实现一个 adapter 即可。"}
