"""Technical indicators on small hand-checked SYNTHETIC series (ADR-0034)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import technical as ta

RISING = pd.Series(np.arange(1.0, 31.0))
FLAT = pd.Series(np.full(30, 5.0))


def _bars(close: pd.Series, spread: float = 1.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    return close + spread, close - spread, close


def test_moving_averages_by_hand() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    assert ta.sma(values, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(ta.sma(values, 3).iloc[1])
    assert ta.wma(values, 3).iloc[2] == pytest.approx((1 + 4 + 9) / 6)  # weights 1, 2, 3
    ema = ta.ema(values, 3)  # alpha 0.5 from the first value: 1, 1.5, 2.25, 3.125, 4.0625
    assert np.isnan(ema.iloc[1])
    assert ema.dropna().tolist() == pytest.approx([2.25, 3.125, 4.0625])
    assert ta.hull(RISING, 9).dropna().iloc[-1] == pytest.approx(30.0, rel=1e-9)  # no lag on a line
    kama = ta.kama(RISING, 10)
    assert kama.iloc[9] == 10.0  # starts at the close of the first full window
    assert kama.dropna().is_monotonic_increasing


def test_rsi_reads_100_without_losses_and_nothing_during_warm_up() -> None:
    values = ta.rsi(RISING, 14)

    assert values.iloc[:13].isna().all()
    assert (values.dropna() == 100.0).all()
    assert (ta.rsi(FLAT, 14).dropna() == 100.0).all()  # ta's convention: no losses, 100


def test_oscillators_on_a_steady_rise() -> None:
    high, low, close = _bars(RISING)

    np.testing.assert_allclose(ta.stochastic(high, low, close, 5).dropna(), 100 * 5 / 6)
    np.testing.assert_allclose(ta.williams_r(high, low, close, 5).dropna(), -100 / 6)
    assert ta.roc(RISING, 1).iloc[1] == pytest.approx(100.0)
    aroon = ta.aroon(high, low, 5)
    assert (aroon["up"].dropna() == 100.0).all()
    assert (aroon["down"].dropna() == 0.0).all()
    macd = ta.macd(RISING, 3, 6, 2)
    assert (macd["line"].dropna() > 0).all()
    np.testing.assert_allclose(macd["histogram"], macd["line"] - macd["signal"])


def test_undefined_ratios_are_gaps_never_numbers() -> None:
    high, low, close = _bars(FLAT, spread=0.0)

    assert ta.stochastic(high, low, close, 5).isna().all()
    assert ta.williams_r(high, low, close, 5).isna().all()
    assert ta.cci(high, low, close, 5).isna().all()
    assert ta.stoch_rsi(FLAT, 5).isna().all()
    assert ta.bollinger(FLAT, 5)["percent_b"].isna().all()
    assert (ta.cmf(high, low, close, pd.Series(np.ones(30)), 5).dropna() == 0.0).all()
    assert ta.volume_ratio(pd.Series(np.zeros(30)), 5).isna().all()


def test_volatility_and_channels() -> None:
    high, low, close = _bars(RISING)

    ranges = ta.true_range(high, low, close)
    assert ranges.iloc[0] == 2.0  # the first bar's own range
    assert ranges.iloc[1] == 2.0  # high - low = 2 > |high - previous close| = 2
    atr = ta.atr(high, low, close, 5)
    assert atr.iloc[:4].isna().all()
    assert atr.dropna().tolist() == pytest.approx([2.0] * 26)
    bands = ta.bollinger(RISING, 5, 2.0)
    assert bands["middle"].iloc[4] == 3.0
    assert bands["upper"].iloc[4] - bands["middle"].iloc[4] == pytest.approx(
        2 * np.std([1, 2, 3, 4, 5])
    )
    donchian = ta.donchian(high, low, 5)
    assert donchian["upper"].iloc[4] == 6.0
    assert donchian["lower"].iloc[4] == 0.0
    keltner = ta.keltner(high, low, close, 5)
    assert ((keltner["upper"] - keltner["middle"]).dropna() > 0).all()


def test_trend_on_a_steady_rise() -> None:
    high, low, close = _bars(RISING)

    adx = ta.adx(high, low, close, 5)
    assert adx["adx"].iloc[:9].isna().all()
    assert adx["adx"].iloc[9] == pytest.approx(100.0)
    assert (adx["plus_di"].dropna() > adx["minus_di"].dropna()).all()
    sar = ta.psar(high, low, close)
    assert sar.iloc[:2].isna().all()
    assert (sar.dropna() < low.iloc[2:]).all()  # below the lows while the trend lasts
    ichimoku = ta.ichimoku(high, low, 3, 5)
    assert ichimoku["conversion"].iloc[2] == 2.0


def test_the_sar_reverses_when_the_trend_breaks() -> None:
    close = pd.Series([10.0, 11, 12, 13, 14, 15, 9, 8, 7, 6])
    high, low, _ = _bars(close, 0.5)

    sar = ta.psar(high, low, close)

    assert sar.iloc[6] > close.iloc[6]  # above the price once it falls through
    assert (sar.iloc[7:] > high.iloc[7:]).all()


def test_money_flow() -> None:
    high, low, close = _bars(RISING)
    volume = pd.Series(np.full(30, 10.0))

    assert (ta.mfi(high, low, close, volume, 5).dropna() == 100.0).all()  # only inflows
    assert ta.cmf(high, low, close, volume, 5).dropna().tolist() == pytest.approx([0.0] * 26)
    assert ta.volume_ratio(volume, 5).dropna().tolist() == pytest.approx([1.0] * 26)


@pytest.mark.parametrize(
    "call",
    [
        lambda: ta.sma(RISING, 0),
        lambda: ta.hull(RISING, 1),
        lambda: ta.kama(RISING, 0),
        lambda: ta.rsi(RISING, 0),
        lambda: ta.aroon(RISING, RISING, 0),
        lambda: ta.adx(RISING, RISING, RISING, 0),
        lambda: ta.atr(RISING, RISING, RISING, 0),
        lambda: ta.ichimoku(RISING, RISING, 0, 5),
        lambda: ta.psar(RISING, RISING, RISING, step=0.3, max_step=0.2),
        lambda: ta.mfi(RISING, RISING, RISING, RISING, 0),
    ],
)
def test_invalid_windows_are_refused(call: object) -> None:
    with pytest.raises(ValueError, match=r"must be|need"):
        call()  # type: ignore[operator]


def test_short_series_are_all_warm_up() -> None:
    short = pd.Series([1.0, 2.0])

    for values in (
        ta.wma(short, 5),
        ta.kama(short, 5),
        ta.atr(short, short, short, 5),
        ta.cci(short, short, short, 5),
        ta.aroon(short, short, 5)["up"],
        ta.adx(short, short, short, 5)["adx"],
    ):
        assert values.isna().all()
    assert ta.psar(short[:1], short[:1], short[:1]).isna().all()


def test_the_catalogue_validates_its_requests() -> None:
    bars = {"close": RISING}

    assert ta.compute("SMA", bars, window=5).name == "SMA"
    assert ta.compute("RSI", bars).equals(ta.rsi(RISING, 14).rename("RSI"))  # defaults
    with pytest.raises(KeyError, match="unknown indicator"):
        ta.compute("NOPE", bars)
    with pytest.raises(KeyError, match=r"needs the \['high', 'low'\] columns"):
        ta.compute("ADX", bars)
    with pytest.raises(ValueError, match=r"no parameters \['speed'\]"):
        ta.compute("RSI", bars, speed=3)
    with pytest.raises(ValueError, match="whole number"):
        ta.compute("RSI", bars, window=14.5)
    with pytest.raises(ValueError, match="positive"):
        ta.compute("BB_UPPER", bars, dev=0)
    with pytest.raises(ValueError, match="outside"):
        ta.Parameter(1, 5, 9)


def test_every_catalogue_entry_has_coherent_metadata() -> None:
    for name, indicator in ta.CATALOGUE.items():
        assert indicator.name == name
        for parameter in indicator.parameters.values():
            assert parameter.low <= parameter.default <= parameter.high
        if indicator.threshold is not None:
            low, high = indicator.threshold
            assert low < high
        assert set(indicator.defaults) == set(indicator.parameters)
