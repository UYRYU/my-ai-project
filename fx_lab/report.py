"""ランキング出力・レポート生成

OOSランキング、頑健性レポート、通貨/時間帯/時間足別ブレイクダウンに対応。
"""

import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def create_ranking(
    results: list[dict],
    min_pf: float = 1.2,
    max_dd_pct: float = 15.0,
    min_trades: int = 100,
) -> pd.DataFrame:
    """バックテスト結果をフィルタリングしてランキング化"""
    if not results:
        logger.warning("結果が空です")
        return pd.DataFrame()

    df = pd.DataFrame(results)

    filtered = df[
        (df["pf"] >= min_pf)
        & (df["max_dd_pct"] <= max_dd_pct)
        & (df["trade_count"] >= min_trades)
    ].copy()

    if filtered.empty:
        logger.info("ランキング条件を満たす戦略がありません")
        df_sorted = df.sort_values("pf", ascending=False).reset_index(drop=True)
        df_sorted.index += 1
        df_sorted.index.name = "rank"
        return df_sorted

    filtered = filtered.sort_values("pf", ascending=False).reset_index(drop=True)
    filtered.index += 1
    filtered.index.name = "rank"

    return filtered


def save_ranking(ranking_df: pd.DataFrame, output_dir: str) -> str:
    """ランキングをCSVファイルとして保存"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "ranking.csv")
    ranking_df.to_csv(filepath, encoding="utf-8-sig")
    logger.info(f"ランキングを保存: {filepath}")
    return filepath


def save_all_results(results: list[dict], output_dir: str) -> str:
    """全バックテスト結果をCSVファイルとして保存"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "all_results.csv")
    df = pd.DataFrame(results)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    logger.info(f"全結果を保存: {filepath}")
    return filepath


def save_oos_ranking(ranking_df: pd.DataFrame, results_dir: str) -> str:
    """OOSランキングを保存"""
    os.makedirs(results_dir, exist_ok=True)
    filepath = os.path.join(results_dir, "out_of_sample_ranking.csv")
    ranking_df.to_csv(filepath, encoding="utf-8-sig")
    logger.info(f"OOSランキング保存: {filepath}")
    return filepath


def save_robustness_report(robustness: list[dict], results_dir: str) -> str:
    """頑健性レポートを保存"""
    os.makedirs(results_dir, exist_ok=True)
    filepath = os.path.join(results_dir, "robustness_report.csv")
    df = pd.DataFrame(robustness)
    if not df.empty:
        df = df.sort_values("spread_robustness", ascending=False).reset_index(drop=True)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    logger.info(f"頑健性レポート保存: {filepath}")
    return filepath


def save_detail_breakdown(results: list[dict], results_dir: str) -> None:
    """通貨ペア別、時間帯別、時間足別の成績ブレイクダウンCSVを保存"""
    os.makedirs(results_dir, exist_ok=True)
    df = pd.DataFrame(results)

    if df.empty:
        return

    # --- 通貨ペア別 ---
    if "symbol" in df.columns:
        symbol_agg = df.groupby(["strategy_name", "symbol"]).agg(
            pf=("pf", "mean"),
            winrate=("winrate", "mean"),
            total_pnl=("total_pnl", "sum"),
            trade_count=("trade_count", "sum"),
            max_dd_pct=("max_dd_pct", "max"),
        ).reset_index()
        symbol_agg.to_csv(
            os.path.join(results_dir, "breakdown_by_symbol.csv"),
            index=False, encoding="utf-8-sig"
        )

    # --- 時間足別 ---
    if "timeframe" in df.columns:
        tf_agg = df.groupby(["strategy_name", "timeframe"]).agg(
            pf=("pf", "mean"),
            winrate=("winrate", "mean"),
            total_pnl=("total_pnl", "sum"),
            trade_count=("trade_count", "sum"),
            max_dd_pct=("max_dd_pct", "max"),
        ).reset_index()
        tf_agg.to_csv(
            os.path.join(results_dir, "breakdown_by_timeframe.csv"),
            index=False, encoding="utf-8-sig"
        )

    # --- 時間帯別 (セッション別PNL) ---
    session_cols = ["pnl_tokyo", "pnl_london", "pnl_newyork",
                    "trades_tokyo", "trades_london", "trades_newyork"]
    has_session = all(c in df.columns for c in session_cols)
    if has_session:
        session_agg = df.groupby("strategy_name").agg(
            pnl_tokyo=("pnl_tokyo", "sum"),
            pnl_london=("pnl_london", "sum"),
            pnl_newyork=("pnl_newyork", "sum"),
            trades_tokyo=("trades_tokyo", "sum"),
            trades_london=("trades_london", "sum"),
            trades_newyork=("trades_newyork", "sum"),
        ).reset_index()
        session_agg.to_csv(
            os.path.join(results_dir, "breakdown_by_session.csv"),
            index=False, encoding="utf-8-sig"
        )

    logger.info(f"ブレイクダウン保存: {results_dir}/breakdown_by_*.csv")


def print_summary(ranking_df: pd.DataFrame, all_results: list[dict]) -> None:
    """結果サマリーを表示"""
    print("\n" + "=" * 70)
    print("  FX スキャルピング戦略 研究結果サマリー")
    print("=" * 70)

    print(f"\n  テスト結果数（全組み合わせ）: {len(all_results)}")
    print(f"  ランキング掲載数: {len(ranking_df)}")

    if not ranking_df.empty:
        print("\n  --- ランキング上位 ---")
        cols = ["strategy_name", "symbol", "timeframe", "pf", "winrate",
                "max_dd_pct", "total_pnl", "trade_count", "max_consecutive_losses",
                "expectancy", "category"]
        display_cols = [c for c in cols if c in ranking_df.columns]
        print(ranking_df[display_cols].head(20).to_string())
    else:
        print("\n  ランキング条件を満たす戦略はありませんでした。")

    print("\n" + "=" * 70)
