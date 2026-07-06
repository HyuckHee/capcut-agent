import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
"""나레이션 음성 비교 샘플 생성 (완성영상/나레이션샘플)."""
import shutil
from pathlib import Path

from app import config
from app.narrate import synth, warm

LINE = "불이 꺼지자, 그의 눈이 뜨였다. 그는 어둠 속에서만 볼 수 있는 자였다."
OUT = Path(r"C:\Users\leehh\OneDrive\문서\캡컷에이전트\완성영상\나레이션샘플")
OUT.mkdir(exist_ok=True)

jobs = [
    ("Hyunsu_원본", "ko-KR-HyunsuMultilingualNeural", False),
    ("Hyunsu_따뜻하게", "ko-KR-HyunsuMultilingualNeural", True),
    ("InJoon_따뜻하게", "ko-KR-InJoonNeural", True),
    ("SunHi_따뜻하게", "ko-KR-SunHiNeural", True),
]
for name, voice, do_warm in jobs:
    wav = OUT / f"{name}.wav"
    synth(LINE, wav, voice=voice, rate="-6%", pitch="+0Hz")
    if do_warm:
        warm(wav, config.FFMPEG)
    print("made:", name)
print("폴더:", OUT)
