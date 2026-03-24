"""ランキング出力・レポート生成"""

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

    # フィルタリング
    filtered = df[
        (df["pf"] >= min_pf)
        & (df["max_dd_pct"] <= max_dd_pct)
        & (df["trade_count"] >= min_trades)
    ].copy()

    if filtered.empty:
        logger.info("ランキング条件を満たす戦略がありません")
        # 全結果をPFでソートして返す（参考用）
        df_sorted = df.sort_values("pf", ascending=False).reset_index(drop=True)
        df_sorted.index += 1
        df_sorted.index.name = "rank"
        return df_sorted

    # PF降順でランキング
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


def print_summary(ranking_df: pd.DataFrame, all_results: list[dict]) -> None:
    """結果サマリーを表示"""
    print("\n" + "=" * 70)
    print("  FX スキャルピング戦略 研究結果サマリー")
    print("=" * 70)

    print(f"\n  テスト戦略数（全組み合わせ）: {len(all_results)}")
    print(f"  ランキング掲載数: {len(ranking_df)}")

    if not ranking_df.empty:
        print("\n  --- ランキング上位 ---")
        cols = ["strategy_name", "symbol", "timeframe", "pf", "winrate",
                "max_dd_pct", "total_pnl", "trade_count"]
        display_cols = [c for c in cols if c in ranking_df.columns]
        print(ranking_df[display_cols].to_string())
    else:
        print("\n  ランキング条件を満たす戦略はありませんでした。")
        print("  （全結果はall_results.csvを確認してください）")

    print("\n" + "=" * 70)
