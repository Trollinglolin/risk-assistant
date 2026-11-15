import numpy as np
import pandas as pd
import pytest

from hkrisk.portfolio import hypothetical_pnl, position_values, simple_returns


@pytest.fixture
def toy():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    prices = pd.DataFrame({"A": [10.0, 11.0, 9.9], "B": [100.0, 98.0, 99.96]}, index=idx)
    return {"A": 100, "B": 10}, prices


def test_simple_returns(toy):
    _, p = toy
    r = simple_returns(p)
    np.testing.assert_allclose(r["A"], [0.10, -0.10])
    np.testing.assert_allclose(r["B"], [-0.02, 0.02])


def test_position_values(toy):
    h, p = toy
    v = position_values(h, p, "2024-01-04")
    assert v["A"] == pytest.approx(990.0) and v["B"] == pytest.approx(999.6)


def test_hypothetical_pnl_toy(toy):
    h, p = toy
    pnl = hypothetical_pnl(h, p, "2024-01-04", window=2)
    # today's values (990, 999.6) x each day's returns
    expected = [990 * 0.10 + 999.6 * -0.02, 990 * -0.10 + 999.6 * 0.02]
    np.testing.assert_allclose(pnl.values, expected, atol=1e-9)
    assert round(pnl.iloc[0], 2) == 79.01


def test_no_lookahead(small_prices, holdings):
    as_of = small_prices.index[-30]
    a = hypothetical_pnl(holdings, small_prices, as_of, window=100)
    future_shock = small_prices.copy()
    future_shock.loc[future_shock.index > as_of] *= 0.5
    b = hypothetical_pnl(holdings, future_shock, as_of, window=100)
    pd.testing.assert_series_equal(a, b)
    assert a.index[-1] <= as_of


def test_window_too_long_raises(small_prices, holdings):
    with pytest.raises(ValueError):
        hypothetical_pnl(holdings, small_prices, None, window=10_000)
