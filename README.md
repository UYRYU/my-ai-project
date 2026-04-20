# bs_edge — Polymarket BTC Up/Down edge detector

Price Polymarket "Bitcoin Up or Down" binary markets as cash-or-nothing
digital options (`P(S_T > K) = Φ(d2)` under Black-Scholes), compare to
the market-implied probability, and detect mispricings.

**Read-only.** This package does not place orders. It provides:

1. A historical data layer (Binance 1m OHLCV + Polymarket Gamma/Data)
   with parquet caching.
2. Digital-option pricing (`bs_edge.pricing`) and several realised-vol
   estimators (`bs_edge.volatility`: close-to-close, Parkinson,
   Garman-Klass, Yang-Zhang, EWMA).
3. A bar-by-bar backtest engine (`bs_edge.backtest`) and a
   walk-forward validator (`bs_edge.walkforward`) so the σ window and
   estimator are chosen on training folds and evaluated OOS.
4. Metrics (`bs_edge.metrics`): PnL, profit factor, Sharpe, win rate,
   Brier score, calibration MAE.
5. A read-only live scanner (`bs_edge.scanner`) that emits alerts and
   writes nothing else.

## Install

```bash
pip install -r requirements.txt
```

## Run a backtest

```bash
python run_backtest.py --since 2025-10-01 --until 2025-11-01 \
  --edge-threshold 0.05 --walk-forward --output out/trades.parquet
```

All parameters (σ window candidates, edge threshold, fees, stake mode,
Kelly cap, walk-forward splits) live in `bs_edge/config.py` and can be
overridden via a JSON/YAML file or `BSEDGE_*` environment variables.

## Tests

```bash
pytest -q
```
