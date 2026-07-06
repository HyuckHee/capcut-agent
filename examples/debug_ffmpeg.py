import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""추적용 ffmpeg 호출 디버그 — stderr를 그대로 출력."""
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app import config

path = sys.argv[1]
print("path repr:", repr(path))
proc = subprocess.run(
    [config.FFMPEG, "-v", "error", "-ss", "0.5", "-to", "2.2", "-i", path,
     "-vf", "fps=5,scale=96:54,format=gray", "-f", "rawvideo", "-"],
    capture_output=True, timeout=120,
)
print("returncode:", proc.returncode)
print("stdout bytes:", len(proc.stdout))
print("stderr:", proc.stderr.decode("utf-8", errors="replace")[:1000])
