import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""완성본 검증 몽타주: python check_out.py <출력경로> <타임스탬프,콤마구분> <저장.jpg>"""
import subprocess
import sys
from pathlib import Path

from app import config

video, stamps, out = sys.argv[1], sys.argv[2], sys.argv[3]
tmp = Path(out).parent
tiles = []
for i, t in enumerate(stamps.split(",")):
    f = tmp / f"_ck{i}.jpg"
    subprocess.run([config.FFMPEG, "-y", "-v", "error", "-ss", t, "-i", video,
                    "-frames:v", "1", "-vf", "scale=200:-1", str(f)], check=True)
    tiles.append(str(f))
cmd = [config.FFMPEG, "-y", "-v", "error"]
for f in tiles:
    cmd += ["-i", f]
n = len(tiles)
cmd += ["-filter_complex", f"{''.join(f'[{i}]' for i in range(n))}hstack=inputs={n}", str(out)]
subprocess.run(cmd, check=True)
print("done:", out)
