"""오디오 이벤트 감지 — 발성(동물 울음·사람 대사)과 무음.

발성 = 음성 대역(250~3000Hz) RMS가 튀면서 스펙트럼 평탄도가 낮은(tonal) 구간.
단순 RMS만 쓰면 부스럭 잡음을 오인하므로 반드시 두 신호를 조합한다.
"""
import re
import subprocess
import tempfile
from pathlib import Path

from . import config

WIN = 0.2  # 분석 창(초)


def _metadata_series(path: str, af: str, key: str) -> dict[float, float]:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "m.txt"
        subprocess.run(
            [config.FFMPEG, "-hide_banner", "-nostats", "-i", path,
             "-af", f"{af},ametadata=print:key={key}:file={out.name}",
             "-f", "null", "-"],
            cwd=td, capture_output=True, timeout=900,
        )
        raw = out.read_text(encoding="utf-8") if out.exists() else ""
    series = {}
    for t, v in re.findall(rf"pts_time:([\d.]+)\s*\n{re.escape(key)}=(-?[\d.eE+]+|-inf|nan)", raw):
        try:
            series[round(float(t), 1)] = float(v)
        except ValueError:
            series[round(float(t), 1)] = -90.0
    return series


def vocal_windows(path: str) -> list[tuple[float, float]]:
    """발성 구간 [(t, 강도 0~1)] — 0.2초 창 단위."""
    n = int(44100 * WIN)
    rms = _metadata_series(
        path, f"highpass=f=250,lowpass=f=3000,asetnsamples={n},astats=metadata=1:reset=1",
        "lavfi.astats.Overall.RMS_level")
    flat = _metadata_series(
        path, f"asetnsamples={n},aspectralstats=measure=flatness:win_size=2048",
        "lavfi.aspectralstats.1.flatness")
    if not rms:
        return []
    base = sorted(rms.values())[len(rms) // 2]
    out = []
    for t, v in sorted(rms.items()):
        f = flat.get(t, 1.0)
        if v > base + 10 and f < 0.15:  # 크고 + tonal = 발성
            strength = min(1.0, (v - base - 10) / 20)
            out.append((t, max(0.3, strength)))
    return out


def silence_ranges(path: str, noise_db: float = -42, min_dur: float = 1.0) -> list[tuple[float, float]]:
    """무음 구간 [(시작, 끝)]."""
    proc = subprocess.run(
        [config.FFMPEG, "-hide_banner", "-nostats", "-i", path,
         "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    pairs = list(zip(starts, ends))
    if len(starts) == len(ends) + 1:
        pairs.append((starts[-1], 1e9))
    return pairs
