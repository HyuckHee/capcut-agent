"""ffmpeg silencedetect 기반 무음 감지 → 보존(발화) 구간 리스트 산출."""
import re
import subprocess
from dataclasses import dataclass

from . import config


@dataclass
class VideoInfo:
    duration: float   # 초
    width: int
    height: int
    fps: float


def probe(video_path: str) -> VideoInfo:
    out = subprocess.run(
        [config.FFPROBE, "-v", "error",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate:format=duration",
         "-of", "default=noprint_wrappers=1", video_path],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=60,
    )
    kv = dict(line.split("=", 1) for line in out.stdout.strip().splitlines() if "=" in line)
    num, den = kv["r_frame_rate"].split("/")
    return VideoInfo(
        duration=float(kv["duration"]),
        width=int(kv["width"]),
        height=int(kv["height"]),
        fps=float(num) / float(den),
    )


def detect_silences(video_path: str,
                    noise_db: float = config.SILENCE_NOISE_DB,
                    min_dur: float = config.SILENCE_MIN_DUR) -> list[tuple[float, float]]:
    """(silence_start, silence_end) 초 단위 리스트. silencedetect 로그는 stderr로 나온다."""
    proc = subprocess.run(
        [config.FFMPEG, "-hide_banner", "-nostats", "-i", video_path,
         "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    silences = list(zip(starts, ends))
    # 파일 끝까지 이어지는 무음은 silence_end가 없다
    if len(starts) == len(ends) + 1:
        silences.append((starts[-1], float("inf")))
    return silences


def keep_segments(video_path: str, *,
                  noise_db: float = config.SILENCE_NOISE_DB,
                  min_dur: float = config.SILENCE_MIN_DUR,
                  pad: float = config.KEEP_PAD) -> tuple[list[tuple[float, float]], VideoInfo]:
    """무음의 여집합 + 패딩/병합/최소길이 필터 → 보존 구간 [(start, end)] 초 단위."""
    info = probe(video_path)
    silences = detect_silences(video_path, noise_db, min_dur)

    # 무음 여집합 = 발화 구간
    segs: list[tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor:
            segs.append((cursor, s_start))
        cursor = max(cursor, min(s_end, info.duration))
    if cursor < info.duration:
        segs.append((cursor, info.duration))

    # 발화 앞뒤 패딩 (컷이 너무 타이트하면 어색함)
    segs = [(max(0.0, s - pad), min(info.duration, e + pad)) for s, e in segs]

    # 패딩으로 겹치거나 MERGE_GAP 이하로 붙은 구간 병합
    merged: list[tuple[float, float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= config.MERGE_GAP:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # 너무 짧은 조각 제거
    merged = [(s, e) for s, e in merged if e - s >= config.MIN_KEEP_DUR]
    return merged, info
