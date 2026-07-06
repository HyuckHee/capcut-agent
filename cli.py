"""1단 CLI: python cli.py <영상.mp4> → CapCut 점프컷 드래프트 생성."""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 cp949 대응

from app import config
from app.silence_detect import keep_segments
from app.build_draft import build_jumpcut_draft


def main() -> None:
    parser = argparse.ArgumentParser(description="캡컷 에이전트 — 무음 점프컷 드래프트 생성")
    parser.add_argument("video", help="입력 영상 (mp4/mov)")
    parser.add_argument("--noise-db", type=float, default=config.SILENCE_NOISE_DB,
                        help=f"무음 임계값 dB (기본 {config.SILENCE_NOISE_DB})")
    parser.add_argument("--min-silence", type=float, default=config.SILENCE_MIN_DUR,
                        help=f"무음 최소 길이 초 (기본 {config.SILENCE_MIN_DUR})")
    parser.add_argument("--name", default=None, help="드래프트 이름 (기본: agent_MMDD_HHMMSS)")
    args = parser.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"파일 없음: {video}")

    print(f"[1/2] 무음 감지 중... ({video.name})")
    segments, info = keep_segments(str(video), noise_db=args.noise_db, min_dur=args.min_silence)

    total = info.duration
    kept = sum(e - s for s, e in segments)
    print(f"      영상 {total:.1f}s / 보존 {kept:.1f}s / 컷 {total - kept:.1f}s "
          f"({len(segments)}개 구간, {info.width}x{info.height} {info.fps:.2f}fps)")

    print("[2/2] CapCut 드래프트 생성 중...")
    name = build_jumpcut_draft(str(video), segments, info, args.name)

    print(f"\n완료 — CapCut을 열고 프로젝트 '{name}' 을 재생해서 검증하세요.")
    print("(CapCut이 이미 열려 있었다면 프로젝트 목록을 새로고침하거나 재시작 필요)")


if __name__ == "__main__":
    main()
