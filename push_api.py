# -*- coding: utf-8 -*-
"""
走 GitHub REST API 提交（github.com 的 443 连不上时用这个，走 api.github.com）。

    python push_api.py "提交信息"
    python push_api.py "提交信息" app.py README.md     # 只提交指定文件

一次生成一个 commit（Git Data API: blob → tree → commit → 更新 ref），
不会对每个文件各来一个 commit。
"""
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GH = Path("D:/tools/gh/bin/gh.exe")
REPO = "dh8818/retail-analytics-dashboard"
BRANCH = "master"
API = "https://api.github.com"


def token():
    out = subprocess.run([str(GH), "auth", "token"], capture_output=True).stdout.decode().strip()
    if not out:
        sys.exit("✗ 拿不到 token，先跑 gh auth login")
    return out


TOK = token()


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOK)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ {method} {path} → {e.code}: {e.read().decode()[:300]}")


def main():
    msg = (sys.argv[1] if len(sys.argv) > 1 else None) or "update"
    only = sys.argv[2:]

    changed = only or [l[3:].strip() for l in subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True
    ).stdout.decode().splitlines() if l.strip() and not l.startswith("??")]
    changed = [f for f in changed if (ROOT / f).exists()]
    if not changed:
        print("没有已跟踪文件的改动可提交。")
        return 0
    print("将提交：", ", ".join(changed))

    ref = call("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
    parent = ref["object"]["sha"]
    base_tree = call("GET", f"/repos/{REPO}/git/commits/{parent}")["tree"]["sha"]

    entries = []
    for f in changed:
        raw = (ROOT / f).read_bytes()
        blob = call("POST", f"/repos/{REPO}/git/blobs",
                    {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
        entries.append({"path": f.replace("\\", "/"), "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})

    tree = call("POST", f"/repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    commit = call("POST", f"/repos/{REPO}/git/commits",
                  {"message": msg, "tree": tree["sha"], "parents": [parent]})
    call("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}", {"sha": commit["sha"]})
    print("✓ 已提交 ", commit["sha"][:7], msg)
    print("  https://github.com/" + REPO + "/commit/" + commit["sha"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
