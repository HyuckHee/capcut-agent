"""Typecast API 클라이언트 — 나레이션 TTS (유료 크레딧, 자연스러움 최상급)."""
import json
import urllib.request
from pathlib import Path

API_BASE = "https://api.typecast.ai"
KEY_FILE = Path(__file__).resolve().parent.parent / ".secrets" / "typecast.key"


def _key() -> str:
    return KEY_FILE.read_text(encoding="utf-8").strip()


def list_voices() -> list[dict]:
    req = urllib.request.Request(f"{API_BASE}/v2/voices", headers={"X-API-KEY": _key()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def tts(text: str, voice_id: str, out_path: Path, *,
        model: str = "ssfm-v30", language: str = "kor",
        emotion: str | None = None, intensity: float = 1.0) -> None:
    """음성 합성 → out_path (wav). emotion 예: 'normal', 'happy', 'sad', 'angry' (모델별 상이)."""
    body: dict = {
        "voice_id": voice_id,
        "text": text,
        "model": model,
        "language": language,
        "output": {"audio_format": "wav"},
    }
    if emotion:
        body["prompt"] = {"emotion_preset": emotion, "emotion_intensity": intensity}
    req = urllib.request.Request(
        f"{API_BASE}/v1/text-to-speech",
        data=json.dumps(body).encode("utf-8"),
        headers={"X-API-KEY": _key(), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        out_path.write_bytes(r.read())


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    voices = list_voices()
    print(f"총 {len(voices)}개 음성")
    for v in voices:
        emos = ",".join(v.get("emotions", [])[:6])
        print(f"{v.get('voice_id')} | {v.get('voice_name')} | {v.get('model')} | {emos}")
