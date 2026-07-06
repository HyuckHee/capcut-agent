"""움직임 기반 피사체 추적 — 세로 크롭 창이 강아지를 따라가게 한다.

프레임 간 차이(움직임)의 무게중심을 추적한다. 배경/가구는 정지해 있으므로
움직이는 유일한 대상(강아지/손)이 잡힌다. 결과는 crop 필터의 x/y 시간 함수식.
"""
import subprocess

import numpy as np

from . import config

W, H = 96, 54          # 분석 해상도 (원본 비율 유지)
FPS = 5                # 분석 프레임레이트
DIFF_THRESHOLD = 14    # 이 밝기차 이상인 픽셀만 움직임으로 침
MIN_PIXELS = 12        # 움직임 픽셀이 이보다 적으면 직전 위치 유지
SMOOTH_WIN = 7         # 이동평균 창 (5fps 기준 1.4초 — 크롭 잔떨림 방지)
KNOT_STEP = 3          # 식으로 내보낼 때 3프레임(0.6초)마다 절점


def track(video_path: str, start: float, end: float,
          fallback_x: float = 0.5, fallback_y: float = 0.65) -> list[tuple[float, float, float]]:
    """[(세그먼트 내 상대시각, x비율, y비율)] 절점 목록을 반환."""
    proc = subprocess.run(
        [config.FFMPEG, "-v", "error", "-ss", str(start), "-to", str(end), "-i", video_path,
         "-vf", f"fps={FPS},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=300, check=True,
    )
    frames = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = len(frames) // (W * H)
    frames = frames[:n * W * H].reshape(n, H, W).astype(np.int16)

    xs: list[float | None] = [None]
    ys: list[float | None] = [None]
    for i in range(1, n):
        diff = np.abs(frames[i] - frames[i - 1]) > DIFF_THRESHOLD
        if diff.sum() < MIN_PIXELS:
            xs.append(xs[-1])
            ys.append(ys[-1])
            continue
        yy, xx = np.nonzero(diff)
        xs.append(float(xx.mean()) / W)
        ys.append(float(yy.mean()) / H)

    # 앞쪽 None은 첫 유효값으로, 그래도 없으면 fallback
    first_x = next((v for v in xs if v is not None), fallback_x)
    first_y = next((v for v in ys if v is not None), fallback_y)
    fx = [v if v is not None else first_x for v in xs]
    fy = [v if v is not None else first_y for v in ys]
    # None 이후 유지값 처리(위 루프에서 직전값 복사로 이미 처리됨) 후 스무딩
    if n > SMOOTH_WIN * 2:
        kernel = np.ones(SMOOTH_WIN) / SMOOTH_WIN
        sx = np.convolve(np.array(fx), kernel, mode="same")
        sy = np.convolve(np.array(fy), kernel, mode="same")
        # convolve 가장자리 왜곡 보정: 양끝은 원값 쪽으로
        edge = SMOOTH_WIN // 2
        sx[:edge], sx[-edge:] = fx[:edge], fx[-edge:]
        sy[:edge], sy[-edge:] = fy[:edge], fy[-edge:]
    else:  # 짧은 세그먼트는 스무딩 생략
        sx, sy = np.array(fx), np.array(fy)

    knots = []
    for i in range(0, n, KNOT_STEP):
        knots.append((i / FPS, float(sx[i]), float(sy[i])))
    if (n - 1) / FPS - knots[-1][0] > 0.1:
        knots.append(((n - 1) / FPS, float(sx[-1]), float(sy[-1])))
    return knots


def crop_expr(knots: list[tuple[float, float, float]], axis: str) -> str:
    """절점을 crop 필터용 구간별 선형보간 식으로 변환. axis: 'x' 또는 'y'."""
    idx = 1 if axis == "x" else 2
    dim = "iw" if axis == "x" else "ih"
    out = "ow" if axis == "x" else "oh"
    anchor = 0.5 if axis == "x" else 0.55  # 창 안에서 피사체가 올 위치

    if len(knots) == 1:
        center = f"{dim}*{knots[0][idx]:.4f}"
    else:
        parts = []
        for (t0, *k0), (t1, *k1) in zip(knots, knots[1:]):
            v0, v1 = k0[idx - 1], k1[idx - 1]
            # [t0, t1) 반개구간 — 경계 순간 두 조각이 중복 합산되지 않도록
            seg = (f"gte(t,{t0:.3f})*lt(t,{t1:.3f})*"
                   f"({v0:.4f}+({v1 - v0:.4f})*(t-{t0:.3f})/{t1 - t0:.3f})")
            parts.append(seg)
        last_t, *last_k = knots[-1]
        parts.append(f"gte(t,{last_t:.3f})*{last_k[idx - 1]:.4f}")
        center = f"{dim}*(" + "+".join(parts) + ")"
    return f"max(0,min({dim}-{out},{center}-{out}*{anchor}))"
