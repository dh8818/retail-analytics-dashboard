# -*- coding: utf-8 -*-
"""
启动脚本：启动 Streamlit，并屏蔽「浏览器断开连接」时 Windows 事件循环打印的噪音。

为什么要这个：Windows 用的是 Proactor 事件循环，客户端（浏览器）切走或关闭时，
socket 关闭会抛 ConnectionResetError [WinError 10054]，asyncio 把它当成未处理异常，
打印一整段 Traceback。它不影响运行，但会把日志刷满、看起来像程序崩了。
"""
import sys


def _patch_proactor():
    """吞掉 _call_connection_lost 里的断连异常（仅 Windows 的 proactor 实现存在）。"""
    try:
        from asyncio import proactor_events as pe
    except ImportError:          # 非 Windows 平台没有这个模块
        return
    cls = getattr(pe, "_ProactorBasePipeTransport", None)
    if cls is None:
        return
    orig = getattr(cls, "_call_connection_lost", None)
    if orig is None or getattr(orig, "_quiet_patched", False):
        return

    def _call_connection_lost(self, exc):
        try:
            return orig(self, exc)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            try:
                self._sock = None
            except Exception:
                pass
            return None

    _call_connection_lost._quiet_patched = True
    cls._call_connection_lost = _call_connection_lost


def main():
    _patch_proactor()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", "app.py",
                "--server.port", "8501",
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
