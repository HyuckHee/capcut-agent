"""자막 분할·정렬 로직 테스트 (미디어/네트워크 불필요)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from render_cinema import chunk_script, wrap, est_units, sync_chunks


def test_chunk_script_splits_by_length():
    chunks = chunk_script("하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열", limit=8)
    assert all(len(c) <= 12 for c in chunks)
    assert " ".join(chunks) == "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열"


def test_chunk_script_breaks_at_punctuation():
    chunks = chunk_script("불이 꺼지는 순간, 눈을 뜹니다.", limit=13)
    assert chunks[0].endswith(",")


def test_wrap_short_text_untouched():
    assert wrap("짧은 문장", 18) == "짧은 문장"


def test_wrap_long_text_two_lines():
    out = wrap("아주 길고 긴 문장이 두 줄로 나뉘어야 합니다", 10)
    assert "\n" in out
    assert out.replace("\n", " ") == "아주 길고 긴 문장이 두 줄로 나뉘어야 합니다"


def test_est_units_fullwidth_vs_ascii():
    assert est_units("가나다") > est_units("abc")
    assert est_units("가 나") < est_units("가나나")


def test_sync_chunks_fallback_proportional(tmp_path):
    """음성 파일이 없으면 글자수 비례 배치로 폴백한다."""
    fake = tmp_path / "none.wav"
    out = sync_chunks("첫 문장입니다. 두 번째 문장입니다.", fake, dur=10.0, mode="sentence")
    assert len(out) == 2
    assert out[0][0] == 0.0
    assert abs(out[-1][1] - 10.0) < 0.01
    # 경계 단조 증가
    assert out[0][1] <= out[1][0] + 1e-6


def test_sync_chunks_manual_pipe_split(tmp_path):
    fake = tmp_path / "none.wav"
    out = sync_chunks("앞부분|뒷부분", fake, dur=4.0)
    assert [c[2] for c in out] == ["앞부분", "뒷부분"]
