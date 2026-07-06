import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""프레임 몽타주 추출: python frames.py <영상> <ss> <to> <fps> <cols> <rows> <출력.jpg>

한글 경로는 반드시 인자로 넘길 것 (python -c 내 문자열은 PowerShell이 깨뜨림).
"""
import subprocess
import sys

from app import config

video, ss, to, fps, cols, rows, out = sys.argv[1:8]
subprocess.run(
    [config.FFMPEG, "-y", "-v", "error", "-ss", ss, "-to", to, "-i", video,
     "-vf", f"fps={fps},scale=280:-1,tile={cols}x{rows}", "-frames:v", "1", out],
    check=True, timeout=300,
)
print("done:", out)
