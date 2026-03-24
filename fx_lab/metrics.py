"""評価指標の計算ロジック

基本指標に加え、最大連敗数・spread感応度・頑健性テストに対応。
"""

import copy
from strategy_base import Trade


def calculate_pf(trades: list[Trade]) -> float:
    """Profit Factor = 総利益 / 総損失（絶対値）"""
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calculate_winrate(trades: list[Trade]) -> float:
    """勝率(%)"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return (wins / len(trades)) * 100


def calculate_drawdown(trades: list[Trade], initial_balance: float = 100000) -> tuple[float, float]:
    """最大ドローダウンを計算。Returns: (最大DD金額, 最大DD%)"""
    if not trades:
        return 0.0, 0.0
    balance = initial_balance
    peak = initial_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in trades:
        balance += t.pnl
        if balance > peak:
            peak = balance
        dd = peak - balance
        dd_pct = (dd / peak) * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
    return max_dd, max_dd_pct


def calculate_total_pnl(trades: list[Trade]) -> float:
    """総損益"""
    return sum(t.pnl for t in trades)


def calculate_avg_holding_time(trades: list[Trade]) -> float:
    """平均保有時間（秒）"""
    if not trades:
        return 0.0
    return sum(t.holding_seconds for t in trades) / len(trades)


def calculate_max_consecutive_losses(trades: list[Trade]) -> int:
    """最大連敗数"""
    if not trades:
        return 0
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t.pnl < 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def calculate_max_consecutive_wins(trades: list[Trade]) -> int:
    """最大連勝数"""
    if not trades:
        return 0
    max_streak = 0
    current_streak = 0
    for t in trades:
        if t.pnl > 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def calculate_expectancy(trades: list[Trade]) -> float:
    """期待値 (1トレードあたりの平均PNL)"""
    if not trades:
        return 0.0
    return sum(t.pnl for t in trades) / len(trades)


def calculate_payoff_ratio(trades: list[Trade]) -> float:
    """ペイオフレシオ = 平均利益 / 平均損失"""
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [abs(t.pnl) for t in trades if t.pnl < 0]
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    if avg_loss == 0:
        return float("inf")
    return avg_win / avg_loss


def evaluate_strategy(trades: list[Trade], initial_balance: float = 100000) -> dict:
    """全評価指標をまとめて計算"""
    max_dd, max_dd_pct = calculate_drawdown(trades, initial_balance)

    return {
        "pf": round(calculate_pf(trades), 4),
        "winrate": round(calculate_winrate(trades), 2),
        "max_dd": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "total_pnl": round(calculate_total_pnl(trades), 2),
        "avg_holding_seconds": round(calculate_avg_holding_time(trades), 1),
        "trade_count": len(trades),
        "max_consecutive_losses": calculate_max_consecutive_losses(trades),
        "max_consecutive_wins": calculate_max_consecutive_wins(trades),
        "expectancy": round(calculate_expectancy(trades), 4),
        "payoff_ratio": round(calculate_payoff_ratio(trades), 4),
    }


# ================================================================
# Spread感応度テスト
# ================================================================

def spread_sensitivity_test(
    strategy,
    df,
    initial_balance: float = 100000,
    spread_multipliers: list[float] | None = None,
) -> list[dict]:
    """異なるスプレッドでバックテストし、感応度を測定

    Args:
        strategy: ConfigurableStrategy インスタンス
        df: OHLCデータフレーム
        initial_balance: 初期残高
        spread_multipliers: スプレッド倍率リスト (デフォルト: [0.5, 1.0, 1.5, 2.0, 3.0])

    Returns: [{spread_mult, pf, winrate, total_pnl, trade_count}, ...]
    """
    if spread_multipliers is None:
        spread_multipliers = [0.5, 1.0, 1.5, 2.0, 3.0]

    base_spread = strategy.spread
    results = []

    for mult in spread_multipliers:
        strategy.spread = base_spread * mult
        trades = strategy.backtest(df, initial_balance=initial_balance)
        metrics = evaluate_strategy(trades, initial_balance)
        metrics["spread_mult"] = mult
        results.append(metrics)

    strategy.spread = base_spread  # 復元
    return results


def calculate_spread_robustness(sensitivity_results: list[dict]) -> float:
    """Spread感応度スコア: 2倍spreadでもPF>1.0ならrobust

    Returns: 0.0-1.0 (1.0が最も頑健)
    """
    if not sensitivity_results:
        return 0.0

    base = None
    double = None
    for r in sensitivity_results:
        if abs(r["spread_mult"] - 1.0) < 0.01:
            base = r
        if abs(r["spread_mult"] - 2.0) < 0.01:
            double = r

    if base is None or double is None:
        return 0.0

    base_pf = base.get("pf", 0)
    double_pf = double.get("pf", 0)

    if base_pf <= 0:
        return 0.0

    # PF維持率 (2倍spreadでもPFがどれだけ保たれるか)
    retention = double_pf / base_pf if base_pf > 0 else 0.0
    return min(1.0, max(0.0, retention))
