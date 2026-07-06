"""프레임 간 변화량(YDIF) 기반 움직임 이벤트 감지 — 효과음 배치 타이밍용."""
import re
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import config

BIN = 0.2          # 곡선 해상도 (초)
MIN_GAP = 0.7      # 이벤트 간 최소 간격 (초)
THRESHOLD_OVER = 0.5   # baseline 대비 이만큼 초과해야 이벤트


@dataclass
class MotionEvent:
    time: float      # 이벤트 시작 (초)
    strength: float  # 피크 세기 (baseline 차감값)


def motion_curve(video_path: str) -> list[tuple[float, float]]:
    """0.2초 단위 (time, YDIF 평균) 곡선."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "motion.txt"
        subprocess.run(
            [config.FFMPEG, "-v", "error", "-i", video_path,
             "-vf", f"scale=192:108,signalstats,metadata=print:key=lavfi.signalstats.YDIF:file={out.name}",
             "-an", "-f", "null", "-"],
            cwd=td, capture_output=True, text=True, timeout=600, check=True,
        )
        raw = out.read_text(encoding="utf-8")
    pairs = re.findall(r"pts_time:([\d.]+)\s*\nlavfi\.signalstats\.YDIF=([\d.]+)", raw)

    bins: dict[float, list[float]] = {}
    for t, v in pairs:
        key = round(float(t) / BIN) * BIN
        bins.setdefault(key, []).append(float(v))
    return sorted((t, sum(vs) / len(vs)) for t, vs in bins.items())


def detect_events(video_path: str, max_events: int = 8) -> list[MotionEvent]:
    """움직임 피크 이벤트 목록 (시간순). 세기 내림차순 상위 max_events개만."""
    curve = motion_curve(video_path)
    if not curve:
        return []
    baseline = statistics.median(v for _, v in curve)
    thresh = baseline + THRESHOLD_OVER

    # 임계 초과 구간을 이벤트로 묶기 (시작 시각 + 구간 내 최대 세기)
    events: list[MotionEvent] = []
    current: MotionEvent | None = None
    last_above = -1e9
    for t, v in curve:
        if v >= thresh:
            if current is None or t - last_above > MIN_GAP:
                current = MotionEvent(time=t, strength=v - baseline)
                events.append(current)
            else:
                current.strength = max(current.strength, v - baseline)
            last_above = t
        # 임계 미만이어도 current는 유지 — MIN_GAP 이상 벌어지면 새 이벤트로 시작됨

    events.sort(key=lambda e: e.strength, reverse=True)
    events = events[:max_events]
    events.sort(key=lambda e: e.time)
    return events
