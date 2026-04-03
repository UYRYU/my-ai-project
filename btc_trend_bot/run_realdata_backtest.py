"""
Real Data Backtest Runner for BTC Trend Long Bot
=================================================
Run backtests on real BTCUSDT data from Bitget.
Compares all 8 strategies x multiple exit methods.
Generates regime-split reports and strategy rankings.

Usage:
    python -m btc_trend_bot.run_realdata_backtest
    python -m btc_trend_bot.run_realdata_backtest --data data/raw/BTCUSDT_1h.csv
    python -m btc_trend_bot.run_realdata_backtest --fetch --start 2023-01-01
    python -m btc_trend_bot.run_realdata_backtest --strategy pullback_strict --exit partial_trail
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger

from btc_trend_bot.env_loader import load_env

from btc_trend_bot.data_loader import DataLoader
from btc_trend_bot.feature_engineering import FeatureEngineer
from btc_trend_bot.extract_bull_runs import BullRunExtractor
from btc_trend_bot.backtest.engine import BacktestEngine
from btc_trend_bot.backtest.exit_manager import ExitManager
from btc_trend_bot.metrics import calc_all_metrics, get_top_trades, analyze_top_trades
from btc_trend_bot.report_generator import ReportGenerator


def _get_all_strategy_classes() -> dict:
    """Import and return all 8 strategy classes."""
    from btc_trend_bot.strategies.trend_long.pullback_strategy import PullbackStrategy
    from btc_trend_bot.strategies.trend_long.breakout_strategy import BreakoutStrategy
    from btc_trend_bot.strategies.trend_long.reacceleration_strategy import ReaccelerationStrategy
    from btc_trend_bot.strategies.trend_long.multi_tf_strategy import MultiTFStrategy

    strategy_map = {
        "pullback": PullbackStrategy,
        "breakout": BreakoutStrategy,
        "reacceleration": ReaccelerationStrategy,
        "multi_tf": MultiTFStrategy,
    }

    # Try importing strict variants
    try:
        from btc_trend_bot.strategies.trend_long.pullback_strict import PullbackStrictStrategy
        strategy_map["pullback_strict"] = PullbackStrictStrategy
    except ImportError:
        logger.warning("PullbackStrictStrategy not available")
    try:
        from btc_trend_bot.strategies.trend_long.breakout_confirmed import BreakoutConfirmedStrategy
        strategy_map["breakout_confirmed"] = BreakoutConfirmedStrategy
    except ImportError:
        logger.warning("BreakoutConfirmedStrategy not available")
    try:
        from btc_trend_bot.strategies.trend_long.reacceleration_quality import ReaccelerationQualityStrategy
        strategy_map["reacceleration_quality"] = ReaccelerationQualityStrategy
    except ImportError:
        logger.warning("ReaccelerationQualityStrategy not available")
    try:
        from btc_trend_bot.strategies.trend_long.multi_tf_trend_hold import MultiTFTrendHoldStrategy
        strategy_map["multi_tf_trend_hold"] = MultiTFTrendHoldStrategy
    except ImportError:
        logger.warning("MultiTFTrendHoldStrategy not available")

    return strategy_map


def load_config(config_path: str | None = None) -> dict:
    config_file = Path(__file__).parent / "config" / "settings.yaml"
    if config_path:
        config_file = Path(config_path)
    if not config_file.exists():
        return {}
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_strategy(
    name: str,
    strategy_class,
    df: pd.DataFrame,
    config: dict,
    exit_method: str,
    higher_tf_df: pd.DataFrame | None = None,
) -> dict | None:
    """Run a single strategy+exit combination."""
    strat_config = config.get("strategies", {}).get(name, {})

    # Create strategy instance
    if name == "multi_tf":
        strategy = strategy_class(strat_config)
        if higher_tf_df is not None:
            strategy.set_higher_tf_data(higher_tf_df)
        else:
            return None
    else:
        strategy = strategy_class(strat_config)

    # Generate signals
    signals = strategy.generate_signals(df)
    if not signals:
        return {
            "strategy": name, "exit_method": exit_method,
            "signals_count": 0, "trades": pd.DataFrame(),
            "equity": pd.Series(dtype=float), "metrics": {},
        }

    # Run backtest
    exit_config = config.get("exit", {})
    exit_config["method"] = exit_method
    exit_manager = ExitManager(exit_config)
    bt_config = config.get("backtest", {})
    engine = BacktestEngine(bt_config)
    result = engine.run(df, signals, exit_manager)

    return {
        "strategy": name,
        "exit_method": exit_method,
        "signals_count": len(signals),
        "trades": result.trades,
        "equity": result.equity_curve,
        "metrics": result.metrics,
    }


def build_regime_comparison(all_results: list[dict], df: pd.DataFrame) -> pd.DataFrame:
    """Build a DataFrame comparing each strategy's performance in bull/bear/sideways."""
    rows = []
    if "trend_regime" not in df.columns:
        return pd.DataFrame()

    for r in all_results:
        trades = r.get("trades")
        if trades is None or trades.empty:
            continue

        m = r.get("metrics", {})
        row = {
            "strategy": r["strategy"],
            "exit_method": r["exit_method"],
            "all_trades": len(trades),
            "all_pf": m.get("profit_factor", 0),
            "all_wr": m.get("win_rate", 0),
            "all_calmar": m.get("calmar_ratio", 0),
        }

        # Split trades by regime at entry time
        for regime in ["bull", "bear", "sideways"]:
            regime_mask = []
            for _, trade in trades.iterrows():
                entry_time = trade.get("entry_time")
                if entry_time is not None and entry_time in df.index:
                    regime_mask.append(df.loc[entry_time, "trend_regime"] == regime)
                else:
                    # Find nearest
                    try:
                        idx = df.index.get_indexer([entry_time], method="nearest")[0]
                        regime_mask.append(df.iloc[idx]["trend_regime"] == regime)
                    except Exception:
                        regime_mask.append(False)

            regime_trades = trades[regime_mask]
            if len(regime_trades) > 0:
                wins = regime_trades[regime_trades["pnl"] > 0]
                row[f"{regime}_trades"] = len(regime_trades)
                row[f"{regime}_wr"] = len(wins) / len(regime_trades)
                row[f"{regime}_avg_pnl"] = regime_trades["pnl"].mean()
                total_win = wins["pnl"].sum() if len(wins) > 0 else 0
                total_loss = abs(regime_trades[regime_trades["pnl"] <= 0]["pnl"].sum())
                row[f"{regime}_pf"] = total_win / total_loss if total_loss > 0 else float("inf")
            else:
                row[f"{regime}_trades"] = 0
                row[f"{regime}_wr"] = 0
                row[f"{regime}_avg_pnl"] = 0
                row[f"{regime}_pf"] = 0

        rows.append(row)

    return pd.DataFrame(rows)


def build_strategy_exit_matrix(all_results: list[dict]) -> pd.DataFrame:
    """Build strategy x exit method matrix of Calmar ratios."""
    rows = []
    for r in all_results:
        m = r.get("metrics", {})
        rows.append({
            "strategy": r["strategy"],
            "exit_method": r["exit_method"],
            "calmar_ratio": m.get("calmar_ratio", 0),
            "profit_factor": m.get("profit_factor", 0),
            "win_rate": m.get("win_rate", 0),
            "total_profit": m.get("total_profit", 0),
        })
    df_matrix = pd.DataFrame(rows)
    return df_matrix


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Real Data Backtest Runner")
    parser.add_argument("--data", type=str, default=None, help="CSV file path")
    parser.add_argument("--fetch", action="store_true",
                        help="Fetch data from Bitget first")
    parser.add_argument("--start", type=str, default="2023-01-01",
                        help="Start date for fetch")
    parser.add_argument("--end", type=str, default=None,
                        help="End date for fetch")
    parser.add_argument("--strategy", type=str, default="all",
                        help="Strategy name or 'all'")
    parser.add_argument("--exit", type=str, default="all",
                        help="Exit method or 'all'")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(str(log_dir / "realdata_backtest.log"), rotation="10 MB", level="DEBUG")

    config = load_config(args.config)

    # --- Step 1: Obtain data ---
    data_path = args.data
    if args.fetch:
        logger.info("Fetching data from Bitget...")
        from btc_trend_bot.exchange.bitget_public import BitgetPublicClient
        from btc_trend_bot.exchange.models import ExchangeConfig
        client = BitgetPublicClient(ExchangeConfig(
            api_key=os.environ.get("BITGET_API_KEY", ""),
            api_secret=os.environ.get("BITGET_API_SECRET", ""),
            passphrase=os.environ.get("BITGET_PASSPHRASE", ""),
        ))
        end_date = args.end or str(pd.Timestamp.now(tz="UTC").date())
        output_dir = str(Path(__file__).parent / "data" / "raw")
        data_path = client.download_and_save("BTCUSDT", "1h", args.start, end_date, output_dir)
        logger.info(f"Data saved: {data_path}")

    if data_path is None:
        # Try default location
        default = Path(__file__).parent / "data" / "raw" / "BTCUSDT_1h.csv"
        if default.exists():
            data_path = str(default)
        else:
            logger.error("No data file found. Use --data or --fetch")
            sys.exit(1)

    # --- Step 2: Load and prepare data ---
    loader = DataLoader(str(Path(data_path).parent))
    df = loader.load_csv(data_path)
    logger.info(f"Loaded {len(df)} bars: {df.index[0]} to {df.index[-1]}")

    fe = FeatureEngineer(config.get("trend_detection", {}))
    df = fe.add_all_features(df)

    # Bull runs
    extractor = BullRunExtractor(config.get("bull_run_extraction", {}))
    bull_runs = extractor.extract(df)
    logger.info(f"Bull runs found: {len(bull_runs)}")

    # Higher TF
    higher_tf_df = None
    try:
        higher_tf_df = loader.resample(df, "4h")
        fe_htf = FeatureEngineer(config.get("trend_detection", {}))
        higher_tf_df = fe_htf.add_all_features(higher_tf_df)
    except Exception as e:
        logger.warning(f"Higher TF prep failed: {e}")

    # --- Step 3: Run backtests ---
    strategy_map = _get_all_strategy_classes()
    exit_methods = ["atr_trailing", "partial_trail", "ema_break", "swing_low", "fixed_rr", "volume_fade"]

    if args.strategy != "all":
        strategy_map = {k: v for k, v in strategy_map.items() if k == args.strategy}
    if args.exit != "all":
        exit_methods = [args.exit]

    all_results = []
    total_combos = len(strategy_map) * len(exit_methods)
    logger.info(f"Running {total_combos} strategy/exit combinations...")

    for strat_name, strat_class in strategy_map.items():
        for exit_method in exit_methods:
            logger.info(f"  {strat_name} + {exit_method}")
            try:
                result = run_strategy(
                    strat_name, strat_class, df, config,
                    exit_method, higher_tf_df,
                )
                if result:
                    all_results.append(result)
            except Exception as e:
                logger.error(f"  Error: {e}")

    # --- Step 4: Generate reports ---
    report_dir = Path(__file__).parent / config.get("reports", {}).get("real_data_dir", "reports/real_data")
    report_dir.mkdir(parents=True, exist_ok=True)
    reporter = ReportGenerator(str(report_dir))

    # Strategy ranking
    ranking_rows = []
    for r in all_results:
        m = r.get("metrics", {})
        ranking_rows.append({
            "strategy": r["strategy"],
            "exit_method": r["exit_method"],
            "trades": r.get("signals_count", 0),
            "total_profit": m.get("total_profit", 0),
            "profit_factor": m.get("profit_factor", 0),
            "calmar_ratio": m.get("calmar_ratio", 0),
            "win_rate": m.get("win_rate", 0),
            "max_dd_pct": m.get("max_dd_pct", 0),
            "expectancy": m.get("expectancy", 0),
            "avg_rr": m.get("avg_win_loss_ratio", 0),
            "high_tp_rate": m.get("high_tp_rate", 0),
        })
    ranking_df = pd.DataFrame(ranking_rows).sort_values("calmar_ratio", ascending=False)
    ranking_df.to_csv(report_dir / "実データ戦略ランキング.csv", index=False, encoding="utf-8-sig")

    # Bull-only ranking
    if not bull_runs.empty:
        bull_df = extractor.filter_data_to_bull_runs(df, bull_runs)
        if len(bull_df) > 250:
            bull_fe = FeatureEngineer(config.get("trend_detection", {}))
            bull_df = bull_fe.add_all_features(bull_df)
            bull_results = []
            for strat_name, strat_class in strategy_map.items():
                try:
                    result = run_strategy(strat_name, strat_class, bull_df, config, "atr_trailing", higher_tf_df)
                    if result:
                        bull_results.append(result)
                except Exception:
                    pass

            bull_rows = []
            for r in bull_results:
                m = r.get("metrics", {})
                bull_rows.append({
                    "strategy": r["strategy"],
                    "trades": r.get("signals_count", 0),
                    "total_profit": m.get("total_profit", 0),
                    "profit_factor": m.get("profit_factor", 0),
                    "calmar_ratio": m.get("calmar_ratio", 0),
                    "win_rate": m.get("win_rate", 0),
                })
            bull_ranking = pd.DataFrame(bull_rows).sort_values("calmar_ratio", ascending=False)
            bull_ranking.to_csv(report_dir / "bull_only_ranking.csv", index=False)

    # Regime comparison
    regime_df = build_regime_comparison(all_results, df)
    if not regime_df.empty:
        regime_df.to_csv(report_dir / "regime_comparison.csv", index=False)

    # Strategy x Exit matrix
    matrix_df = build_strategy_exit_matrix(all_results)
    matrix_df.to_csv(report_dir / "strategy_vs_exit_matrix.csv", index=False)

    # Top trades
    for r in all_results:
        trades = r.get("trades")
        if trades is not None and not trades.empty and len(trades) >= 3:
            prefix = f"{r['strategy']}_{r['exit_method']}"
            try:
                best = get_top_trades(trades, n=10, best=True)
                best.to_csv(report_dir / f"best_trade_examples_{prefix}.csv", index=False)
                worst = get_top_trades(trades, n=10, best=False)
                worst.to_csv(report_dir / f"worst_trade_examples_{prefix}.csv", index=False)
            except Exception:
                pass

    # Individual reports for top 5
    for r in ranking_df.head(5).itertuples():
        match = [x for x in all_results if x["strategy"] == r.strategy and x["exit_method"] == r.exit_method]
        if match and match[0].get("trades") is not None and not match[0]["trades"].empty:
            reporter.generate_full_report(match[0], f"{r.strategy}_{r.exit_method}")

    # Best strategy summary (Japanese)
    if not ranking_df.empty:
        best = ranking_df.iloc[0]
        best_result = [x for x in all_results
                       if x["strategy"] == best["strategy"] and x["exit_method"] == best["exit_method"]]
        if best_result:
            _write_best_strategy_md(report_dir, best, best_result[0], ranking_df, regime_df)

    # --- Step 5: Print summary ---
    logger.info("\n" + "=" * 80)
    logger.info("REAL DATA BACKTEST RESULTS")
    logger.info("=" * 80)
    logger.info(f"{'Strategy':25s} | {'Exit':15s} | {'Trades':>6s} | {'PF':>6s} | {'WR':>6s} | {'Calmar':>8s} | {'DD%':>6s}")
    logger.info("-" * 80)
    for _, row in ranking_df.head(15).iterrows():
        wr = row['win_rate'] * 100 if row['win_rate'] <= 1 else row['win_rate']
        dd = row['max_dd_pct'] * 100 if abs(row['max_dd_pct']) < 1 else row['max_dd_pct']
        logger.info(
            f"{row['strategy']:25s} | {row['exit_method']:15s} | "
            f"{row['trades']:6.0f} | {row['profit_factor']:6.2f} | "
            f"{wr:5.1f}% | {row['calmar_ratio']:8.2f} | {dd:5.1f}%"
        )

    logger.info(f"\nReports saved to: {report_dir}")


def _write_best_strategy_md(
    report_dir: Path,
    best_row,
    best_result: dict,
    ranking_df: pd.DataFrame,
    regime_df: pd.DataFrame,
):
    """Generate best_strategy_realdata.md in Japanese."""
    m = best_result.get("metrics", {})
    trades = best_result.get("trades", pd.DataFrame())

    content = f"""# ベスト戦略分析レポート（実データ）

## 最も優秀な戦略

| 項目 | 値 |
|------|-----|
| 戦略名 | {best_row['strategy']} |
| 出口方式 | {best_row['exit_method']} |
| Calmar Ratio | {m.get('calmar_ratio', 0):.2f} |
| Profit Factor | {m.get('profit_factor', 0):.2f} |
| 勝率 | {m.get('win_rate', 0)*100:.1f}% |
| 総利益 | {m.get('total_profit', 0):.2f} USDT |
| 最大DD | {m.get('max_dd_pct', 0)*100:.1f}% |
| Expectancy | {m.get('expectancy', 0):.2f} |
| 高TP達成率 (RR>3) | {m.get('high_tp_rate', 0)*100:.1f}% |
| 総トレード数 | {len(trades)} |

## なぜ上昇相場で強いのか

この戦略は以下の理由で上昇トレンドに強い：
- 複合トレンド判定（EMA + ADX + 構造 + 出来高）で厳格にブル相場を識別
- ダマシ回避フィルタにより、レンジ相場での無駄なエントリーを抑制
- 上昇トレンド確認後のみエントリーするため、トレンド方向への確度が高い

## 相場別成績
"""

    if not regime_df.empty:
        match = regime_df[
            (regime_df["strategy"] == best_row["strategy"])
            & (regime_df["exit_method"] == best_row["exit_method"])
        ]
        if not match.empty:
            r = match.iloc[0]
            content += f"""
| 相場 | トレード数 | 勝率 | 平均PnL | PF |
|------|-----------|------|---------|-----|
| Bull | {r.get('bull_trades', 0):.0f} | {r.get('bull_wr', 0)*100:.1f}% | {r.get('bull_avg_pnl', 0):.2f} | {r.get('bull_pf', 0):.2f} |
| Sideways | {r.get('sideways_trades', 0):.0f} | {r.get('sideways_wr', 0)*100:.1f}% | {r.get('sideways_avg_pnl', 0):.2f} | {r.get('sideways_pf', 0):.2f} |
| Bear | {r.get('bear_trades', 0):.0f} | {r.get('bear_wr', 0)*100:.1f}% | {r.get('bear_avg_pnl', 0):.2f} | {r.get('bear_pf', 0):.2f} |
"""

    content += f"""
## 高TPを実現できた理由

- 出口方式「{best_row['exit_method']}」により、利益の伸びる局面では保有を継続
- トレーリングストップが利益を守りつつ、トレンド継続時に最大化
- 固定利確ではなく、相場の動きに追従する出口設計

## ダマシが増える条件

- レンジ相場（ADX低下、出来高減少）では信号精度が低下
- 急騰後の天井圏でのエントリーは損失リスクが高い（overextendedフィルタで対応）
- 出来高が伴わないブレイクはフェイクの可能性が高い

## Bitgetペーパー運用の次ステップ

1. `python -m btc_trend_bot.fetch_data --all-timeframes --start 2023-01-01` でデータ取得
2. `python -m btc_trend_bot.run_realdata_backtest --fetch` で実データ検証
3. `python -m btc_trend_bot.run_paper` でペーパートレード開始
4. 1〜2週間のペーパー成績を確認後、リアル接続検討

## 出口方式の比較（上位5件）
"""

    for i, (_, row) in enumerate(ranking_df.head(5).iterrows()):
        content += f"{i+1}. **{row['strategy']}** + {row['exit_method']}: Calmar={row['calmar_ratio']:.2f}, PF={row['profit_factor']:.2f}\n"

    content += f"""
## 実運用時の注意点

- Bitgetのtaker手数料 (0.06%) とスリッページ (5bps) を考慮済み
- 最大DD {m.get('max_dd_pct', 0)*100:.1f}% を許容できるか確認
- リスク管理: 1トレードあたり資金の2%以内
- 回線障害・API障害時のフォールバック計画が必要
- 深夜帯（日本時間）はスプレッドが広がる可能性あり
"""

    md_path = report_dir / "best_strategy_realdata.md"
    md_path.write_text(content, encoding="utf-8")
    logger.info(f"Best strategy summary saved: {md_path}")


if __name__ == "__main__":
    main()
