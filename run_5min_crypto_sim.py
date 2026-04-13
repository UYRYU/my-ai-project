#!/usr/bin/env python3
"""5分仮想通貨マーケット arb ペーパートレードシミュレーション.

Polymarket の短期クリプトマーケット（5分解決）にarbロジックを適用。
50万円スタート、1日分のシミュレーション。

5分ごとに新しいマーケットセットが生成され、
一部にミスプライシング（arb機会）が埋め込まれる。
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from polymarket_arbitrage.models.market import (
    ArbitrageType,
    Event,
    Market,
    MarketStatus,
    Token,
)
from polymarket_arbitrage.arbitrage.intra_market import (
    detect_single_condition_arbitrage,
    detect_negrisk_arbitrage,
)
from bot.portfolio import (
    PortfolioState,
    calculate_position_size,
    load_state,
    record_entry,
    record_exit,
    print_dashboard,
    save_state,
)

random.seed(42)  # reproducible

# 対象コイン
COINS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "MATIC"]

# ベース価格 (USD)
BASE_PRICES = {
    "BTC": 104_500, "ETH": 3_420, "SOL": 178, "DOGE": 0.38,
    "XRP": 2.45, "AVAX": 42, "LINK": 18.5, "MATIC": 0.85,
}

# 5分マーケットのタイプ
MARKET_TYPES = [
    "above_below",      # 「X以上？」 YES/NO (single-condition)
    "price_brackets",   # 「どのレンジに入る？」 (NegRisk)
]


def _make_token(id: str, outcome: str, price: float) -> Token:
    return Token(token_id=id, outcome=outcome, price=round(price, 4))


def _generate_5min_round(
    round_num: int,
    now: datetime,
) -> list[Event]:
    """1ラウンド分（5分）の全コインマーケット生成.

    各コインに対して:
      1. Above/Below マーケット (single-condition)
      2. Price Brackets マーケット (NegRisk, 3-5レンジ)

    一定確率でミスプライシングを埋め込む。
    """
    events: list[Event] = []
    end_time = now + timedelta(minutes=5)

    for coin in COINS:
        base = BASE_PRICES[coin]
        # ランダムな価格変動 (±2%)
        current = base * (1 + random.uniform(-0.02, 0.02))

        # ─── 1. Above/Below (single-condition) ───
        threshold = round(current * random.choice([0.995, 1.0, 1.005]), 2)
        fair_yes = random.uniform(0.35, 0.65)
        fair_no = 1.0 - fair_yes

        # 30% の確率でミスプライシング (1-5%の乖離)
        if random.random() < 0.30:
            noise = random.uniform(0.01, 0.05)
            if random.random() < 0.5:
                # sum < 1 (LONG arb)
                yes_p = fair_yes - noise * 0.5
                no_p = fair_no - noise * 0.5
            else:
                # sum > 1 (SHORT arb)
                yes_p = fair_yes + noise * 0.5
                no_p = fair_no + noise * 0.5
        else:
            # 正常価格 (±0.5%のノイズ)
            tiny = random.uniform(-0.005, 0.005)
            yes_p = fair_yes + tiny
            no_p = fair_no - tiny

        yes_p = max(0.01, min(0.99, yes_p))
        no_p = max(0.01, min(0.99, no_p))

        mid = f"ab_{coin}_{round_num}"
        events.append(Event(
            id=f"evt_{mid}",
            title=f"{coin} above ${threshold:,.2f} in 5min?",
            slug=f"{coin.lower()}-5min-r{round_num}",
            markets=[Market(
                id=mid,
                question=f"Will {coin} be above ${threshold:,.2f} in 5 minutes?",
                condition_id=f"cond_{mid}",
                slug=f"{coin.lower()}-above-{round_num}",
                tokens=[
                    _make_token(f"{mid}_y", "Yes", yes_p),
                    _make_token(f"{mid}_n", "No", no_p),
                ],
                status=MarketStatus.ACTIVE,
                volume=random.uniform(30_000, 500_000),
                liquidity=random.uniform(10_000, 200_000),
                end_date=end_time,
            )],
        ))

        # ─── 2. Price Brackets (NegRisk) ───
        # 3-4 brackets: e.g. <99K, 99K-101K, >101K
        n_brackets = random.choice([3, 4])
        pct_steps = [0.99, 1.00, 1.01] if n_brackets == 3 else [0.985, 0.995, 1.005, 1.015]
        thresholds = [round(current * s, 2) for s in pct_steps]

        # Generate fair prices that sum to 1
        raw = [random.uniform(0.5, 2.0) for _ in range(n_brackets)]
        total = sum(raw)
        fair_prices = [r / total for r in raw]

        # 25% chance of NegRisk mispricing
        if random.random() < 0.25:
            noise = random.uniform(0.02, 0.08)
            if random.random() < 0.6:
                # sum < 1 (LONG)
                scale = (1.0 - noise) / sum(fair_prices)
            else:
                # sum > 1 (SHORT)
                scale = (1.0 + noise) / sum(fair_prices)
            bracket_prices = [max(0.01, min(0.99, p * scale)) for p in fair_prices]
        else:
            # Small noise
            bracket_prices = [
                max(0.01, min(0.99, p + random.uniform(-0.005, 0.005)))
                for p in fair_prices
            ]

        bracket_labels = []
        for i in range(n_brackets):
            if i == 0:
                bracket_labels.append(f"{coin} below ${thresholds[0]:,.2f}")
            elif i == n_brackets - 1:
                bracket_labels.append(f"{coin} above ${thresholds[-1]:,.2f}")
            else:
                bracket_labels.append(
                    f"{coin} ${thresholds[i-1]:,.2f}-${thresholds[i]:,.2f}"
                )

        nr_id = f"nr_{coin}_{round_num}"
        nr_markets = []
        for i, (label, price) in enumerate(zip(bracket_labels, bracket_prices)):
            m_id = f"{nr_id}_{i}"
            nr_markets.append(Market(
                id=m_id,
                question=f"Will {label} in 5 minutes?",
                condition_id=f"cond_{m_id}",
                slug=f"{coin.lower()}-bracket-{round_num}-{i}",
                tokens=[
                    _make_token(f"{m_id}_y", "Yes", price),
                    _make_token(f"{m_id}_n", "No", round(1.0 - price + random.uniform(-0.02, 0.02), 4)),
                ],
                status=MarketStatus.ACTIVE,
                volume=random.uniform(20_000, 300_000),
                liquidity=random.uniform(5_000, 100_000),
                end_date=end_time,
            ))

        events.append(Event(
            id=f"evt_{nr_id}",
            title=f"{coin} 5min price range",
            slug=f"{coin.lower()}-range-r{round_num}",
            neg_risk=True,
            markets=nr_markets,
        ))

    return events


def main():
    print("=" * 60)
    print("  5分クリプトマーケット Arb ペーパートレード")
    print("  50万円 ($3,145) / 1日シミュレーション")
    print("=" * 60)
    print(f"  対象: {', '.join(COINS)} ({len(COINS)}コイン)")
    print(f"  マーケット/ラウンド: {len(COINS)*2} (Above/Below + Brackets)")
    print(f"  5分 × 12ラウンド/時 × 24時間 = 288ラウンド")
    print(f"  ※デモは48ラウンド (4時間分) で実行\n")

    # Initialize portfolio
    state = PortfolioState(
        initial_capital=3145.0,
        available_cash=3145.0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    now = datetime.now(timezone.utc)
    n_rounds = 48  # 4時間分 (48 × 5min)
    total_arbs_found = 0
    total_arbs_executed = 0
    total_skipped = 0
    round_stats: list[dict] = []

    print_dashboard(state)

    for r in range(1, n_rounds + 1):
        round_time = now + timedelta(minutes=5 * (r - 1))
        time_str = round_time.strftime("%H:%M")

        # Generate markets for this round
        events = _generate_5min_round(r, round_time)
        all_markets = [m for e in events for m in e.markets]

        # Detect arbs
        single_opps = detect_single_condition_arbitrage(all_markets)
        negrisk_opps = detect_negrisk_arbitrage(events)
        all_opps = single_opps + negrisk_opps

        # Filter: min 1.5% profit
        opps = [o for o in all_opps if o.net_profit_per_dollar >= 0.015]
        total_arbs_found += len(opps)

        # First: resolve all open positions from previous round (5 min passed)
        for pos in list(state.open_positions):
            record_exit(state, pos.id)

        # Execute new arbs
        executed_this_round = 0
        for opp in opps:
            size = calculate_position_size(state, opp)
            if size is None:
                total_skipped += 1
                continue
            record_entry(state, opp, size)
            executed_this_round += 1
            total_arbs_executed += 1

        round_stats.append({
            "round": r,
            "time": time_str,
            "markets": len(all_markets),
            "arbs_found": len(opps),
            "arbs_executed": executed_this_round,
            "equity": state.total_equity,
        })

        # Print every 12 rounds (1 hour)
        if r % 12 == 0 or r == 1:
            hour = (r * 5) // 60
            print(f"\n{'─'*60}")
            print(f"  {time_str} | Round {r}/{n_rounds} | Hour {hour}")
            print(f"  Markets: {len(all_markets)} | "
                  f"Arbs: {len(opps)} found, {executed_this_round} executed")
            print(f"  Equity: ${state.total_equity:,.2f} | "
                  f"PnL: ${state.total_realized_pnl:,.2f} "
                  f"({state.roi*100:+.2f}%)")

    # Final resolution
    for pos in list(state.open_positions):
        record_exit(state, pos.id)

    # ── Results ──
    print(f"\n{'='*60}")
    print(f"  RESULTS: 4時間 (48ラウンド) シミュレーション")
    print(f"{'='*60}")

    print(f"""
  マーケット統計:
    総ラウンド:        {n_rounds}
    総マーケット数:     {n_rounds * len(COINS) * 2} ({len(COINS)}コイン × 2タイプ × {n_rounds}ラウンド)
    arb検出数:         {total_arbs_found}
    arb実行数:         {total_arbs_executed}
    スキップ:          {total_skipped} (リスク制限)
    arb率:             {total_arbs_found/(n_rounds*len(COINS)*2)*100:.1f}%
""")

    print_dashboard(state)

    # Hourly breakdown
    print(f"\n  時間別推移:")
    print(f"  {'時刻':>6s}  {'資産':>10s}  {'PnL':>10s}  {'arb数':>5s}")
    print(f"  {'─'*6}  {'─'*10}  {'─'*10}  {'─'*5}")
    for rs in round_stats:
        if rs["round"] % 12 == 0:
            pnl = rs["equity"] - 3145.0
            print(f"  {rs['time']:>6s}  ${rs['equity']:>9,.2f}  ${pnl:>+9,.2f}  {rs['arbs_found']:>5d}")

    # Daily projection
    daily_pnl = state.total_realized_pnl * (288 / n_rounds)  # scale to 24h
    monthly_pnl = daily_pnl * 30

    print(f"""
  ┌──────────────────────────────────────────────┐
  │  4時間実績:                                   │
  │    PnL: ${state.total_realized_pnl:>10,.2f} ({state.roi*100:+.2f}%)          │
  │    取引数: {total_arbs_executed}                                │
  │                                              │
  │  24時間換算 (×6):                             │
  │    PnL: ${daily_pnl:>10,.2f}                         │
  │    取引数: {total_arbs_executed * 6}                              │
  │                                              │
  │  月間換算 (×30日):                            │
  │    PnL: ${monthly_pnl:>10,.2f} (≈¥{monthly_pnl*159:,.0f})       │
  │    月利: {monthly_pnl/3145*100:.1f}%                              │
  │                                              │
  │  50万円 → 月 +¥{monthly_pnl*159/10000:.1f}万円 (5分arb)        │
  └──────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()
