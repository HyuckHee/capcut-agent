"""피사체 추적 crop 식 생성 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.track_subject import crop_expr


def test_single_knot_static_center():
    expr = crop_expr([(0.0, 0.5, 0.6)], "x")
    assert "iw*0.5" in expr
    assert expr.startswith("max(0,min(iw-ow,")


def test_multi_knot_piecewise():
    knots = [(0.0, 0.2, 0.6), (1.0, 0.4, 0.6), (2.0, 0.8, 0.6)]
    expr = crop_expr(knots, "x")
    # 반개구간 조합 — 경계 중복 합산 방지
    assert "gte(t,0.000)*lt(t,1.000)" in expr
    assert "gte(t,1.000)*lt(t,2.000)" in expr
    # 마지막 절점 이후 값 유지
    assert "gte(t,2.000)*0.8" in expr


def test_y_axis_uses_height_vars():
    expr = crop_expr([(0.0, 0.5, 0.7), (1.0, 0.5, 0.3)], "y")
    assert "ih" in expr and "oh" in expr and "iw" not in expr
