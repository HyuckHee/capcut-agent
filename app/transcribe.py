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


_WM_CACHE: dict = {}


def transcribe_segments(segments: list[dict], model_size: str = "medium") -> list[dict]:
    """편집 세그먼트[{path,a,b,spd}] → 완성영상 기준 시각의 대사 자막 [{a,b,text}].

    각 세그먼트 구간(a~b)만 잘라 whisper로 돌리고, 배속(spd)·컷 순서를 반영해
    완성 영상 타임라인 좌표로 환산한다. 원본 통째 전사(transcribe())와 달리
    편집 후 세그먼트에만, 그 위치 그대로 대사 자막이 붙는다.
    """
    from faster_whisper import WhisperModel

    if model_size not in _WM_CACHE:
        _WM_CACHE[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    model = _WM_CACHE[model_size]

    out: list[dict] = []
    cursor = 0.0
    with tempfile.TemporaryDirectory() as td:
        for i, seg in enumerate(segments):
            a, b, spd = float(seg["a"]), float(seg["b"]), float(seg.get("spd") or 1)
            length = (b - a) / spd
            wav = Path(td) / f"seg{i}.wav"
            subprocess.run(
                [config.FFMPEG, "-y", "-v", "error", "-ss", str(a), "-to", str(b),
                 "-i", seg["path"], "-ar", "16000", "-ac", "1", str(wav)],
                check=True, capture_output=True, timeout=300,
            )
            whisper_segs, _info = model.transcribe(str(wav), language="ko", vad_filter=True)
            for s in whisper_segs:
                text = s.text.strip()
                if not text:
                    continue
                out.append({"a": round(cursor + s.start / spd, 2),
                           "b": round(cursor + s.end / spd, 2), "text": text})
            cursor += length
    return out


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
