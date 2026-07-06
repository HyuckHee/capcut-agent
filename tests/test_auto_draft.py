"""자동 틀 구간 병합/선택 로직 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auto_draft import _merge_bins, load_profile


def test_merge_adjacent_bins():
    scores = [0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 1]
    # gap=1: 1칸 공백까지만 이어붙임 (3~4 두 칸 공백은 분리)
    assert _merge_bins(scores, 0.5, gap=1) == [(1, 2), (5, 5), (9, 11)]
    # gap=2: 두 칸 공백도 병합
    assert _merge_bins(scores, 0.5, gap=2) == [(1, 5), (9, 11)]


def test_merge_respects_gap():
    scores = [1, 0, 0, 0, 1]
    assert _merge_bins(scores, 0.5, gap=1) == [(0, 0), (4, 4)]


def test_no_bins_above_threshold():
    assert _merge_bins([0.1, 0.2], 0.5) == []


def test_profiles_loadable():
    for name in ("wanghee", "cinema"):
        p = load_profile(name)
        assert p["target_len"] > 0
        assert 0 < p["w_vocal"]
