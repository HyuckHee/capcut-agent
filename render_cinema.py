"""영화/드라마 짤 쇼츠 렌더러 — 검은 배경 + 상단 제목 + 대사/설명 자막 + 나레이션.

사용:
  python render_cinema.py <영상> <출력.mp4> --seg 시작-끝|파일|시작|끝 ...
      --title "첫줄|둘째줄"
      --subs 대본.json            (기본입력 원본시각 기준 대사 자막)
      --sub  "A-B:텍스트"         (타임라인 시각 기준 대사 자막)
      --exp  "A-B:텍스트"         (설명 자막 — 큰 노란 박스, 나레이터 톤)
      --narr "A:텍스트"           (한국어 TTS 나레이션, 원본 오디오 자동 덕킹)
      --crop W:H:X:Y

대사 자막 = 흰색 작게 하단. 설명 자막 = 노란 박스 크게. BGM/효과음 없음(원본 사운드 유지).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app import config
from app.narrate import synth, warm, DEFAULT_VOICE, DEFAULT_RATE, DEFAULT_PITCH

OUT_W, OUT_H = 1080, 1920
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}  # 정지 이미지 세그먼트 (b-a = 표시 초)
FONT_SOURCE = (Path("C:/Windows/Fonts/malgunbd.ttf") if os.name == "nt"   # 맑은고딕 (대사 자막용)
               else Path(__file__).resolve().parent / "library" / "fonts" / "Pretendard-ExtraBold.otf")
FONT_EXP = Path(__file__).resolve().parent / "library" / "fonts" / "Pretendard-ExtraBold.otf"
FONT_NARR = Path(__file__).resolve().parent / "library" / "fonts" / "Gungsuh.ttf"  # 궁서 (영화 로고)
FONT_ROUND = Path(__file__).resolve().parent / "library" / "fonts" / "Jua-Regular.ttf"  # 주아 (나레이션, 둥글둥글)

# 비디오헤드클리너 구도: 상단 소제목 / 중앙 영상 / 하단 자막 / 최하단 영화 로고 타이틀
TITLE_SIZE = 54        # 소제목 (영상 위)
TITLE_Y = 575
TITLE_LINE_GAP = 72
SUB_SIZE = 40          # 대사 자막 (영상 하단 안쪽)
SUB_Y = 1115
EXP_SIZE = 50          # 나레이션 자막 (영상 바로 아래, 항상 1줄)
EXP_Y = 1255
LOGO_SIZE = 130        # 영화 로고 타이틀 (궁서)
LOGO_Y = 1500
LOGO_SUB_SIZE = 34
LOGO_SUB_Y = 1665
LABEL_SIZE = 38        # 인물 설명 라벨
BUBBLE_SIZE = 60       # 말풍선 자막 (피사체 옆 대사·효과음, 주아체)
MIN_SUB_LEN = 0.3
NARR_DUCK = 0.30       # 나레이션 중 원본 볼륨
NARR_VOL = 1.6         # 나레이션 볼륨
EXP_HL = "0xFFD400"    # 키워드 포함 구 강조색 (노랑)
EXP_WHITE = "white"
CHUNK_CHARS = 13       # 나레이션 자막 구 길이


def chunk_script(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """나레이션 문장을 짧은 구 단위로 분할 (치고 빠지는 쇼츠 자막용)."""
    words = text.split()
    chunks, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and (len(cand) > limit or cur[-1] in ",.!?…"):
            chunks.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


def word_timings(wav: Path) -> list[tuple[float, float, str]]:
    """faster-whisper 단어 타임스탬프 — TTS 음성은 인식률이 높아 타이밍 그리드로 적합."""
    from faster_whisper import WhisperModel
    global _WM
    if "_WM" not in globals():
        _WM = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _WM.transcribe(str(wav), language="ko", word_timestamps=True)
    out = []
    for s in segs:
        for w in (s.words or []):
            out.append((w.start, w.end, w.word.strip()))
    return out


def sync_chunks(text: str, wav: Path, dur: float,
                mode: str = "chunk") -> list[tuple[float, float, str]]:
    """스크립트 텍스트를 나누고 실제 음성의 단어 타이밍에 정렬.

    '|' = 수동 분할. mode="sentence"면 문장 단위 통표시 (잘게 안 쪼갬 — 싱크 체감 좋음),
    mode="chunk"면 짧은 구 단위 (치고 빠지는 쇼츠 스타일).
    """
    if "|" in text:
        chunks = [c.strip() for c in text.split("|") if c.strip()]
    elif mode == "sentence":
        chunks = [c.strip() for c in re.split(r"(?<=[.!?…])\s+", text) if c.strip()]
    else:
        chunks = chunk_script(text)
    try:
        words = word_timings(wav)
        assert words
    except Exception:
        # 폴백: 글자수 비례 배치
        chars = sum(len(c) for c in chunks) or 1
        cursor, out = 0.0, []
        for c in chunks:
            w = dur * len(c) / chars
            out.append((cursor, cursor + w, c))
            cursor += w
        return out
    # 스크립트 누적 글자비율 → 인식 단어 누적 글자비율에 매핑해 경계 시각 결정
    script_total = sum(len(c.replace(" ", "")) for c in chunks) or 1
    rec_lens = [len(w[2]) for w in words]
    rec_total = sum(rec_lens) or 1
    out, acc = [], 0
    t_prev = words[0][0]
    for c in chunks:
        acc += len(c.replace(" ", ""))
        target = acc / script_total * rec_total
        run, t_end = 0, words[-1][1]
        for idx, L in enumerate(rec_lens):
            run += L
            if run >= target:
                # 경계 = 다음 단어의 시작 (단어 끝 기준이면 자막이 살짝 늦게 떠서 밀림)
                t_end = words[idx + 1][0] if idx + 1 < len(words) else words[idx][1]
                break
        out.append([t_prev, max(t_end, t_prev + 0.25), c])
        t_prev = t_end

    # 보정: 최소 표시시간 보장 + 경계 단조 정렬 (인식 누락으로 짧아진 청크 방지)
    prev_end = None
    for ch in out:
        if prev_end is not None and ch[0] < prev_end:
            ch[0] = prev_end
        ch[1] = max(ch[1], ch[0] + 0.45)
        prev_end = ch[1]
    # 마지막 자막은 음성 끝 + 최소 1.2초 여운 (말 끝나자마자 사라지지 않게)
    out[-1][1] = max(out[-1][1], dur - 0.02, out[-1][0] + 1.2)
    return [tuple(ch) for ch in out]


def est_units(text: str) -> float:
    """대략적 표시 폭 (전각=1, 공백/반각=0.5)."""
    u = 0.0
    for ch in text:
        if ch == " ":
            u += 0.45
        elif ord(ch) > 0x2E80:
            u += 1.0
        else:
            u += 0.55
    return u


def wrap(text: str, limit: int = 18) -> str:
    if len(text) <= limit or " " not in text:
        return text
    mid = len(text) // 2
    spaces = [i for i, c in enumerate(text) if c == " "]
    at = min(spaces, key=lambda i: abs(i - mid))
    return text[:at] + "\n" + text[at + 1:]


def probe_dur(path: Path) -> float:
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=60)
    return float(out.stdout.strip())


def parse_ranges(specs, three=False):
    out = []
    for spec in specs:
        rng, text = spec.split(":", 1)
        a, b = rng.split("-")
        out.append((float(a), float(b), text.strip()))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("video", nargs="?")
    p.add_argument("output", nargs="?")
    p.add_argument("--spec", default=None, help="UTF-8 JSON으로 모든 파라미터 전달 (한글 안전)")
    p.add_argument("--seg", action="append", default=[], metavar="시작-끝|파일|시작|끝")
    p.add_argument("--title", default="")
    p.add_argument("--subs", default=None)
    p.add_argument("--sub", action="append", default=[])
    p.add_argument("--exp", action="append", default=[], metavar="A-B:텍스트")
    p.add_argument("--narr", action="append", default=[], metavar="A:텍스트")
    p.add_argument("--voice", default=DEFAULT_VOICE, help="edge-tts 음성 (기본 여성 SunHi)")
    p.add_argument("--narr-rate", default=DEFAULT_RATE, help="나레이션 속도 예: +5%%")
    p.add_argument("--narr-pitch", default=DEFAULT_PITCH, help="나레이션 피치 예: +8Hz")
    p.add_argument("--crop", default=None, metavar="W:H:X:Y")
    args = p.parse_args()

    # ── --spec JSON 우선: {video, output, crop, title, voice, rate, pitch,
    #     segs:[[파일,A,B] 또는 [A,B]], subs:[[A,B,텍스트]], exps:[...], narrs:[[A,텍스트]]}
    if args.spec:
        sp = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        video = sp.get("video", args.video)
        output = sp["output"]
        crop_val = sp.get("crop", args.crop)
        title = sp.get("title", "")
        voice = sp.get("voice", DEFAULT_VOICE)
        rate = sp.get("rate", DEFAULT_RATE)
        pitch = sp.get("pitch", DEFAULT_PITCH)
        # segs 항목: [A,B] / [파일,A,B] / [파일,A,B,배속] / [파일,A,B,배속,회전]
        #           / [파일,A,B,배속,회전,확대,중심x,중심y]
        # (배속 0.5=슬로우, 회전 90/270 = 촬영 중 폰을 돌려 누운 구간 바로 세우기,
        #  확대 1.5=피사체 줌인 — 중심 0~1 비율, 생략 시 화면 중앙)
        segs = []
        for s in sp["segs"]:
            if isinstance(s[0], str):
                spd = float(s[3]) if len(s) > 3 else 1.0
                rot = int(s[4]) if len(s) > 4 else 0
                zoom = float(s[5]) if len(s) > 5 else 1.0
                zcx = float(s[6]) if len(s) > 6 else 0.5
                zcy = float(s[7]) if len(s) > 7 else 0.5
                if Path(s[0]).suffix.lower() in IMG_EXTS:
                    spd = 1.0  # 이미지는 배속 개념 없음 (표시 시간 = b-a)
                segs.append((s[0], float(s[1]), float(s[2]), spd, rot, zoom, zcx, zcy))
            else:
                segs.append((video, float(s[0]), float(s[1]), 1.0, 0, 1.0, 0.5, 0.5))
        subs = [(float(a), float(b), t) for a, b, t in sp.get("subs", [])]
        exps = [(float(a), float(b), t) for a, b, t in sp.get("exps", [])]
        # narrs 항목: [at, text] / [at, text, wav경로] /
        #   {"at":.., "text": 말할 내용, "caption": 자막 텍스트('|'=수동분할), "wav": 경로,
        #    "vol": 배수(1.0=기본), "speak": false=음성 없이 자막만,
        #    "voice": 이 문장만 다른 음성(예: 나레이터+캐릭터 혼성 나레이션)}
        narrs = []
        for entry in sp.get("narrs", []):
            if isinstance(entry, dict):
                narrs.append((float(entry["at"]), entry["text"],
                              entry.get("wav"), entry.get("caption"),
                              float(entry.get("vol", 1.0)),
                              bool(entry.get("speak", True)),
                              entry.get("voice")))
            else:
                wav = entry[2] if len(entry) > 2 else None
                narrs.append((float(entry[0]), entry[1], wav, None, 1.0, True, None))
        # 말풍선 자막: [[a, b, "텍스트", fx, fy]] — fx/fy는 화면 비율(0~1), 주아체로 피사체 옆에 표시
        bubbles = sp.get("bubbles", [])
        # 효과음: [[at, 파일경로, vol]] — 지정 시각에 강조음 삽입
        sfx = sp.get("sfx", [])
        narr_captions = sp.get("narr_captions", False)
        narr_warm = sp.get("narr_warm", True)
        keywords = sp.get("keywords", [])
        exp_color = sp.get("exp_color", EXP_HL)
        caption_mode = sp.get("caption_mode", "chunk")  # "sentence" = 문장 통표시
        logo = sp.get("logo")            # {"text": "올빼미", "sub": "The Night Owl · 2022"}
        labels = sp.get("labels", [])    # [[t0, t1, "(맹인 침술사)", x, y], ...]
        wide = sp.get("aspect") == "wide"  # 가로 16:9 (롱폼용)
        src_portrait = sp.get("src_portrait", False)  # 세로 촬영 소스 → 풀스크린
        bgm = sp.get("bgm")              # {"path": wav(생략시 라이브러리 첫 곡), "vol": 0.18}
        src_vol = float(sp.get("src_vol", 1.0))  # 원본 소리 배수 (0=무음, 1=그대로)
        # 발성 부스트: {"windows":[[a,b],...], "factor":3.0} — 출력초 기준 발성 구간만 원본 증폭
        vocal_boost = sp.get("vocal_boost")
        preview = sp.get("preview", False)  # 빠른 미리보기: 절반 해상도 + ultrafast 인코딩
    else:
        video, output, crop_val = args.video, args.output, args.crop
        title, voice, rate, pitch = args.title, args.voice, args.narr_rate, args.narr_pitch
        segs = []
        for spec in args.seg:
            if "|" in spec:
                path, a, b = spec.rsplit("|", 2)
                segs.append((path, float(a), float(b), 1.0, 0, 1.0, 0.5, 0.5))
            else:
                a, b = spec.split("-")
                segs.append((video, float(a), float(b), 1.0, 0, 1.0, 0.5, 0.5))
        subs = parse_ranges(args.sub)
        if args.subs:
            script = json.loads(Path(args.subs).read_text(encoding="utf-8"))
            cursor = 0.0
            for path, a, b, _spd, _rot, *_z in segs:
                if path == video:
                    for s in script:
                        s0, s1 = max(s["start"], a), min(s["end"], b)
                        if s1 - s0 >= MIN_SUB_LEN:
                            subs.append((cursor + s0 - a, cursor + s1 - a, s["text"]))
                cursor += b - a
        exps = parse_ranges(args.exp)
        narrs = [(float(s.split(":", 1)[0]), s.split(":", 1)[1].strip(), None, None, 1.0, True, None)
                 for s in args.narr]
        bubbles = []
        sfx = []
        src_vol = 1.0
        vocal_boost = None
        narr_captions = False
        narr_warm = True
        keywords = []
        exp_color = EXP_HL
        caption_mode = "chunk"
        logo = None
        labels = []
        wide = False
        src_portrait = False
        bgm = None
        preview = False

    total = sum((b - a) / spd for _, a, b, spd, _rot, *_z in segs)
    subs.sort()

    # ── 레이아웃 좌표 (세로 쇼츠 vs 가로 롱폼)
    if wide:  # 1920x1080: 본편 원크기 중앙(위아래 검은 바 138px), 바 안에 제목/자막
        out_w, out_h = 1920, 1080
        title_size, title_y, title_gap = 42, 40, 52
        sub_size, sub_y = 40, 845          # 대사: 본편 하단 안쪽
        exp_size, exp_y = 48, 972          # 나레이션: 하단 검은 바
        logo_size, logo_y = 52, 32         # 로고: 우상단 코너
        logo_right = True
        logo_sub_on = False
    else:     # 1080x1920 쇼츠
        out_w, out_h = OUT_W, OUT_H
        title_size, title_y, title_gap = TITLE_SIZE, TITLE_Y, TITLE_LINE_GAP
        sub_size, sub_y = SUB_SIZE, SUB_Y
        exp_size, exp_y = EXP_SIZE, EXP_Y
        logo_size, logo_y = LOGO_SIZE, LOGO_Y
        logo_right = False
        logo_sub_on = True
    # spec에서 나레이션 자막 크기/위치 직접 지정 가능
    if args.spec:
        exp_size = sp.get("exp_size", exp_size)
        exp_y = sp.get("exp_y", exp_y)
        title_y = sp.get("title_y", title_y)  # 수동 지정 시 자동 배치보다 우선

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        import shutil
        shutil.copy(FONT_SOURCE, tmp / "font.ttf")
        shutil.copy(FONT_EXP, tmp / "fontx.otf")   # Pretendard ExtraBold (제목)
        shutil.copy(FONT_NARR, tmp / "fontn.ttf")   # 궁서 (영화 로고)
        shutil.copy(FONT_ROUND, tmp / "fontr.ttf")  # 주아 (나레이션 자막 — 대사와 폰트 차별화)

        # ── 나레이션 TTS 생성 + 길이 측정
        # 캐시: 같은 (음성|속도|피치|후처리|문구)면 저장본 재사용 → API 크레딧 절약.
        # 바뀐 문장만 새로 합성된다.
        import hashlib
        cache_dir = Path(__file__).resolve().parent / ".cache" / "narr"
        cache_dir.mkdir(parents=True, exist_ok=True)
        narr_files = []
        for ni, (at, text, wavsrc, _cap, vol, speak, nvoice) in enumerate(narrs):
            if not speak:  # 자막만 — TTS 합성 없음 (자막 길이는 아래에서 글자수로 추정)
                narr_files.append((at, None, 0.0, vol))
                continue
            wav = tmp / f"narr{ni}.wav"
            if wavsrc:  # 외부 음성 파일 직접 삽입 — 24kHz mono로 정규화
                subprocess.run([config.FFMPEG, "-y", "-v", "error", "-i", wavsrc,
                                "-ar", "24000", "-ac", "1", str(wav)], check=True, timeout=120)
                if narr_warm:
                    warm(wav, config.FFMPEG)
            else:
                # 문장별 음성 오버라이드 (혼성 나레이션). Typecast는 이미 자연스러워 warm 생략
                voice_i = nvoice or voice
                warm_i = False if str(voice_i).startswith("tc_") else narr_warm
                key = hashlib.sha1(
                    f"{voice_i}|{rate}|{pitch}|{warm_i}|{text}".encode("utf-8")
                ).hexdigest()[:16]
                cached = cache_dir / f"{key}.wav"
                if cached.exists():
                    shutil.copy(cached, wav)
                    print(f"  나레이션 {ni + 1}: 캐시 재사용")
                else:
                    synth(text, wav, voice=voice_i, rate=rate, pitch=pitch)
                    if warm_i:
                        warm(wav, config.FFMPEG)
                    shutil.copy(wav, cached)
                    print(f"  나레이션 {ni + 1}: 새로 합성 (캐시 저장)")
            narr_files.append((at, wav, probe_dur(wav), vol))

        # 나레이션 = 자막: 구 단위 분할 + Whisper 단어 타이밍 정렬 + 키워드 강조색
        # 자막 싱크(whisper)는 (문구|모드|음성wav)가 같으면 재사용 → 반복 미리보기/재렌더 시 whisper 생략
        sync_cache = Path(__file__).resolve().parent / ".cache" / "narrsync"
        sync_cache.mkdir(parents=True, exist_ok=True)

        def cached_sync(txt, wavf, dur, mode):
            h = hashlib.sha1(f"{mode}|{txt}|".encode("utf-8") + wavf.read_bytes()).hexdigest()[:16]
            cf = sync_cache / f"{h}.json"
            if cf.exists():
                return json.loads(cf.read_text(encoding="utf-8"))
            chunks = sync_chunks(txt, wavf, dur, mode=mode)
            cf.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
            return chunks

        if narr_captions:
            exps = []
            for (at, text, _src, cap, _vol, speak, _nv), (_, wavf, dur, _v) in zip(narrs, narr_files):
                if not speak:  # 자막만: whisper 싱크 없이 글자수 기반 표시 시간 추정
                    ctext = (cap or text).replace("…", "").rstrip(".").strip()
                    est = min(6.0, max(1.3, 0.62 + 0.145 * len(ctext)))
                    exps.append((at, at + est, ctext, exp_color))
                    continue
                for c0, c1, ctext in cached_sync(cap or text, wavf, dur, caption_mode):
                    # 주아체에 '…' 글리프가 없어 네모로 깨짐 → 자막에서는 제거 (음성엔 유지)
                    ctext_clean = ctext.replace("…", "").rstrip(".").strip()
                    # keywords 미지정 시 단일색(exp_color). 지정 시에만 키워드 구 강조
                    color = EXP_HL if (keywords and any(k in ctext_clean for k in keywords)) \
                        else exp_color
                    # 앞 자막이 뒷 자막과 겹치지 않게 경계에서 0.06s 먼저 사라짐
                    c_end = max(c0 + 0.2, c1 - 0.06)
                    exps.append((at + c0, at + c_end, ctext_clean, color))
            # 나레이션 사이 전역 겹침 방지: 마지막 자막의 여운이 다음 나레이션
            # 첫 자막을 침범하면 다음 시작 직전까지로 잘라낸다
            exps.sort(key=lambda e: e[0])
            for i in range(len(exps) - 1):
                t0, t1, txt, col = exps[i]
                nxt = exps[i + 1][0]
                if t1 > nxt - 0.05:
                    exps[i] = (t0, max(t0 + 0.2, nxt - 0.05), txt, col)

        # ── 비디오/오디오 세그먼트
        # 세로 풀스크린 모드는 세그먼트별로 방향을 판단한다:
        #   회전(rot) 지정 → transpose로 바로 세움 / 가로 세그먼트 → 블러 배경 채움(찌그러뜨리지 않음)
        _dims_cache: dict[str, tuple[int, int]] = {}

        def display_dims(p: str) -> tuple[int, int]:
            """회전 메타데이터 반영된 표시 크기 (ffmpeg가 디코딩 시 자동 회전하므로 이것이 실제 프레임)."""
            if p not in _dims_cache:
                out_ = subprocess.run(
                    [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height:stream_side_data=rotation",
                     "-of", "json", p], capture_output=True, text=True, timeout=60)
                st = json.loads(out_.stdout)["streams"][0]
                w, h = int(st["width"]), int(st["height"])
                rot_meta = 0
                for sd in st.get("side_data_list", []):
                    rot_meta = int(sd.get("rotation", 0) or 0)
                if abs(rot_meta) % 180 == 90:
                    w, h = h, w
                _dims_cache[p] = (w, h)
            return _dims_cache[p]

        inputs, input_idx, lines, pairs = [], {}, [], []
        crop = f"crop={crop_val}," if crop_val else ""
        for i, (path, a, b, spd, rot, zoom, zcx, zcy) in enumerate(segs):
            if path not in input_idx:
                input_idx[path] = len(inputs)
                inputs.append(path)
            src = input_idx[path]
            tp = {90: "transpose=1,", 270: "transpose=2,", -90: "transpose=2,"}.get(rot, "")
            # 확대: 중심(zcx,zcy) 기준 1/zoom 크기로 크롭 → 이후 scale 정규화가 확대 효과
            zf = ""
            if zoom > 1.001:
                w0, h0 = display_dims(path)
                if rot in (90, 270, -90):
                    w0, h0 = h0, w0
                cw, ch = int(w0 / zoom) // 2 * 2, int(h0 / zoom) // 2 * 2
                zx = min(max(int(w0 * zcx - cw / 2), 0), w0 - cw)
                zy = min(max(int(h0 * zcy - ch / 2), 0), h0 - ch)
                zf = f"crop={cw}:{ch}:{zx}:{zy},"
            if Path(path).suffix.lower() in IMG_EXTS:
                # 정지 이미지: 첫 프레임을 (b-a)초 반복 + 비율 보존 레터박스, 오디오는 무음
                dur = round(max(0.1, b - a), 3)
                tw, th = (out_w, out_h) if (src_portrait and not wide) else (1920, 1080)
                lines.append(
                    f"[{src}:v]loop=loop=-1:size=1:start=0,trim=0:{dur},setpts=PTS-STARTPTS,"
                    f"fps=30,{tp}{zf}scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                    f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v{i}];")
                lines.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{dur},asetpts=PTS-STARTPTS[a{i}];")
                pairs.append(f"[v{i}][a{i}]")
                continue
            head = (f"[{src}:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{spd},{tp}{zf}" if spd != 1.0
                    else f"[{src}:v]trim={a}:{b},setpts=PTS-STARTPTS,{tp}{zf}")
            if src_portrait and not wide:
                w0, h0 = display_dims(path)
                if rot in (90, 270, -90):
                    w0, h0 = h0, w0
                if h0 > w0:   # 세로 → 풀스크린 (비율 보존 cover-crop)
                    lines.append(f"{head}scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                                 f"crop={out_w}:{out_h},setsar=1[v{i}];")
                else:         # 가로 → 블러 확대 배경 + 원본 중앙 (쇼츠 표준)
                    lines.append(f"{head}split=2[bg{i}][fg{i}];")
                    lines.append(f"[bg{i}]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                                 f"crop={out_w}:{out_h},boxblur=24:2[bgb{i}];")
                    lines.append(f"[fg{i}]scale={out_w}:-2[fgs{i}];")
                    lines.append(f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[v{i}];")
            else:
                nw, nh = (1080, 1920) if src_portrait else (1920, 1080)
                w0, h0 = display_dims(path)
                if rot in (90, 270, -90):
                    w0, h0 = h0, w0
                # 캔버스와 방향이 다른 소스(예: 가로 롱폼에 세로 촬영본)는 늘리지 않고
                # 블러 확대 배경 + 원본 중앙 (src_portrait 모드의 가로 처리와 동일 기법)
                if (w0 < h0) != (nw < nh):
                    lines.append(f"{head}split=2[bg{i}][fg{i}];")
                    lines.append(f"[bg{i}]scale={nw}:{nh}:force_original_aspect_ratio=increase,"
                                 f"crop={nw}:{nh},boxblur=24:2[bgb{i}];")
                    lines.append(f"[fg{i}]scale=-2:{nh}[fgs{i}];" if nw > nh
                                 else f"[fg{i}]scale={nw}:-2[fgs{i}];")
                    lines.append(f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[v{i}];")
                else:
                    lines.append(f"{head}scale={nw}:{nh},setsar=1[v{i}];")
            if spd != 1.0:  # 배속 (0.5 = 슬로우모션, 오디오는 피치 유지)
                # atempo는 [0.5, 100] 범위만 지원 → 벗어나면 체인으로 분할 (예: 0.4 = 0.5×0.8)
                tempos, rest = [], spd
                while rest < 0.5:
                    tempos.append(0.5)
                    rest /= 0.5
                tempos.append(round(rest, 4))
                chain = ",".join(f"atempo={t}" for t in tempos)
                lines.append(f"[{src}:a]atrim={a}:{b},asetpts=PTS-STARTPTS,{chain}[a{i}];")
            else:
                lines.append(f"[{src}:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}];")
            pairs.append(f"[v{i}][a{i}]")
        lines.append(f"{''.join(pairs)}concat=n={len(segs)}:v=1:a=1[vc][ac];")

        # 본편 → 검은 캔버스 중앙 (가로 모드는 본편 원폭 그대로 = 위아래 검은 바)
        lines.append(f"[vc]{crop}scale={out_w}:-2,setsar=1[film];")
        lines.append(f"color=black:s={out_w}x{out_h}:d={total:.3f}[canvas];")
        lines.append(f"[canvas][film]overlay=0:(H-h)/2:shortest=1[base];")

        vin = "base"
        title_lines = [l for l in title.split("|") if l]
        if wide and title_lines:  # 가로: 상단 바 한 줄
            title_lines = [" ".join(title_lines)]
        # 세로 레터박스: 제목 블록(줄수 반영)이 영상 상단을 침범하지 않게 자동 배치
        # (예: 2줄 제목이 16:9 영상 위 검은 바(656px)를 넘어 겹치던 문제)
        manual_ty = args.spec and "title_y" in sp
        if title_lines and not wide and not src_portrait and not manual_ty:
            cw, ch = 1920.0, 1080.0            # concat 전에 이 크기로 정규화됨
            if crop_val:
                p = crop_val.split(":")
                cw, ch = float(p[0]), float(p[1])
            film_top = (out_h - out_w * ch / cw) / 2
            block_h = title_size + (len(title_lines) - 1) * title_gap
            title_y = int(max(60, min(title_y, film_top - block_h - 28)))
        elif title_lines and not wide and src_portrait and not manual_ty:
            title_y = 140  # 풀스크린은 최상단이 그림이 제일 예쁨 (피사체 안 가림)
        # 풀스크린(세로 원본)은 영상 위에 제목이 얹히므로 반투명 검은 박스로 가독성 확보
        title_box = (":box=1:boxcolor=black@0.5:boxborderw=16"
                     if (src_portrait and not wide) else "")
        if title_box:
            # 줄 간격을 박스 높이(글자+패딩 16×2)에 정확히 맞춰 박스끼리 겹침(진해짐)도 틈도 없게
            title_gap = max(title_gap, title_size + 32)
        from app.bubble_png import has_emoji as _has_emoji, render_text_png
        # 줄별 y 커서: 이모지 줄(PNG)은 실제 이미지 높이가 title_gap보다 클 수 있어
        # 고정 간격 대신 렌더된 높이만큼 내려야 다음 줄과 겹치지 않는다
        ty = title_y
        for li, line in enumerate(title_lines):
            if _has_emoji(line):
                # 이모지 포함 제목: drawtext는 이모지 글리프가 없어 깨짐 → PIL 컬러 렌더 PNG 오버레이
                _pw, _ph = render_text_png(line, tmp / f"title{li}.png", font_path=FONT_EXP,
                                           fontsize=title_size, stroke=5, box=bool(title_box))
                lines.append(f"movie=title{li}.png[timg{li}];")
                lines.append(f"[{vin}][timg{li}]overlay=(W-w)/2:{ty}[vtt{li}];")
                ty += max(title_gap, _ph - 6)
            else:
                (tmp / f"title{li}.txt").write_text(line, encoding="utf-8")
                lines.append(
                    f"[{vin}]drawtext=fontfile=fontx.otf:textfile=title{li}.txt"
                    f":fontsize={title_size}:fontcolor=white:borderw=5:bordercolor=black"
                    f"{title_box}:x=(w-text_w)/2:y={ty}[vtt{li}];")
                ty += title_gap
            vin = f"vtt{li}"

        for si, (t0, t1, text) in enumerate(subs):
            (tmp / f"sub{si}.txt").write_text(wrap(text, 20), encoding="utf-8")
            lines.append(
                f"[{vin}]drawtext=fontfile=font.ttf:textfile=sub{si}.txt"
                f":fontsize={sub_size}:fontcolor=white:borderw=4:bordercolor=black"
                f":line_spacing=-25:x=(w-text_w)/2:y={sub_y}"
                f":enable='between(t,{t0:.2f},{t1:.2f})'[vsub{si}];")
            vin = f"vsub{si}"

        # 나레이션 자막: 주아체(둥글둥글), 항상 1줄 — 대사(맑은고딕)와 차별화
        for ei, exp in enumerate(exps):
            t0, t1, text = exp[0], exp[1], exp[2]
            color = exp[3] if len(exp) > 3 else exp_color
            # 한 줄 우선: 화면 폭(1040px)에 맞게 글자 크기 자동 축소.
            # 그래도 46px 미만이 필요하면 그때만 2줄 (간격 밀착)
            fit = min(exp_size, int(1040 / max(est_units(text), 1.0)))
            if fit >= 46:
                out_text, fsize = text, fit
            else:
                out_text, fsize = wrap(text, max(8, int(1000 / exp_size))), exp_size
            (tmp / f"exp{ei}.txt").write_text(out_text, encoding="utf-8")
            lines.append(
                f"[{vin}]drawtext=fontfile=fontr.ttf:textfile=exp{ei}.txt"
                f":fontsize={fsize}:fontcolor={color}:borderw=6:bordercolor=black"
                f":line_spacing=0:x=(w-text_w)/2:y={exp_y}"
                f":enable='between(t,{t0:.2f},{t1:.2f})'[vexp{ei}];")
            vin = f"vexp{ei}"

        # 영화 로고 타이틀 (궁서) — 세로: 최하단 중앙 + 부제 / 가로: 우상단 코너
        if logo:
            (tmp / "logo.txt").write_text(logo["text"], encoding="utf-8")
            logo_x = "w-text_w-46" if logo_right else "(w-text_w)/2"
            lines.append(
                f"[{vin}]drawtext=fontfile=fontn.ttf:textfile=logo.txt"
                f":fontsize={logo_size}:fontcolor=white:borderw=6:bordercolor=black"
                f":x={logo_x}:y={logo_y}[vlogo];")
            vin = "vlogo"
            if logo.get("sub") and logo_sub_on:
                (tmp / "logosub.txt").write_text(logo["sub"], encoding="utf-8")
                lines.append(
                    f"[{vin}]drawtext=fontfile=fontx.otf:textfile=logosub.txt"
                    f":fontsize={LOGO_SUB_SIZE}:fontcolor=0xBBBBBB:borderw=3:bordercolor=black"
                    f":x=(w-text_w)/2:y={LOGO_SUB_Y}[vlogos];")
                vin = "vlogos"

        # 인물 설명 라벨 (등장인물 옆에 표시)
        for li2, (t0, t1, text, lx, ly) in enumerate(labels):
            (tmp / f"label{li2}.txt").write_text(text, encoding="utf-8")
            lines.append(
                f"[{vin}]drawtext=fontfile=fontx.otf:textfile=label{li2}.txt"
                f":fontsize={LABEL_SIZE}:fontcolor=white:borderw=3:bordercolor=black"
                f":box=1:boxcolor=black@0.35:boxborderw=10"
                f":x={lx}:y={ly}:enable='between(t,{t0:.2f},{t1:.2f})'[vlab{li2}];")
            vin = f"vlab{li2}"

        # 말풍선 자막 — 강아지(피사체) 옆에 짧은 대사·효과음 (주아체, 흰 글씨 + 검정 테두리)
        # 이모지 포함 시 drawtext(단일 폰트)로는 깨지므로 PNG로 그려 overlay
        from app.bubble_png import has_emoji, render_bubble
        for bi, (b0, b1, text, fx, fy) in enumerate(bubbles):
            btext = text.replace("…", "").replace("·", "").strip()  # 주아체 미지원 글리프 제거
            bx, by = round(float(fx) * out_w), round(float(fy) * out_h)
            en = f"enable='between(t,{float(b0):.2f},{float(b1):.2f})'"
            if has_emoji(btext):
                render_bubble(btext, tmp / f"bubble{bi}.png", fontsize=BUBBLE_SIZE)
                lines.append(f"movie=bubble{bi}.png[bimg{bi}];")
                lines.append(f"[{vin}][bimg{bi}]overlay=x={bx}-w/2:y={by}-h/2:{en}[vbub{bi}];")
            else:
                (tmp / f"bubble{bi}.txt").write_text(btext, encoding="utf-8")
                lines.append(
                    f"[{vin}]drawtext=fontfile=fontr.ttf:textfile=bubble{bi}.txt"
                    f":fontsize={BUBBLE_SIZE}:fontcolor=white:borderw=7:bordercolor=black"
                    f":x={bx}-text_w/2:y={by}-text_h/2:{en}[vbub{bi}];")
            vin = f"vbub{bi}"

        # 원본 소리 볼륨 (0=무음 — 유행곡을 유튜브에서 얹을 영상 등)
        # + 발성 부스트: 발성 구간만 원본을 키워 BGM 음역에 묻힌 울음 복원 (bgm.duck과 짝)
        if vocal_boost and vocal_boost.get("windows"):
            _bf = float(vocal_boost.get("factor", 3.0))
            _bc = "+".join(f"between(t,{float(a):.2f},{float(b):.2f})" for a, b in vocal_boost["windows"])
            lines.append(f"[ac]volume='if({_bc},{round(src_vol * _bf, 3)},{round(src_vol, 3)})'"
                         f":eval=frame[acv];")
        else:
            lines.append(f"[ac]volume={round(src_vol, 3)}[acv];")

        # ── BGM: 원본과 먼저 믹스 (이후 나레이션 덕킹이 BGM에도 함께 적용됨)
        if bgm:
            bgm_path = bgm.get("path")
            if not bgm_path:
                lib_bgm = sorted((Path(__file__).resolve().parent / "library" / "bgm").glob("*.wav"))
                bgm_path = str(lib_bgm[0])
            bgm_vol = bgm.get("vol", 0.18)
            bgm_idx = len(inputs)
            inputs.append(bgm_path)
            # 발성 덕킹: duck 윈도우(출력초 [[a,b],...]) 동안 BGM을 duck_vol로 —
            # 오르골처럼 강아지 발성과 같은 음역인 BGM이 울음을 묻는 것 방지
            duck_windows = bgm.get("duck") or []
            if duck_windows:
                duck_vol = bgm.get("duck_vol", 0.05)
                cond = "+".join(f"between(t,{float(a):.2f},{float(b):.2f})" for a, b in duck_windows)
                lines.append(f"[{bgm_idx}:a]volume='if({cond},{duck_vol},{bgm_vol})':eval=frame,"
                             f"atrim=0:{total:.3f}[bgmx];")
            else:
                lines.append(f"[{bgm_idx}:a]volume={bgm_vol},atrim=0:{total:.3f}[bgmx];")
            lines.append(f"[acv][bgmx]amix=inputs=2:duration=first:normalize=0[acb];")
            lines.append(f"[acb]anull[ac2];")
        else:
            lines.append(f"[acv]anull[ac2];")

        # ── 오디오: 나레이션 사이드체인 자동 덕킹 (성우가 말할 때만 원본이 부드럽게 내려갔다 복귀)
        spoken_files = [nf for nf in narr_files if nf[1] is not None]  # 자막만 항목 제외
        if spoken_files:
            base_idx = len(inputs)
            narr_labels = []
            for ni, (at, wavf, _dur, vol) in enumerate(spoken_files):
                inputs.append(str(wavf))
                lines.append(f"[{base_idx + ni}:a]adelay={round(at * 1000)}:all=1,"
                             f"volume={round(NARR_VOL * vol, 3)}[n{ni}];")
                narr_labels.append(f"[n{ni}]")
            # 나레이션 버스 (전 구간 길이) → 사이드체인용/믹스용 분리
            if len(narr_labels) > 1:
                lines.append(f"{''.join(narr_labels)}amix=inputs={len(narr_labels)}:"
                             f"duration=longest:normalize=0[narrbus];")
            else:
                lines.append(f"{narr_labels[0]}anull[narrbus];")
            lines.append(f"[narrbus]apad=whole_dur={total:.3f},asplit=2[nsc][nmix];")
            # 원본(+BGM)을 나레이션 신호로 덕킹 (attack/release로 자연스러운 dip·복귀)
            lines.append(f"[ac2][nsc]sidechaincompress=threshold=0.03:ratio=12:"
                         f"attack=20:release=400[ducked];")
            lines.append(f"[ducked][nmix]amix=inputs=2:duration=first:normalize=0,"
                         f"alimiter=limit=0.95[aout];")
            amap = "[aout]"
        else:
            amap = "[ac2]"

        # ── 효과음: 지정 시각에 얹기 (덕킹 대상 아님 — 짧고 또렷한 강조음)
        if sfx:
            sfx_labels = []
            for si, entry in enumerate(sfx):
                at, path = float(entry[0]), entry[1]
                vol = float(entry[2]) if len(entry) > 2 else 0.9
                sidx = len(inputs)
                inputs.append(path)
                lines.append(f"[{sidx}:a]aformat=sample_rates=44100:channel_layouts=mono,"
                             f"adelay={round(at * 1000)}:all=1,volume={round(vol, 3)}[sfx{si}];")
                sfx_labels.append(f"[sfx{si}]")
            lines.append(f"{amap}{''.join(sfx_labels)}amix=inputs={1 + len(sfx_labels)}:"
                         f"duration=first:normalize=0,alimiter=limit=0.97[asfx];")
            amap = "[asfx]"

        # 빠른 미리보기: 레이아웃(1080 기준 좌표)은 그대로 그리고 마지막에 절반 축소 → 인코딩 부담↓
        if preview:
            pw, ph = (out_w // 2) & ~1, (out_h // 2) & ~1  # 짝수 보정
            lines.append(f"[{vin}]scale={pw}:{ph}[vpv];")
            vin = "vpv"

        (tmp / "filter.txt").write_text("\n".join(lines), encoding="utf-8")
        cmd = [config.FFMPEG, "-y", "-v", "error"]
        for f in inputs:
            cmd += ["-i", f]
        v_opts = (["-preset", "ultrafast", "-crf", "30"] if preview
                  else ["-preset", "medium", "-crf", "18"])
        cmd += ["-filter_complex_script", str(tmp / "filter.txt"),
                "-map", f"[{vin}]", "-map", amap,
                "-c:v", "libx264", *v_opts,
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                output]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=1800, cwd=str(tmp))
        if result.returncode != 0:
            print(result.stderr[:3000])
            sys.exit("렌더링 실패")

    out = Path(output)
    print(f"완료: {out} ({out.stat().st_size / 1e6:.1f} MB, {total:.1f}s, "
          f"대사 {len(subs)} / 설명 {len(exps)} / 나레이션 {len(narrs)})")


if __name__ == "__main__":
    main()
