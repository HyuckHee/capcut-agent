"""faster-whisper 전사 — 전체 대본(세그먼트+타임스탬프) 추출."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config


def transcribe(video_path: str, model_size: str = "medium") -> list[dict]:
    """[{start, end, text}] 세그먼트 목록."""
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        subprocess.run(
            [config.FFMPEG, "-y", "-v", "error", "-i", video_path,
             "-ar", "16000", "-ac", "1", str(wav)],
            check=True, capture_output=True, timeout=600,
        )
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(wav), language="ko", vad_filter=True)
        return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    video = sys.argv[1]
    out_json = sys.argv[2] if len(sys.argv) > 2 else None
    segs = transcribe(video)
    for s in segs:
        print(f"{s['start']:7.1f} ~ {s['end']:7.1f}  {s['text']}")
    if out_json:
        Path(out_json).write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n저장: {out_json}")
