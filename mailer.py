# -*- coding: utf-8 -*-
"""
邮件发送：把分析结果 / 数据直接发到用户的邮箱。

用 SMTP（用户自己的发件邮箱 + 授权码），不依赖任何第三方平台、换电脑也能用。
支持常见邮箱：QQ、163、126、Gmail 等（只需在邮箱设置里开 SMTP 拿授权码）。

- 授权码不是登录密码：QQ 邮箱在「设置→账户→POP3/SMTP 服务→生成授权码」；
  163/126 在「设置→POP3/SMTP/IMAP→开启→客户端授权密码」。
- 配置存在本地 data/mail_config.json，只存发件人自己填的信息，不涉及任何隐私外发。

设计：纯函数 send_mail(...)，Streamlit 里调用；配置读写与 scheduler 的 push_config 同风格。
"""
from __future__ import annotations

import json
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

# 常见邮箱的 SMTP 服务器与端口（用户选邮箱类型时自动填）
SMTP_SERVERS = {
    "QQ 邮箱": ("smtp.qq.com", 465),
    "163 邮箱": ("smtp.163.com", 465),
    "126 邮箱": ("smtp.126.com", 465),
    "Gmail": ("smtp.gmail.com", 465),
    "Outlook": ("smtp.office365.com", 587),
    "其他（手动填）": ("", 465),
}


def _cfg_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "mail_config.json"


def _load() -> dict:
    p = _cfg_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(cfg: dict):
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def save_config(sender, auth_code, smtp_host, smtp_port, use_ssl=True):
    cfg = _load()
    cfg.update({"sender": sender, "auth_code": auth_code,
                "smtp_host": smtp_host, "smtp_port": int(smtp_port or 465),
                "use_ssl": bool(use_ssl)})
    _save(cfg)
    return cfg


def get_config() -> dict:
    return _load()


def send_mail(sender, auth_code, to, subject, body, smtp_host, smtp_port,
              use_ssl=True, attachments=None, body_html=False):
    """发送一封邮件，可带附件。

    attachments: list[(文件名, bytes, MIME类型)]，例如 [("结果.csv", b"...", "text/csv")]。
    返回 (ok: bool, msg: str)。
    """
    if not all([sender, auth_code, to, smtp_host]):
        return False, "发件邮箱、授权码、收件邮箱、SMTP 服务器都不能为空"
    try:
        msg = MIMEMultipart()
        msg["From"] = formataddr(("经营分析", sender))
        msg["To"] = to
        msg["Subject"] = subject
        # 正文：默认纯文本，body_html=True 时用 HTML
        if body_html:
            msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            msg.attach(MIMEText(body, "plain", "utf-8"))

        for fn, data, mime in (attachments or []):
            part = MIMEApplication(data, Name=fn)
            part["Content-Disposition"] = f'attachment; filename="{fn}"'
            msg.attach(part)

        if use_ssl:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(smtp_host, int(smtp_port), timeout=20, context=context)
        else:
            server = smtplib.SMTP(smtp_host, int(smtp_port), timeout=20)
            server.starttls(context=ssl.create_default_context())
        server.login(sender, auth_code)
        server.sendmail(sender, [to], msg.as_string())
        server.quit()
        return True, f"已发送到 {to}"
    except smtplib.SMTPAuthenticationError:
        return False, "授权码或账号不对（授权码不是登录密码，需在邮箱设置里生成）"
    except Exception as e:
        return False, f"发送失败：{e}"


def smtp_for(kind: str):
    """按邮箱类型返回 (host, port)。"""
    return SMTP_SERVERS.get(kind, ("", 465))
