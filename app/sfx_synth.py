"""귀여운 카툰 효과음 + BGM 합성기.

library/sfx/, library/bgm/ 에 wav를 생성한다.
같은 이름의 파일이 이미 있으면 재생성하지 않으므로,
더 좋은 음원을 구하면 같은 이름으로 덮어쓰면 그대로 쓰인다.
"""
import wave
from pathlib import Path

import numpy as np

SR = 44100
LIBRARY = Path(__file__).resolve().parent.parent / "library"


def _write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = np.max(np.abs(samples)) or 1.0
    pcm = (samples / peak * 0.85 * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _t(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur)) / SR


def _env(t: np.ndarray, attack: float, decay: float) -> np.ndarray:
    """빠른 어택 + 지수 감쇠 엔벨로프."""
    return np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-t / decay)


def _sine_sweep(t: np.ndarray, freq: np.ndarray) -> np.ndarray:
    """시변 주파수의 사인파 (위상 적분)."""
    return np.sin(2 * np.pi * np.cumsum(freq) / SR)


def make_pop(path: Path) -> None:
    """뽁 — 짧은 피치 드랍 버블."""
    t = _t(0.16)
    freq = 850 * np.exp(-t * 14) + 250
    s = _sine_sweep(t, freq) * _env(t, 0.003, 0.05)
    _write_wav(path, s)


def make_boing(path: Path) -> None:
    """보잉 — 스프링처럼 출렁이며 가라앉는 피치."""
    t = _t(0.55)
    freq = 260 + 200 * np.exp(-t * 5) * np.cos(2 * np.pi * 9 * t * np.exp(-t * 1.5))
    s = _sine_sweep(t, freq)
    s += 0.4 * _sine_sweep(t, freq * 2.01)  # 살짝 어긋난 배음 → 통통한 질감
    s *= _env(t, 0.004, 0.22)
    _write_wav(path, s)


def make_squeak(path: Path) -> None:
    """뾱 — 장난감 삑삑이 (올라갔다 내려오는 벤드)."""
    t = _t(0.28)
    bend = np.sin(np.pi * t / 0.28)  # 0→1→0
    freq = 900 + 900 * bend
    s = _sine_sweep(t, freq)
    s += 0.5 * _sine_sweep(t, freq * 1.5) + 0.25 * _sine_sweep(t, freq * 2.5)
    s *= np.sin(np.pi * t / 0.28) ** 0.6 * 0.9
    _write_wav(path, s)


def make_whoosh(path: Path) -> None:
    """슉 — 노이즈 스윕 (구르기/움직임)."""
    rng = np.random.default_rng(7)
    t = _t(0.4)
    noise = rng.standard_normal(len(t))
    # 이동평균 컷오프를 시간에 따라 좁혀 밝아지는 스윕 질감
    k1 = np.convolve(noise, np.ones(24) / 24, mode="same")
    k2 = np.convolve(noise, np.ones(6) / 6, mode="same")
    mix = np.linspace(0, 1, len(t))
    s = (k1 * (1 - mix) + k2 * mix) * np.sin(np.pi * t / 0.4) ** 1.5 * 3
    _write_wav(path, s)


def make_wiggle(path: Path) -> None:
    """꾸물꾸물 — 뒤척이는 부스럭 리듬 (부드러운 노이즈 펄스 + 몽글 저음)."""
    rng = np.random.default_rng(3)
    t = _t(0.75)
    noise = rng.standard_normal(len(t))
    soft = np.convolve(noise, np.ones(40) / 40, mode="same")        # 이불 부스럭 질감
    pulses = (0.5 * (1 + np.sin(2 * np.pi * 5.5 * t - np.pi / 2))) ** 1.5  # ~5.5Hz 꾸물 리듬
    wob = 0.35 * _sine_sweep(t, 90 + 25 * np.sin(2 * np.pi * 3 * t))       # 몽글거리는 저음
    s = (soft * 3 + wob) * pulses * np.exp(-t * 1.2)
    _write_wav(path, s)


def make_whine(path: Path) -> None:
    """낑낑 — 강아지 애교 낑낑 두 번 (가늘게 떨리는 상승-하강 톤)."""
    def one(f0_scale: float, dur: float) -> np.ndarray:
        t = _t(dur)
        bend = np.sin(np.pi * t / dur) ** 0.8          # 올라갔다 내려오는 콧소리 벤드
        freq = (750 + 750 * bend) * f0_scale
        vib = 1 + 0.02 * np.sin(2 * np.pi * 27 * t)    # 가는 떨림
        s = _sine_sweep(t, freq * vib)
        s += 0.45 * _sine_sweep(t, freq * vib * 2) + 0.18 * _sine_sweep(t, freq * vib * 3)
        return s * np.sin(np.pi * t / dur) ** 1.2

    gap = np.zeros(int(SR * 0.10))
    s = np.concatenate([one(1.0, 0.32), gap, one(0.92, 0.38) * 0.9])
    _write_wav(path, s)


def make_sparkle(path: Path) -> None:
    """반짝 — 상행 벨 아르페지오 (마무리 귀여움)."""
    notes = [1046.5, 1318.5, 1568.0, 2093.0]  # C6 E6 G6 C7
    total = 0.09 * len(notes) + 0.5
    s = np.zeros(int(SR * total))
    for i, f in enumerate(notes):
        t = _t(0.5)
        bell = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t)) * _env(t, 0.002, 0.14)
        start = int(SR * 0.09 * i)
        s[start:start + len(bell)] += bell
    _write_wav(path, s)


def make_musicbox_bgm(path: Path, duration: float = 45.0) -> None:
    """오르골풍 잔잔·귀여운 BGM 루프 (C–G–Am–F 아르페지오)."""
    bpm = 88
    eighth = 60 / bpm / 2
    chords = [  # 각 마디의 아르페지오 음 (Hz, 4옥타브 기준)
        [261.6, 392.0, 523.3, 659.3, 523.3, 392.0, 329.6, 392.0],   # C
        [196.0, 293.7, 392.0, 587.3, 493.9, 392.0, 293.7, 392.0],   # G
        [220.0, 329.6, 440.0, 523.3, 440.0, 329.6, 261.6, 329.6],   # Am
        [174.6, 261.6, 349.2, 523.3, 440.0, 349.2, 261.6, 349.2],   # F
    ]
    s = np.zeros(int(SR * duration) + SR)
    pos = 0.0
    ci = 0
    while pos < duration:
        for f in chords[ci % len(chords)]:
            t = _t(0.8)
            pluck = (np.sin(2 * np.pi * f * 2 * t)          # 오르골은 한 옥타브 위
                     + 0.3 * np.sin(2 * np.pi * f * 4 * t)
                     + 0.12 * np.sin(2 * np.pi * f * 6 * t)) * _env(t, 0.002, 0.35)
            start = int(SR * pos)
            s[start:start + len(pluck)] += pluck * 0.6
            pos += eighth
            if pos >= duration:
                break
        ci += 1
    _write_wav(path, s[:int(SR * duration)])


def make_ukulele_bgm(path: Path, duration: float = 45.0) -> None:
    """경쾌한 우쿨렐레풍 스트럼 BGM (I–V–vi–IV, 110bpm) — 신나는 놀이 장면용."""
    bpm = 110
    beat = 60 / bpm
    chords = [
        [261.6, 329.6, 392.0],   # C
        [196.0, 246.9, 293.7],   # G
        [220.0, 261.6, 329.6],   # Am
        [174.6, 220.0, 261.6],   # F
    ]
    s = np.zeros(int(SR * duration) + SR)
    pos = 0.0
    ci = 0
    pattern = [1.0, 0.5, 0.75, 0.5, 1.0, 0.5, 0.75, 0.5]  # 스트럼 세기
    while pos < duration:
        chord = chords[ci % len(chords)]
        for amp in pattern:
            t = _t(0.35)
            strum = np.zeros(len(t))
            for k, f in enumerate(chord):
                delay = int(SR * 0.012 * k)  # 스트럼 딜레이
                pluck = (np.sin(2 * np.pi * f * 2 * t) + 0.4 * np.sin(2 * np.pi * f * 4 * t))
                pluck *= _env(t, 0.002, 0.12)
                strum[delay:] += pluck[:len(strum) - delay]
            start = int(SR * pos)
            s[start:start + len(strum)] += strum * amp * 0.4
            pos += beat / 2
            if pos >= duration:
                break
        ci += 1
    _write_wav(path, s[:int(SR * duration)])


def make_pizzicato_bgm(path: Path, duration: float = 45.0) -> None:
    """통통 튀는 피치카토 BGM (120bpm, 스타카토 멜로디) — 장꾸/코믹 장면용."""
    bpm = 120
    eighth = 60 / bpm / 2
    melody = [523.3, 659.3, 783.99, 659.3, 880.0, 783.99, 659.3, 523.3,
              587.3, 698.5, 880.0, 698.5, 783.99, 659.3, 587.3, 523.3]
    bass = [261.6, 196.0, 220.0, 174.6]
    s = np.zeros(int(SR * duration) + SR)
    pos = 0.0
    i = 0
    while pos < duration:
        f = melody[i % len(melody)]
        t = _t(0.16)
        pluck = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2 * t)) * _env(t, 0.001, 0.05)
        start = int(SR * pos)
        s[start:start + len(pluck)] += pluck * 0.5
        if i % 4 == 0:  # 베이스
            fb = bass[(i // 8) % len(bass)]
            tb = _t(0.3)
            bs = np.sin(2 * np.pi * fb * tb) * _env(tb, 0.002, 0.12)
            s[start:start + len(bs)] += bs * 0.35
        pos += eighth
        i += 1
    _write_wav(path, s[:int(SR * duration)])


GENERATORS = {
    "sfx/pop.wav": make_pop,
    "sfx/boing.wav": make_boing,
    "sfx/squeak.wav": make_squeak,
    "sfx/whoosh.wav": make_whoosh,
    "sfx/wiggle.wav": make_wiggle,
    "sfx/whine.wav": make_whine,
    "sfx/sparkle.wav": make_sparkle,
    "bgm/cute_musicbox.wav": make_musicbox_bgm,
    "bgm/ukulele_bounce.wav": make_ukulele_bgm,
    "bgm/pizzicato_play.wav": make_pizzicato_bgm,
}


def ensure_library() -> Path:
    """라이브러리 폴더를 보장하고 없는 음원만 합성. 라이브러리 루트 반환."""
    for rel, gen in GENERATORS.items():
        target = LIBRARY / rel
        if not target.exists():
            gen(target)
    return LIBRARY


if __name__ == "__main__":
    root = ensure_library()
    for p in sorted(root.rglob("*.wav")):
        print(p.relative_to(root))
