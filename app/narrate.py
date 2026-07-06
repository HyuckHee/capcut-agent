"""한국어 나레이션 TTS.

1순위: edge-tts (Microsoft Edge 신경망 음성, 무료·API키 불필요, 인터넷 필요) — 자연스러움
2순위: Windows SAPI Heami (오프라인 폴백, 다소 기계적)

edge-tts 음성:
  ko-KR-InJoonNeural (남, 다큐/나레이션 추천)
  ko-KR-HyunsuMultilingualNeural (남)
  ko-KR-SunHiNeural (여)
"""
import subprocess
import sys
from pathlib import Path

from . import config

DEFAULT_VOICE = "ko-KR-SunHiNeural"   # 여성
DEFAULT_RATE = "+5%"                  # 살짝 빠르게
DEFAULT_PITCH = "+8Hz"               # 살짝 높게 = 가벼운 톤


def _edge(text: str, out_wav: Path, voice: str, rate: str, pitch: str) -> None:
    mp3 = out_wav.with_suffix(".mp3")
    subprocess.run(
        [sys.executable, "-m", "edge_tts", "--voice", voice, f"--rate={rate}",
         f"--pitch={pitch}", "--text", text, "--write-media", str(mp3)],
        check=True, capture_output=True, timeout=120,
    )
    subprocess.run(
        [config.FFMPEG, "-y", "-v", "error", "-i", str(mp3),
         "-ar", "24000", "-ac", "1", str(out_wav)],
        check=True, capture_output=True, timeout=60,
    )


_SAPI_PS = """
Add-Type -AssemblyName System.Speech
$text = Get-Content -Raw -Encoding UTF8 '{txt}'
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{ $s.SelectVoice('Microsoft Heami Desktop') }} catch {{}}
$s.Rate = -1
$s.SetOutputToWaveFile('{wav}')
$s.Speak($text)
$s.Dispose()
"""


def _sapi(text: str, out_wav: Path) -> None:
    txt = out_wav.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    ps = out_wav.with_suffix(".ps1")
    ps.write_text(_SAPI_PS.format(txt=str(txt).replace("\\", "/"),
                                  wav=str(out_wav).replace("\\", "/")),
                  encoding="utf-8-sig")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)],
        check=True, capture_output=True, timeout=120,
    )


def _typecast(text: str, out_wav: Path, voice_id: str, emotion: str | None) -> None:
    from . import typecast_api
    raw = out_wav.with_name(out_wav.stem + "_tc.wav")
    typecast_api.tts(text, voice_id, raw, emotion=emotion)
    subprocess.run([config.FFMPEG, "-y", "-v", "error", "-i", str(raw),
                    "-ar", "24000", "-ac", "1", str(out_wav)], check=True, timeout=60)


def synth(text: str, out_wav: Path, voice: str = DEFAULT_VOICE,
          rate: str = DEFAULT_RATE, pitch: str = DEFAULT_PITCH,
          emotion: str | None = None) -> None:
    """text를 out_wav로 합성.

    voice가 'tc_'로 시작하면 Typecast API(최상급 자연스러움, 크레딧 소모),
    아니면 edge-tts(무료), 실패 시 SAPI 폴백.
    """
    if voice.startswith("tc_"):
        _typecast(text, out_wav, voice, emotion)
        return
    try:
        _edge(text, out_wav, voice, rate, pitch)
    except Exception as e:
        print(f"  (edge-tts 실패 → SAPI 폴백: {e})")
        _sapi(text, out_wav)


# 팟캐스트풍 "따뜻한 마이크" 후처리: 저역 정리 + 바디/프레즌스 EQ + 하쉬 억제 +
# 컴프레션(고른 레벨) + 아주 옅은 룸(친밀감) + 살짝 새츄레이션. 딱딱한 TTS 음색 완화.
WARM_CHAIN = (
    "highpass=f=80,"
    "equalizer=f=200:t=q:w=1.0:g=3,"     # 바디/따뜻함
    "equalizer=f=450:t=q:w=1.3:g=1.2,"   # 풍성함
    "equalizer=f=3000:t=q:w=2.5:g=-3,"   # 디지털 하쉬 억제
    "equalizer=f=7000:t=q:w=2.0:g=1.5,"  # 공기감/프레즌스
    "lowpass=f=13500,"
    "acompressor=threshold=-20dB:ratio=3:attack=8:release=260:makeup=3,"
    "aecho=0.85:0.9:22:0.12,"            # 아주 옅은 룸 (팟캐스트 친밀감)
    "asoftclip=type=tanh,"               # 옅은 아날로그 새츄레이션
    "alimiter=limit=0.95"
)


def warm(wav: Path, ffmpeg: str) -> None:
    """나레이션 wav에 팟캐스트풍 톤을 입힌다 (제자리 갱신)."""
    tmp = wav.with_name(wav.stem + "_w.wav")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(wav),
                    "-af", WARM_CHAIN, "-ar", "24000", "-ac", "1", str(tmp)],
                   check=True, timeout=120)
    tmp.replace(wav)
