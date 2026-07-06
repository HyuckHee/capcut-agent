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


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    clip_id = uuid.uuid4().hex[:8]
    ext = Path(file.filename).suffix.lower() or ".mp4"
    dest = UPLOAD_DIR / f"{clip_id}{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    info = probe(dest)
    thumb, portrait = make_thumb(dest, clip_id, info["duration"])
    CLIPS[clip_id] = {"id": clip_id, "name": file.filename, "path": str(dest),
                      "duration": round(info["duration"], 1), "thumb": thumb,
                      "portrait": portrait}
    return CLIPS[clip_id]


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


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
