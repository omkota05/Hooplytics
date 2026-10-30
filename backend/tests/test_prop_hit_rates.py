from app.analytics.lines import evaluate_line


def test_push_not_counted_as_win_or_loss():
    result = evaluate_line([20, 21, 20, 19], 20.0)
    assert result.push == 2
    assert result.over == 1
    assert result.under == 1
    decided = result.over + result.under
    assert result.over_pct_excluding_pushes == round(100 * result.over / decided, 1)


def test_half_point_line_hit_rates():
    result = evaluate_line([21, 22, 18, 19], 20.5)
    assert result.push == 0
    assert result.over == 2
    assert result.under == 2
    assert result.over_pct == 50.0
