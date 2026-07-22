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

# 작업별 모델 분리 — 품질이 중요한 작문·스토리 설계만 큰 모델, 나머지는 빠른 모델
# (별칭은 CLI가 최신 버전으로 해석: sonnet→Sonnet 5, opus→Opus 4.8)
MODEL_FAST = "sonnet"   # 화면 관찰(1단계) · 말풍선 · 효과음 배치
MODEL_SMART = "opus"    # 나레이션 작문(2단계) · 편집 구간 추천


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
TARGET_FRAMES = 56     # 완성 영상 전체에서 뽑을 대략적 프레임 수 (촘촘히 = 영상을 실제로 봄)
TILES_PER_IMG = 12     # 몽타주 한 장당 칸 수 (4×3)
TILE = 480             # 몽타주 칸 크기(px) — 표정·꼬리 같은 세부가 보이는 최소선

# 2패스 관찰: 코스 관찰에서 고른 결정적 순간 주변만 촘촘히 재샘플
DENSE_SPAN = 1.5       # 핵심 순간 앞뒤로 살필 범위(초)
DENSE_STEP = 0.3       # 재샘플 간격(초)
DENSE_MAX_PTS = 36     # 재샘플 프레임 상한 (비용 방어)


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
        vf = (f"scale={TILE}:{TILE}:force_original_aspect_ratio=decrease,"
              f"pad={TILE}:{TILE}:(ow-iw)/2:(oh-ih)/2:color=black,"
              f"drawtext=fontfile=font.otf:text='{lab:.1f}s':x=8:y=6:fontsize=40:"
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
    interval = max(0.5, total / TARGET_FRAMES)
    pts = _sample_points(segments, interval)
    return _render_montages(pts, workdir, ""), round(total, 1)


def build_source_montages(clip: dict, workdir: Path, prefix: str,
                          target_frames: int = 56) -> list[dict]:
    """원본 클립 '전체'를 원본 기준 시각 몽타주로. clip={path, duration}."""
    workdir.mkdir(parents=True, exist_ok=True)
    dur = float(clip["duration"])
    interval = max(0.5, dur / target_frames)
    pts, t = [], 0.0
    while t < dur - 1e-6:
        pts.append((round(t, 1), clip["path"], round(t, 2)))
        t += interval
    return _render_montages(pts, workdir, prefix)


def observe_prompt(montages: list[dict], synopsis: str, movie: str = "") -> str:
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
    if movie:
        lines += [
            "",
            f"[작품 정보] 이 영상은 '{movie}'의 장면들이다. 네가 이 작품을 안다면 인물·장소 식별에",
            "활용해도 된다 (예: '갓 쓴 남자' 대신 '침술사 경수'). 단, 화면에 없는 사건을 관찰에 넣지 마라.",
        ]
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
        "관찰과 별도로, 행동·상황이 가장 크게 바뀌는 '결정적 순간' 시각을 3~6개 골라라",
        "(예: 물기 시작, 고개 돌림, 달리기 시작 — 이 순간들은 이후 더 촘촘히 재확인한다).",
        "",
        "이미지를 모두 확인한 뒤, 다른 말 없이 아래 JSON만 출력해라:",
        '{"observations": [{"t": 2.0, "see": "그 시각에 화면에 보이는 것"}],'
        ' "key_moments": [12.5, 24.0]' + check_field + "}",
    ]
    return "\n".join(lines)


def _dense_points(segments: list[dict], moments: list[float],
                  total: float) -> list[tuple[float, str, float]]:
    """결정적 순간 주변을 DENSE_STEP 간격으로 재샘플한 (출력시각, 소스경로, 소스시각) 목록."""
    pts, seen = [], set()
    for m in moments:
        t = max(0.0, float(m) - DENSE_SPAN)
        end = min(total - 0.05, float(m) + DENSE_SPAN)
        while t <= end:
            key = round(t, 1)
            if key not in seen:
                seen.add(key)
                seg, st = _out_to_src(segments, t)
                pts.append((key, seg["path"], round(st, 2)))
            t += DENSE_STEP
    pts.sort(key=lambda p: p[0])
    return pts[:DENSE_MAX_PTS]


def refine_prompt(montages: list[dict], observations: list[dict]) -> str:
    """1.5단계: 결정적 순간 주변 촘촘한 몽타주로 관찰 로그를 세부 보강."""
    obs_text = "\n".join(f"- {o.get('t')}s: {o.get('see', '')}" for o in observations)
    lines = [
        "앞서 성긴 간격으로 만든 관찰 로그가 아래에 있다. 이번 몽타주는 결정적 순간 주변만",
        f"{DENSE_STEP}초 간격으로 다시 뽑은 것이다. Read 도구로 전부 확인해라.",
        "각 칸 좌상단 노란 숫자는 완성 영상 기준 시각(초)이다.",
        "",
        "[세부 몽타주]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    lines += [
        "",
        "[기존 관찰 로그]",
        obs_text,
        "",
        "[임무] 기존 로그를 유지하되, 세부 몽타주에서 확인한 내용으로 보강해라:",
        "- 행동의 시작·정점·끝이 정확히 몇 초인지",
        "- 성긴 관찰에서 놓친 세부 (표정, 시선 방향, 몸 자세, 입에 문 물체 등)",
        "- 기존 로그가 화면과 어긋나면 고쳐라. 여전히 추측·상상은 금지.",
        "",
        "합쳐진 전체 관찰 로그를, 다른 말 없이 아래 JSON만으로 출력해라:",
        '{"observations": [{"t": 2.0, "see": "그 시각에 화면에 보이는 것"}]}',
    ]
    return "\n".join(lines)


def _question_lines(what: str) -> list[str]:
    """A. 비차단 질문 — 갈림길에서만 questions 필드에 담게 하는 공용 블록."""
    return [
        "",
        "[질문 — 갈림길에서만]",
        f"화면·맥락 해석이 갈려서 {what} 내용이 실제로 달라지는 지점이 있으면 questions에 1~2개만 담아라",
        '(예: "6초에 물고 있는 게 장난감인가요, 간식인가요?"). 편집자가 한 줄로 답할 수 있게 구체적으로.',
        "확신이 서면 빈 배열 []로 두고 최선의 추측으로 진행해라 — 사소한 취향·디테일은 질문하지 말 것.",
        "대부분의 경우 질문 0개가 정상이다.",
    ]


def _pick_questions(data: dict) -> list[str]:
    return [str(q).strip() for q in data.get("questions", [])
            if str(q).strip()][:2]


def _direction_block(direction: str) -> list[str]:
    """편집자가 웹 UI 코멘트란에 남긴 편집 디렉션 → 프롬프트 블록."""
    if not direction.strip():
        return []
    return [
        "",
        "[편집자 디렉션 — 최우선 반영]",
        direction.strip(),
        "- 위는 편집자가 직접 남긴 요청이다. 다른 규칙과 충돌하면 디렉션을 우선하되,",
        "  화면에 없는 장면을 지어내는 것만은 금지다.",
        "- 디렉션 속 시각(초)은 편집된 완성 영상 타임라인 기준이다 (몽타주 라벨과 같은 좌표계).",
    ]


def narrate_prompt(observations: list[dict], style: str, synopsis: str, total: float,
                   dialogue: list[dict] | None = None,
                   examples: list[dict] | None = None, movie: str = "",
                   direction: str = "") -> str:
    """2단계: 관찰 로그에 앵커링한 나레이션·제목. dialogue=[{a,b,text}] 대사 구간은 피해서 배치.

    movie(작품명)를 주면 Claude가 이미 아는 그 영화의 줄거리·인물 지식을 활용한다
    (파라메트릭 지식 — 긴 줄거리 없이 제목 한 줄로 맥락 확보).
    """
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
    if movie:
        lines += [
            "",
            f"[작품 정보] 이 영상은 '{movie}'의 장면들이다.",
            "네가 이미 아는 이 작품의 줄거리·인물 관계·반전·결말 지식을 적극 활용해 맥락 있는 나레이션을 써라.",
            "단, 이 작품을 모르거나 기억이 불확실하면 지어내지 말고 화면 관찰과 제공된 줄거리만 근거로 해라.",
        ]
    if examples:
        lines += [
            "",
            "[이 채널에서 실제 사용된 나레이션 예시 — 말투·문장 길이·어미만 참고해라]",
            "주의: 예시 속 인물 이름·작품 고유 단어는 그 영상 전용이다. 이 영상에 가져오지 마라.",
        ]
        for e in examples:
            lines.append(f"- \"{e['text']}\"")
    if synopsis:
        lines += [
            "",
            "[줄거리·맥락] 화면에 안 보이는 인물관계·반전 '해석'에만 참고해라. 장면 묘사는 관찰 로그와",
            "일치시키고, 복선은 반전 장면(관찰 로그상 후반) 전에 깔아라.",
            synopsis,
        ]
    if dialogue:
        lines += [
            "",
            "[원본 대사 구간 — 나레이션 배치 금지 시간대]",
            "아래 시간대엔 배우가 말하고 있다. 나레이션이 겹치면 자동 덕킹으로 대사 소리가 묻힌다.",
        ]
        for d in dialogue:
            lines.append(f"- {float(d['a']):.1f}~{float(d['b']):.1f}초: \"{d.get('text', '')}\"")
        lines += [
            "- 나레이션은 at부터 약 3초간 재생된다 — at ~ at+3초가 위 구간과 겹치지 않게 대사 사이 틈에 배치해라.",
            "- 틈이 3초보다 짧으면 그 자리는 건너뛰어라. 대사 내용은 맥락 참고용으로 활용해도 된다.",
        ]
    lines += _direction_block(direction)
    lines += [
        "",
        "[나레이션 규칙]",
        "- 문장당 2~3초 분량의 짧은 한 문장. 나레이션 사이 최소 3초 간격.",
        f"- at은 0.5 ~ {max(0.5, total - 2):.1f}초 범위, 관찰된 시각 근처에 배치.",
        "- 구독·좋아요·채널 방문 유도 문구(CTA)는 엔딩 포함 전면 금지. 예시에 있어도 따라 하지 마라.",
        "- 장면을 하나하나 중계하지 마라('어? 저기 인형도 있네!' 식 나열 금지).",
        "  영상 전체를 관통하는 한 가지 이야기(궁금증 → 전개 → 해소)로 문장들이 이어져야 한다.",
    ]
    lines += _question_lines("나레이션")
    lines += [
        "",
        "아래 JSON만 출력해라:",
        '{"title": "윗줄|아랫줄", "out_name": "출력파일명", "narrs": [{"at": 0.5, "text": "..."}],'
        ' "questions": []}',
    ]
    return "\n".join(lines)


def run_claude(prompt: str, cwd: Path, model: str | None = None) -> dict:
    exe = find_claude()
    if not exe:
        raise RuntimeError("Claude Code CLI(claude)를 찾을 수 없습니다. PATH를 확인하세요.")
    cmd = [exe, "-p", prompt, "--output-format", "json", "--allowedTools", "Read"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(
        cmd,
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


def ai_draft(segments: list[dict], style: str, synopsis: str = "",
             dialogue: list[dict] | None = None, preset: str = "",
             movie: str = "", direction: str = "") -> dict:
    """segments: [{path, a, b, spd, tags}] → {title, out_name, narrs, observations, synopsis_check?}.

    2단계: (1) 촘촘한 몽타주로 화면 관찰 로그 작성 (줄거리 제공 시 일치 검사) →
           (2) 관찰 로그에 앵커링한 나레이션·제목 작성.
    dialogue=[{a,b,text}] (완성영상 시각 기준 대사 자막)를 주면 그 시간대를 피해 배치한다.
    preset을 주면 같은 채널의 확정 나레이션을 말투 예시로 쓰고, 제안을 로그에 남긴다.
    movie(작품명)를 주면 Claude가 이미 아는 그 작품의 줄거리 지식을 활용한다.
    """
    workdir = FRAME_DIR / uuid.uuid4().hex[:8]
    montages, total = build_montages(segments, workdir)

    obs = run_claude(observe_prompt(montages, synopsis, movie), workdir, MODEL_FAST)
    observations = obs.get("observations", [])

    # 2패스: 결정적 순간 주변을 촘촘히 재관찰해 세부 보강 (실패해도 코스 관찰로 진행)
    moments = [m for m in obs.get("key_moments", []) if isinstance(m, (int, float))][:6]
    if moments:
        try:
            dense = _dense_points(segments, moments, total)
            if dense:
                dm = _render_montages(dense, workdir, "d_")
                obs2 = run_claude(refine_prompt(dm, observations), workdir, MODEL_FAST)
                if obs2.get("observations"):
                    observations = obs2["observations"]
        except Exception:
            pass

    data = run_claude(narrate_prompt(observations, style, synopsis, total, dialogue,
                                     narr_examples(preset) if preset else None, movie,
                                     direction),
                      workdir, MODEL_SMART)
    narrs = [{"at": float(n["at"]), "text": str(n["text"]).strip()}
             for n in data.get("narrs", []) if str(n.get("text", "")).strip()]
    narrs.sort(key=lambda n: n["at"])
    narrs = verify_items(narrs, segments, workdir, total, kind="narr")
    log_narrs("ai", narrs, preset=preset)

    result = {"title": data.get("title", ""), "out_name": data.get("out_name", ""),
              "narrs": narrs, "observations": observations,
              "questions": _pick_questions(data)}
    if synopsis and isinstance(obs.get("synopsis_check"), dict):
        result["synopsis_check"] = obs["synopsis_check"]
    return result


# ── 사용 로그 (채널별 학습): 말풍선·나레이션·효과음이 같은 구조를 공유한다
# source: 'ai'(제안) / 'final'(렌더에 실제 사용). final이 같은 채널의 다음 제안 예시가 된다.
BUBBLE_LOG = ROOT / "logs" / "bubbles.jsonl"
NARR_LOG = ROOT / "logs" / "narrs.jsonl"
SFX_LOG = ROOT / "logs" / "sfx.jsonl"


def _log_rows(path: Path, source: str, items: list[dict],
              preset: str = "", video: str = "") -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for it in items:
            row = {"source": source, "preset": preset, "video": video, **it}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _final_rows(path: Path, preset: str) -> list[dict]:
    """같은 채널의 확정(final) 행만 — 다른 채널의 작품 고유 단어 유입 방지."""
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if d.get("source") == "final" and d.get("preset") == preset:
            rows.append(d)
    return rows


_CTA_RE = re.compile(r"구독|좋아요|채널로|채널에|풀영상|놀러\s*와")


def _text_examples(path: Path, preset: str, limit: int, per_video: int = 3) -> list[dict]:
    """최신 우선 + 같은 텍스트 중복 제거 + 영상당 상한(한 작품의 고유 단어 독점 방지).

    CTA 문장은 제외 — 2026-07-13 사용자 확정(구독·좋아요 유도 안 씀) 이전 영상의
    확정본이 예시로 유입돼 금지된 톤을 학습시키는 것을 막는다.
    """
    out, seen_text, per_vid = [], set(), {}
    for d in reversed(_final_rows(path, preset)):
        t, v = d.get("text", ""), d.get("video", "")
        if not t or t in seen_text or per_vid.get(v, 0) >= per_video:
            continue
        if _CTA_RE.search(t):
            continue
        seen_text.add(t)
        per_vid[v] = per_vid.get(v, 0) + 1
        out.append(d)
        if len(out) >= limit:
            break
    return list(reversed(out))


def log_bubbles(source: str, items: list[dict], preset: str = "", video: str = "") -> None:
    _log_rows(BUBBLE_LOG, source, items, preset, video)


def log_narrs(source: str, items: list[dict], preset: str = "", video: str = "") -> None:
    _log_rows(NARR_LOG, source, items, preset, video)


def log_sfx(source: str, items: list[dict], preset: str = "", video: str = "") -> None:
    _log_rows(SFX_LOG, source, items, preset, video)


def _bubble_examples(preset: str, limit: int = 14) -> list[dict]:
    return _text_examples(BUBBLE_LOG, preset, limit)


def narr_examples(preset: str, limit: int = 10) -> list[dict]:
    return _text_examples(NARR_LOG, preset, limit)


def sfx_counts() -> dict[str, int]:
    """최종 렌더에 실제 쓰인 효과음별 누적 횟수 (채널 무관 합산 — UI 표시용)."""
    from collections import Counter
    cnt: Counter = Counter()
    if SFX_LOG.exists():
        for ln in SFX_LOG.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if d.get("source") == "final" and d.get("name"):
                cnt[d["name"]] += 1
    return dict(cnt)


def sfx_usage(preset: str, top: int = 8) -> list[tuple[str, int]]:
    """이 채널에서 실제 쓴 효과음 사용 빈도 — AI가 채널 취향의 소리를 우선하게."""
    from collections import Counter
    cnt = Counter(d.get("name", "") for d in _final_rows(SFX_LOG, preset) if d.get("name"))
    return cnt.most_common(top)


def bubble_prompt(montages: list[dict], style: str, synopsis: str,
                  total: float, examples: list[dict], preset: str = "wanghee",
                  direction: str = "",
                  vocals: list[tuple[float, float, float]] | None = None) -> str:
    if preset == "cinema":
        role = "너는 영화·드라마 짤 쇼츠의 말풍선 자막 작가다."
        kinds = ["- 인물의 속마음·리액션 짧은 자막(예: 환청인가..?, (당황)) 또는 상황 강조 텍스트"]
    else:
        role = "너는 반려동물 쇼츠의 말풍선 자막 작가다."
        kinds = [
            "- 잘 먹히는 유형 4가지 (이 채널 확정본에서 검증된 순서):",
            "  ①괄호 상태어 — 감정·상태를 한 단어로: (부글), (무시), (집중), (허우적), (피곤)",
            "  ②짧은 외침 — 감정이 터지는 순간: 앙!, 흐엑!, 내꺼야!, 들켰다!",
            "  ③이름·호칭 외치기 (맥락에 이름이 있을 때)",
            "  ④러닝 개그 — 같은 행동이 반복되면 같은 말풍선 반복 또는 (1트)→(2트) 카운트",
            "- 설명조·평서문 대사(예: 쓰담 좋아, 눈 감겨, 더 만져줘)는 재미없어서 전부 버려진다.",
            "  '상황을 설명'하지 말고 '감정이 터지는 순간의 속마음'을 써라.",
        ]
    lines = [
        role + " 아래 몽타주 이미지를 Read 도구로 전부 확인해라.",
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
        lines += [
            "",
            "[이 채널에서 실제 사용된 말풍선 예시 — 말투·길이·리듬만 참고해라]",
            "주의: 예시 속 인물 이름·작품 고유 단어는 그 영상 전용이다. 이 영상에 그대로 가져오지 마라.",
        ]
        for e in examples:
            lines.append(f"- \"{e['text']}\"")
    lines += _vocal_block(vocals or [], [
        "- 강아지가 '말하는' 대사 말풍선은 가능하면 발성 구간에 at을 맞춰라 (소리와 대사가 싱크).",
        "- 발성이 없는 시간대의 말풍선은 화면에 보이는 행동 기반(속마음·의성어)으로.",
    ])
    lines += _direction_block(direction)
    lines += [
        "",
        "[임무] 화면에서 실제로 보이는 행동 중 '웃긴 순간'에만 말풍선을 달아라.",
        *kinds,
        "- 텍스트 2~8자. 느낌표는 최대 1개. 이모지는 어울릴 때만 끝에 1개 (예: 저리 비켜😤)",
        f"- 개수는 {max(2, int(total // 8))}~{max(3, int(total // 5))}개가 기준이지만,"
        " 어울리는 순간이 없으면 더 적게 — 억지 배치가 제일 나쁘다",
        "- 서로 3초 이상 간격 (러닝 개그 반복은 예외)",
        "- at은 그 행동이 보이는 시각, dur은 1.5~2.5초",
        "- 보이지 않는 행동을 지어내지 말 것",
    ]
    lines += _question_lines("말풍선")
    lines += [
        "",
        "아래 JSON만 출력해라:",
        '{"bubbles": [{"at": 3.2, "dur": 1.8, "text": "앙!"}], "questions": []}',
    ]
    return "\n".join(lines)


def _vocal_ranges_out(segments: list[dict], min_gap: float = 0.4) -> list[tuple[float, float, float]]:
    """원본 발성 이벤트(0.2초 창)를 완성 타임라인 발성 구간 [(a, b, 강도)]로 병합·매핑.

    말풍선·효과음 AI가 '실제 소리가 나는 시각'을 앵커로 쓰게 한다. 분석 실패 시 빈 목록.
    """
    from .audio_events import vocal_windows

    WIN = 0.2
    cache: dict[str, list] = {}
    events, cursor = [], 0.0
    for s in segments:
        spd = s.get("spd") or 1
        if s["path"] not in cache:
            try:
                cache[s["path"]] = vocal_windows(s["path"])
            except Exception:
                cache[s["path"]] = []
        for t, strength in cache[s["path"]]:
            if s["a"] - WIN < t < s["b"]:
                events.append((cursor + max(0.0, t - s["a"]) / spd, strength))
        cursor += (s["b"] - s["a"]) / spd
    events.sort()

    ranges: list[list[float]] = []
    for t, strength in events:
        if ranges and t - ranges[-1][1] <= min_gap:
            ranges[-1][1] = t + WIN
            ranges[-1][2] = max(ranges[-1][2], strength)
        else:
            ranges.append([t, t + WIN, strength])
    return [(round(a, 1), round(b, 1), round(st, 2)) for a, b, st in ranges]


def _vocal_block(vocals: list[tuple[float, float, float]], rules: list[str]) -> list[str]:
    """발성 구간 목록 → 프롬프트 블록."""
    if not vocals:
        return []
    lines = ["", "[실제 발성 구간 — 이 시간대에 강아지 소리(짖음·낑낑·으르렁)가 실제로 난다 (완성 기준)]"]
    for a, b, st in vocals:
        lines.append(f"- {a:.1f}~{b:.1f}초 (강도 {st:.1f})")
    return lines + rules


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


_DIMS_CACHE: dict[str, tuple[int, int]] = {}


def _display_dims(path: str) -> tuple[int, int]:
    """회전 메타데이터 반영된 표시 크기 (render_cinema.display_dims와 동일 로직)."""
    if path not in _DIMS_CACHE:
        out = subprocess.run(
            [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:stream_side_data=rotation",
             "-of", "json", path], capture_output=True, text=True, timeout=60)
        st = json.loads(out.stdout)["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        rot = 0
        for sd in st.get("side_data_list", []):
            rot = int(sd.get("rotation", 0) or 0)
        if abs(rot) % 180 == 90:
            w, h = h, w
        _DIMS_CACHE[path] = (w, h)
    return _DIMS_CACHE[path]


def _bubble_pos(seg: dict, cx: float, cy: float, preset: str) -> tuple[float, float]:
    """피사체 중심(원본 프레임 비율) → 완성 프레임 비율 좌표.

    피사체 추적은 원본 클립 프레임에서 돌지만 말풍선 fx/fy는 완성(1080x1920) 프레임
    기준이다. render_cinema의 세그먼트 변환(회전 → 확대 크롭 → 캔버스 배치)을 그대로
    따라가 좌표계를 일치시킨다 — 안 하면 확대·회전·가로 소스에서 위치가 어긋난다.
    """
    try:
        w0, h0 = _display_dims(seg["path"])
    except Exception:
        return cx, cy
    rot = int(seg.get("rot") or 0)
    if rot in (90, 270, -90):
        cx, cy = (1 - cy, cx) if rot == 90 else (cy, 1 - cx)
        w0, h0 = h0, w0
    zoom = float(seg.get("zoom") or 1)
    if zoom > 1.001:
        cw, ch = int(w0 / zoom) // 2 * 2, int(h0 / zoom) // 2 * 2
        zcx, zcy = seg.get("zcx"), seg.get("zcy")
        zcx = 0.5 if zcx is None else float(zcx)
        zcy = 0.5 if zcy is None else float(zcy)
        zx = min(max(int(w0 * zcx - cw / 2), 0), w0 - cw)
        zy = min(max(int(h0 * zcy - ch / 2), 0), h0 - ch)
        cx = min(max((cx * w0 - zx) / cw, 0.0), 1.0)
        cy = min(max((cy * h0 - zy) / ch, 0.0), 1.0)
        w0, h0 = cw, ch
    if preset == "cinema":
        # 1920x1080 정규화 → 세로 캔버스 중앙 밴드(높이 1080*1080/1920)로 축소 배치
        if h0 > w0:  # 세로 소스는 밴드 안 블러 중앙
            cx = 0.5 + (cx - 0.5) * (1080 * w0 / h0) / 1920
        return cx, 0.5 + (cy - 0.5) * (1080 * 1080 / 1920) / 1920
    # src_portrait 풀스크린 (1080x1920)
    if h0 > w0:   # 세로 → cover-crop
        s = max(1080 / w0, 1920 / h0)
        return (0.5 + (cx - 0.5) * w0 * s / 1080,
                0.5 + (cy - 0.5) * h0 * s / 1920)
    disp_h = 1080 * h0 / w0    # 가로 → 블러 배경 + 원본 중앙
    return cx, 0.5 + (cy - 0.5) * disp_h / 1920


def verify_prompt(montages: list[dict], items: list[dict], kind: str) -> str:
    what = "나레이션" if kind == "narr" else "말풍선"
    lines = [
        f"너는 쇼츠 {what} 검수자다. 아래 각 항목은 완성 영상의 특정 시각에 표시될 {what}이다.",
        "몽타주 이미지를 Read 도구로 전부 확인해라. 각 칸 좌상단 노란 숫자는 완성 영상 기준",
        "시각(초)이고, 각 항목의 표시 시각과 그 직후 프레임이 포함돼 있다.",
        "",
        "[검수 항목]",
    ]
    for i, it in enumerate(items):
        lines.append(f"- {i}) at {float(it['at']):.1f}초: \"{it['text']}\"")
    lines += [
        "",
        "[몽타주]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    lines += [
        "",
        "[판정 기준]",
        "- keep: 그 시각 화면과 텍스트가 자연스럽게 맞음",
        "- fix: 내용은 맞지만 시각이 어긋남(at을 ±2초 내로 조정) 또는 화면과 살짝 어긋난 표현 수정",
        "- drop: 화면에서 근거를 찾을 수 없는 내용 (지어낸 행동·감정)",
        "- 확신이 없으면 keep. fix여도 말투·문체는 유지하고 사실 관계만 고쳐라.",
        "",
        "다른 말 없이 아래 JSON만 출력해라 (모든 항목 포함):",
        '{"items": [{"i": 0, "action": "keep", "at": 3.2, "text": "...", "why": "화면 근거"}]}',
    ]
    return "\n".join(lines)


def verify_items(items: list[dict], segments: list[dict], workdir: Path,
                 total: float, kind: str = "narr") -> list[dict]:
    """생성된 나레이션/말풍선을 해당 시각 프레임으로 재검증 — keep/fix/drop 반영.

    각 항목의 at과 at+1.2초 프레임을 뽑아 화면↔텍스트 일치를 판정시킨다.
    검증 자체가 실패하면 원본을 그대로 반환한다 (검증이 생성을 깨면 안 됨).
    """
    if not items:
        return items
    try:
        pts, seen = [], set()
        for it in items:
            for t in (float(it["at"]), float(it["at"]) + 1.2):
                t = min(max(0.0, t), max(0.0, total - 0.05))
                key = round(t, 1)
                if key in seen:
                    continue
                seen.add(key)
                seg, st = _out_to_src(segments, t)
                pts.append((key, seg["path"], round(st, 2)))
        pts.sort(key=lambda p: p[0])
        montages = _render_montages(pts, workdir, "v_")
        data = run_claude(verify_prompt(montages, items, kind), workdir, MODEL_FAST)
    except Exception:
        return items

    verdicts = {}
    for v in data.get("items", []):
        try:
            verdicts[int(v["i"])] = v
        except (KeyError, TypeError, ValueError):
            continue
    out = []
    for i, it in enumerate(items):
        v = verdicts.get(i)
        action = str(v.get("action", "keep")) if v else "keep"
        if action == "drop":
            continue
        if action == "fix" and v:
            it = dict(it)
            try:
                new_at = float(v.get("at", it["at"]))
                if abs(new_at - float(it["at"])) <= 2.0:
                    it["at"] = round(min(max(0.0, new_at), max(0.0, total - 1)), 1)
            except (TypeError, ValueError):
                pass
            new_text = str(v.get("text", "")).strip()
            if new_text:
                it["text"] = new_text
        out.append(it)
    out.sort(key=lambda x: float(x["at"]))
    return out


def ai_bubbles(segments: list[dict], style: str, synopsis: str = "",
               preset: str = "wanghee", direction: str = "") -> dict:
    """segments → {bubbles:[{a,b,text,fx,fy}]}. 텍스트·시각은 Claude, 좌표는 피사체 추적.

    few-shot 예시는 같은 채널(preset)의 확정본만 사용한다.
    """
    from .track_subject import track

    workdir = FRAME_DIR / ("bub_" + uuid.uuid4().hex[:8])
    montages, total = build_montages(segments, workdir)
    vocals = _vocal_ranges_out(segments) if preset != "cinema" else []
    data = run_claude(
        bubble_prompt(montages, style, synopsis, total,
                      _bubble_examples(preset), preset, direction, vocals),
        workdir, MODEL_FAST)

    raw = []
    for b in data.get("bubbles", []):
        at = float(b.get("at", 0))
        dur = min(2.5, max(1.2, float(b.get("dur", 1.8))))
        text = str(b.get("text", "")).strip()
        if not text or at >= total:
            continue
        raw.append({"at": round(at, 1), "dur": dur, "text": text})
    raw = verify_items(raw, segments, workdir, total, kind="bubble")

    track_cache: dict[int, list] = {}
    bubbles = []
    for b in raw:
        at, dur, text = b["at"], b["dur"], b["text"]
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
        # 편집 변환(회전·확대·캔버스 배치)을 통과시켜 완성 프레임 좌표로.
        # 오프셋 없이 피사체 중심 높이 그대로 — 확정본 실측(36쌍)에서 머리 위(-0.11)
        # 오프셋을 사용자가 매번 +0.10 되돌렸다.
        fx, fy = _bubble_pos(seg, cx, cy, preset)
        fx = min(0.85, max(0.15, fx))          # 텍스트가 화면 밖으로 안 잘리게
        fy = min(0.80, max(0.10, fy))
        bubbles.append({"a": round(at, 1), "b": round(min(total, at + dur), 1),
                        "text": text, "fx": round(fx, 3), "fy": round(fy, 3)})
    bubbles.sort(key=lambda x: x["a"])
    log_bubbles("ai", bubbles, preset=preset)
    return {"bubbles": bubbles, "questions": _pick_questions(data)}


def ai_sfx(segments: list[dict], style: str, sfx_options: list[dict],
           synopsis: str = "", preset: str = "", direction: str = "") -> dict:
    """편집본을 관찰해 효과음 배치를 제안. sfx_options: [{name, label}]. → {sfx:[{at, name, why}]}.

    preset을 주면 이 채널에서 자주 쓴 효과음 빈도를 참고시키고, 제안을 로그에 남긴다.
    """
    workdir = FRAME_DIR / ("sfx_" + uuid.uuid4().hex[:8])
    montages, total = build_montages(segments, workdir)
    valid = {o["name"] for o in sfx_options}
    role = ("너는 영화·드라마 짤 쇼츠의 효과음(SFX) 편집자다." if preset == "cinema"
            else "너는 반려동물 쇼츠의 효과음(SFX) 편집자다.")

    lines = [
        role + " 아래 몽타주를 Read로 전부 확인해라.",
        "각 칸 좌상단 노란 숫자는 완성 영상 기준 시각(초)이다.",
        "",
        "[몽타주]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    lines += ["", f"[채널 스타일]\n{style}"]
    if synopsis:
        lines += ["", "[맥락]", synopsis]
    lines += ["", "[쓸 수 있는 효과음 — name만 그대로 사용]"]
    for o in sfx_options:
        lines.append(f"- {o['name']}: {o['label']}")
    usage = sfx_usage(preset) if preset else []
    if usage:
        lines += ["", "[이 채널에서 실제 자주 쓴 효과음 — 취향 참고용, 화면에 맞는 소리가 항상 우선]"]
        for name, cnt in usage:
            lines.append(f"- {name} ({cnt}회)")
    vocals = _vocal_ranges_out(segments) if preset != "cinema" else []
    lines += _vocal_block(vocals, [
        "- 발성 구간엔 짖음·낑낑류 효과음을 겹치지 마라 — 진짜 소리가 이미 있다.",
        "- 발성 순간을 강조하고 싶으면 그 직전·직후 시각에 배치해라.",
    ])
    lines += _direction_block(direction)
    lines += [
        "",
        "[임무] 화면에 보이는 행동·순간에 어울리는 효과음을 배치해라.",
        "- 강아지가 무언가 물거나 짖는 순간 → 짖음/낑낑, 통통 튀는 움직임 → 팝/보잉 식으로 매칭",
        f"- 개수는 {max(1, int(total // 8))}~{max(2, int(total // 4))}개, 서로 2초 이상 간격",
        "- at은 그 행동이 시작되는 시각. 화면과 안 맞으면 넣지 마라 (억지 배치 금지)",
        "- name은 위 목록에 있는 것만.",
        *_question_lines("효과음 배치"),
        "",
        "아래 JSON만 출력해라:",
        '{"sfx": [{"at": 3.2, "name": "dog_whine1", "why": "화면 근거"}], "questions": []}',
    ]
    data = run_claude("\n".join(lines), workdir, MODEL_FAST)
    out = []
    for s in data.get("sfx", []):
        name, at = str(s.get("name", "")), float(s.get("at", -1))
        if name in valid and 0 <= at < total:
            out.append({"at": round(at, 1), "name": name, "why": str(s.get("why", ""))})
    out.sort(key=lambda x: x["at"])
    log_sfx("ai", [{"at": s["at"], "name": s["name"]} for s in out], preset=preset)
    return {"sfx": out, "questions": _pick_questions(data)}


def recommend_prompt(clip_montages: list[dict], synopsis: str, style: str,
                     target_len: float, max_len: float, direction: str = "") -> str:
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
    ]
    lines += _direction_block(direction)
    lines += [
        "",
        "[임무] 위 줄거리의 흐름(도입 → 복선 → 반전 → 결말)이 담기도록, 원본에서 쇼츠에 넣을",
        "구간을 골라라. 화면에 실제로 보이는 것을 근거로 고르되, 어느 장면이 어느 대목인지는 줄거리로 해석해라.",
        "[규칙]",
        f"- 선택 구간 총합(배속 반영)은 40~{max_len:.0f}초 사이, {target_len:.0f}초 내외가 목표 (쇼츠 규격).",
        "- 소스가 짧아 40초가 안 되면 결정적 순간을 spd 0.4~0.7 슬로우로 늘리거나,",
        "  같은 순간을 정속 → 슬로우로 한 번 더 보여주는 리플레이 연출로 채워라.",
        "- 반전·결정적 순간은 반드시 포함. 복선 장면을 반전보다 앞에 배치.",
        "- 각 구간 2~10초, 시간순. 각 클립 원본 시각 기준 a<b.",
        "- spd는 기본 1.0(정속), 슬로우 강조 구간만 0.4~0.7.",
        "- 화면으로 확인 안 되는 장면을 지어내지 말 것. 줄거리에만 있고 화면에 없으면 note에 밝혀라.",
        "",
        "아래 JSON만 출력해라:",
        '{"segments": [{"clip": 0, "a": 0.0, "b": 5.0, "spd": 1.0, "role": "도입", "why": "화면 근거"}],'
        ' "note": "편집 의도/한계 한두 문장"}',
    ]
    return "\n".join(lines)


def recommend_edit(clips: list[dict], synopsis: str, style: str,
                   target_len: float = 50.0, max_len: float = 60.0,
                   direction: str = "") -> dict:
    """원본 클립 전체 + 줄거리 → 편집 구간 추천. clips=[{path, duration}].

    반환: {segments:[{clip, a, b, spd, role, why}], note}. clip은 clips 리스트 인덱스.
    direction: 편집자 코멘트(예: "10~13초를 슬로우로 한 번 더") — 프롬프트에 최우선 반영.
    """
    workdir = FRAME_DIR / ("rec_" + uuid.uuid4().hex[:8])
    clip_montages = []
    for ci, c in enumerate(clips):
        ms = build_source_montages(c, workdir, prefix=f"c{ci}_")
        clip_montages.append({"ci": ci, "duration": float(c["duration"]), "montages": ms})

    data = run_claude(
        recommend_prompt(clip_montages, synopsis, style, target_len, max_len, direction),
        workdir, MODEL_SMART)

    segments = []
    for s in data.get("segments", []):
        ci = int(s.get("clip", 0))
        if not (0 <= ci < len(clips)):
            continue
        a, b = float(s["a"]), float(s["b"])
        a = max(0.0, min(a, clips[ci]["duration"]))
        b = max(a + 0.5, min(b, clips[ci]["duration"]))
        spd = min(2.0, max(0.3, float(s.get("spd", 1) or 1)))
        segments.append({"clip": ci, "a": round(a, 1), "b": round(b, 1), "spd": spd,
                         "role": str(s.get("role", "")), "why": str(s.get("why", ""))})
    return {"segments": segments, "note": data.get("note", "")}


def clarify_prompt(task: str, context: str) -> str:
    return "\n".join([
        "너는 영상 편집 실행 전에 요청을 검토하는 조수다. 아래 작업은 실행에 몇 분이 걸리므로,",
        "착수 전에 '해석이 갈려서 결과가 크게 달라지는 지점'이 있는지만 판단해라.",
        "",
        f"[작업] {task}",
        "",
        "[요청 내용]",
        context,
        "",
        "[기준]",
        "- 질문을 만들기 전에 요청을 다시 읽어라. 답이 요청 안에 이미 적혀 있으면 그 질문은 금지다.",
        "  (예: '정속으로 리플레이'라고 썼는데 리플레이 속도를 묻기 = 금지)",
        "- 반대로 '임팩트 있게', '더 재밌게'처럼 방향만 있고 방법·구간이 없는 요청은 갈림길이다",
        "  — 연출 방법이나 대상 구간을 선택지로 물어라.",
        "- 기준: 유능한 편집자 두 명이 이 요청만 읽고 서로 크게 다른 결과물을 만들겠는가? 그럴 때만 질문.",
        "- 질문은 최대 2개, 각 질문에 선택지 2~3개를 같이 제시해라 (편집자가 클릭 한 번으로 답하게).",
        "- 사소한 취향·디테일, 실행하면서 화면을 보고 판단할 수 있는 것은 질문 금지.",
        "- 구체적인 요청은 질문 0개가 정상이다.",
        "",
        "다른 말 없이 아래 JSON만 출력해라:",
        '{"questions": [{"q": "질문?", "options": ["선택지1", "선택지2"]}]}',
    ])


def clarify_check(task: str, context: str) -> list[dict]:
    """B. 착수 전 해석 확인 — 텍스트만 보는 빠른 호출(프레임 없음, 수십 초).

    갈림길이면 [{q, options}] 0~2개, 확실하거나 검사 실패면 [] (실패가 실행을 막으면 안 됨).
    """
    workdir = FRAME_DIR / "clarify"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        data = run_claude(clarify_prompt(task, context), workdir, MODEL_FAST)
    except Exception:
        return []
    out = []
    for q in data.get("questions", [])[:2]:
        text = (str(q.get("q", "")) if isinstance(q, dict) else str(q)).strip()
        if not text:
            continue
        opts = [str(o).strip() for o in (q.get("options", []) if isinstance(q, dict) else [])
                if str(o).strip()][:3]
        out.append({"q": text, "options": opts})
    return out


def merge_answers(direction: str, answers: list[dict]) -> str:
    """착수 전 질문에 대한 편집자 답변을 디렉션 텍스트에 병합."""
    rows = [f"Q: {str(a.get('q', '')).strip()} → A: {str(a.get('a', '')).strip()}"
            for a in answers if str(a.get("a", "")).strip()]
    if not rows:
        return direction
    return (direction + "\n\n[착수 전 질문에 대한 편집자 답변 — 반드시 반영]\n"
            + "\n".join(rows)).strip()


def edit_apply_prompt(montages: list[dict], seg_lines: list[str], style: str,
                      direction: str, total: float) -> str:
    """현재 편집본 몽타주 + 세그먼트 매핑 + 디렉션 → 수정된 세그먼트 목록 프롬프트."""
    lines = [
        "너는 유튜브 쇼츠 편집자다. '현재 편집본'과 편집자의 수정 디렉션이 주어진다.",
        "아래 몽타주는 현재 편집본을 시간순으로 훑은 것이다. 각 칸 좌상단의 노란 숫자는",
        "완성 영상 기준 시각(초)이다. Read 도구로 전부 확인해라.",
        "",
        "[현재 편집본 몽타주]",
    ]
    for m in montages:
        lines.append(f"- {m['name']} (칸별 시각: {', '.join(str(s) for s in m['stamps'])}초)")
    lines += [
        "",
        f"[현재 세그먼트 — 완성 시각 ↔ 원본 매핑, 총 {total:.1f}초]",
        *seg_lines,
        "",
        f"[채널 스타일]\n{style}",
        "",
        "[편집자 디렉션 — 이걸 편집에 반영하는 게 임무다]",
        direction.strip(),
        "",
        "[임무] 디렉션을 반영한 '전체 세그먼트 목록'을 다시 출력해라.",
        "디렉션과 무관한 구간은 그대로 유지하고, 지목된 구간만 고친다.",
        "[연출 도구]",
        "- 슬로우: spd 0.4~0.7 (기본 1.0)",
        "- 리플레이: 같은 원본 구간 세그먼트를 하나 더 넣어 정속 → 슬로우 순으로 반복 재생",
        "- 확대(줌인): zoom 1.3~2.0 — 피사체·표정 강조. 지목된 세그먼트에만 (중심은 시스템이 피사체 추적으로 자동 결정)",
        "- 분할: 디렉션이 세그먼트 일부만 지목하면 그 부분을 잘라 별도 세그먼트로 나눠 연출",
        "[규칙]",
        "- 디렉션의 시각은 완성 영상 기준이다 → 위 매핑 표로 원본 시각(a, b)으로 환산해라.",
        "- clip은 매핑 표의 클립 번호. a<b. 완성 영상에 나올 순서대로 나열해라.",
        "- 총 길이(배속 반영)는 60초를 넘지 말 것.",
        "",
        "아래 JSON만 출력해라:",
        '{"segments": [{"clip": 0, "a": 0.3, "b": 2.8, "spd": 1.0, "zoom": 1.0, "why": "변경 이유(유지 구간은 생략)"}],'
        ' "note": "디렉션을 어떻게 반영했는지 한두 문장"}',
    ]
    return "\n".join(lines)


def ai_edit_apply(segments: list[dict], style: str, direction: str,
                  preset: str = "wanghee") -> dict:
    """현재 세그먼트 + 편집 디렉션 → 슬로우·리플레이·확대가 반영된 세그먼트 목록.

    segments: [{path, a, b, spd, zoom?}]. 디렉션 시각(완성 기준)을 원본으로 환산할 수 있게
    매핑 표를 프롬프트에 제공한다. zoom 세그먼트는 피사체 추적으로 중심을 자동 결정(wanghee).
    반환: {segments:[{clip,a,b,spd,zoom,zcx,zcy,why}], paths, note} — clip은 paths 인덱스.
    """
    workdir = FRAME_DIR / ("edit_" + uuid.uuid4().hex[:8])
    montages, total = build_montages(segments, workdir)

    paths: list[str] = []
    for s in segments:
        if s["path"] not in paths:
            paths.append(s["path"])
    seg_lines, cursor = [], 0.0
    for i, s in enumerate(segments):
        spd = float(s.get("spd", 1) or 1)
        dur = (float(s["b"]) - float(s["a"])) / spd
        extra = f", spd {spd}" if spd != 1 else ""
        if float(s.get("zoom", 1) or 1) != 1:
            extra += f", zoom {s['zoom']}"
        seg_lines.append(f"{i + 1}) 완성 {cursor:.1f}~{cursor + dur:.1f}초 = "
                         f"클립{paths.index(s['path'])} 원본 {s['a']:.1f}~{s['b']:.1f}초{extra}")
        cursor += dur

    data = run_claude(edit_apply_prompt(montages, seg_lines, style, direction, total),
                      workdir, MODEL_SMART)

    out = []
    for s in data.get("segments", []):
        ci = int(s.get("clip", 0))
        if not (0 <= ci < len(paths)):
            continue
        a, b = float(s["a"]), float(s["b"])
        if b <= a:
            continue
        spd = min(2.0, max(0.3, float(s.get("spd", 1) or 1)))
        zoom = min(2.5, max(1.0, float(s.get("zoom", 1) or 1)))
        zcx = zcy = 0.5
        if zoom > 1.001 and preset == "wanghee":
            try:  # 확대 중심 = 그 구간 피사체(강아지) 위치
                from .track_subject import track
                knots = track(paths[ci], a, b)
                mid = knots[len(knots) // 2]
                zcx, zcy = float(mid[1]), float(mid[2])
            except Exception:
                pass
        out.append({"clip": ci, "a": round(a, 1), "b": round(b, 1), "spd": spd,
                    "zoom": round(zoom, 2), "zcx": round(zcx, 3), "zcy": round(zcy, 3),
                    "why": str(s.get("why", ""))})
    return {"segments": out, "paths": paths, "note": data.get("note", "")}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if spec.get("mode") == "recommend":
        print(json.dumps(recommend_edit(spec["clips"], spec.get("synopsis", ""),
                                         spec.get("style", "")), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(ai_draft(spec["segments"], spec["style"], spec.get("synopsis", "")),
                         ensure_ascii=False, indent=1))
