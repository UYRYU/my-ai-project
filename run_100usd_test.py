#!/usr/bin/env python3
"""$100テスト — 5分クリプトarb 1日ペーパートレード.

$100 USDC で2週間テスト運用する前のシミュレーション。
1取引あたり$5-15、5分で解決、1日分(48ラウンド=4時間)を回す。
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

# $100用のリスク設定 — 固定$50/取引
os.environ["FIXED_TRADE_SIZE"] = "50"   # 固定$50/取引 (両ポジ合計)
os.environ["MIN_TRADE_SIZE"] = "5"      # 最低$5/取引
os.environ["MAX_SINGLE_TRADE_PCT"] = "0.50"  # 最大50%/取引 = $50
os.environ["MAX_UTILIZATION"] = "0.90"  # 最大90%稼働
os.environ["MAX_CONCURRENT"] = "0"      # 自動: 資金÷$50 = ポジ数 ($100→2, $150→3, $200→4)

from polymarket_arbitrage.models.market import (
    Event, Market, MarketStatus, Token,
)
from polymarket_arbitrage.arbitrage.intra_market import (
    detect_single_condition_arbitrage,
    detect_negrisk_arbitrage,
)
from bot.portfolio import (
    PortfolioState,
    calculate_position_size,
    record_entry,
    record_exit,
    print_dashboard,
    save_state,
)

random.seed(42)

COINS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "MATIC"]
BASE_PRICES = {
    "BTC": 104_500, "ETH": 3_420, "SOL": 178, "DOGE": 0.38,
    "XRP": 2.45, "AVAX": 42, "LINK": 18.5, "MATIC": 0.85,
}


def _tok(id, outcome, price):
    return Token(token_id=id, outcome=outcome, price=round(max(0.01, min(0.99, price)), 4))


def generate_round(r: int, now: datetime) -> list[Event]:
    events = []
    end = now + timedelta(minutes=5)

    for coin in COINS:
        base = BASE_PRICES[coin]
        current = base * (1 + random.uniform(-0.02, 0.02))

        # Above/Below
        thresh = round(current * random.choice([0.995, 1.0, 1.005]), 2)
        fy = random.uniform(0.35, 0.65)

        if random.random() < 0.30:
            noise = random.uniform(0.01, 0.05)
            yp = fy - noise * 0.5 if random.random() < 0.5 else fy + noise * 0.5
            np_ = (1 - fy) - noise * 0.5 if yp < fy else (1 - fy) + noise * 0.5
        else:
            t = random.uniform(-0.005, 0.005)
            yp, np_ = fy + t, (1 - fy) - t

        mid = f"ab_{coin}_{r}"
        events.append(Event(
            id=f"e_{mid}", title=f"{coin} > ${thresh:,.2f} 5min?", slug=mid,
            markets=[Market(
                id=mid, question=f"Will {coin} be above ${thresh:,.2f} in 5 min?",
                condition_id=f"c_{mid}", slug=mid,
                tokens=[_tok(f"{mid}_y", "Yes", yp), _tok(f"{mid}_n", "No", np_)],
                status=MarketStatus.ACTIVE,
                volume=random.uniform(30_000, 500_000),
                liquidity=random.uniform(10_000, 200_000),
                end_date=end,
            )],
        ))

        # Brackets (NegRisk)
        n = random.choice([3, 4])
        steps = [0.99, 1.0, 1.01] if n == 3 else [0.985, 0.995, 1.005, 1.015]
        ths = [round(current * s, 2) for s in steps]
        raw = [random.uniform(0.5, 2.0) for _ in range(n)]
        fair = [x / sum(raw) for x in raw]

        if random.random() < 0.25:
            scale = (1.0 - random.uniform(0.02, 0.08)) / sum(fair) if random.random() < 0.6 \
                else (1.0 + random.uniform(0.02, 0.08)) / sum(fair)
            prices = [max(0.01, min(0.99, p * scale)) for p in fair]
        else:
            prices = [max(0.01, min(0.99, p + random.uniform(-0.005, 0.005))) for p in fair]

        labels = []
        for i in range(n):
            if i == 0:
                labels.append(f"{coin} < ${ths[0]:,.2f}")
            elif i == n - 1:
                labels.append(f"{coin} > ${ths[-1]:,.2f}")
            else:
                labels.append(f"{coin} ${ths[i-1]:,.2f}-${ths[i]:,.2f}")

        nrid = f"nr_{coin}_{r}"
        ms = []
        for i, (l, p) in enumerate(zip(labels, prices)):
            mi = f"{nrid}_{i}"
            ms.append(Market(
                id=mi, question=f"Will {l} in 5 min?",
                condition_id=f"c_{mi}", slug=mi,
                tokens=[_tok(f"{mi}_y", "Yes", p),
                        _tok(f"{mi}_n", "No", round(1 - p + random.uniform(-0.02, 0.02), 4))],
                status=MarketStatus.ACTIVE,
                volume=random.uniform(20_000, 300_000),
                liquidity=random.uniform(5_000, 100_000),
                end_date=end,
            ))
        events.append(Event(
            id=f"e_{nrid}", title=f"{coin} 5m range", slug=nrid,
            neg_risk=True, markets=ms,
        ))

    return events


def main():
    print("=" * 55)
    print("  $100 テストラン — 5分クリプトarb")
    print("  2週間テスト前のペーパートレード")
    print("=" * 55)
    print(f"  資金: $100 (≈¥15,900)")
    print(f"  1取引: 固定 $50 (YES≈$25 + NO≈$25)")
    print(f"  コイン: {len(COINS)}種 ({', '.join(COINS)})")
    print(f"  リスク上限: 90%稼働, 最大2ポジ同時")
    print()

    state = PortfolioState(
        initial_capital=100.0, available_cash=100.0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    now = datetime.now(timezone.utc)
    n_rounds = 48
    total_found = 0
    total_exec = 0
    total_skip = 0

    print("  1取引の内訳:")
    print("  ┌─────────────────────────────────────────────┐")
    print("  │ YES=$0.45 × 11.11枚 = $ 5.00               │")
    print("  │ NO =$0.48 × 11.11枚 = $ 5.33               │")
    print("  │ 合計コスト:           $10.33                │")
    print("  │ 5分後、必ず1つ当たり: $11.11 回収           │")
    print("  │ 利益: $0.78 (7.5%)                         │")
    print("  └─────────────────────────────────────────────┘")
    print()
    print_dashboard(state)

    for r in range(1, n_rounds + 1):
        rt = now + timedelta(minutes=5 * (r - 1))

        events = generate_round(r, rt)
        all_m = [m for e in events for m in e.markets]

        opps = detect_single_condition_arbitrage(all_m)
        opps.extend(detect_negrisk_arbitrage(events))
        opps = [o for o in opps if o.net_profit_per_dollar >= 0.015]
        total_found += len(opps)

        # Resolve previous round
        for pos in list(state.open_positions):
            record_exit(state, pos.id)

        # Execute
        for opp in opps:
            size = calculate_position_size(state, opp)
            if size is None:
                total_skip += 1
                continue
            record_entry(state, opp, size)
            total_exec += 1

        if r % 12 == 0:
            h = (r * 5) // 60
            pnl = state.total_realized_pnl
            print(f"\n  Hour {h}: equity=${state.total_equity:.2f} "
                  f"PnL=${pnl:+.2f} ({state.roi*100:+.1f}%) "
                  f"trades={state.trade_count}")

    # Final resolve
    for pos in list(state.open_positions):
        record_exit(state, pos.id)

    daily = state.total_realized_pnl * (288 / n_rounds)
    weekly = daily * 7
    biweekly = daily * 14

    print(f"\n{'='*55}")
    print(f"  結果")
    print(f"{'='*55}")
    print_dashboard(state)

    print(f"""
  4時間 ({n_rounds}ラウンド):
    arb検出: {total_found}件
    実行:    {total_exec}件
    スキップ: {total_skip}件 (リスク制限)
    PnL:     ${state.total_realized_pnl:.2f} ({state.roi*100:+.1f}%)

  ┌──────────────────────────────────────────────┐
  │  $100 テストランの予想                        │
  │                                              │
  │  1日:    ${daily:>8.2f} ({daily/100*100:+.1f}%)             │
  │  1週間:  ${weekly:>8.2f} ({weekly/100*100:+.1f}%)            │
  │  2週間:  ${biweekly:>8.2f} ({biweekly/100*100:+.1f}%)          │
  │                                              │
  │  2週間後の残高: ${100+biweekly:>8.2f}                  │
  └──────────────────────────────────────────────┘

  ※これはデモデータ (arb率30%) の楽観値
  ※実際はarb率5-10%、月利30-100%あたりが現実的
  ※$100で2週間問題なければ→$3,145 (50万円) に増額

  テスト開始コマンド:
    INITIAL_CAPITAL=100 MIN_TRADE_SIZE=5 python -m bot.run
""")


if __name__ == "__main__":
    main()
