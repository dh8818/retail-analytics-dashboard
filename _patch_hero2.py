# -*- coding: utf-8 -*-
"""修：老板视角不要再显示专业顶部四卡。
做法：模式开关放回「口径条之前」（那里 qty_c 已定义），
顶部四卡改成按 session_state 里的模式决定是否渲染。"""
from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8").replace("\r\n", "\n")

# 1) 把模式块从 _hero 前面挪回口径条之前
start = s.index('_VIEW = st.radio(')
end = s.index('_hero = [\n')
block = s[start:end]
assert "st.stop()" in block
s = s[:start] + s[end:]

anchor = "# ---------- 当前口径条 + 顶部字典 ----------"
assert anchor in s
s = s.replace(anchor, block + anchor, 1)

# 2) 顶部四卡按模式渲染
old_hero = '''_hc = st.columns(4)
for _i, (_lab, _val, _sub, _color) in enumerate(_hero):'''
new_hero = '''_IS_BOSS = str(st.session_state.get("view_mode", "老板视角（简单）")).startswith("老板")
_hc = st.columns(4) if not _IS_BOSS else []
for _i, (_lab, _val, _sub, _color) in (enumerate(_hero) if not _IS_BOSS else []):'''
assert old_hero in s
s = s.replace(old_hero, new_hero, 1)
p.write_text(s, encoding="utf-8", newline="\n")
print("四卡按模式隐藏；模式块回到口径条之前")
