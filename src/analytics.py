"""Paper取引の分析エンジン。

trades は list[dict] で、各要素に以下のキーを持つ:
  trade_id, signal_time, market_id, market_title, direction,
  entry_price, entry_amount_usd, exit_price, pnl_usd,
  holding_minutes, result, model_version, created_at
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


# ── モデルフィルタ ───────────────────────────────────────────

def filter_by_model(trades: list[dict], model: str = "v2_binary") -> list[dict]:
    """指定モデルバージョンの取引のみ返す。"""
    return [t for t in trades if t.get("model_version") == model]


# ── Entry Price 帯別分析 ─────────────────────────────────────

PRICE_BANDS = [
    ("0.00-0.20", 0.0, 0.2),
    ("0.20-0.40", 0.2, 0.4),
    ("0.40-0.60", 0.4, 0.6),
    ("0.60-0.80", 0.6, 0.8),
    ("0.80-1.00", 0.8, 1.0),
]


def by_entry_price_band(trades: list[dict]) -> dict[str, dict]:
    """entry_price 帯別の成績。"""
    groups: dict[str, list[dict]] = {label: [] for label, _, _ in PRICE_BANDS}
    for t in trades:
        ep = t.get("entry_price", 0)
        for label, lo, hi in PRICE_BANDS:
            if lo <= ep < hi or (hi == 1.0 and ep == 1.0):
                groups[label].append(t)
                break
    return {k: _group_stats(v) for k, v in groups.items() if v}


def avg_entry_price(trades: list[dict]) -> float:
    """全取引の平均 entry_price。"""
    if not trades:
        return 0.0
    return round(sum(t["entry_price"] for t in trades) / len(trades), 4)


# ── Edge 指標（勝率 vs 期待勝率）─────────────────────────────

def compute_edge_indicator(trades: list[dict]) -> dict:
    """シグナルのエッジを計量する。

    二値モデルでは entry_price = 理論上の勝率。
    実際の勝率が entry_price の加重平均を上回っていれば、
    シグナルにエッジがある（正のアルファ）と判断できる。

    Returns:
        {
          "count": int,
          "actual_win_rate": float,        # 実際の勝率 (%)
          "expected_win_rate": float,       # entry_price 加重平均の期待勝率 (%)
          "edge_pct": float,               # actual - expected (pp)
          "has_edge": bool,                 # edge > 0
          "edge_per_band": dict[str, dict], # 帯別の edge
        }
    """
    if not trades:
        return {
            "count": 0, "actual_win_rate": 0.0, "expected_win_rate": 0.0,
            "edge_pct": 0.0, "has_edge": False, "edge_per_band": {},
        }

    wins = sum(1 for t in trades if t["result"] == "win")
    actual_wr = round(wins / len(trades) * 100, 1)

    # 期待勝率 = entry_price の平均（Buy 前提）
    # Buy: 期待勝率 = entry_price
    # Sell: 期待勝率 = 1 - entry_price
    expected_probs = []
    for t in trades:
        ep = t["entry_price"]
        direction = t.get("direction", "")
        if direction.startswith("Sell"):
            expected_probs.append(1.0 - ep)
        else:
            expected_probs.append(ep)

    expected_wr = round(sum(expected_probs) / len(expected_probs) * 100, 1)
    edge = round(actual_wr - expected_wr, 1)

    # 帯別 edge
    edge_per_band: dict[str, dict] = {}
    for label, lo, hi in PRICE_BANDS:
        band_trades = [
            t for t in trades
            if lo <= t.get("entry_price", 0) < hi
            or (hi == 1.0 and t.get("entry_price", 0) == 1.0)
        ]
        if not band_trades:
            continue
        b_wins = sum(1 for t in band_trades if t["result"] == "win")
        b_actual = round(b_wins / len(band_trades) * 100, 1)
        b_expected_probs = []
        for t in band_trades:
            ep = t["entry_price"]
            if t.get("direction", "").startswith("Sell"):
                b_expected_probs.append(1.0 - ep)
            else:
                b_expected_probs.append(ep)
        b_expected = round(sum(b_expected_probs) / len(b_expected_probs) * 100, 1)
        edge_per_band[label] = {
            "count": len(band_trades),
            "actual_win_rate": b_actual,
            "expected_win_rate": b_expected,
            "edge_pct": round(b_actual - b_expected, 1),
        }

    return {
        "count": len(trades),
        "actual_win_rate": actual_wr,
        "expected_win_rate": expected_wr,
        "edge_pct": edge,
        "has_edge": edge > 0,
        "edge_per_band": edge_per_band,
    }


# ── v2 検証完了チェック ──────────────────────────────────────

def check_v2_readiness(trades: list[dict]) -> dict:
    """v2_binary で案2(edge)へ進む準備ができているか判定する。

    Returns:
        {
          "trade_count": int,
          "enough_trades": bool,       # 100+
          "has_edge": bool,            # 勝率 > 期待勝率
          "profit_factor_ok": bool,    # PF > 1.0
          "stable_across_markets": bool,  # 2+ マーケットで勝率 > 期待値
          "all_passed": bool,
          "checks": list[dict],        # 各チェックの詳細
        }
    """
    v2 = filter_by_model(trades, "v2_binary")
    n = len(v2)

    summary = compute_summary(v2) if v2 else compute_summary([])
    edge = compute_edge_indicator(v2)
    markets = by_market(v2)

    # PF > 1.0
    pf = summary.get("profit_factor", 0)
    pf_ok = pf > 1.0 if pf != float("inf") else True

    # マーケット別安定性: 2+ マーケットで勝率 > 期待
    stable_markets = 0
    for mkt_name, mkt_stats in markets.items():
        mkt_trades = [t for t in v2 if t.get("market_title", t.get("market_id")) == mkt_name]
        if len(mkt_trades) >= 5:
            mkt_edge = compute_edge_indicator(mkt_trades)
            if mkt_edge["has_edge"]:
                stable_markets += 1
    stable = stable_markets >= 2

    checks = [
        {
            "name": "トレード数 >= 100",
            "passed": n >= 100,
            "value": f"{n}/100",
        },
        {
            "name": "勝率 > 期待勝率 (edge > 0)",
            "passed": edge["has_edge"],
            "value": f"edge={edge['edge_pct']:+.1f}pp "
                     f"(実績{edge['actual_win_rate']}% vs 期待{edge['expected_win_rate']}%)",
        },
        {
            "name": "Profit Factor > 1.0",
            "passed": pf_ok,
            "value": f"PF={pf}",
        },
        {
            "name": "2+ マーケットで edge > 0",
            "passed": stable,
            "value": f"{stable_markets} マーケット",
        },
    ]

    return {
        "trade_count": n,
        "enough_trades": n >= 100,
        "has_edge": edge["has_edge"],
        "profit_factor_ok": pf_ok,
        "stable_across_markets": stable,
        "all_passed": all(c["passed"] for c in checks),
        "checks": checks,
    }
