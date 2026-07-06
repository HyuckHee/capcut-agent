import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""드래프트 자동 내보내기: python export_video.py <드래프트이름> <출력.mp4> [--res 1080P] [--fps 60fps]

주의: 실행 중 CapCut 창을 자동 조작하므로 마우스/키보드를 건드리지 말 것.
CapCut은 홈(프로젝트 목록) 화면에 있어야 가장 안정적이다.
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from pycapcut.jianying_controller import ExportResolution, ExportFramerate
from app.exporter import CapCutController


def main() -> None:
    parser = argparse.ArgumentParser(description="캡컷 에이전트 — 드래프트 자동 내보내기")
    parser.add_argument("draft", help="드래프트 이름")
    parser.add_argument("output", help="출력 mp4 경로")
    parser.add_argument("--res", default=None, choices=[r.value for r in ExportResolution],
                        help="해상도 (기본: CapCut 현재 설정 유지)")
    parser.add_argument("--fps", default=None, choices=[f.value for f in ExportFramerate],
                        help="프레임레이트 (기본: CapCut 현재 설정 유지)")
    args = parser.parse_args()

    res = next((r for r in ExportResolution if r.value == args.res), None)
    fps = next((f for f in ExportFramerate if f.value == args.fps), None)

    print(f"CapCut 자동 조작 시작 — 완료까지 마우스/키보드를 건드리지 마세요.")
    controller = CapCutController()
    controller.export_draft(args.draft, args.output, resolution=res, framerate=fps)
    print(f"\n완료: {args.output}")


if __name__ == "__main__":
    main()
