import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""왕희 유튜브 폴더 영상을 ASCII 경로로 복사 + 길이 출력."""
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app import config

SRC = Path(r"C:\Users\leehh\OneDrive\문서\캡컷에이전트\원본영상\왕희 유튜브")
DST = Path(sys.argv[1])

for f in sorted(SRC.glob("*.mp4")):
    dst = DST / f.name
    if not dst.exists() or dst.stat().st_size != f.stat().st_size:
        shutil.copy(f, dst)
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(dst)],
        capture_output=True, text=True, timeout=60)
    print(f"{f.name}  {float(out.stdout.strip()):.1f}s")
