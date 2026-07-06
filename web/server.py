"""캡컷 에이전트 웹 — 업로드한 영상으로 spec을 짜고 렌더링하는 로컬 사이트.

실행:  .venv\\Scripts\\python.exe -m uvicorn web.server:app --port 8765
접속:  http://localhost:8765
"""
import asyncio
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent   # 캡컷에이전트
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402

UPLOAD_DIR = ROOT / "웹업로드"
THUMB_DIR = Path(__file__).parent / "static" / "thumbs"
OUTPUT_DIR = ROOT / "완성영상"
SPEC_DIR = ROOT / ".cache" / "webspecs"
for d in (UPLOAD_DIR, THUMB_DIR, OUTPUT_DIR, SPEC_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="캡컷 에이전트")

JOBS: dict[str, "queue.Queue[str|None]"] = {}
CLIPS: dict[str, dict] = {}


def probe(path: Path) -> dict:
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True)
    j = json.loads(out.stdout)
    return {"duration": float(j["format"]["duration"]),
            "width": j["streams"][0]["width"], "height": j["streams"][0]["height"]}


def make_thumb(path: Path, clip_id: str, duration: float) -> tuple[str, bool]:
    """10프레임 스트립 생성. (썸네일 상대경로, 세로여부) 반환 — 세로 판정은 디코딩 결과 기준."""
    thumb = THUMB_DIR / f"{clip_id}.jpg"
    if not thumb.exists():  # 재시작 복원 시 재생성 생략
        fps = max(10 / duration, 0.05)
        subprocess.run(
            [config.FFMPEG, "-y", "-v", "error", "-i", str(path),
             "-vf", f"fps={fps},scale=150:-2,tile=10x1", "-frames:v", "1", str(thumb)],
            capture_output=True, timeout=300, check=True)
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(thumb)],
        capture_output=True, text=True, timeout=30, check=True)
    w, h = map(int, out.stdout.strip().rstrip(",").split(",")[:2])
    portrait = (h / 1) > (w / 10)  # 타일 1칸의 세로가 가로보다 크면 세로 영상
    return f"thumbs/{clip_id}.jpg", portrait


def register_clip(dest: Path, orig_name: str) -> dict:
    """클립을 CLIPS에 등록하고 사이드카 메타를 남긴다 (서버 재시작 후 복원용)."""
    clip_id = dest.stem
    info = probe(dest)
    thumb, portrait = make_thumb(dest, clip_id, info["duration"])
    c = {"id": clip_id, "name": orig_name, "path": str(dest),
         "duration": round(info["duration"], 1), "thumb": thumb, "portrait": portrait}
    CLIPS[clip_id] = c
    (UPLOAD_DIR / f"{clip_id}.json").write_text(
        json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return c


def restore_clips() -> None:
    """웹업로드 폴더를 훑어 지난 세션 업로드를 복원한다."""
    for meta in UPLOAD_DIR.glob("*.json"):
        try:
            c = json.loads(meta.read_text(encoding="utf-8"))
            if Path(c["path"]).exists():
                CLIPS[c["id"]] = c
        except Exception:
            pass
    for f in UPLOAD_DIR.glob("*.mp4"):
        if f.stem not in CLIPS:  # 사이드카 없던 구버전 업로드
            try:
                register_clip(f, f.name)
            except Exception:
                pass


restore_clips()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    clip_id = uuid.uuid4().hex[:8]
    ext = Path(file.filename).suffix.lower() or ".mp4"
    dest = UPLOAD_DIR / f"{clip_id}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return register_clip(dest, file.filename)


@app.get("/api/clips")
async def list_clips():
    return sorted(CLIPS.values(), key=lambda c: c["id"])


@app.get("/api/voices")
async def voices():
    return [
        {"id": "tc_65fbe54e2668bc4ddbd8b2a6", "name": "왕희 목소리 (타입캐스트)"},
        {"id": "tc_68257f68bc6e3c161ab5078d", "name": "영화 나레이션 (타입캐스트)"},
        {"id": "ko-KR-SunHiNeural", "name": "선히 · 여성 (edge-tts 무료)"},
        {"id": "ko-KR-InJoonNeural", "name": "인준 · 남성 (edge-tts 무료)"},
        {"id": "ko-KR-HyunsuMultilingualNeural", "name": "현수 · 남성 (edge-tts 무료)"},
    ]


@app.get("/api/bgms")
async def bgms():
    return [{"name": f.stem, "path": str(f)}
            for f in sorted((ROOT / "library" / "bgm").glob("*.wav"))]


# ── 휴리스틱 자동 틀 + 프로파일 튜닝
from app.auto_draft import draft, load_profile, save_profile  # noqa: E402


@app.get("/api/profile/{name}")
async def get_profile(name: str):
    return load_profile(name)


@app.put("/api/profile/{name}")
async def put_profile(name: str, data: dict):
    data.pop("_설명", None)
    merged = {**load_profile(name), **data}
    save_profile(name, merged)
    return merged


@app.post("/api/autodraft")
async def autodraft(payload: dict):
    """업로드된 클립들을 신호 분석해서 초안 세그먼트를 뽑는다 (수 분 소요 가능)."""
    clip_ids = payload["clips"]
    profile = load_profile(payload.get("profile", "wanghee"))
    paths = [CLIPS[c]["path"] for c in clip_ids if c in CLIPS]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, draft, paths, profile)
    # clip 인덱스 → clip id로 변환
    for seg in result["segments"]:
        seg["clip_id"] = clip_ids[seg.pop("clip")]
    return result


from app.ai_draft import ai_draft, recommend_edit, find_claude  # noqa: E402


@app.post("/api/airecommend")
async def airecommend(payload: dict):
    """원본 클립 전체 + 줄거리를 Claude에게 보여주고 편집 구간을 추천받는다."""
    profile = load_profile(payload.get("profile", "wanghee"))
    style = profile.get("ai_style", "")
    target_len = float(profile.get("target_len", 45))
    max_len = 59.0 if payload.get("profile") == "cinema" else 90.0
    clip_ids = payload["clips"]
    clips = [{"path": CLIPS[c]["path"], "duration": CLIPS[c]["duration"]}
             for c in clip_ids if c in CLIPS]
    if not clips:
        return JSONResponse({"error": "업로드된 클립이 없습니다"}, status_code=400)
    if not find_claude():
        return JSONResponse({"error": "Claude Code CLI(claude)를 찾을 수 없습니다"}, status_code=500)
    synopsis = (payload.get("synopsis") or "").strip()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, recommend_edit, clips, synopsis, style, target_len, max_len)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    for seg in result["segments"]:
        seg["clip_id"] = clip_ids[seg.pop("clip")]
    return result


@app.post("/api/aidraft")
async def aidraft(payload: dict):
    """세그먼트 대표 프레임을 Claude 헤드리스에 보여주고 제목·나레이션 초안을 받는다."""
    profile = load_profile(payload.get("profile", "wanghee"))
    style = profile.get("ai_style", "")
    segments = []
    for s in payload["segments"]:
        c = CLIPS.get(s["clip_id"])
        if not c:
            return JSONResponse({"error": f"클립 없음: {s['clip_id']}"}, status_code=400)
        segments.append({"path": c["path"], "a": s["a"], "b": s["b"],
                         "spd": s.get("spd", 1), "tags": s.get("tags", "")})
    if not segments:
        return JSONResponse({"error": "세그먼트가 없습니다"}, status_code=400)
    if not find_claude():
        return JSONResponse({"error": "Claude Code CLI(claude)를 찾을 수 없습니다"}, status_code=500)
    synopsis = (payload.get("synopsis") or "").strip()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, ai_draft, segments, style, synopsis)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return result


@app.get("/api/storage")
async def storage():
    files = list(UPLOAD_DIR.glob("*"))
    return {"files": len(files), "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1)}


@app.post("/api/storage/cleanup")
async def storage_cleanup():
    """현재 세션에서 쓰지 않는 업로드 파일·썸네일 삭제."""
    keep = {Path(c["path"]).name for c in CLIPS.values()}
    keep |= {f"{c['id']}.json" for c in CLIPS.values()}
    removed = 0
    for f in UPLOAD_DIR.glob("*"):
        if f.name not in keep:
            f.unlink(missing_ok=True)
            (THUMB_DIR / f"{f.stem}.jpg").unlink(missing_ok=True)
            removed += 1
    files = list(UPLOAD_DIR.glob("*"))
    return {"removed": removed, "files": len(files),
            "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1)}


def run_job(job_id: str, spec: dict):
    q = JOBS[job_id]
    try:
        spec_path = SPEC_DIR / f"{job_id}.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        q.put("STEP:나레이션 합성")
        proc = subprocess.Popen(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"),
             str(ROOT / "render_cinema.py"), "--spec", str(spec_path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
        rendering = False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            q.put(f"LOG:{line}")
            if "나레이션" in line and not rendering:
                pass
            if line.startswith("완료:"):
                rendering = True
        proc.wait()
        if proc.returncode == 0:
            q.put("STEP:완료")
            q.put(f"DONE:{spec['output']}")
        else:
            q.put(f"ERR:렌더링 실패 (코드 {proc.returncode})")
    except Exception as e:
        q.put(f"ERR:{e}")
    finally:
        q.put(None)


@app.post("/api/render")
async def render(payload: dict):
    job_id = uuid.uuid4().hex[:8]
    title_out = (payload.get("output_name") or f"웹렌더_{job_id}").strip()
    if title_out.lower().endswith(".mp4"):
        title_out = title_out[:-4]
    spec = payload["spec"]
    spec["output"] = str(OUTPUT_DIR / f"{title_out}.mp4")
    JOBS[job_id] = queue.Queue()
    threading.Thread(target=run_job, args=(job_id, spec), daemon=True).start()
    return {"job": job_id, "output": spec["output"]}


@app.get("/api/events/{job_id}")
async def events(job_id: str):
    q = JOBS.get(job_id)

    async def gen():
        if q is None:
            yield "data: ERR:작업 없음\n\n"
            return
        loop = asyncio.get_event_loop()
        while True:
            msg = await loop.run_in_executor(None, q.get)
            if msg is None:
                break
            yield f"data: {msg}\n\n"
            await asyncio.sleep(0.05)  # 스테퍼 가시화

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/video")
async def video(path: str):
    p = Path(path)
    if p.exists() and p.suffix == ".mp4" and OUTPUT_DIR in p.parents:
        return FileResponse(p, media_type="video/mp4")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/clip/{clip_id}")
async def clip_stream(clip_id: str):
    """업로드된 원본 클립 스트리밍 (플레이어용 — Range 지원으로 탐색 가능)."""
    c = CLIPS.get(clip_id)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(c["path"], media_type="video/mp4")


@app.delete("/api/clip/{clip_id}")
async def clip_delete(clip_id: str):
    """클립 파일·사이드카·썸네일 삭제 (용량 관리)."""
    c = CLIPS.pop(clip_id, None)
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    Path(c["path"]).unlink(missing_ok=True)
    (UPLOAD_DIR / f"{clip_id}.json").unlink(missing_ok=True)
    (THUMB_DIR / f"{clip_id}.jpg").unlink(missing_ok=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
