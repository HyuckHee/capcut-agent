import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""올빼미 클립 무음 분석 — 임계값별 보존량 비교."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.silence_detect import keep_segments

VIDEO = sys.argv[1]

for noise_db, min_dur in [(-45, 1.0), (-42, 0.8), (-38, 0.8), (-35, 0.6)]:
    segs, info = keep_segments(VIDEO, noise_db=noise_db, min_dur=min_dur)
    kept = sum(e - s for s, e in segs)
    print(f"noise={noise_db}dB min_dur={min_dur}s → 보존 {kept:.1f}s / {info.duration:.1f}s "
          f"({len(segs)}개 구간, 컷 {info.duration - kept:.1f}s)")
    if len(segs) <= 40:
        print("   " + " | ".join(f"{s:.1f}-{e:.1f}" for s, e in segs))
