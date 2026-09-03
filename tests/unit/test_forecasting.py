"""Unit tests for FinLedger time-series analytics."""

import numpy as np
import pandas as pd
import pytest

from finledger.analytics.forecasting import (
    build_daily_series,
    compare_forecasts,
    forecast_arima,
    forecast_ets,
    forecast_sarima,
    test_stationarity,
)


def daily_series(days: int = 70) -> pd.Series:
    index = pd.date_range("2026-01-01", periods=days, freq="D")
    values = 100 + np.arange(days) * 0.5 + 10 * np.sin(2 * np.pi * np.arange(days) / 7)
    return pd.Series(values, index=index)


def test_build_daily_series_fills_missing_days():
    frame = pd.DataFrame(
        {
            "created_at": ["2026-01-01T10:00:00Z", "2026-01-03T10:00:00Z"],
            "amount": [10, 25],
        }
    )
    result = build_daily_series(frame)
    assert len(result) == 3
    assert result.loc["2026-01-02"] == 0


def test_stationarity_returns_adf_diagnostics():
    result = test_stationarity(daily_series())
    assert "adf_statistic" in result
    assert "p_value" in result
    assert isinstance(result["stationary_at_5pct"], bool)


def test_ets_forecasts_requested_horizon():
    result = forecast_ets(daily_series(), horizon=7)
    assert result.model == "ETS"
    assert len(result.forecast) == 7


def test_arima_forecasts_requested_horizon():
    result = forecast_arima(daily_series(), horizon=5)
    assert result.model == "ARIMA"
    assert len(result.forecast) == 5


def test_sarima_forecasts_requested_horizon():
    result = forecast_sarima(daily_series(), horizon=5)
    assert result.model == "SARIMA"
    assert len(result.forecast) == 5


def test_compare_forecasts_uses_holdout():
    result = compare_forecasts(daily_series(), horizon=7)
    assert not result.empty
    assert {"model", "MAE", "RMSE", "MAPE_pct"}.issubset(result.columns)
    assert result["RMSE"].notna().all()


@pytest.mark.parametrize("horizon", [0, -1])
def test_forecast_rejects_invalid_horizon(horizon):
    with pytest.raises(ValueError):
        forecast_ets(daily_series(), horizon=horizon)
