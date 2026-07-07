"""AI 초안 — 완성 영상을 촘촘한 타임스탬프 몽타주로 만들어 Claude(헤드리스)가 실제로 '보게' 하고,
2단계로 (1) 화면 관찰 로그 → (2) 관찰에 앵커링한 나레이션·제목을 받는다.

핵심: 구간당 1장이 아니라 ~1초 간격으로 프레임을 뽑아 화면 전개를 실제로 읽는다. 줄거리를 주면
1단계에서 '요약 줄거리 ↔ 관찰 내용' 일치 검사도 한다. Claude Code CLI(`claude -p`)라 Max 구독으로
커버되고 API 과금이 없다.
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


import math

FONT_SRC = ROOT / "library" / "fonts" / "Pretendard-ExtraBold.otf"
TARGET_FRAMES = 28     # 완성 영상 전체에서 뽑을 대략적 프레임 수 (촘촘히 = 영상을 실제로 봄)
TILES_PER_IMG = 12     # 몽타주 한 장당 칸 수 (4×3)


def _sample_points(segments: list[dict], interval: float) -> list[tuple[float, str, float]]:
    """완성 영상 타임라인을 interval초 간격으로 샘플 → [(출력시각, 소스경로, 소스시각)].

    나레이션 at은 완성영상 기준 초이므로, 샘플도 컷·배속을 반영한 출력 타임라인 기준으로 뽑아야
    프레임 라벨의 시각과 나레이션 시각이 같은 좌표계가 된다.
    """
    pts, cursor = [], 0.0
    for s in segments:
        a, b, spd = s["a"], s["b"], (s.get("spd") or 1)
        length = (b - a) / spd
        t = 0.0
        while t < length - 1e-6:
            pts.append((round(cursor + t, 1), s["path"], round(a + t * spd, 2)))
            t += interval
        cursor += length
    return pts


def _render_montages(points: list[tuple], workdir: Path, prefix: str) -> list[dict]:
    """points=[(라벨초, 소스경로, 소스초)] → 타임스탬프 몽타주 이미지들. [{name, stamps}] 반환.

    각 칸 좌상단에 라벨 시각(초)을 노란 글씨로 박아 Claude가 시각을 앵커로 쓸 수 있게 한다.
    360×360 letterbox라 세로/가로 소스 모두 타일 정렬된다.
    """
    if not (workdir / "font.otf").exists():
        shutil.copy(FONT_SRC, workdir / "font.otf")  # drawtext는 상대 폰트경로 필요 (윈도 C:\ 이스케이프 회피)
    for k, (lab, src, st) in enumerate(points):
        vf = ("scale=360:360:force_original_aspect_ratio=decrease,"
              "pad=360:360:(ow-iw)/2:(oh-ih)/2:color=black,"
              f"drawtext=fontfile=font.otf:text='{lab:.1f}s':x=8:y=6:fontsize=30:"
              "fontcolor=yellow:box=1:boxcolor=black@0.6:boxborderw=5")
        subprocess.run(
            [config.FFMPEG, "-y", "-v", "error", "-ss", f"{st:.2f}", "-i", src,
             "-vf", vf, "-frames:v", "1", "-q:v", "4", f"{prefix}f{k:03d}.jpg"],
            capture_output=True, timeout=120, check=True, cwd=str(workdir))

    montages = []
    for g in range(0, len(points), TILES_PER_IMG):
        grp = points[g:g + TILES_PER_IMG]
        gdir = workdir / f"{prefix}g{g}"
        gdir.mkdir(exist_ok=True)
        for j, k in enumerate(range(g, g + len(grp))):
            shutil.copy(workdir / f"{prefix}f{k:03d}.jpg", gdir / f"{j}.jpg")
        cols = 4
        rows = math.ceil(len(grp) / cols)
        name = f"{prefix}montage{len(montages)}.jpg"
        subprocess.run(
            [config.FFMPEG, "-y", "-v", "error", "-start_number", "0",
             "-i", str(gdir / "%d.jpg"), "-frames:v", "1",
             "-vf", f"tile={cols}x{rows}", str(workdir / name)],
            capture_output=True, timeout=120, check=True)
        montages.append({"name": name, "stamps": [round(p[0], 1) for p in grp]})
    return montages


def build_montages(segments: list[dict], workdir: Path) -> tuple[list[dict], float]:
    """완성(편집) 영상을 완성영상 기준 시각 몽타주로. (montages, 총길이)."""
    workdir.mkdir(parents=True, exist_ok=True)
    total = sum((s["b"] - s["a"]) / (s.get("spd") or 1) for s in segments)
    interval = max(1.0, total / TARGET_FRAMES)
    pts = _sample_points(segments, interval)
    return _render_montages(pts, workdir, ""), round(total, 1)


def build_source_montages(clip: dict, workdir: Path, prefix: str,
                          target_frames: int = 44) -> list[dict]:
    """원본 클립 '전체'를 원본 기준 시각 몽타주로. clip={path, duration}."""
    workdir.mkdir(parents=True, exist_ok=True)
    dur = float(clip["duration"])
    interval = max(0.8, dur / target_frames)
    pts, t = [], 0.0
    while t < dur - 1e-6:
        pts.append((round(t, 1), clip["path"], round(t, 2)))
        t += interval
    return _render_montages(pts, workdir, prefix)


def observe_prompt(montages: list[dict], synopsis: str) -> str:
    """1단계: 화면에서 실제로 보이는 것을 시각 순 관찰 로그로."""
    lines = [
        "아래 몽타주 이미지들을 Read 도구로 전부 열어 확인해라. 각 칸 좌상단의 노란 숫자는",
        "완성 영상 기준 시각(초)이다. 시간 순서대로, 화면에 '실제로 보이는 것'만 관찰 로그로 적어라.",
        "추측·상상·해석은 금지. 안 보이면 안 보인다고 해라.",
        "",
        "[몽타주 이미지]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    check_field = ""
    if synopsis:
        lines += [
            "",
            "[사용자가 제공한 줄거리] — 아래 줄거리가 네가 실제로 관찰한 화면과 맞는지 판단해라.",
            "어긋나는 부분(줄거리엔 있는데 화면엔 없음, 또는 화면과 반대)이 있으면 구체적으로 지적해라.",
            synopsis,
        ]
        check_field = ', "synopsis_check": {"match": true, "note": "일치/불일치 근거 한두 문장"}'
    lines += [
        "",
        "이미지를 모두 확인한 뒤, 다른 말 없이 아래 JSON만 출력해라:",
        '{"observations": [{"t": 2.0, "see": "그 시각에 화면에 보이는 것"}]' + check_field + "}",
    ]
    return "\n".join(lines)


def narrate_prompt(observations: list[dict], style: str, synopsis: str, total: float) -> str:
    """2단계: 관찰 로그에 앵커링한 나레이션·제목."""
    obs_text = "\n".join(f"- {o.get('t')}s: {o.get('see', '')}" for o in observations)
    lines = [
        "너는 유튜브 쇼츠 나레이터다. 아래 '화면 관찰 로그'는 영상에서 실제로 보이는 내용이다.",
        "이 관찰에 근거해 나레이션을 써라. 각 나레이션 at은 관찰된 시각에 맞추고, 그 시각에",
        "화면에 보이는 것과 일치하는 내용을 말해라. 관찰 로그에 없는 장면을 지어내면 안 된다.",
        "",
        f"[채널 스타일]\n{style}",
        "",
        "[화면 관찰 로그]",
        obs_text,
    ]
    if synopsis:
        lines += [
            "",
            "[줄거리·맥락] 화면에 안 보이는 인물관계·반전 '해석'에만 참고해라. 장면 묘사는 관찰 로그와",
            "일치시키고, 복선은 반전 장면(관찰 로그상 후반) 전에 깔아라.",
            synopsis,
        ]
    lines += [
        "",
        "[나레이션 규칙]",
        "- 문장당 2~3초 분량의 짧은 한 문장. 나레이션 사이 최소 3초 간격.",
        f"- at은 0.5 ~ {max(0.5, total - 2):.1f}초 범위, 관찰된 시각 근처에 배치.",
        "",
        "아래 JSON만 출력해라:",
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
    """segments: [{path, a, b, spd, tags}] → {title, out_name, narrs, observations, synopsis_check?}.

    2단계: (1) 촘촘한 몽타주로 화면 관찰 로그 작성 (줄거리 제공 시 일치 검사) →
           (2) 관찰 로그에 앵커링한 나레이션·제목 작성.
    """
    workdir = FRAME_DIR / uuid.uuid4().hex[:8]
    montages, total = build_montages(segments, workdir)

    obs = run_claude(observe_prompt(montages, synopsis), workdir)
    observations = obs.get("observations", [])

    data = run_claude(narrate_prompt(observations, style, synopsis, total), workdir)
    narrs = [{"at": float(n["at"]), "text": str(n["text"]).strip()}
             for n in data.get("narrs", []) if str(n.get("text", "")).strip()]
    narrs.sort(key=lambda n: n["at"])

    result = {"title": data.get("title", ""), "out_name": data.get("out_name", ""),
              "narrs": narrs, "observations": observations}
    if synopsis and isinstance(obs.get("synopsis_check"), dict):
        result["synopsis_check"] = obs["synopsis_check"]
    return result


# ── AI 말풍선: Claude가 순간+대사를 정하고, 피사체 추적이 좌표를 찍는다
BUBBLE_LOG = ROOT / "logs" / "bubbles.jsonl"


def log_bubbles(source: str, items: list[dict]) -> None:
    """말풍선 사용 로그 적재 — source: 'ai'(제안) / 'final'(렌더에 실제 사용).

    final 로그는 다음 AI 제안의 few-shot 예시가 되어 쓸수록 채널 말투에 수렴한다.
    """
    if not items:
        return
    BUBBLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with BUBBLE_LOG.open("a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps({"source": source, **it}, ensure_ascii=False) + "\n")


def _bubble_examples(limit: int = 14) -> list[dict]:
    """최근 확정(final) 말풍선 — AI 프롬프트 few-shot용."""
    if not BUBBLE_LOG.exists():
        return []
    out = []
    for ln in BUBBLE_LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if d.get("source") == "final" and d.get("text"):
            out.append(d)
    return out[-limit:]


def bubble_prompt(montages: list[dict], style: str, synopsis: str,
                  total: float, examples: list[dict]) -> str:
    lines = [
        "너는 반려동물 쇼츠의 말풍선 자막 작가다. 아래 몽타주 이미지를 Read 도구로 전부 확인해라.",
        "각 칸 좌상단의 노란 숫자는 완성 영상 기준 시각(초)이다.",
        "",
        "[몽타주]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    lines += [
        "",
        f"[채널 스타일]\n{style}",
    ]
    if synopsis:
        lines += ["", "[맥락]", synopsis]
    if examples:
        lines += ["", "[이 채널에서 실제 사용된 말풍선 예시 — 말투·길이를 여기에 맞춰라]"]
        for e in examples:
            lines.append(f"- \"{e['text']}\"")
    lines += [
        "",
        "[임무] 화면에서 실제로 보이는 행동에 맞춰 말풍선을 제안해라.",
        "- 강아지 1인칭 짧은 대사(예: 내 인형이야!) 또는 효과음(예: 앙!, 킁킁, 쿨쿨)",
        "- 텍스트 2~8자. 이모지는 어울릴 때만 끝에 1개 (예: 저리 비켜😤)",
        f"- 개수는 {max(2, int(total // 8))}~{max(3, int(total // 5))}개, 서로 3초 이상 간격",
        "- at은 그 행동이 보이는 시각, dur은 1.5~2.5초",
        "- 보이지 않는 행동을 지어내지 말 것",
        "",
        "아래 JSON만 출력해라:",
        '{"bubbles": [{"at": 3.2, "dur": 1.8, "text": "앙!"}]}',
    ]
    return "\n".join(lines)


def _out_to_src(segments: list[dict], t: float) -> tuple[dict, float]:
    """완성영상 시각 → (세그먼트, 원본 시각)."""
    cursor = 0.0
    for s in segments:
        spd = s.get("spd") or 1
        length = (s["b"] - s["a"]) / spd
        if t < cursor + length or s is segments[-1]:
            return s, s["a"] + max(0.0, min(t - cursor, length)) * spd
        cursor += length
    return segments[-1], segments[-1]["b"]


def ai_bubbles(segments: list[dict], style: str, synopsis: str = "") -> dict:
    """segments → {bubbles:[{a,b,text,fx,fy}]}. 텍스트·시각은 Claude, 좌표는 피사체 추적."""
    from .track_subject import track

    workdir = FRAME_DIR / ("bub_" + uuid.uuid4().hex[:8])
    montages, total = build_montages(segments, workdir)
    data = run_claude(
        bubble_prompt(montages, style, synopsis, total, _bubble_examples()), workdir)

    track_cache: dict[int, list] = {}
    bubbles = []
    for b in data.get("bubbles", []):
        at = float(b.get("at", 0))
        dur = min(2.5, max(1.2, float(b.get("dur", 1.8))))
        text = str(b.get("text", "")).strip()
        if not text or at >= total:
            continue
        seg, src_t = _out_to_src(segments, at + dur / 2)  # 표시 구간 중간 시점의 피사체 위치
        si = segments.index(seg)
        if si not in track_cache:
            try:
                track_cache[si] = track(seg["path"], seg["a"], seg["b"])
            except Exception:
                track_cache[si] = [(0.0, 0.5, 0.6)]
        knots = track_cache[si]
        rel = src_t - seg["a"]
        # 절점 선형보간으로 피사체 중심 → 머리 위쪽에 오프셋
        cx, cy = knots[-1][1], knots[-1][2]
        for (t0, x0, y0), (t1, x1, y1) in zip(knots, knots[1:]):
            if t0 <= rel <= t1:
                r = (rel - t0) / max(1e-6, t1 - t0)
                cx, cy = x0 + (x1 - x0) * r, y0 + (y1 - y0) * r
                break
        else:
            if rel < knots[0][0]:
                cx, cy = knots[0][1], knots[0][2]
        fx = min(0.85, max(0.15, cx))          # 텍스트가 화면 밖으로 안 잘리게
        fy = min(0.80, max(0.10, cy - 0.11))   # 피사체 위쪽
        bubbles.append({"a": round(at, 1), "b": round(min(total, at + dur), 1),
                        "text": text, "fx": round(fx, 3), "fy": round(fy, 3)})
    bubbles.sort(key=lambda x: x["a"])
    log_bubbles("ai", bubbles)
    return {"bubbles": bubbles}


def recommend_prompt(clip_montages: list[dict], synopsis: str, style: str,
                     target_len: float, max_len: float) -> str:
    """원본 전체 관찰 몽타주 + 줄거리 → 편집 구간 추천 프롬프트."""
    lines = [
        "너는 유튜브 쇼츠 편집자다. 아래는 '원본 영상 전체'를 시간순으로 훑은 몽타주다.",
        "각 칸 좌상단의 노란 숫자는 그 클립의 원본 기준 시각(초)이다. Read 도구로 전부 확인해라.",
        "",
        "[원본 몽타주]",
    ]
    for cm in clip_montages:
        lines.append(f"■ 클립 {cm['ci']} (길이 {cm['duration']:.0f}초):")
        for m in cm["montages"]:
            lines.append(f"  - {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    if synopsis:
        lines += ["", "[줄거리]", synopsis]
    lines += [
        "",
        f"[채널 스타일]\n{style}",
        "",
        "[임무] 위 줄거리의 흐름(도입 → 복선 → 반전 → 결말)이 담기도록, 원본에서 쇼츠에 넣을",
        "구간을 골라라. 화면에 실제로 보이는 것을 근거로 고르되, 어느 장면이 어느 대목인지는 줄거리로 해석해라.",
        "[규칙]",
        f"- 선택 구간 총합 {target_len:.0f}초 내외, 최대 {max_len:.0f}초 (쇼츠 한도).",
        "- 반전·결정적 순간은 반드시 포함. 복선 장면을 반전보다 앞에 배치.",
        "- 각 구간 2~10초, 시간순. 각 클립 원본 시각 기준 a<b.",
        "- 화면으로 확인 안 되는 장면을 지어내지 말 것. 줄거리에만 있고 화면에 없으면 note에 밝혀라.",
        "",
        "아래 JSON만 출력해라:",
        '{"segments": [{"clip": 0, "a": 0.0, "b": 5.0, "role": "도입", "why": "화면 근거"}],'
        ' "note": "편집 의도/한계 한두 문장"}',
    ]
    return "\n".join(lines)


def recommend_edit(clips: list[dict], synopsis: str, style: str,
                   target_len: float = 45.0, max_len: float = 59.0) -> dict:
    """원본 클립 전체 + 줄거리 → 편집 구간 추천. clips=[{path, duration}].

    반환: {segments:[{clip, a, b, role, why}], note}. clip은 clips 리스트 인덱스.
    """
    workdir = FRAME_DIR / ("rec_" + uuid.uuid4().hex[:8])
    clip_montages = []
    for ci, c in enumerate(clips):
        ms = build_source_montages(c, workdir, prefix=f"c{ci}_")
        clip_montages.append({"ci": ci, "duration": float(c["duration"]), "montages": ms})

    data = run_claude(
        recommend_prompt(clip_montages, synopsis, style, target_len, max_len), workdir)

    segments = []
    for s in data.get("segments", []):
        ci = int(s.get("clip", 0))
        if not (0 <= ci < len(clips)):
            continue
        a, b = float(s["a"]), float(s["b"])
        a = max(0.0, min(a, clips[ci]["duration"]))
        b = max(a + 0.5, min(b, clips[ci]["duration"]))
        segments.append({"clip": ci, "a": round(a, 1), "b": round(b, 1),
                         "role": str(s.get("role", "")), "why": str(s.get("why", ""))})
    return {"segments": segments, "note": data.get("note", "")}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if spec.get("mode") == "recommend":
        print(json.dumps(recommend_edit(spec["clips"], spec.get("synopsis", ""),
                                         spec.get("style", "")), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(ai_draft(spec["segments"], spec["style"], spec.get("synopsis", "")),
                         ensure_ascii=False, indent=1))
