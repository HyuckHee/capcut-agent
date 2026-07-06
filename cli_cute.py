"""귀여움 모드 CLI: python cli_cute.py <영상.mp4>

컷 없이 영상 전체를 보존하고, 움직임(행동) 타이밍에 효과음 + 잔잔한 BGM을 얹는다.
"""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.build_cute_draft import build_cute_draft
from app.motion_detect import detect_events
from app.silence_detect import probe


def main() -> None:
    parser = argparse.ArgumentParser(description="캡컷 에이전트 — 귀여움 모드 (행동 효과음 + BGM)")
    parser.add_argument("video", help="입력 영상 (mp4/mov)")
    parser.add_argument("--max-sfx", type=int, default=8, help="효과음 최대 개수 (기본 8)")
    parser.add_argument("--no-bgm", action="store_true", help="BGM 트랙 생략")
    parser.add_argument("--name", default=None, help="드래프트 이름 (기본: cute_MMDD_HHMMSS)")
    parser.add_argument("--cut", action="append", default=[], metavar="시작-끝",
                        help="잘라낼 구간 (초). 예: --cut 5.35-5.85 (반복 가능)")
    parser.add_argument("--sfx", action="append", default=[], metavar="시각:이름",
                        help="특정 이벤트의 효과음 지정. 예: --sfx 13.0:wiggle (반복 가능)")
    parser.add_argument("--highlight", action="append", default=[], metavar="시작-끝",
                        help="강조 구간: 0.5배 슬로우 + 줌인. 예: --highlight 5.85-8.3 (반복 가능)")
    parser.add_argument("--caption", action="append", default=[], metavar="시작-끝:텍스트",
                        help='자막. 예: --caption "5.9-7.0:어? 나 봤어?" (반복 가능)')
    parser.add_argument("--add-sfx", action="append", default=[], metavar="시각:이름",
                        help="움직임 이벤트와 무관하게 효과음 추가. 예: --add-sfx 5.95:sparkle (반복 가능)")
    parser.add_argument("--sfx-vol", action="append", default=[], metavar="시각:배율",
                        help="특정 효과음 볼륨 배율. 예: --sfx-vol 0.6:0.5 (반복 가능)")
    args = parser.parse_args()

    cut_ranges = []
    for spec in args.cut:
        a, b = spec.split("-")
        cut_ranges.append((float(a), float(b)))
    sfx_overrides = {}
    for spec in args.sfx:
        t, name = spec.split(":")
        sfx_overrides[float(t)] = name.strip()
    highlights = []
    for spec in args.highlight:
        a, b = spec.split("-")
        highlights.append((float(a), float(b)))
    captions = []
    for spec in args.caption:
        rng, text = spec.split(":", 1)
        a, b = rng.split("-")
        captions.append((float(a), float(b), text.strip()))
    extra_sfx = []
    for spec in args.add_sfx:
        t, name = spec.split(":")
        extra_sfx.append((float(t), name.strip()))
    sfx_volumes = {float(t): float(f) for t, f in (s.split(":") for s in args.sfx_vol)}

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"파일 없음: {video}")

    print(f"[1/3] 영상 분석 중... ({video.name})")
    info = probe(str(video))
    print(f"      {info.duration:.1f}s, {info.width}x{info.height} {info.fps:.2f}fps")

    print("[2/3] 움직임(행동) 감지 중...")
    events = detect_events(str(video), max_events=args.max_sfx)
    for ev in events:
        print(f"      {ev.time:5.1f}s  세기 {ev.strength:.2f}")
    if not events:
        print("      감지된 움직임 없음 — 효과음 없이 BGM만 얹습니다.")

    print("[3/3] CapCut 드래프트 생성 중...")
    name, placed = build_cute_draft(str(video), events, info, args.name,
                                    with_bgm=not args.no_bgm,
                                    cut_ranges=cut_ranges, sfx_overrides=sfx_overrides,
                                    highlights=highlights, captions=captions,
                                    extra_sfx=extra_sfx, sfx_volumes=sfx_volumes)
    for a, b in cut_ranges:
        print(f"      ✂ {a:.2f}s ~ {b:.2f}s 컷")
    for a, b in highlights:
        print(f"      ★ {a:.2f}s ~ {b:.2f}s 슬로우 0.5x + 줌인")
    for a, b, text in captions:
        print(f"      💬 {a:.1f}~{b:.1f}s  {text}")
    for t, sfx in placed:
        print(f"      {t:5.1f}s  ♪ {sfx}")

    print(f"\n완료 - CapCut을 열고 프로젝트 '{name}' 을 재생해서 검증하세요.")
    print("(효과음/BGM 교체: library/sfx, library/bgm 폴더에 같은 이름의 wav를 덮어쓰면 됩니다)")


if __name__ == "__main__":
    main()
