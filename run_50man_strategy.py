#!/usr/bin/env python3
"""50万円スタート戦略シミュレーター.

コアロジック (Sports Betting + Prediction Markets) はそのまま固定。
資金配分・回転率・リスク管理を50万円に合わせて最適化。
"""

from __future__ import annotations

import math


JPY_PER_USD = 159.0
BUDGET_JPY = 500_000
BUDGET_USD = BUDGET_JPY / JPY_PER_USD  # ~$3,145


def jpy(usd: float) -> str:
    y = usd * JPY_PER_USD
    if abs(y) >= 10_000:
        return f"¥{y/10000:.1f}万"
    return f"¥{y:,.0f}"


def usd(v: float) -> str:
    return f"${v:,.0f}"


def simulate_month(
    capital: float,
    monthly_rolls: float,
    arb_hit_rate: float,
    avg_margin: float,
    fee_rate: float,
) -> float:
    """1ヶ月のリターンを計算."""
    turnover = capital * monthly_rolls
    arb_volume = turnover * arb_hit_rate
    gross_profit = arb_volume * avg_margin
    net_profit = gross_profit * (1 - fee_rate)
    return net_profit


def simulate_compound(
    capital: float,
    monthly_rolls: float,
    arb_hit_rate: float,
    avg_margin: float,
    fee_rate: float,
    months: int,
) -> list[float]:
    """複利で月次シミュレーション."""
    balances = [capital]
    current = capital
    for _ in range(months):
        profit = simulate_month(current, monthly_rolls, arb_hit_rate, avg_margin, fee_rate)
        current += profit
        balances.append(current)
    return balances


def main():
    print("=" * 60)
    print(f"  50万円 (≈{usd(BUDGET_USD)}) スタート戦略")
    print(f"  Sports Betting + Prediction Markets 併用")
    print("=" * 60)

    # ================================================================
    # 資金配分
    # ================================================================
    sports_alloc = 0.40   # 40% → スポーツベッティング
    poly_alloc = 0.60     # 60% → Prediction Markets

    sports_capital = BUDGET_USD * sports_alloc
    poly_capital = BUDGET_USD * poly_alloc

    print(f"""
  資金配分:
  ┌─────────────────────────────────────────────┐
  │  総資金:    ¥50万 ({usd(BUDGET_USD)})             │
  │                                             │
  │  Sports Betting:  {sports_alloc*100:.0f}% = {jpy(sports_capital):>7s} ({usd(sports_capital)})  │
  │  Prediction Mkts: {poly_alloc*100:.0f}% = {jpy(poly_capital):>7s} ({usd(poly_capital)})  │
  └─────────────────────────────────────────────┘

  なぜこの配分？
    → Sports Betting: 少額でも回転が効く、確実性が高い
    → Polymarket: 1回のarb利益率が大きい (3-9%)、Bot化で効率UP
""")

    # ================================================================
    # Domain 1: Sports Betting
    # ================================================================
    print("─" * 60)
    print("  DOMAIN 1: Sports Betting")
    print("─" * 60)

    # Parameters
    s_rolls = 20          # 月20回転 (1日あたり0.7回転、控えめ)
    s_hit_rate = 0.35     # 賭けの35%がarb (arb専用スキャナー使用)
    s_margin = 0.015      # 平均1.5%マージン
    s_fee = 0.05          # 手数料5%

    s_profit = simulate_month(sports_capital, s_rolls, s_hit_rate, s_margin, s_fee)

    print(f"""
  パラメータ:
    資金:        {jpy(sports_capital)} ({usd(sports_capital)})
    月間回転数:  {s_rolls}回 (1日あたり{s_rolls/30:.1f}回)
    arb発見率:   {s_hit_rate*100:.0f}% (全ベットのうちarbになる割合)
    平均マージン: {s_margin*100:.1f}%
    手数料:      {s_fee*100:.0f}%

  月間シミュレーション:
    月間ターンオーバー: {jpy(sports_capital * s_rolls)} ({usd(sports_capital * s_rolls)})
    arb取引額:         {jpy(sports_capital * s_rolls * s_hit_rate)}
    粗利:              {jpy(sports_capital * s_rolls * s_hit_rate * s_margin)}
    手数料控除後:       {jpy(s_profit)} ({usd(s_profit)})
    月利:              {s_profit/sports_capital*100:.1f}%

  運用方法:
    ・3-5個のブックメーカー口座に分散 (各{jpy(sports_capital/4)})
    ・OddsJam / BetBurger 等のスキャナー使用 (月$30-50)
    ・1日1-2件のsure betを手動実行
    ・利益は毎週リバランス
""")

    # ================================================================
    # Domain 2: Prediction Markets (Polymarket)
    # ================================================================
    print("─" * 60)
    print("  DOMAIN 2: Prediction Markets (Polymarket)")
    print("─" * 60)

    # Parameters - 2 strategies
    # Strategy A: Manual NegRisk arb (easy, no bot)
    p_manual_rolls = 8    # 月8回転 (2日に1回)
    p_manual_hit = 0.50   # 50% hit rate (NegRisk arbは常に存在する)
    p_manual_margin = 0.04  # 4% average margin (NegRiskは大きめ)
    p_manual_fee = 0.10   # 10% (gas + Polymarket fee)

    p_manual_profit = simulate_month(
        poly_capital, p_manual_rolls, p_manual_hit, p_manual_margin, p_manual_fee,
    )

    # Strategy B: Bot (after month 2-3)
    p_bot_rolls = 30      # 月30回転 (1日1回)
    p_bot_hit = 0.60      # Bot is better at finding
    p_bot_margin = 0.03   # slightly smaller (Bot catches smaller opps too)
    p_bot_fee = 0.08      # lower gas with optimization

    p_bot_profit = simulate_month(
        poly_capital, p_bot_rolls, p_bot_hit, p_bot_margin, p_bot_fee,
    )

    print(f"""
  パラメータ:
    資金: {jpy(poly_capital)} ({usd(poly_capital)})

  Strategy A: 手動 NegRisk arb (初月から)
    月間回転数:  {p_manual_rolls}回 (2日に1回チェック)
    arb発見率:   {p_manual_hit*100:.0f}%
    平均マージン: {p_manual_margin*100:.1f}% (NegRiskは大きめの乖離)
    手数料:      {p_manual_fee*100:.0f}%

    月間収益: {jpy(p_manual_profit)} ({usd(p_manual_profit)})
    月利:     {p_manual_profit/poly_capital*100:.1f}%

  Strategy B: Bot化後 (3ヶ月目から)
    月間回転数:  {p_bot_rolls}回 (毎日自動スキャン)
    arb発見率:   {p_bot_hit*100:.0f}%
    平均マージン: {p_bot_margin*100:.1f}%
    手数料:      {p_bot_fee*100:.0f}%

    月間収益: {jpy(p_bot_profit)} ({usd(p_bot_profit)})
    月利:     {p_bot_profit/poly_capital*100:.1f}%

  運用方法:
    ・Polymarketアカウント開設 (USDC入金)
    ・まず手動: NegRiskイベントの sum(YES) を毎日チェック
    ・乖離 > 2% のイベントで全YES購入 (LONG arb)
    ・3ヶ月目: 今回作ったコードをcron化してBot運用
""")

    # ================================================================
    # 12ヶ月シミュレーション (複利)
    # ================================================================
    print("─" * 60)
    print("  12ヶ月複利シミュレーション")
    print("─" * 60)

    # Phase 1 (month 1-2): manual only
    # Phase 2 (month 3-12): bot + sports
    total_capital = BUDGET_USD
    monthly_log = []

    for month in range(1, 13):
        s_cap = total_capital * sports_alloc
        p_cap = total_capital * poly_alloc

        s_p = simulate_month(s_cap, s_rolls, s_hit_rate, s_margin, s_fee)

        if month <= 2:
            # Manual phase
            p_p = simulate_month(p_cap, p_manual_rolls, p_manual_hit, p_manual_margin, p_manual_fee)
            phase = "手動"
        else:
            # Bot phase
            p_p = simulate_month(p_cap, p_bot_rolls, p_bot_hit, p_bot_margin, p_bot_fee)
            phase = "Bot "

        total_profit = s_p + p_p
        total_capital += total_profit
        monthly_log.append((month, total_capital, s_p, p_p, total_profit, phase))

    print(f"\n  {'月':>3s}  {'残高':>10s}  {'Sports':>9s}  {'Poly':>9s}  {'合計':>9s}  Phase")
    print(f"  {'─'*3}  {'─'*10}  {'─'*9}  {'─'*9}  {'─'*9}  {'─'*5}")
    print(f"  {'0':>3s}  {jpy(BUDGET_USD):>10s}  {'─':>9s}  {'─':>9s}  {'─':>9s}  開始")

    for month, bal, sp, pp, tp, phase in monthly_log:
        print(f"  {month:>3d}  {jpy(bal):>10s}  {jpy(sp):>9s}  {jpy(pp):>9s}  {jpy(tp):>9s}  {phase}")

    final = monthly_log[-1][1]
    total_gain = final - BUDGET_USD
    print(f"""
  ┌─────────────────────────────────────────────┐
  │  12ヶ月後の残高: {jpy(final):>10s} ({usd(final)})       │
  │  総利益:         {jpy(total_gain):>10s} ({usd(total_gain)})       │
  │  年利:           {total_gain/BUDGET_USD*100:>8.0f}%                   │
  │  50万円 → {jpy(final)}                         │
  └─────────────────────────────────────────────┘
""")

    # ================================================================
    # リスクと注意点
    # ================================================================
    print("─" * 60)
    print("  リスクと注意点")
    print("─" * 60)
    print("""
  ⚠ Sports Betting:
    ・アカウント制限: 3-6ヶ月で利益が出ると制限される可能性
    ・対策: 少額で始める、通常ベットも混ぜる、複数プラットフォーム
    ・最悪ケース: 全口座制限 → Sports配分をPolyに移す

  ⚠ Prediction Markets:
    ・流動性リスク: 小さいマーケットでは注文が通らない
    ・対策: volume > $50K のマーケットのみ対象
    ・ガス代: Polygon L2なので安い ($0.01-0.05/tx)
    ・規制リスク: 日本からのアクセス制限の可能性

  ⚠ 共通:
    ・上記は「楽観シナリオ」。現実は70-80%程度の達成率
    ・月利10%ではなく5-8%が現実的ライン
    ・最初の2ヶ月は勉強代と割り切る

  ✓ 始め方 (Day 1):
    1. Polymarket アカウント開設 + USDC ¥30万分入金
    2. ブックメーカー 3つ開設 + 各¥7万入金
    3. python main.py でarbスキャン開始
    4. NegRiskイベントで sum(YES) < 0.97 を探す → 全YES購入
""")


if __name__ == "__main__":
    main()
