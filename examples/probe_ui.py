import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""CapCut UI 트리 덤프 — 자동화용 컨트롤 이름 확인."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

import uiautomation as uia

win = uia.WindowControl(searchDepth=1, Compare=lambda c, d: c.Name in ("CapCut", "CapCut专业版"))
if not win.Exists(3):
    sys.exit("CapCut 창 없음")

print(f"창: Name={win.Name!r} ClassName={win.ClassName!r}\n")


count = 0

def walk(ctrl, depth, max_depth):
    global count
    if depth > max_depth or count > 250:
        return
    try:
        desc = str(ctrl.GetPropertyValue(30159) or "")
    except Exception:
        desc = ""
    if desc:  # 자동화 desc가 있는 컨트롤만 출력
        count += 1
        print(f"[{depth}] {ctrl.ControlTypeName} cls={ctrl.ClassName[:40]!r} name={(ctrl.Name or '')[:30]!r} desc={desc[:80]!r}")
    for child in ctrl.GetChildren():
        walk(child, depth + 1, max_depth)


walk(win, 0, 10)
print(f"\n(desc 있는 컨트롤 {count}개)")
