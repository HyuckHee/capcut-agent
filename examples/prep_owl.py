import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""한글 경로 문제 우회 — 대상 클립을 ASCII 경로로 복사."""
import shutil
import sys
from pathlib import Path

SRC_ROOT = Path(r"C:\Users\leehh\OneDrive\문서\캡컷에이전트\원본영상")
DST = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "owl.mp4"

matches = list(SRC_ROOT.rglob("올빼미 세자 아픔.mp4"))
if not matches:
    sys.exit("원본 못 찾음")
shutil.copy(matches[0], DST)
print(f"복사: {matches[0]} -> {DST} ({DST.stat().st_size/1e6:.0f}MB)")
