"""경로/기본값 설정. 트랙 C (Windows, faster-whisper)."""
import os
import shutil
from pathlib import Path

def _find_ffmpeg_bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # winget(Gyan.FFmpeg) 설치 경로 — PATH 미반영 세션 대비
    packages = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Packages"
    for exe in packages.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"):
        return str(exe)
    raise FileNotFoundError(f"{name}을 찾을 수 없습니다. winget install Gyan.FFmpeg 후 다시 시도하세요.")

FFMPEG = _find_ffmpeg_bin("ffmpeg")
FFPROBE = _find_ffmpeg_bin("ffprobe")

CAPCUT_DRAFT_FOLDER = str(
    Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
)

# 무음 감지 기본값
SILENCE_NOISE_DB = -35        # 이보다 조용하면 무음 후보
SILENCE_MIN_DUR = 0.45        # 이 길이(초) 이상 지속돼야 무음으로 판정
KEEP_PAD = 0.12               # 발화 구간 앞뒤로 남길 여유(초)
MIN_KEEP_DUR = 0.20           # 이보다 짧은 발화 조각은 버림(초)
MERGE_GAP = 0.15              # 이 간격(초) 이하로 붙은 발화 구간은 병합
