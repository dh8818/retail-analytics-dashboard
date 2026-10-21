# -*- coding: utf-8 -*-
"""
改完代码跑一下这个：自动提交 + 推送到 GitHub，Streamlit Cloud 会自动重新部署。

    python push_update.py                # 用默认提交信息
    python push_update.py "改了配色"     # 自定义提交信息
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GH = Path("D:/tools/gh/bin/gh.exe")


def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True)
    raw = p.stdout + p.stderr
    for enc in ("utf-8", "gbk"):
        try:
            return p.returncode, raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return p.returncode, raw.decode("utf-8", "ignore").strip()


def main():
    msg = " ".join(sys.argv[1:]).strip() or f"update: {datetime.now():%Y-%m-%d %H:%M}"

    code, out = run(["git", "status", "--porcelain"])
    if code != 0:
        print("✗ 这里不是 git 仓库，或者 git 不可用：\n" + out)
        return 1

    if not out.strip():
        print("没有改动，不用推。")
        return 0

    print("准备提交这些改动：")
    for line in out.strip().splitlines()[:20]:
        print("  " + line)

    run(["git", "add", "-A"])
    code, out = run(["git", "commit", "-m", msg])
    if code != 0:
        print("✗ 提交失败：\n" + out)
        return 1
    print("✓ 已提交：" + msg)

    code, out = run(["git", "push", "origin", "master"])
    if code != 0:
        code2, out2 = run(["git", "push", "origin", "HEAD"])
        if code2 != 0:
            print("✗ 推送失败：\n" + out + "\n" + out2)
            print("  检查：网络/代理是否正常，gh 是否还登录着（gh auth status）")
            return 1
        out = out2

    print("✓ 已推送到 GitHub")
    if GH.exists():
        code, out = run([str(GH), "repo", "view", "--json", "url", "--jq", ".url"])
        if code == 0 and out:
            print("  仓库：" + out)
    print("\nStreamlit Cloud 会自动拉取新提交并重新部署，1–2 分钟后刷新线上页面即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
