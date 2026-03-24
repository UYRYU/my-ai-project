"""評価指標の計算ロジック"""

from strategy_base import Trade


def calculate_pf(trades: list[Trade]) -> float:
    """Profit Factor = 総利益 / 総損失（絶対値）"""
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calculate_winrate(trades: list[Trade]) -> float:
    """勝率(%) = 勝ちトレード数 / 全トレード数 * 100"""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return (wins / len(trades)) * 100


def calculate_drawdown(trades: list[Trade], initial_balance: float = 100000) -> tuple[float, float]:
    """最大ドローダウンを計算。

    Returns: (最大DD金額, 最大DD%)
    """
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


def evaluate_strategy(trades: list[Trade], initial_balance: float = 100000) -> dict:
    """全評価指標をまとめて計算"""
    max_dd, max_dd_pct = calculate_drawdown(trades, initial_balance)
    avg_hold = calculate_avg_holding_time(trades)

    return {
        "pf": round(calculate_pf(trades), 4),
        "winrate": round(calculate_winrate(trades), 2),
        "max_dd": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "total_pnl": round(calculate_total_pnl(trades), 2),
        "avg_holding_seconds": round(avg_hold, 1),
        "trade_count": len(trades),
    }
