"""AI 초안 — 세그먼트 대표 프레임을 Claude(헤드리스)에게 보여주고 제목·나레이션을 받는다.

Claude Code CLI(`claude -p`)를 사용하므로 Max 구독으로 커버되고 API 과금이 없다.
"""
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from . import config

ROOT = Path(__file__).resolve().parent.parent
FRAME_DIR = ROOT / ".cache" / "aidraft"

CLAUDE_TIMEOUT = 420  # 프레임 여러 장 읽으면 수 분 걸릴 수 있음


def find_claude() -> str | None:
    exe = shutil.which("claude")
    if exe:
        return exe
    # 데스크톱 앱 번들 CLI. 앱은 MSIX 패키지라 Roaming\Claude 경로는 앱 내부에서만 보이고,
    # 일반 프로세스(웹 서버 등)에서는 Packages\...\LocalCache 실제 경로로 접근해야 한다.
    import os
    roots = [Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"]
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roots += [p / "LocalCache" / "Roaming" / "Claude" / "claude-code"
              for p in local.glob("Packages/Claude_*")]
    cands = [c for r in roots for c in r.glob("*/claude.exe")]
    cands.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", p.parent.name)] or [0])
    return str(cands[-1]) if cands else None


def extract_frames(segments: list[dict], workdir: Path) -> list[dict]:
    """세그먼트별 대표 프레임 추출. [{idx, out_a, out_b, frames:[파일명…], tags}] 반환."""
    workdir.mkdir(parents=True, exist_ok=True)
    out, cursor = [], 0.0
    for i, s in enumerate(segments):
        a, b, spd = s["a"], s["b"], s.get("spd", 1) or 1
        length = (b - a) / spd
        # 6초 넘는 구간은 2장, 아니면 중간 1장
        ts = [a + (b - a) * 0.33, a + (b - a) * 0.75] if b - a > 6 else [(a + b) / 2]
        frames = []
        for k, t in enumerate(ts):
            name = f"seg{i + 1:02d}_{k}.jpg"
            subprocess.run(
                [config.FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", s["path"],
                 "-vf", "scale=560:-2", "-frames:v", "1", "-q:v", "5", str(workdir / name)],
                capture_output=True, timeout=120, check=True)
            frames.append(name)
        out.append({"idx": i + 1, "out_a": round(cursor, 1), "out_b": round(cursor + length, 1),
                    "frames": frames, "tags": s.get("tags", "")})
        cursor += length
    return out


def build_prompt(seg_info: list[dict], style: str, total: float, synopsis: str = "") -> str:
    lines = [
        "너는 유튜브 쇼츠 편집 어시스턴트다. 아래 세그먼트별 대표 프레임 이미지를 Read 도구로 전부 확인한 뒤,",
        "실제로 보이는 것만 근거로 제목과 나레이션을 작성해라. 프레임에서 보이지 않는 시각적 상황을 지어내면 안 된다.",
        "",
        f"[채널 스타일]\n{style}",
    ]
    if synopsis:
        lines += [
            "",
            "[줄거리·맥락] 사용자가 제공한 배경 정보다. 화면에 안 보이는 인물 관계·반전·결말의 근거로 삼되,",
            "나레이션에 쓰는 장면 묘사 자체는 반드시 프레임에 보이는 것과 일치해야 한다. 복선은 반전 장면 전에 깔아라.",
            synopsis,
        ]
    lines += [
        "",
        f"[타임라인] 총 {total:.0f}초, 세그먼트 {len(seg_info)}개 (시각은 완성 영상 기준):",
    ]
    for s in seg_info:
        lines.append(f"- 세그먼트{s['idx']}: {s['out_a']}~{s['out_b']}초 {s['tags']} → 프레임: {', '.join(s['frames'])}")
    lines += [
        "",
        "[나레이션 규칙]",
        "- 문장당 2~3초 분량의 짧은 한 문장. 나레이션 사이 최소 3초 간격.",
        "- 각 나레이션의 at(초)은 해당 장면 세그먼트 구간 안에 둘 것.",
        "- 첫 나레이션은 0.5초 부근에서 시작. 마지막 나레이션은 영상 끝 3초 전 이내.",
        "",
        "이미지를 모두 확인한 뒤, 다른 말 없이 아래 JSON만 출력해라:",
        '{"title": "윗줄|아랫줄", "out_name": "출력파일명", "narrs": [{"at": 0.5, "text": "..."}]}',
    ]
    return "\n".join(lines)


def run_claude(prompt: str, cwd: Path) -> dict:
    exe = find_claude()
    if not exe:
        raise RuntimeError("Claude Code CLI(claude)를 찾을 수 없습니다. PATH를 확인하세요.")
    proc = subprocess.run(
        [exe, "-p", prompt, "--output-format", "json", "--allowedTools", "Read"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=CLAUDE_TIMEOUT, cwd=str(cwd), shell=False)
    if "Not logged in" in proc.stdout:
        raise RuntimeError("Claude CLI 로그인 필요 — 프로젝트 폴더의 'AI 로그인.bat'을 한 번 실행해서 /login 하세요 (Max 구독 계정, 최초 1회)")
    if proc.returncode != 0:
        raise RuntimeError(f"claude 실행 실패: {(proc.stderr or proc.stdout)[:400]}")
    result = json.loads(proc.stdout).get("result", "")
    m = re.search(r"\{.*\}", result, re.DOTALL)
    if not m:
        raise RuntimeError(f"JSON 응답을 찾지 못함: {result[:400]}")
    return json.loads(m.group(0))


def ai_draft(segments: list[dict], style: str, synopsis: str = "") -> dict:
    """segments: [{path, a, b, spd, tags}] → {title, out_name, narrs}."""
    workdir = FRAME_DIR / uuid.uuid4().hex[:8]
    seg_info = extract_frames(segments, workdir)
    total = seg_info[-1]["out_b"] if seg_info else 0.0
    data = run_claude(build_prompt(seg_info, style, total, synopsis), workdir)
    narrs = [{"at": float(n["at"]), "text": str(n["text"]).strip()}
             for n in data.get("narrs", []) if str(n.get("text", "")).strip()]
    narrs.sort(key=lambda n: n["at"])
    return {"title": data.get("title", ""), "out_name": data.get("out_name", ""),
            "narrs": narrs}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(ai_draft(spec["segments"], spec["style"], spec.get("synopsis", "")),
                     ensure_ascii=False, indent=1))
