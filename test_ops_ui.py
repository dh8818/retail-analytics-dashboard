# -*- coding: utf-8 -*-
"""用 Streamlit AppTest 跑主应用：确认「经营诊断」真的渲染，且未影响其他模块。"""
import sys
import traceback

from streamlit.testing.v1 import AppTest


def blocks(at):
    md = [str(m.value) for m in at.markdown]
    html = [str(h.value) for h in getattr(at, "html", [])]
    return md + html


def check(label, state, must=(), forbid=()):
    at = AppTest.from_file("app.py", default_timeout=180)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    errs = list(at.exception)
    texts = blocks(at)
    blob = "\n".join(texts)
    missing = [m for m in must if m not in blob]
    bad = [f for f in forbid if f in blob]
    print(f"[{label}] 异常={len(errs)} 缺失={missing} 不应出现={bad} "
          f"markdown={len(texts)} tabs={len(at.tabs)}")
    for e in errs[:3]:
        print("  !", e.message)
        if e.stack_trace:
            print("   ", e.stack_trace[-1][:500])
    return not errs and not missing and not bad


if __name__ == "__main__":
    base = {"_demo": True, "view_mode": "专业分析（完整）"}
    ok = []
    try:
        at = check("经营诊断", {**base, "sec_pick": "经营诊断"},
                   must=["诊断结论", "行动清单", "判断路径", "六道门槛"])
        ok.append(at is not None)
        ok.append(check("概览", {**base, "sec_pick": "概览"}, must=["业务总结"]))
        ok.append(check("经营", {**base, "sec_pick": "经营"}, must=[]))
        ok.append(check("库存订货", {**base, "sec_pick": "库存订货"}, must=[]))
        ok.append(check("数据清洗", {**base, "sec_pick": "数据清洗"}, must=[]))
        ok.append(check("老板视角", {**base, "view_mode": "老板视角（简单）"}, must=[]))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
    print("RESULT:", "PASS" if all(ok) else "FAIL", ok)
    sys.exit(0 if all(ok) else 1)
