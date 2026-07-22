"""귀여움 모드 직접 렌더링: 드래프트와 동일한 편집을 ffmpeg으로 mp4 출력.

CapCut 신버전이 UI 자동화를 막고 있어, 내보내기는 이 경로를 쓴다.
사용법은 cli_cute.py와 동일 + <출력.mp4> 인자 추가.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app import config
from app.build_cute_draft import (
    BGM_VOLUME, CUT_EVENT_MARGIN, HIGHLIGHT_OFFSET_X, HIGHLIGHT_OFFSET_Y,
    HIGHLIGHT_SCALE, OVERRIDE_TOLERANCE, SFX_LEAD, SFX_VOLUME, _assign_sfx,
    _in_cut, _layout_pieces, _to_timeline,
)
from app.motion_detect import detect_events
from app.silence_detect import probe
from app.sfx_synth import ensure_library

OUT_W, OUT_H = 1920, 1080
FONT_SOURCE = (Path("C:/Windows/Fonts/malgunbd.ttf") if os.name == "nt"   # 맑은고딕
               else Path(__file__).resolve().parent / "library" / "fonts" / "Pretendard-ExtraBold.otf")
CAPTION_FONT_SIZE = 52
CAPTION_Y_CENTER = 0.875  # transform_y -0.75 에 해당하는 세로 위치


def build_filter(pieces, captions, sfx_placements, total, tmp: Path,
                 n_video_inputs_offset: int, freeze: float = 0.0,
                 vertical: bool = False, subject_x: float = 0.35,
                 src_portrait: bool = False,
                 ducks: list[tuple[float, float, float]] | None = None,
                 boosts: list[tuple[float, float, float]] | None = None,
                 font: Path | None = None,
                 bgm_name: str | None = None,
                 caption_size: int | None = None) -> tuple[str, list[str]]:
    """filter_complex 스크립트와 추가 입력 파일 목록을 만든다."""
    lines = []
    extra_inputs: list[str] = []

    if vertical or src_portrait:  # 쇼츠 9:16 출력
        out_w, out_h = 1080, 1920
        if src_portrait:  # 소스가 이미 세로(추적 크롭된 마스터 등) — 크롭 없음
            base = ""
        else:  # 가로 소스 → 피사체 x중심, 하단 기준으로 세로 크롭
            vh = 0.8  # 원본 높이의 80%만 사용 (바닥의 피사체를 프레임 중앙부로 올림)
            base = (f"crop=ih*{vh * 9 / 16:.4f}:ih*{vh}"
                    f":max(0\\,{subject_x:.4f}*iw-ih*{vh * 9 / 32:.4f}):ih*{1 - vh:.2f},")
        font_size, cap_y = 44, 0.80  # 쇼츠 UI(하단 제목/버튼)를 피해 약간 위로
    else:
        out_w, out_h = OUT_W, OUT_H
        base = ""
        font_size, cap_y = CAPTION_FONT_SIZE, CAPTION_Y_CENTER
    if caption_size:  # 자막 크기 수동 지정
        font_size = caption_size

    # ── 비디오/오디오 조각
    zoom_w = round(out_w * HIGHLIGHT_SCALE / 2) * 2
    zoom_h = round(out_h * HIGHLIGHT_SCALE / 2) * 2
    # transform: 콘텐츠가 오른쪽/위로 이동 = 크롭 창은 왼쪽/아래로
    # (세로 모드는 크롭으로 이미 피사체가 가로 중앙이므로 x 이동 없음)
    offset_x = 0.0 if (vertical or src_portrait) else HIGHLIGHT_OFFSET_X
    crop_x = round((zoom_w - out_w) / 2 - offset_x * out_w / 2)
    crop_y = round((zoom_h - out_h) / 2 + HIGHLIGHT_OFFSET_Y * out_h / 2)
    crop_x = max(0, min(zoom_w - out_w, crop_x))
    crop_y = max(0, min(zoom_h - out_h, crop_y))

    pairs = []
    for i, p in enumerate(pieces):
        if p.highlight:
            setpts = f"(PTS-STARTPTS)/{p.speed}"
            vchain = f"{base}scale={zoom_w}:{zoom_h},crop={out_w}:{out_h}:{crop_x}:{crop_y}"
            achain = f"asetpts=PTS-STARTPTS,atempo={p.speed}"
        else:
            setpts = "PTS-STARTPTS"
            vchain = f"{base}scale={out_w}:{out_h}"
            achain = "asetpts=PTS-STARTPTS"
        lines.append(f"[0:v]trim={p.src_start}:{p.src_end},setpts={setpts},{vchain}[v{i}];")
        lines.append(f"[0:a]atrim={p.src_start}:{p.src_end},{achain}[a{i}];")
        pairs.append(f"[v{i}][a{i}]")
    lines.append(f"{''.join(pairs)}concat=n={len(pieces)}:v=1:a=1[vc0][ac0];")
    # 엔딩 프리즈: 마지막 프레임을 복제해 아웃트로 구간 확보
    if freeze > 0:
        lines.append(f"[vc0]tpad=stop_mode=clone:stop_duration={freeze}[vc];")
        lines.append(f"[ac0]apad=pad_dur={freeze}[acp];")
    else:
        lines.append("[vc0]null[vc];")
        lines.append("[ac0]anull[acp];")
    # 부스트: 지정 구간의 원본 소리(강아지 울음 등)를 키운다
    boost_expr = "1.0"
    for a, b, factor in (boosts or []):
        boost_expr = f"if(between(t,{a:.3f},{b:.3f}),{factor:.3f},{boost_expr})"
    lines.append(f"[acp]volume='{boost_expr}':eval=frame[ac];")
    render_end = total + freeze

    # ── 자막 (ffmpeg는 cwd=tmp로 실행 — 필터 안 경로에 드라이브 콜론이 없도록 상대경로 사용)
    import shutil
    shutil.copy(font if font else FONT_SOURCE, tmp / "font.ttf")
    vin = "vc"
    for i, (c_start, c_end, text) in enumerate(captions):
        tl_a = _to_timeline(c_start, pieces, clamp=True)
        tl_b = _to_timeline(c_end, pieces, clamp=True)
        if c_end >= pieces[-1].src_end - 0.05:  # 영상 끝까지 가는 자막은 프리즈 구간도 커버
            tl_b = render_end
        (tmp / f"cap{i}.txt").write_text(text, encoding="utf-8")
        lines.append(
            f"[{vin}]drawtext=fontfile=font.ttf:textfile=cap{i}.txt"
            f":fontsize={font_size}:fontcolor=white:borderw=5:bordercolor=black"
            f":x=(w-text_w)/2:y={cap_y}*h-text_h/2"
            f":enable='between(t,{tl_a:.3f},{tl_b:.3f})'[vt{i}];")
        vin = f"vt{i}"

    # ── 오디오 믹스 (원본 + BGM + 효과음)
    library = ensure_library()
    if bgm_name:  # 곡 지정 (library/bgm의 파일명, 확장자 생략 가능)
        bgm_pick = library / "bgm" / (bgm_name if bgm_name.endswith(".wav") else f"{bgm_name}.wav")
        if not bgm_pick.exists():
            sys.exit(f"BGM 파일 없음: {bgm_pick}")
        bgm_files = [bgm_pick]
    else:
        bgm_files = sorted((library / "bgm").glob("*.wav"))
    mix_ins = ["[ac]"]
    idx = n_video_inputs_offset
    if bgm_files:
        extra_inputs.append(str(bgm_files[0]))
        # 덕킹: 지정 구간에서 BGM을 낮춰 원본 소리(강아지 소리 등)를 살린다
        vol_expr = str(BGM_VOLUME)
        for a, b, factor in (ducks or []):
            vol_expr = f"if(between(t,{a:.3f},{b:.3f}),{BGM_VOLUME * factor:.4f},{vol_expr})"
        lines.append(f"[{idx}:a]volume='{vol_expr}':eval=frame,atrim=0:{render_end:.3f}[bgm];")
        mix_ins.append("[bgm]")
        idx += 1
    for j, (tl_t, sfx_path, vol) in enumerate(sfx_placements):
        extra_inputs.append(str(sfx_path))
        delay_ms = max(0, round((tl_t - SFX_LEAD) * 1000))
        lines.append(f"[{idx}:a]volume={vol:.3f},adelay={delay_ms}:all=1[s{j}];")
        mix_ins.append(f"[s{j}]")
        idx += 1
    lines.append(
        f"{''.join(mix_ins)}amix=inputs={len(mix_ins)}:duration=first:normalize=0,"
        f"alimiter=limit=0.95[am]")

    return "\n".join(lines), extra_inputs


def main() -> None:
    parser = argparse.ArgumentParser(description="캡컷 에이전트 — mp4 직접 렌더링")
    parser.add_argument("video")
    parser.add_argument("output")
    parser.add_argument("--max-sfx", type=int, default=8)
    parser.add_argument("--no-bgm", action="store_true")
    parser.add_argument("--cut", action="append", default=[])
    parser.add_argument("--sfx", action="append", default=[])
    parser.add_argument("--highlight", action="append", default=[])
    parser.add_argument("--caption", action="append", default=[])
    parser.add_argument("--add-sfx", action="append", default=[])
    parser.add_argument("--sfx-vol", action="append", default=[], metavar="시각:배율",
                        help="특정 효과음 볼륨 배율. 예: --sfx-vol 0.6:0.5 (반복 가능)")
    parser.add_argument("--freeze", type=float, default=0.0,
                        help="마지막 프레임 정지 시간(초) — 아웃트로/구독 유도용")
    parser.add_argument("--vertical", action="store_true", help="쇼츠용 9:16 세로 출력")
    parser.add_argument("--subject-x", type=float, default=0.35,
                        help="세로 크롭 중심의 가로 위치 (0~1, 기본 0.35)")
    parser.add_argument("--duck", action="append", default=[], metavar="시작-끝:배율",
                        help="BGM 덕킹 구간. 예: --duck 7.8-16.5:0.3 (반복 가능)")
    parser.add_argument("--boost", action="append", default=[], metavar="시작-끝:배율",
                        help="원본 소리 증폭 구간. 예: --boost 9.0-10.0:2.0 (반복 가능)")
    parser.add_argument("--font", default=None, metavar="TTF경로",
                        help="자막 폰트 파일 (기본: 맑은고딕/Pretendard-ExtraBold)")
    parser.add_argument("--bgm", default=None, metavar="이름",
                        help="library/bgm의 곡 지정 (기본: 정렬 첫 곡)")
    parser.add_argument("--caption-size", type=int, default=None,
                        help="자막 fontsize (기본: 쇼츠 44 / 가로 기본값)")
    args = parser.parse_args()

    cut_ranges = [tuple(map(float, s.split("-"))) for s in args.cut]
    sfx_overrides = {float(t): n.strip() for t, n in (s.split(":") for s in args.sfx)}
    highlights = [tuple(map(float, s.split("-"))) for s in args.highlight]
    captions = []
    for spec in args.caption:
        rng, text = spec.split(":", 1)
        a, b = rng.split("-")
        captions.append((float(a), float(b), text.strip()))
    extra_sfx = [(float(t), n.strip()) for t, n in (s.split(":") for s in args.add_sfx)]
    sfx_volumes = {float(t): float(f) for t, f in (s.split(":") for s in args.sfx_vol)}
    ducks = []
    for spec in args.duck:
        rng, factor = spec.split(":")
        a, b = rng.split("-")
        ducks.append((float(a), float(b), float(factor)))
    boosts = []
    for spec in args.boost:
        rng, factor = spec.split(":")
        a, b = rng.split("-")
        boosts.append((float(a), float(b), float(factor)))

    video = Path(args.video).resolve()
    print(f"[1/3] 분석 중... ({video.name})")
    info = probe(str(video))
    events = detect_events(str(video), max_events=args.max_sfx)
    pieces = _layout_pieces(info.duration, cut_ranges, highlights)
    total = (pieces[-1].tl_start_us + pieces[-1].tl_dur_us) / 1_000_000

    library = ensure_library()
    auto = [(t, p) for t, p in _assign_sfx(events, library / "sfx", sfx_overrides)
            if not _in_cut(t, cut_ranges, CUT_EVENT_MARGIN)]
    manual = [(t, library / "sfx" / f"{n}.wav") for t, n in extra_sfx]
    placements = []
    for src_t, sfx_path in sorted(auto + manual):
        tl_t = _to_timeline(src_t, pieces)
        if tl_t is not None:
            factor = next((f for t, f in sfx_volumes.items()
                           if abs(t - src_t) <= OVERRIDE_TOLERANCE), 1.0)
            placements.append((tl_t, sfx_path, SFX_VOLUME * factor))
            vol_note = f" (볼륨 {factor:.0%})" if factor != 1.0 else ""
            print(f"      ♪ {tl_t:5.1f}s  {sfx_path.stem}{vol_note}")

    print(f"[2/3] 렌더링 중... (타임라인 {total:.1f}s, 1080p)")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        filter_script, extra = build_filter(
            pieces, captions, placements, total, tmp, n_video_inputs_offset=1,
            freeze=args.freeze, vertical=args.vertical, subject_x=args.subject_x,
            src_portrait=info.height > info.width, ducks=ducks, boosts=boosts,
            font=Path(args.font).resolve() if args.font else None, bgm_name=args.bgm,
            caption_size=args.caption_size)
        script_path = tmp / "filter.txt"
        script_path.write_text(filter_script, encoding="utf-8")

        cmd = [config.FFMPEG, "-y", "-v", "error", "-stats", "-i", str(video)]
        for f in extra:
            cmd += ["-i", f]
        cmd += ["-filter_complex_script", str(script_path),
                "-map", "[vt%d]" % (len(captions) - 1) if captions else "[vc]",
                "-map", "[am]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                args.output]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=1800, cwd=str(tmp))
        if result.returncode != 0:
            print(result.stderr[:2500])
            sys.exit("렌더링 실패")

    out = Path(args.output)
    print(f"[3/3] 완료: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
