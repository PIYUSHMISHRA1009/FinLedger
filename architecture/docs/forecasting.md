# FinLedger Time-Series Forecasting

## Objective

FinLedger now contains a dedicated analytics layer for forecasting transaction activity. The feature is designed to demonstrate practical time-series analysis rather than simply adding an ML model.

The transaction model provides timestamped `created_at` observations and numeric `amount` values. The analytics layer aggregates these observations into daily series and leaves the financial ledger untouched.

## Coursework alignment

The implementation is intentionally based on the Time Series Analysis topics studied in the Mathematics and Computing curriculum:

- **Stationarity:** Augmented Dickey-Fuller testing and explicit stationarity diagnostics.
- **Basic time-series models:** daily aggregation and trend inspection.
- **ARIMA:** autoregressive/integrated/moving-average forecasting.
- **SARIMA:** seasonal extension for recurring weekly patterns in daily transaction activity.
- **Forecasting methods and comparison:** chronological holdout evaluation using MAE, RMSE and MAPE.
- **Model identification/estimation:** candidate-model comparison rather than assuming one model is universally best.
- **Multivariate-ready design:** the daily aggregation layer can be extended with additional exogenous variables such as transaction count, fraud-event count or average transaction value.

The course also covers cointegration, causality, ARCH/GARCH and neural networks for time series. These are intentionally not presented as implemented features unless and until they are backed by a tested implementation and suitable data.

## Current implementation

`src/finledger/analytics/forecasting.py` provides:

- `build_daily_series()` — converts timestamped transaction records into a continuous daily series.
- `test_stationarity()` — runs the Augmented Dickey-Fuller test.
- `forecast_ets()` — Holt-style exponential smoothing with a damped trend.
- `forecast_arima()` — ARIMA forecasting.
- `forecast_sarima()` — SARIMA forecasting with weekly seasonality.
- `compare_forecasts()` — chronological holdout comparison using MAE, RMSE and MAPE.

## Recommended analytical workflow

```text
Transactions
    |
    v
Data validation + completed/posted filtering
    |
    v
Daily aggregation (per currency)
    |
    +--> EDA / trend / seasonality
    |
    +--> ADF stationarity test
    |
    +--> Baseline
    |
    +--> ETS / ARIMA / SARIMA
    |
    v
Chronological holdout evaluation
    |
    v
Best validated model
    |
    v
Forecast + uncertainty + metadata
```

## Important financial-data rule

Currencies must not be aggregated together. A USD series and an INR series represent different units. A future dashboard/API should either forecast each currency separately or apply an explicit, documented FX conversion methodology.

## Next extension: multivariate forecasting

A strong next iteration would create a daily feature table containing:

- total transaction value;
- transaction count;
- average transaction amount;
- completed/failed transaction counts;
- fraud-event count/risk score;
- optional external market variables.

This can support regression-with-time-series-errors or other multivariate methods after leakage-safe validation.

## Evaluation requirements

Do not use random train/test splits for time-series evaluation. Keep temporal order intact. Report MAE and RMSE at minimum, and report MAPE only where the target contains meaningful non-zero values.

Any resume claim should be based on measured results from a reproducible dataset and evaluation script.
