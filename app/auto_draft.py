"""휴리스틱 자동 틀 — 영상을 신호(움직임·발성·무음) 점수로 훑어 쇼츠 초안 세그먼트를 뽑는다.

내용 이해는 못 하는 규칙 기반 초안이다. 프로파일(profiles/*.json)의 가중치를
채널 유형별로 계속 튜닝하며 쓰는 것이 설계 의도.
"""
import json
import statistics
from pathlib import Path

from .audio_events import silence_ranges, vocal_windows
from .motion_detect import motion_curve
from .silence_detect import probe

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


def load_profile(name: str) -> dict:
    return json.loads((PROFILE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def save_profile(name: str, data: dict) -> None:
    (PROFILE_DIR / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def score_bins(path: str, profile: dict) -> tuple[list[float], float]:
    """1초 단위 점수 배열과 영상 길이를 반환."""
    info = probe(path)
    dur = info.duration
    n = max(1, int(dur))
    bin_s = profile.get("bin", 1.0)

    # 움직임 (0.2s 곡선 → 1s 평균, baseline 대비 정규화)
    mcurve = motion_curve(path)
    mbins = [0.0] * n
    counts = [0] * n
    for t, v in mcurve:
        i = min(n - 1, int(t / bin_s))
        mbins[i] += v
        counts[i] += 1
    mbins = [m / c if c else 0.0 for m, c in zip(mbins, counts)]
    # 백분위 순위 정규화 — "이 클립 안에서 상대적으로 활발한 순간"을 뽑는다.
    # (중앙값 편차 방식은 내내 활동적인 클립에서 모든 순간이 평범해지는 문제가 있음)
    order = sorted(range(n), key=lambda i: mbins[i])
    mnorm = [0.0] * n
    for r, i in enumerate(order):
        mnorm[i] = r / max(1, n - 1)

    # 발성
    vbins = [0.0] * n
    for t, s in vocal_windows(path):
        i = min(n - 1, int(t / bin_s))
        vbins[i] = max(vbins[i], s)

    # 무음
    silent = [False] * n
    for a, b in silence_ranges(path, profile.get("silence_db", -42),
                               profile.get("silence_min", 1.0)):
        for i in range(int(a), min(n, int(b) + 1)):
            silent[i] = True

    w_m = profile.get("w_motion", 1.0)
    w_v = profile.get("w_vocal", 2.5)
    w_s = profile.get("w_silence", 1.0)
    scores = [w_m * mnorm[i] + w_v * vbins[i] - (w_s if silent[i] else 0.0)
              for i in range(n)]
    return scores, dur


def _merge_bins(scores: list[float], thresh: float, gap: int = 1) -> list[tuple[int, int]]:
    """임계 초과 빈들을 구간으로 병합. gap = 이어붙일 수 있는 최대 연속 공백 칸 수."""
    segs, start, last = [], None, -99
    for i, s in enumerate(scores):
        if s >= thresh:
            empty = i - last - 1  # 직전 히트와의 공백 칸 수
            if start is None or empty > gap:
                if start is not None:
                    segs.append((start, last))
                start = i
            last = i
    if start is not None:
        segs.append((start, last))
    return segs


def draft_segments(path: str, profile: dict) -> dict:
    """단일 영상 → 초안 세그먼트 목록 (점수·태그 포함)."""
    scores, dur = score_bins(path, profile)
    n = len(scores)
    # 상위 40% 순간을 후보로 (프로파일로 조절 가능)
    q = profile.get("top_quantile", 0.6)
    thresh = sorted(scores)[min(n - 1, int(n * q))]

    pad = profile.get("pad", 0.3)
    min_seg = profile.get("min_seg", 2.0)
    max_seg = profile.get("max_seg", 10.0)

    cands = []
    for i0, i1 in _merge_bins(scores, thresh):
        # 긴 활동 구간은 max_seg 단위로 분할해 여러 후보로 (하나로 뭉치면 다양성 상실)
        length = i1 - i0 + 1
        n_parts = max(1, round(length / max_seg + 0.34))
        bounds = [i0 + round(k * length / n_parts) for k in range(n_parts + 1)]
        for k in range(n_parts):
            p0, p1 = bounds[k], max(bounds[k], bounds[k + 1] - 1)
            a, b = max(0.0, p0 - pad), min(dur, p1 + 1 + pad)
            if b - a < min_seg:
                continue
            window = scores[p0:p1 + 1]
            mean = sum(window) / len(window)
            cands.append({"a": round(a, 1), "b": round(b, 1),
                          "score": round(mean, 2),
                          "peak": round(max(window), 2)})

    # 발성 태그 다시 계산 (표시용)
    vocal_ts = {int(t) for t, _ in vocal_windows(path)}
    for c in cands:
        t_range = set(range(int(c["a"]), int(c["b"]) + 1))
        c["tags"] = ("🔊발성 " if t_range & vocal_ts else "") + "⚡움직임"

    cands.sort(key=lambda c: -c["score"])
    return {"duration": round(dur, 1), "candidates": cands}


def draft(paths: list[str], profile: dict) -> dict:
    """여러 영상 → 목표 길이에 맞는 초안 (시간순 배치, 잔잔한 엔딩 옵션)."""
    target = profile.get("target_len", 40.0)
    per = [dict(path=p, **draft_segments(p, profile)) for p in paths]

    # 전 클립 후보를 점수순으로 채우되, 클립 순서·시간 순서 유지
    pool = []
    for ci, d in enumerate(per):
        for c in d["candidates"]:
            pool.append({**c, "clip": ci})
    pool.sort(key=lambda c: -c["score"])

    chosen, total = [], 0.0
    for c in pool:
        if total >= target:
            break
        chosen.append(c)
        total += c["b"] - c["a"]
    chosen.sort(key=lambda c: (c["clip"], c["a"]))

    # 잔잔한 엔딩: 마지막 클립 끝부분의 저점수(정적) 구간을 엔딩으로 추가
    if profile.get("calm_ending") and per:
        last = per[-1]
        tail_start = last["duration"] * 0.75
        already = any(c["clip"] == len(per) - 1 and c["a"] >= tail_start for c in chosen)
        if not already:
            a = max(tail_start, last["duration"] - 6.0)
            chosen.append({"clip": len(per) - 1, "a": round(a, 1),
                           "b": round(last["duration"], 1),
                           "score": 0.0, "tags": "🌙엔딩(정적)"})

    return {"segments": chosen, "total": round(sum(c["b"] - c["a"] for c in chosen), 1),
            "per_clip": [{"duration": d["duration"], "found": len(d["candidates"])} for d in per]}
