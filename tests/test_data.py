import numpy as np
import pandas as pd
import pytest

from hkrisk import data


@pytest.mark.parametrize("name", ["small_prices", "snapshot"])
def test_price_frame_invariants(request, name):
    df = request.getfixturevalue(name)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert not df.index.duplicated().any()
    assert df.index.is_monotonic_increasing
    assert not df.isna().all().any()
    assert (df.min() > 0).all()  # min() skips NaN


def test_snapshot_covers_2007_to_as_of(snapshot):
    assert snapshot.index[0] <= pd.Timestamp("2007-01-05")
    assert snapshot.index[-1] == pd.Timestamp(data.SNAPSHOT_AS_OF)
    assert "^HSI" in snapshot


def test_align_prices_ffill_at_most_one_day():
    idx = pd.date_range("2024-01-01", periods=6)
    df = pd.DataFrame({"A": [1, np.nan, 3, np.nan, np.nan, 6], "B": range(1, 7)}, idx, dtype=float)
    out = data.align_prices(df)
    assert out.loc[idx[1], "A"] == 1  # one-day gap filled
    assert idx[4] not in out.index  # second consecutive gap day dropped
    assert not out.isna().any().any()


def test_load_prices_uses_cache_without_network(tmp_path, monkeypatch):
    calls = []

    def fake_download(tickers, start, end):
        calls.append(1)
        return pd.DataFrame({"X": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2))

    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "download_prices", fake_download)
    a = data.load_prices(["X"], "2024-01-01", "2024-01-02")
    b = data.load_prices(["X"], "2024-01-01", "2024-01-02")
    assert len(calls) == 1
    pd.testing.assert_frame_equal(a, b, check_freq=False)
    data.load_prices(["X"], "2024-01-01", "2024-01-02", refresh=True)
    assert len(calls) == 2
