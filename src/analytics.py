"""Paper取引の分析エンジン。

trades は list[dict] で、各要素に以下のキーを持つ:
  trade_id, signal_time, market_id, market_title, direction,
  entry_price, entry_amount_usd, exit_price, pnl_usd,
  holding_minutes, result, created_at
"""

from collections import defaultdict


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return round(a / b, 4) if b else default


def _group_stats(trades: list[dict]) -> dict:
    """取引リストから基本統計を算出する。"""
    if not trades:
        return {
            "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    pnls = [t["pnl_usd"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(trades), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
    }


# ── 全体サマリー ──────────────────────────────────────────

def compute_summary(trades: list[dict]) -> dict:
    """メインのパフォーマンスサマリー（既存互換 + 新指標）。"""
    base = _group_stats(trades)
    if not trades:
        return {
            **base,
            "max_consecutive_losses": 0, "avg_holding_minutes": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
            "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
            "profit_factor": 0.0,
        }

    pnls = [t["pnl_usd"] for t in trades]

    # 最大連敗
    max_streak = current = 0
    for t in trades:
        if t["result"] == "loss":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0

    # 最大ドローダウン
    equity = build_equity_curve(trades)
    dd_abs, dd_pct = compute_max_drawdown(equity)

    # Profit Factor
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p <= 0))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf")

    return {
        **base,
        "max_consecutive_losses": max_streak,
        "avg_holding_minutes": round(
            sum(t["holding_minutes"] for t in trades) / len(trades), 1
        ),
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "max_drawdown": dd_abs,
        "max_drawdown_pct": dd_pct,
        "profit_factor": pf,
    }


# ── Equity Curve & Drawdown ──────────────────────────────

def build_equity_curve(trades: list[dict]) -> list[dict]:
    """累積損益の時系列を構築する。"""
    curve = []
    cumulative = 0.0
    for i, t in enumerate(trades):
        cumulative += t["pnl_usd"]
        curve.append({
            "trade_no": i + 1,
            "signal_time": t.get("signal_time", ""),
            "pnl_usd": t["pnl_usd"],
            "cumulative_pnl": round(cumulative, 2),
            "market_title": t.get("market_title", ""),
            "direction": t.get("direction", ""),
            "result": t.get("result", ""),
        })
    return curve


def compute_max_drawdown(equity_curve: list[dict]) -> tuple[float, float]:
    """最大ドローダウン（絶対値）とピークからの％を返す。"""
    if not equity_curve:
        return 0.0, 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for row in equity_curve:
        cum = row["cumulative_pnl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = round(dd / peak * 100, 1) if peak > 0 else 0.0
    return round(max_dd, 2), max_dd_pct


# ── グループ別分析 ────────────────────────────────────────

def by_market(trades: list[dict]) -> dict[str, dict]:
    """マーケット別の成績。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = t.get("market_title", t.get("market_id", "unknown"))
        groups[key].append(t)
    return {k: _group_stats(v) for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))}


def by_direction(trades: list[dict]) -> dict[str, dict]:
    """Direction別の成績。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        groups[t.get("direction", "unknown")].append(t)
    return {k: _group_stats(v) for k, v in sorted(groups.items())}


def by_hour(trades: list[dict]) -> dict[str, dict]:
    """時間帯別（UTC）の成績。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        st = t.get("signal_time", "")
        if "T" in st:
            hour = st.split("T")[1][:2]
        elif " " in st:
            hour = st.split(" ")[1][:2]
        else:
            hour = "??"
        groups[f"{hour}:00"].append(t)
    return {k: _group_stats(v) for k, v in sorted(groups.items())}


def by_signal_strength(trades: list[dict], signals_data: list[dict] | None = None) -> dict[str, dict]:
    """シグナル強度別の成績。

    paper_trades テーブルには is_strong がないため、
    entry_amount_usd の合計をシグナルの total_amount として推定分類する。
    signals_data がある場合はそちらを使う。
    """
    # signals_data が渡された場合: signal の is_strong でマッチ
    signal_strength_map: dict[str, str] = {}
    if signals_data:
        for s in signals_data:
            key = f"{s.get('market_id', '')}_{s.get('direction', '')}"
            strong = s.get("is_strong", 0)
            total = s.get("total_amount_usdc", 0)
            if strong:
                if total >= 5000:
                    signal_strength_map[key] = "STRONG+"
                else:
                    signal_strength_map[key] = "STRONG"
            else:
                signal_strength_map[key] = "NORMAL"

    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = f"{t.get('market_id', '')}_{t.get('direction', '')}"
        strength = signal_strength_map.get(key, "STRONG")  # デフォルトSTRONG (MVPでは全てSTRONG)
        groups[strength].append(t)

    return {k: _group_stats(v) for k, v in sorted(groups.items())}


def recent_n(trades: list[dict], n: int = 20) -> dict:
    """直近N件の成績。"""
    return _group_stats(trades[-n:]) if trades else _group_stats([])
