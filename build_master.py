"""여러 클립에서 구간을 뽑아 피사체 추적 세로(9:16) 마스터를 합성.

사용: python build_master.py <출력.mp4> --seg "클립경로|시작|끝" ...
각 세그먼트는 움직임 추적으로 크롭 창이 피사체를 따라간다.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app import config
from app.track_subject import crop_expr, track

OUT_W, OUT_H = 1080, 1920
VH = 0.8  # (tight 모드) 원본 높이 중 사용할 비율 — 낮을수록 줌인

# 기본은 wide(줌아웃) 모드: 피사체 중심 정사각(전체 높이) 크롭을 화면 폭에 맞추고
# 위아래는 블러 배경으로 채운다. 피사체가 절대 잘리지 않는다.
FG_H = OUT_W          # 전경(정사각) 높이 = 1080
FG_Y = (OUT_H - FG_H) // 2  # 세로 중앙 배치 오프셋 = 420


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--seg", action="append", required=True, metavar="경로|시작|끝")
    parser.add_argument("--tight", action="store_true",
                        help="구버전 꽉찬 크롭 (피사체가 잘릴 수 있음). 기본은 줌아웃+블러 배경")
    args = parser.parse_args()

    segs = []
    for spec in args.seg:
        path, a, b = spec.rsplit("|", 2)
        segs.append((path, float(a), float(b)))

    inputs: list[str] = []
    input_idx: dict[str, int] = {}
    lines = []
    pairs = []
    cursor = 0.0
    for i, (path, a, b) in enumerate(segs):
        if path not in input_idx:
            input_idx[path] = len(inputs)
            inputs.append(path)
        src = input_idx[path]

        print(f"[추적 {i + 1}/{len(segs)}] {Path(path).name} {a}~{b}s")
        knots = track(path, a, b)
        ex = crop_expr(knots, "x")
        ey = crop_expr(knots, "y")

        if args.tight:
            lines.append(
                f"[{src}:v]trim={a}:{b},setpts=PTS-STARTPTS,"
                f"crop=ih*{VH * 9 / 16:.4f}:ih*{VH}:x='{ex}':y='{ey}',"
                f"scale={OUT_W}:{OUT_H}[v{i}];")
        else:
            # 줌아웃: 정사각(전체 높이) 추적 크롭 → 폭 맞춤 + 블러 배경
            lines.append(
                f"[{src}:v]trim={a}:{b},setpts=PTS-STARTPTS,"
                f"crop=ih:ih:x='{ex}':y=0,split=2[t{i}a][t{i}b];")
            lines.append(
                f"[t{i}a]scale={OUT_H}:{OUT_H},crop={OUT_W}:{OUT_H}:{FG_Y}:0,"
                f"boxblur=20:2,eq=brightness=-0.06[bg{i}];")
            lines.append(f"[t{i}b]scale={OUT_W}:{FG_H}[fg{i}];")
            lines.append(f"[bg{i}][fg{i}]overlay=0:{FG_Y}[v{i}];")
        lines.append(f"[{src}:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];")
        pairs.append(f"[v{i}][a{i}]")
        print(f"        마스터 {cursor:.1f}s ~ {cursor + b - a:.1f}s")
        cursor += b - a
    lines.append(f"{''.join(pairs)}concat=n={len(segs)}:v=1:a=1[v][a]")

    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "filter.txt"
        script.write_text("\n".join(lines), encoding="utf-8")
        cmd = [config.FFMPEG, "-y", "-v", "error"]
        for f in inputs:
            cmd += ["-i", f]
        cmd += ["-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                "-c:a", "aac", "-b:a", "192k", args.output]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=1800)
        if result.returncode != 0:
            print(result.stderr[:2500])
            sys.exit("합성 실패")
    print(f"완료: {args.output} (총 {cursor:.1f}s)")


if __name__ == "__main__":
    main()
