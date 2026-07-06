"""귀여움 모드 — 컷/하이라이트(슬로우+줌)/자막/효과음/BGM 트랙 구성."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pycapcut as cc

from . import config
from .motion_detect import MotionEvent
from .silence_detect import VideoInfo
from .sfx_synth import ensure_library

US = 1_000_000

SFX_VOLUME = 0.9
BGM_VOLUME = 0.18
SFX_LEAD = 0.08          # 효과음을 행동 살짝 앞에 배치 (체감 싱크)
CUT_EVENT_MARGIN = 0.35  # 컷 경계 이만큼 안쪽의 이벤트도 함께 제거
OVERRIDE_TOLERANCE = 0.7  # --sfx 시각 지정이 이벤트와 매칭되는 허용 오차 (초)

ROTATION = ("pop", "wiggle", "squeak", "whine", "whoosh")

# 하이라이트 연출 기본값 (강조 구간: 슬로우모션 + 피사체 줌인)
HIGHLIGHT_SPEED = 0.5
HIGHLIGHT_SCALE = 1.3
HIGHLIGHT_OFFSET_X = 0.30   # 반캔버스 단위, 양수 = 화면 오른쪽으로 (좌측 피사체를 중앙에)
HIGHLIGHT_OFFSET_Y = 0.25   # 양수 = 위로 (하단 피사체를 중앙에)

CAPTION_TRANSFORM_Y = -0.75  # 자막 위치 (CapCut 자막 관례상 하단 -0.8 부근)


@dataclass
class Piece:
    """타임라인에 올라갈 비디오 조각 (원본 구간 + 배속/줌 여부)."""
    src_start: float
    src_end: float
    highlight: bool
    tl_start: float = 0.0   # _layout에서 채움 (초)
    tl_start_us: int = 0    # 세그먼트 배치용 정수 누적값 (마이크로초)
    tl_dur_us: int = 0

    @property
    def speed(self) -> float:
        return HIGHLIGHT_SPEED if self.highlight else 1.0


def _keep_ranges(duration: float, cut_ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for c_start, c_end in sorted(cut_ranges):
        if c_start > cursor:
            keeps.append((cursor, min(c_start, duration)))
        cursor = max(cursor, c_end)
    if cursor < duration:
        keeps.append((cursor, duration))
    return [(s, e) for s, e in keeps if e - s > 0.01]


def _layout_pieces(duration: float,
                   cut_ranges: list[tuple[float, float]],
                   highlights: list[tuple[float, float]]) -> list[Piece]:
    """보존 구간을 하이라이트 경계에서 쪼개고 타임라인 위치를 계산."""
    pieces: list[Piece] = []
    for s, e in _keep_ranges(duration, cut_ranges):
        bounds = {s, e}
        for h_start, h_end in highlights:
            for b in (h_start, h_end):
                if s < b < e:
                    bounds.add(b)
        pts = sorted(bounds)
        for a, b in zip(pts, pts[1:]):
            mid = (a + b) / 2
            hl = any(h_s <= mid < h_e for h_s, h_e in highlights)
            pieces.append(Piece(a, b, hl))

    # VideoSegment의 target 길이 계산(round(src_dur/speed))과 정확히 일치하도록
    # 마이크로초 정수로 누적해 겹침/틈을 방지한다
    cursor_us = 0
    for p in pieces:
        src_dur_us = round(p.src_end * US) - round(p.src_start * US)
        p.tl_dur_us = round(src_dur_us / p.speed)
        p.tl_start_us = cursor_us
        p.tl_start = cursor_us / US
        cursor_us += p.tl_dur_us
    return pieces


def _to_timeline(src_t: float, pieces: list[Piece], *, clamp: bool = False) -> float | None:
    """원본 시각 → 타임라인 시각. 컷 안이면 None (clamp=True면 다음 조각 시작으로)."""
    for p in pieces:
        if p.src_start <= src_t <= p.src_end:
            return p.tl_start + (src_t - p.src_start) / p.speed
        if src_t < p.src_start:  # 컷 구간에 떨어짐
            return p.tl_start if clamp else None
    last = pieces[-1]
    return (last.tl_start_us + last.tl_dur_us) / US if clamp else None


def _in_cut(src_t: float, cut_ranges: list[tuple[float, float]], margin: float) -> bool:
    return any(s - margin <= src_t <= e + margin for s, e in cut_ranges)


def _assign_sfx(events: list[MotionEvent], sfx_dir: Path,
                overrides: dict[float, str]) -> list[tuple[float, Path]]:
    """이벤트별 효과음 배정 → [(원본 시각, 파일)]. 기본 규칙 + 사용자 지정 덮어쓰기."""
    if not events:
        return []
    available = {p.stem: p for p in sfx_dir.glob("*.wav")}
    rotation = [n for n in ROTATION if n in available]

    biggest = max(events, key=lambda e: e.strength)
    names: dict[int, str] = {}
    ri = 0
    for i, ev in enumerate(events):
        if ev is biggest and "boing" in available:
            names[i] = "boing"
        elif ev is events[-1] and ev is not biggest and "sparkle" in available:
            names[i] = "sparkle"
        elif rotation:
            names[i] = rotation[ri % len(rotation)]
            ri += 1

    for want_t, want_name in overrides.items():
        if want_name not in available:
            raise ValueError(f"효과음 '{want_name}' 없음. 사용 가능: {sorted(available)}")
        nearest = min(range(len(events)), key=lambda i: abs(events[i].time - want_t))
        if abs(events[nearest].time - want_t) <= OVERRIDE_TOLERANCE:
            names[nearest] = want_name

    return [(events[i].time, available[n]) for i, n in sorted(names.items())]


def build_cute_draft(video_path: str,
                     events: list[MotionEvent],
                     info: VideoInfo,
                     draft_name: str | None = None,
                     with_bgm: bool = True,
                     cut_ranges: list[tuple[float, float]] | None = None,
                     sfx_overrides: dict[float, str] | None = None,
                     highlights: list[tuple[float, float]] | None = None,
                     captions: list[tuple[float, float, str]] | None = None,
                     extra_sfx: list[tuple[float, str]] | None = None,
                     sfx_volumes: dict[float, float] | None = None,
                     ) -> tuple[str, list[tuple[float, str]]]:
    """드래프트 이름과 [(원본 시각, 효과음이름)] 배치 내역을 반환."""
    library = ensure_library()
    cut_ranges = cut_ranges or []
    sfx_overrides = sfx_overrides or {}
    highlights = highlights or []
    captions = captions or []
    extra_sfx = extra_sfx or []
    sfx_volumes = sfx_volumes or {}
    if draft_name is None:
        draft_name = f"cute_{datetime.now():%m%d_%H%M%S}"

    folder = cc.DraftFolder(config.CAPCUT_DRAFT_FOLDER)
    fps = round(info.fps) or 30
    script = folder.create_draft(draft_name, info.width, info.height, fps, allow_replace=True)

    pieces = _layout_pieces(info.duration, cut_ranges, highlights)
    total_us = pieces[-1].tl_start_us + pieces[-1].tl_dur_us

    # ── 비디오 트랙: 조각별 배속/줌 적용
    script.add_track(cc.TrackType.video)
    video_material = cc.VideoMaterial(video_path)
    zoom = cc.ClipSettings(scale_x=HIGHLIGHT_SCALE, scale_y=HIGHLIGHT_SCALE,
                           transform_x=HIGHLIGHT_OFFSET_X, transform_y=HIGHLIGHT_OFFSET_Y)
    for p in pieces:
        src_start = round(p.src_start * US)
        src_end = min(round(p.src_end * US), video_material.duration)
        if src_end - src_start <= 0:
            continue
        script.add_segment(cc.VideoSegment(
            video_material,
            cc.trange(p.tl_start_us, p.tl_dur_us),
            source_timerange=cc.trange(src_start, src_end - src_start),
            speed=p.speed,
            clip_settings=zoom if p.highlight else None,
        ))

    # ── 효과음 트랙 (겹치면 sfx2, sfx3...에 레이어링)
    script.add_track(cc.TrackType.audio, "sfx")
    track_ends = {"sfx": 0}
    placed: list[tuple[float, str]] = []
    auto = [(t, p) for t, p in _assign_sfx(events, library / "sfx", sfx_overrides)
            if not _in_cut(t, cut_ranges, CUT_EVENT_MARGIN)]
    manual = [(t, library / "sfx" / f"{name}.wav") for t, name in extra_sfx]
    for src_t, sfx_path in sorted(auto + manual):
        if not sfx_path.exists():
            raise ValueError(f"효과음 파일 없음: {sfx_path}")
        timeline_t = _to_timeline(src_t, pieces)
        if timeline_t is None:
            continue
        mat = cc.AudioMaterial(str(sfx_path))
        start_us = max(0, round((timeline_t - SFX_LEAD) * US))
        dur_us = min(mat.duration, total_us - start_us)
        if dur_us <= 0:
            continue
        track = next((t for t, end in track_ends.items() if start_us >= end), None)
        if track is None:
            track = f"sfx{len(track_ends) + 1}"
            script.add_track(cc.TrackType.audio, track)
            track_ends[track] = 0
        factor = next((f for t, f in sfx_volumes.items() if abs(t - src_t) <= OVERRIDE_TOLERANCE), 1.0)
        script.add_segment(cc.AudioSegment(
            mat, cc.trange(start_us, dur_us),
            source_timerange=cc.trange(0, dur_us),
            volume=SFX_VOLUME * factor,
        ), track)
        track_ends[track] = start_us + dur_us
        placed.append((src_t, sfx_path.stem))

    # ── 자막 트랙
    if captions:
        script.add_track(cc.TrackType.text)
        style = cc.TextStyle(size=11.0, bold=True, align=1, color=(1.0, 1.0, 1.0),
                             auto_wrapping=True)
        border = cc.TextBorder(color=(0.0, 0.0, 0.0), width=55.0)
        pos = cc.ClipSettings(transform_y=CAPTION_TRANSFORM_Y)
        for c_start, c_end, text in captions:
            tl_a = _to_timeline(c_start, pieces, clamp=True)
            tl_b = _to_timeline(c_end, pieces, clamp=True)
            if tl_b - tl_a < 0.1:
                continue
            script.add_segment(cc.TextSegment(
                text, cc.trange(round(tl_a * US), round((tl_b - tl_a) * US)),
                style=style, border=border, clip_settings=pos,
            ))

    # ── BGM 트랙 (영상보다 짧으면 이어붙여 루프)
    if with_bgm:
        bgm_files = sorted((library / "bgm").glob("*.wav")) + sorted((library / "bgm").glob("*.mp3"))
        if bgm_files:
            script.add_track(cc.TrackType.audio, "bgm")
            bgm_mat = cc.AudioMaterial(str(bgm_files[0]))
            cursor = 0
            while cursor < total_us:
                dur_us = min(bgm_mat.duration, total_us - cursor)
                script.add_segment(cc.AudioSegment(
                    bgm_mat, cc.trange(cursor, dur_us),
                    source_timerange=cc.trange(0, dur_us),
                    volume=BGM_VOLUME,
                ), "bgm")
                cursor += dur_us

    script.save()
    return draft_name, placed
