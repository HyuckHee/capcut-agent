#!/usr/bin/env python3
"""캡컷 에이전트 실행기 — 윈도우/맥 공용.

가상환경(.venv) 생성 → 의존성 설치 → 웹 서버 시작 → 브라우저 열기까지 자동 처리.
requirements.txt가 바뀌면 다음 실행 때 자동으로 재설치한다.
"""
import glob
import os
import platform
import shutil
import subprocess
import sys
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PORT = 8765
MIN_PY = (3, 11)


def _apple_silicon() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["sysctl", "-n", "hw.optional.arm64"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out == "1"
    except OSError:
        return False


def _is_rosetta() -> bool:
    """애플 실리콘에서 인텔(x86_64) 모드로 도는지 — 콘다 인텔 빌드 등이 원인.
    이 상태로 서버를 띄우면 arm64 휠(.so)을 못 읽어 크래시한다."""
    return platform.machine() == "x86_64" and _apple_silicon()


def _newer_python_candidates() -> list[str]:
    """PATH와 일반 설치 경로에서 3.11+ 인터프리터 후보를 새 버전 순으로 수집."""
    cands = []
    for minor in range(14, MIN_PY[1] - 1, -1):
        name = f"python3.{minor}"
        p = shutil.which(name)
        if p:
            cands.append(p)
        if os.name == "nt":
            continue
        # 맥: python.org 공식 설치 / Homebrew 경로 (PATH 미반영 셸 대비)
        cands += glob.glob(f"/Library/Frameworks/Python.framework/Versions/3.{minor}/bin/python3")
        cands += glob.glob(f"/opt/homebrew/bin/python3.{minor}")
        cands += glob.glob(f"/usr/local/bin/python3.{minor}")
    if os.name == "nt" and shutil.which("py"):
        cands.append("py")  # 윈도우 py 런처가 최신 3.x 선택
    return cands


def _probe(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd + ["--version"], capture_output=True, timeout=10).returncode == 0
    except OSError:
        return False


def _reexec_suitable_python(reason: str):
    """구버전/로제타 인터프리터면 적합한 파이썬을 찾아 run.py를 다시 실행."""
    fail_msg = (f"{reason}\n적합한 파이썬을 찾지 못했습니다. "
                "https://www.python.org/downloads/ 에서 최신 버전을 설치해주세요.")
    if os.environ.get("CAPCUT_RUN_REEXEC"):  # 재실행 루프 방지
        sys.exit(fail_msg)
    env = dict(os.environ, CAPCUT_RUN_REEXEC="1")
    # 애플 실리콘이면 arch로 네이티브 실행 강제 — 로제타 부모의 자식은 x86_64를 물려받으므로
    prefix = ["arch", "-arm64"] if _apple_silicon() else []
    for cand in _newer_python_candidates():
        base = prefix + ([cand, "-3"] if cand == "py" else [cand])
        if not _probe(base):  # 인텔 전용 빌드 등 arm64 실행 불가면 다음 후보로
            continue
        sys.exit(subprocess.call(base + [str(ROOT / "run.py")], env=env))
    sys.exit(fail_msg)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def ensure_venv() -> Path:
    py = venv_python()
    if not py.exists():
        print("가상환경 생성 중 (.venv)...")
        venv.create(VENV, with_pip=True)

    req = ROOT / "requirements.txt"
    stamp = VENV / ".req-stamp"
    if not stamp.exists() or stamp.read_bytes() != req.read_bytes():
        print("의존성 설치 중... (처음 한 번만 오래 걸립니다)")
        subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(req)])
        stamp.write_bytes(req.read_bytes())
    return py


def main():
    if sys.version_info < MIN_PY:
        _reexec_suitable_python(f"Python {MIN_PY[0]}.{MIN_PY[1]} 이상이 필요합니다 (현재 {sys.version.split()[0]}).")
    if _is_rosetta():
        _reexec_suitable_python("인텔(x86_64) 모드 파이썬 감지 — 애플 실리콘 네이티브로 전환합니다.")
    os.chdir(ROOT)
    py = ensure_venv()
    print()
    print("  캡컷 에이전트 시작 중... 브라우저가 곧 열립니다.")
    print("  (이 창을 닫으면 서버가 종료됩니다)")
    print()
    webbrowser.open(f"http://localhost:{PORT}")
    subprocess.call([str(py), "-m", "uvicorn", "web.server:app",
                     "--port", str(PORT), "--app-dir", str(ROOT)])


if __name__ == "__main__":
    main()
