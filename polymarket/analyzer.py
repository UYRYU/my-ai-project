"""
Polymarket Tracker - パターン分析モジュール
蓄積された取引データをオッズ帯・時間帯・スポーツ・トレーダー別に分析する
"""

import os
from datetime import datetime, timezone
from typing import Dict

import pandas as pd
from loguru import logger

import config


def load_trades() -> pd.DataFrame:
    """
    data/trades.csv を読み込んで DataFrame を返す。
    存在しない場合は空のDataFrameを返す。
    """
    if not os.path.exists(config.DATA_PATH):
        logger.warning(f"{config.DATA_PATH} が存在しません")
        return pd.DataFrame()

    try:
        df = pd.read_csv(config.DATA_PATH)
    except Exception as e:
        logger.error(f"CSV読み込みエラー: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # 数値型に変換 (安全のため)
    for col in ["price", "size", "timestamp"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # resultは bool/int/NaN が混在しうるので数値化
    if "result" in df.columns:
        df["result"] = pd.to_numeric(df["result"], errors="coerce")

    return df


def odds_analysis(df: pd.DataFrame) -> Dict[str, dict]:
    """
    オッズ帯ごとの取引数・平均サイズ・勝率を集計する。
    勝率は result が記録されているレコードのみで計算。

    Returns:
        dict: {"0-0.5": {...}, "0.5-0.65": {...}, ...}
    """
    result: Dict[str, dict] = {}
    if df.empty:
        return result

    # オッズ帯の境界
    bins = [0.0, 0.5, 0.65, 0.75, 1.0001]  # 1.0 を含めるため少しオフセット
    labels = ["0-0.5", "0.5-0.65", "0.65-0.75", "0.75-1.0"]

    df = df.copy()
    df["odds_band"] = pd.cut(df["price"], bins=bins, labels=labels, include_lowest=True)

    for label in labels:
        sub = df[df["odds_band"] == label]
        if sub.empty:
            result[label] = {
                "count": 0,
                "avg_size": 0.0,
                "win_rate": None,
                "decided_count": 0,
            }
            continue

        decided = sub.dropna(subset=["result"])
        if len(decided) > 0:
            win_rate = float(decided["result"].mean())
        else:
            win_rate = None

        result[label] = {
            "count": int(len(sub)),
            "avg_size": float(sub["size"].mean()) if len(sub) else 0.0,
            "win_rate": win_rate,
            "decided_count": int(len(decided)),
        }

    return result


def timing_analysis(df: pd.DataFrame) -> Dict[str, dict]:
    """
    UTC時間帯ごとの取引数・平均サイズ・平均オッズを集計する。
    時間帯: 0-6, 6-12, 12-18, 18-24
    """
    result: Dict[str, dict] = {}
    if df.empty:
        return result

    df = df.copy()
    # timestamp を datetime に変換 (秒 or ミリ秒を自動判別)
    ts = df["timestamp"].fillna(0)
    # ミリ秒っぽい値なら秒に変換
    if ts.max() > 1e12:
        ts = ts / 1000.0
    df["hour"] = ts.apply(
        lambda x: datetime.fromtimestamp(x, tz=timezone.utc).hour if x > 0 else -1
    )

    bands = [
        ("0-6", 0, 6),
        ("6-12", 6, 12),
        ("12-18", 12, 18),
        ("18-24", 18, 24),
    ]

    for label, lo, hi in bands:
        sub = df[(df["hour"] >= lo) & (df["hour"] < hi)]
        if sub.empty:
            result[label] = {
                "count": 0,
                "avg_size": 0.0,
                "avg_price": 0.0,
            }
            continue
        result[label] = {
            "count": int(len(sub)),
            "avg_size": float(sub["size"].mean()),
            "avg_price": float(sub["price"].mean()),
        }

    return result


def sport_analysis(df: pd.DataFrame) -> Dict[str, dict]:
    """
    スポーツ種別ごとの取引数・平均オッズ・平均サイズを集計する。
    """
    result: Dict[str, dict] = {}
    if df.empty or "sport" not in df.columns:
        return result

    grouped = df.groupby("sport")
    for sport, sub in grouped:
        result[str(sport)] = {
            "count": int(len(sub)),
            "avg_price": float(sub["price"].mean()) if len(sub) else 0.0,
            "avg_size": float(sub["size"].mean()) if len(sub) else 0.0,
        }

    return result


def trader_analysis(df: pd.DataFrame) -> Dict[str, dict]:
    """
    上位トレーダーごとの
    - スポーツ特化度 (最多スポーツとその比率)
    - 平均オッズ
    - 最もアクティブな時間帯
    を集計する。
    """
    result: Dict[str, dict] = {}
    if df.empty or "trader" not in df.columns:
        return result

    df = df.copy()
    ts = df["timestamp"].fillna(0)
    if ts.max() > 1e12:
        ts = ts / 1000.0
    df["hour"] = ts.apply(
        lambda x: datetime.fromtimestamp(x, tz=timezone.utc).hour if x > 0 else -1
    )

    for trader, sub in df.groupby("trader"):
        if sub.empty:
            continue

        # スポーツ特化度: 最多スポーツとその比率
        sport_counts = sub["sport"].value_counts()
        top_sport = sport_counts.index[0] if len(sport_counts) else "OTHER"
        focus_ratio = float(sport_counts.iloc[0] / len(sub)) if len(sub) else 0.0

        # 平均オッズ
        avg_price = float(sub["price"].mean()) if len(sub) else 0.0

        # 最もアクティブな時間帯 (6時間区切り)
        hour_bands = {
            "0-6": int(((sub["hour"] >= 0) & (sub["hour"] < 6)).sum()),
            "6-12": int(((sub["hour"] >= 6) & (sub["hour"] < 12)).sum()),
            "12-18": int(((sub["hour"] >= 12) & (sub["hour"] < 18)).sum()),
            "18-24": int(((sub["hour"] >= 18) & (sub["hour"] < 24)).sum()),
        }
        active_band = max(hour_bands, key=hour_bands.get)

        result[str(trader)] = {
            "total_trades": int(len(sub)),
            "top_sport": str(top_sport),
            "sport_focus_ratio": focus_ratio,
            "avg_price": avg_price,
            "active_band": active_band,
            "hour_distribution": hour_bands,
        }

    return result


def _fmt_pct(v) -> str:
    """勝率などのNone安全なフォーマッタ"""
    if v is None:
        return "N/A"
    return f"{v * 100:.1f}%"


def print_report() -> None:
    """
    すべての分析を実行してコンソールに見やすく出力する。
    """
    df = load_trades()
    if df.empty:
        print("\n[!] 取引データがありません。まず `python main.py --collect` を実行してください。\n")
        return

    print("\n" + "=" * 60)
    print(" Polymarket Tracker - 分析レポート")
    print("=" * 60)
    print(f" データ件数      : {len(df)}")
    print(f" ユニークトレーダー : {df['trader'].nunique()}")
    print(f" ユニークマーケット : {df['market_id'].nunique()}")
    print("=" * 60)

    # --- オッズ帯分析 ---
    print("\n[1] オッズ帯ごとの集計")
    print("-" * 60)
    print(f"{'オッズ帯':<12}{'取引数':>8}{'平均サイズ':>14}{'勝率':>12}{'確定数':>10}")
    for band, stats in odds_analysis(df).items():
        print(
            f"{band:<12}"
            f"{stats['count']:>8}"
            f"{stats['avg_size']:>14,.2f}"
            f"{_fmt_pct(stats['win_rate']):>12}"
            f"{stats['decided_count']:>10}"
        )

    # --- 時間帯分析 ---
    print("\n[2] UTC時間帯ごとの集計")
    print("-" * 60)
    print(f"{'時間帯':<12}{'取引数':>8}{'平均サイズ':>14}{'平均オッズ':>14}")
    for band, stats in timing_analysis(df).items():
        print(
            f"{band:<12}"
            f"{stats['count']:>8}"
            f"{stats['avg_size']:>14,.2f}"
            f"{stats['avg_price']:>14,.3f}"
        )

    # --- スポーツ別分析 ---
    print("\n[3] スポーツ種別ごとの集計")
    print("-" * 60)
    print(f"{'スポーツ':<12}{'取引数':>8}{'平均オッズ':>14}{'平均サイズ':>14}")
    for sport, stats in sport_analysis(df).items():
        print(
            f"{sport:<12}"
            f"{stats['count']:>8}"
            f"{stats['avg_price']:>14,.3f}"
            f"{stats['avg_size']:>14,.2f}"
        )

    # --- トレーダー別分析 ---
    print("\n[4] トレーダーごとの特徴")
    print("-" * 60)
    print(f"{'トレーダー':<20}{'取引数':>8}{'主戦場':>10}{'特化度':>10}{'平均オッズ':>12}{'活動帯':>10}")
    trader_stats = trader_analysis(df)
    # 取引数で降順ソート
    sorted_items = sorted(
        trader_stats.items(), key=lambda x: x[1]["total_trades"], reverse=True
    )
    for trader, stats in sorted_items:
        name = (trader[:18] + "..") if len(trader) > 20 else trader
        print(
            f"{name:<20}"
            f"{stats['total_trades']:>8}"
            f"{stats['top_sport']:>10}"
            f"{stats['sport_focus_ratio'] * 100:>9.1f}%"
            f"{stats['avg_price']:>12,.3f}"
            f"{stats['active_band']:>10}"
        )

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    print_report()
