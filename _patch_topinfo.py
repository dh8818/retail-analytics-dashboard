# -*- coding: utf-8 -*-
"""把「文件/主表/识别列」这行技术信息挪到老板视角之后，只在专业模式显示。"""
from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8").replace("\r\n", "\n")

start_mark = "# ---------- 顶部信息 ----------"
start = s.index(start_mark)
# 该段结束于下一个 '# ----------' 或 '_VIEW = st.radio' 之前
nxt = s.index("_VIEW = st.radio(")
block = s[start:nxt]
assert 0 < len(block) < 6000, len(block)

s = s[:start] + s[nxt:]

# 插到 st.stop() 之后（只有专业模式会走到这里）
stop_idx = s.index("    st.stop()") + len("    st.stop()")
insert_at = s.index("\n", stop_idx) + 1
s = s[:insert_at] + "\n" + block.rstrip() + "\n\n" + s[insert_at:]
p.write_text(s, encoding="utf-8", newline="\n")
print("顶部技术信息已移到专业模式")
