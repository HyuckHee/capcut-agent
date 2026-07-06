import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""드래프트 구조 확인용: python verify_draft.py <드래프트이름>"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

name = sys.argv[1]
p = os.path.expandvars(rf"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\{name}\draft_content.json")
d = json.load(open(p, encoding="utf-8"))
print("duration:", round(d["duration"] / 1e6, 2), "s")
for t in d["tracks"]:
    segs = [(round(s["target_timerange"]["start"] / 1e6, 2),
             round(s["target_timerange"]["duration"] / 1e6, 2)) for s in t["segments"]]
    print(f"{t['type']:6} {t.get('name', ''):5} {segs}")
texts = [m["content"][:60] for m in d["materials"]["texts"]]
print("texts:", texts)
