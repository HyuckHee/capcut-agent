"""보존 구간 리스트 → CapCut 점프컷 드래프트 생성 (pycapcut)."""
from datetime import datetime

import pycapcut as cc

from . import config
from .silence_detect import VideoInfo

US = 1_000_000  # 초 → 마이크로초


def build_jumpcut_draft(video_path: str,
                        segments: list[tuple[float, float]],
                        info: VideoInfo,
                        draft_name: str | None = None) -> str:
    """보존 구간만 이어붙인 드래프트를 만들고 드래프트 이름을 반환."""
    if not segments:
        raise ValueError("보존 구간이 없습니다 — 전체가 무음으로 판정됐습니다. 임계값을 조정하세요.")

    if draft_name is None:
        draft_name = f"agent_{datetime.now():%m%d_%H%M%S}"

    folder = cc.DraftFolder(config.CAPCUT_DRAFT_FOLDER)
    fps = round(info.fps) or 30
    script = folder.create_draft(draft_name, info.width, info.height, fps, allow_replace=True)
    script.add_track(cc.TrackType.video)

    material = cc.VideoMaterial(video_path)

    cursor_us = 0  # 주 비디오 트랙은 0부터 빈틈없이 이어붙인다 (CapCut이 강제 정렬함)
    for start_s, end_s in segments:
        src_start = round(start_s * US)
        src_end = min(round(end_s * US), material.duration)
        dur = src_end - src_start
        if dur <= 0:
            continue
        seg = cc.VideoSegment(
            material,
            cc.trange(cursor_us, dur),
            source_timerange=cc.trange(src_start, dur),
        )
        script.add_segment(seg)
        cursor_us += dur

    script.save()
    return draft_name
