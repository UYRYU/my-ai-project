#!/usr/bin/env python3
"""Polymarket 全市場ミスプライシングスキャナー.

全アクティブ市場を取得し、板情報からミスプライシング（YES_ask + NO_ask ≠ 1.0）を検出。
アービトラージ機会をランキング表示する。

Usage:
    cd polymarket_bot
    python scripts/check_markets.py              # ライブスキャン
    python scripts/check_markets.py --top 20     # 上位20件の板を取得
    python scripts/check_markets.py --demo       # デモモード
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.market_discovery import MarketDiscovery

DIV = "=" * 78
THIN = "-" * 78


# ────────────────────────────────────────────────
#  Live mode
# ────────────────────────────────────────────────
async def run_live(top_n: int = 10) -> None:
    config = load_config()
    discovery = MarketDiscovery(config)

    print(DIV)
    print("  Polymarket 全市場ミスプライシングスキャナー")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  CLOB API  : {config.clob_api}")
    print(f"  板取得上位 : {top_n} 件")
    print(DIV)

    # ── Step 1: 全アクティブ市場取得 ──
    print("\n[1/3] CLOB API /markets で全アクティブ市場を取得中...")
    markets = await discovery.fetch_active_markets(max_pages=50)
    print(f"  アクティブ市場: {len(markets)} 件")

    if not markets:
        print("\n  *** 市場が取得できませんでした ***")
        print("  ネットワーク接続を確認してください。")
        print("  デモモード: python scripts/check_markets.py --demo")
        await discovery.close()
        return

    # ── Step 2: トークン価格でプレフィルタ ──
    # APIレスポンスに含まれるprice情報で事前フィルタ
    print("\n[2/3] トークン価格によるプレフィルタ...")

    candidates = []
    for m in markets:
        yes_tok = m.yes_token
        no_tok = m.no_token
        if not yes_tok or not no_tok:
            continue
        # 価格が両方ある場合のみ
        if yes_tok.price > 0 and no_tok.price > 0:
            price_sum = yes_tok.price + no_tok.price
            deviation = abs(1.0 - price_sum)
            candidates.append((m, price_sum, deviation))

    # deviationが大きい順にソート
    candidates.sort(key=lambda x: x[2], reverse=True)
    print(f"  価格データあり: {len(candidates)} 件")

    if candidates:
        print(f"\n  -- 価格偏差 上位10件 (板取得前) --")
        print(f"  {'#':>3}  {'YES':>6} {'NO':>6} {'SUM':>6} {'DEV':>7}  Question")
        print(f"  {THIN}")
        for i, (m, psum, dev) in enumerate(candidates[:10], 1):
            yes_p = m.yes_token.price if m.yes_token else 0
            no_p = m.no_token.price if m.no_token else 0
            q = m.question[:55]
            print(f"  {i:3d}  {yes_p:6.3f} {no_p:6.3f} {psum:6.3f} {dev:7.4f}  {q}")

    # ── Step 3: 上位N件の板情報を取得してリアルなミスプライシングを計算 ──
    check_targets = candidates[:top_n]
    if not check_targets:
        print("\n  板取得対象がありません。")
        await discovery.close()
        return

    print(f"\n[3/3] 上位 {len(check_targets)} 件の板情報を取得中...")

    results = []
    for i, (m, _, _) in enumerate(check_targets, 1):
        await discovery.enrich_market_with_books(m)
        yes = m.yes_token
        no = m.no_token
        if not yes or not no:
            continue

        yb = yes.order_book
        nb = no.order_book

        has_book = (yb.best_bid is not None and yb.best_ask is not None
                    and nb.best_bid is not None and nb.best_ask is not None)

        if has_book:
            ask_sum = yb.best_ask + nb.best_ask
            bid_sum = yb.best_bid + nb.best_bid
            # Pure arb: ask_sum < 1.0 → buy both sides for < $1, guaranteed $1 payout
            arb_edge = max(0.0, 1.0 - ask_sum)
            # Overround: ask_sum > 1.0 → market maker margin
            overround = max(0.0, ask_sum - 1.0)

            results.append({
                "market": m,
                "yes_bid": yb.best_bid,
                "yes_ask": yb.best_ask,
                "yes_spread": yb.spread,
                "yes_bid_size": yb.best_bid_size,
                "yes_ask_size": yb.best_ask_size,
                "no_bid": nb.best_bid,
                "no_ask": nb.best_ask,
                "no_spread": nb.spread,
                "no_bid_size": nb.best_bid_size,
                "no_ask_size": nb.best_ask_size,
                "ask_sum": ask_sum,
                "bid_sum": bid_sum,
                "arb_edge": arb_edge,
                "overround": overround,
            })
            status = f"arb={arb_edge:.4f}" if arb_edge > 0 else f"over={overround:.4f}"
            print(f"  [{i:2d}/{len(check_targets)}] {status}  {m.question[:55]}")
        else:
            print(f"  [{i:2d}/{len(check_targets)}] 板なし    {m.question[:55]}")

    await discovery.close()

    if not results:
        print("\n  板データが取得できた市場がありませんでした。")
        return

    # ── 結果表示 ──
    # arb_edge > 0 のものを上位に、それ以外はoverround小さい順
    results.sort(key=lambda r: (-r["arb_edge"], r["overround"]))

    print(f"\n{DIV}")
    print("  ミスプライシング結果")
    print(DIV)

    arb_count = sum(1 for r in results if r["arb_edge"] > 0)

    if arb_count > 0:
        print(f"\n  *** アービトラージ機会: {arb_count} 件 ***\n")

    for i, r in enumerate(results, 1):
        m = r["market"]
        tag = " *** ARB ***" if r["arb_edge"] > 0 else ""
        print(f"  #{i}{tag}")
        print(f"    Q: {m.question[:70]}")
        print(f"    YES  bid={r['yes_bid']:.4f} ask={r['yes_ask']:.4f}  spread={r['yes_spread']:.4f}  size={r['yes_bid_size']:.0f}/{r['yes_ask_size']:.0f}")
        print(f"    NO   bid={r['no_bid']:.4f} ask={r['no_ask']:.4f}  spread={r['no_spread']:.4f}  size={r['no_bid_size']:.0f}/{r['no_ask_size']:.0f}")
        print(f"    ask_sum={r['ask_sum']:.4f}  bid_sum={r['bid_sum']:.4f}  arb_edge={r['arb_edge']:.4f}  overround={r['overround']:.4f}")
        if r["arb_edge"] > 0:
            cost = r["ask_sum"]
            profit_pct = (r["arb_edge"] / cost) * 100
            print(f"    → 両サイド購入コスト: ${cost:.4f}  利益: ${r['arb_edge']:.4f} ({profit_pct:.2f}%)")
        print()

    # Summary
    print(THIN)
    print(f"  市場スキャン: {len(markets)} 件")
    print(f"  価格データあり: {len(candidates)} 件")
    print(f"  板取得: {len(results)} 件")
    print(f"  アービトラージ機会 (ask_sum < 1.0): {arb_count} 件")
    avg_overround = sum(r["overround"] for r in results) / len(results) if results else 0
    print(f"  平均オーバーラウンド: {avg_overround:.4f}")
    print(THIN)


# ────────────────────────────────────────────────
#  Demo mode
# ────────────────────────────────────────────────
DEMO_RESULTS = [
    {
        "question": "Will Bitcoin reach $100,000 by May 31st?",
        "yes_bid": 0.60, "yes_ask": 0.62, "yes_spread": 0.02,
        "yes_bid_size": 250, "yes_ask_size": 300,
        "no_bid": 0.36, "no_ask": 0.37, "no_spread": 0.01,
        "no_bid_size": 400, "no_ask_size": 350,
        "ask_sum": 0.99, "bid_sum": 0.96,
        "arb_edge": 0.01, "overround": 0.0,
    },
    {
        "question": "Will ETH be above $5,000 by June?",
        "yes_bid": 0.30, "yes_ask": 0.32, "yes_spread": 0.02,
        "yes_bid_size": 500, "yes_ask_size": 450,
        "no_bid": 0.65, "no_ask": 0.67, "no_spread": 0.02,
        "no_bid_size": 600, "no_ask_size": 550,
        "ask_sum": 0.99, "bid_sum": 0.95,
        "arb_edge": 0.01, "overround": 0.0,
    },
    {
        "question": "Will the Fed cut rates in April?",
        "yes_bid": 0.18, "yes_ask": 0.20, "yes_spread": 0.02,
        "yes_bid_size": 800, "yes_ask_size": 750,
        "no_bid": 0.78, "no_ask": 0.81, "no_spread": 0.03,
        "no_bid_size": 1000, "no_ask_size": 900,
        "ask_sum": 1.01, "bid_sum": 0.96,
        "arb_edge": 0.0, "overround": 0.01,
    },
]


async def run_demo() -> None:
    print(DIV)
    print("  Polymarket ミスプライシングスキャナー [DEMO]")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("  ※ デモデータ使用（API接続なし）")
    print(DIV)

    arb_count = sum(1 for r in DEMO_RESULTS if r["arb_edge"] > 0)

    print(f"\n  アクティブ市場: 3 件 (デモ)")
    print(f"\n  *** アービトラージ機会: {arb_count} 件 ***\n")

    for i, r in enumerate(DEMO_RESULTS, 1):
        tag = " *** ARB ***" if r["arb_edge"] > 0 else ""
        print(f"  #{i}{tag}")
        print(f"    Q: {r['question']}")
        print(f"    YES  bid={r['yes_bid']:.4f} ask={r['yes_ask']:.4f}  spread={r['yes_spread']:.4f}  size={r['yes_bid_size']:.0f}/{r['yes_ask_size']:.0f}")
        print(f"    NO   bid={r['no_bid']:.4f} ask={r['no_ask']:.4f}  spread={r['no_spread']:.4f}  size={r['no_bid_size']:.0f}/{r['no_ask_size']:.0f}")
        print(f"    ask_sum={r['ask_sum']:.4f}  bid_sum={r['bid_sum']:.4f}  arb_edge={r['arb_edge']:.4f}  overround={r['overround']:.4f}")
        if r["arb_edge"] > 0:
            cost = r["ask_sum"]
            profit_pct = (r["arb_edge"] / cost) * 100
            print(f"    → 両サイド購入コスト: ${cost:.4f}  利益: ${r['arb_edge']:.4f} ({profit_pct:.2f}%)")
        print()

    print(THIN)
    print("  ライブ実行: python scripts/check_markets.py")
    print("  上位20件: python scripts/check_markets.py --top 20")
    print(THIN)


# ────────────────────────────────────────────────
async def main() -> None:
    if "--demo" in sys.argv:
        await run_demo()
    else:
        top_n = 10
        for i, arg in enumerate(sys.argv):
            if arg == "--top" and i + 1 < len(sys.argv):
                top_n = int(sys.argv[i + 1])
        await run_live(top_n=top_n)


if __name__ == "__main__":
    asyncio.run(main())
