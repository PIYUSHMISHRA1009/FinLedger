"""Time-series analytics for transaction and fraud-event forecasting.

The module follows the concepts covered in the project's Time Series Analysis
coursework: stationarity testing, ARIMA/SARIMA, exponential-smoothing
forecasting, multivariate-ready feature construction, and forecast comparison.

The functions operate on already aggregated daily observations so they can be
used with FinLedger's transaction table without changing ledger semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastResult:
    """Standardized forecast output suitable for an API or dashboard."""

    model: str
    horizon: int
    forecast: pd.Series
    aic: float | None = None


def build_daily_series(
    frame: pd.DataFrame,
    date_col: str = "created_at",
    value_col: str = "amount",
    agg: str = "sum",
) -> pd.Series:
    """Aggregate transaction data into a continuous daily time series."""
    if date_col not in frame or value_col not in frame:
        raise ValueError(f"Missing required columns: {date_col}, {value_col}")

    data = frame[[date_col, value_col]].copy()
    data[date_col] = pd.to_datetime(data[date_col], utc=True, errors="coerce")
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data = data.dropna()
    if data.empty:
        raise ValueError("No valid observations available")

    daily = data.set_index(date_col)[value_col].resample("D").agg(agg).astype(float)
    return daily.asfreq("D", fill_value=0.0)


def test_stationarity(series: Iterable[float]) -> dict[str, float | bool]:
    """Run an Augmented Dickey-Fuller test and return compact diagnostics."""
    from statsmodels.tsa.stattools import adfuller

    values = pd.Series(series, dtype=float).dropna()
    if len(values) < 12:
        raise ValueError("At least 12 observations are required for stationarity testing")

    statistic, p_value, _, _, critical_values, _ = adfuller(values, autolag="AIC")
    return {
        "adf_statistic": float(statistic),
        "p_value": float(p_value),
        "stationary_at_5pct": bool(p_value < 0.05),
        "critical_value_5pct": float(critical_values["5%"]),
    }


def forecast_ets(series: Iterable[float], horizon: int = 7) -> ForecastResult:
    """Forecast with Holt exponential smoothing after trend inspection."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    values = pd.Series(series, dtype=float).dropna().asfreq("D", fill_value=0.0)
    if len(values) < 14:
        raise ValueError("At least 14 daily observations are required")
    if horizon < 1:
        raise ValueError("horizon must be positive")

    fit = ExponentialSmoothing(values, trend="add", damped_trend=True).fit(optimized=True)
    forecast = fit.forecast(horizon)
    return ForecastResult("ETS", horizon, forecast, float(fit.aic))


def forecast_arima(
    series: Iterable[float],
    horizon: int = 7,
    order: tuple[int, int, int] = (1, 1, 1),
) -> ForecastResult:
    """Forecast a univariate series using ARIMA."""
    from statsmodels.tsa.arima.model import ARIMA

    values = pd.Series(series, dtype=float).dropna().asfreq("D", fill_value=0.0)
    if len(values) < 20:
        raise ValueError("At least 20 daily observations are required")
    if horizon < 1:
        raise ValueError("horizon must be positive")

    fit = ARIMA(values, order=order, enforce_stationarity=False, enforce_invertibility=False).fit()
    forecast = fit.forecast(horizon)
    return ForecastResult("ARIMA", horizon, forecast, float(fit.aic))


def forecast_sarima(
    series: Iterable[float],
    horizon: int = 7,
    order: tuple[int, int, int] = (1, 1, 1),
    seasonal_order: tuple[int, int, int, int] = (1, 0, 1, 7),
) -> ForecastResult:
    """Forecast daily data with a weekly seasonal SARIMA model."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    values = pd.Series(series, dtype=float).dropna().asfreq("D", fill_value=0.0)
    if len(values) < 35:
        raise ValueError("At least 35 daily observations are required for weekly seasonality")
    if horizon < 1:
        raise ValueError("horizon must be positive")

    fit = SARIMAX(
        values,
        order=order,
        seasonal_order=seasonal_order,
        enforce_stationarity=False,
        enforce_invertibility=False,
    ).fit(disp=False)
    forecast = fit.forecast(horizon)
    return ForecastResult("SARIMA", horizon, forecast, float(fit.aic))


def compare_forecasts(
    series: Iterable[float],
    horizon: int = 7,
) -> pd.DataFrame:
    """Compare candidate models using a chronological holdout and MAE/RMSE/MAPE."""
    values = pd.Series(series, dtype=float).dropna().asfreq("D", fill_value=0.0)
    if len(values) < max(30, horizon * 3):
        raise ValueError("Insufficient observations for model comparison")

    train = values.iloc[:-horizon]
    test = values.iloc[-horizon:]
    candidates = []
    for name, fn in (
        ("ETS", forecast_ets),
        ("ARIMA", forecast_arima),
    ):
        try:
            result = fn(train, horizon)
            pred = pd.Series(result.forecast, index=test.index)
            error = test - pred
            mae = float(np.mean(np.abs(error)))
            rmse = float(np.sqrt(np.mean(error**2)))
            nonzero = test != 0
            mape = float(np.mean(np.abs(error[nonzero] / test[nonzero])) * 100) if nonzero.any() else None
            candidates.append({"model": name, "MAE": mae, "RMSE": rmse, "MAPE_pct": mape, "AIC": result.aic})
        except (ValueError, np.linalg.LinAlgError):
            continue

    if not candidates:
        raise RuntimeError("No forecasting model could be fitted")
    return pd.DataFrame(candidates).sort_values("RMSE", ignore_index=True)
