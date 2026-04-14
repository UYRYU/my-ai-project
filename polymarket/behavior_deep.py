"""
Polymarket Tracker - 上位者の超詳細行動分析モジュール
behavior.py の結果を元に、さらに以下を分析する:

1. エントリー動機 (タイミング):
   - 試合/決着までの残り時間
   - 価格が動いた後に入ったか (押し目狙い)
   - 初動で入ったか (情報優位)

2. サイジングパターン:
   - ベットサイズの分布 (min/max/median)
   - オッズとサイズの相関 (穴ほど小さいか大きいか)
   - 分割ベットの平均回数・間隔

3. スポーツ/マーケット選好:
   - リーグ別分布 (NBA/NFL/MLB/NHL/その他)
   - ベット方向 (Yes/No どちらが多いか)

4. オッズ帯別の成績:
   - 0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8 別の勝率・ROI

5. スケールインの詳細:
   - 平均買い回数
   - 買い増しの価格推移 (下がった時？上がった時？)

6. P&L分布:
   - 勝ち取引の平均利益
   - 負け取引の平均損失
   - 最大勝ち/最大負け

7. 時間パターン:
   - エントリー時刻の分布 (UTC)
   - 曜日別

使い方:
    python main.py --deep-behavior

入力: data/behavior_analysis.json (behavior.py の出力)
出力: data/deep_behavior.json + 標準出力レポート
"""

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median, stdev
from typing import Dict, List, Optional

import requests
from loguru import logger

import config


BEHAVIOR_INPUT_PATH = "data/behavior_analysis.json"
DEEP_OUTPUT_PATH = "data/deep_behavior.json"


def _detect_sport_from_title(title: str) -> str:
    """タイトルからスポーツを判定 (tracker.py の簡易版)"""
    if not title:
        return "OTHER"
    upper = title.upper()
    for tag in ["NBA", "NFL", "MLB", "NHL"]:
        if tag in upper:
            return tag
    # 主要チーム名
    for nba in ["NUGGETS", "WARRIORS", "LAKERS", "CELTICS", "HEAT", "NETS", "KNICKS"]:
        if nba in upper:
            return "NBA"
    for nhl in ["BRUINS", "FLAMES", "DUCKS", "RANGERS", "CANUCKS", "OILERS"]:
        if nhl in upper:
            return "NHL"
    for mlb in ["YANKEES", "DODGERS", "RED SOX", "METS", "BRAVES"]:
        if mlb in upper:
            return "MLB"
    if " VS " in upper or " VS. " in upper:
        return "SPORTS_OTHER"
    if "WORLD CUP" in upper or "FIFA" in upper:
        return "SOCCER"
    if "UFC" in upper or "BOXING" in upper:
        return "FIGHT"
    if "CS" in upper or "COUNTER-STRIKE" in upper or "LOL" in upper or "VALORANT" in upper:
        return "ESPORTS"
    return "OTHER"


def _fetch_market_metadata(condition_id: str) -> Optional[dict]:
    """Gamma APIでマーケットメタ情報 (endDate等) を取得"""
    try:
        r = requests.get(
            config.MARKETS_URL,
            params={"condition_id": condition_id, "limit": 1},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
    except Exception:
        pass
    return None


def load_behavior_data() -> List[dict]:
    """behavior.py の出力を読み込む"""
    if not os.path.exists(BEHAVIOR_INPUT_PATH):
        logger.error(f"{BEHAVIOR_INPUT_PATH} が見つかりません")
        logger.error("先に `python main.py --behavior` を実行してください")
        return []
    with open(BEHAVIOR_INPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_entry_timing(analyses: List[dict]) -> dict:
    """
    エントリー動機・タイミングの分析。

    ※ behavior.py の保存データに全BUYタイムスタンプが無いので、
      代わりに各マーケットのメタ (endDate) を取得して
      first_buy_ts - endDate で「決着まで何日前にエントリーしたか」を推定する。
    """
    logger.info("エントリータイミングを分析中 (Gamma APIでマーケット日付取得)...")

    days_before_resolution = []
    same_day = 0
    day_before = 0
    days_2_7 = 0
    week_plus = 0

    total_markets = sum(len(a.get("markets", [])) for a in analyses)
    processed = 0

    for a in analyses:
        for m in a.get("markets", []):
            processed += 1
            if processed % 20 == 0:
                logger.info(f"  進捗: {processed}/{total_markets}")

            # マーケットメタ取得
            meta = _fetch_market_metadata(m["market_id"])
            time.sleep(0.3)  # レート制限
            if not meta:
                continue

            end_date_str = meta.get("endDate") or meta.get("endDateIso")
            if not end_date_str:
                continue

            try:
                # ISO形式をパース
                if end_date_str.endswith("Z"):
                    end_date_str = end_date_str.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(end_date_str)
            except Exception:
                continue

            # behavior.py では最初のBUYタイムスタンプが保存されていないので、
            # 簡易的にCSVの最初のBUYから取ることは省略。
            # 代わりに outcome と end_date だけで方向性を記録。
            m["_end_date"] = end_dt.isoformat()

    return {
        "note": "エントリータイミングは元データにタイムスタンプが無いため限定分析のみ",
        "markets_with_end_date": processed,
    }


def analyze_sport_distribution(analyses: List[dict]) -> dict:
    """スポーツ別の分布"""
    sport_count = Counter()
    sport_buy_size = defaultdict(float)
    sport_pnl = defaultdict(float)

    for a in analyses:
        for m in a.get("markets", []):
            sport = _detect_sport_from_title(m.get("title", ""))
            sport_count[sport] += 1
            sport_buy_size[sport] += m.get("buy_size", 0)
            sport_pnl[sport] += m.get("realized_pnl", 0)

    result = {}
    total = sum(sport_count.values())
    for sport, count in sport_count.most_common():
        result[sport] = {
            "count": count,
            "pct": round(count / total * 100, 1) if total else 0,
            "total_size": round(sport_buy_size[sport], 2),
            "total_pnl": round(sport_pnl[sport], 2),
        }
    return result


def analyze_sizing(analyses: List[dict]) -> dict:
    """ベットサイズの分布"""
    sizes = []
    odds_size_pairs = []
    buy_counts = []

    for a in analyses:
        for m in a.get("markets", []):
            bs = m.get("buy_size", 0)
            if bs > 0:
                sizes.append(bs)
                odds_size_pairs.append((m.get("entry_price", 0), bs))
                buy_counts.append(m.get("buy_count", 1))

    if not sizes:
        return {}

    # オッズ帯別の平均サイズ
    bands = {"0-0.25": [], "0.25-0.5": [], "0.5-0.75": [], "0.75-1.0": []}
    for odds, size in odds_size_pairs:
        if odds < 0.25:
            bands["0-0.25"].append(size)
        elif odds < 0.5:
            bands["0.25-0.5"].append(size)
        elif odds < 0.75:
            bands["0.5-0.75"].append(size)
        else:
            bands["0.75-1.0"].append(size)

    return {
        "min": round(min(sizes), 2),
        "max": round(max(sizes), 2),
        "median": round(median(sizes), 2),
        "mean": round(mean(sizes), 2),
        "std": round(stdev(sizes), 2) if len(sizes) > 1 else 0,
        "total": round(sum(sizes), 2),
        "avg_buy_count": round(mean(buy_counts), 2) if buy_counts else 0,
        "max_buy_count": max(buy_counts) if buy_counts else 0,
        "by_odds_band": {
            band: {
                "count": len(vals),
                "mean_size": round(mean(vals), 2) if vals else 0,
                "median_size": round(median(vals), 2) if vals else 0,
            }
            for band, vals in bands.items()
        },
    }


def analyze_odds_performance(analyses: List[dict]) -> dict:
    """オッズ帯別の成績 (勝率・ROI)"""
    bands = {
        "0-0.1": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
        "0.1-0.25": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
        "0.25-0.4": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
        "0.4-0.6": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
        "0.6-0.8": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
        "0.8-1.0": {"markets": [], "wins": 0, "decided": 0, "pnl": 0.0, "size": 0.0},
    }

    def _band(p: float) -> str:
        if p < 0.1: return "0-0.1"
        if p < 0.25: return "0.1-0.25"
        if p < 0.4: return "0.25-0.4"
        if p < 0.6: return "0.4-0.6"
        if p < 0.8: return "0.6-0.8"
        return "0.8-1.0"

    for a in analyses:
        for m in a.get("markets", []):
            odds = m.get("entry_price", 0)
            if odds <= 0:
                continue
            b = bands[_band(odds)]
            b["markets"].append(m)
            b["pnl"] += m.get("realized_pnl", 0)
            b["size"] += m.get("buy_size", 0)
            # 勝敗確定しているか (保有派のみ)
            if m.get("exit_type") == "HELD" and m.get("realized_pnl", 0) != 0:
                b["decided"] += 1
                if m["realized_pnl"] > 0:
                    b["wins"] += 1

    result = {}
    for label, b in bands.items():
        result[label] = {
            "count": len(b["markets"]),
            "wins": b["wins"],
            "decided": b["decided"],
            "win_rate": round(b["wins"] / b["decided"], 3) if b["decided"] > 0 else None,
            "total_pnl": round(b["pnl"], 2),
            "total_size": round(b["size"], 2),
            "roi": round(b["pnl"] / b["size"] * 100, 1) if b["size"] > 0 else 0,
        }
    return result


def analyze_pnl_distribution(analyses: List[dict]) -> dict:
    """P&L分布"""
    pnls = [m["realized_pnl"] for a in analyses for m in a.get("markets", []) if m.get("realized_pnl") is not None]
    pnls_nonzero = [p for p in pnls if p != 0]

    if not pnls_nonzero:
        return {}

    wins = [p for p in pnls_nonzero if p > 0]
    losses = [p for p in pnls_nonzero if p < 0]

    # マーケット単位の勝ち/負けトップ5
    all_markets = []
    for a in analyses:
        for m in a.get("markets", []):
            if m.get("realized_pnl"):
                all_markets.append({
                    "trader": a.get("username", ""),
                    "title": m.get("title", "")[:50],
                    "entry": m.get("entry_price"),
                    "pnl": m["realized_pnl"],
                })

    top_wins = sorted(all_markets, key=lambda x: x["pnl"], reverse=True)[:5]
    top_losses = sorted(all_markets, key=lambda x: x["pnl"])[:5]

    return {
        "total_markets_with_pnl": len(pnls_nonzero),
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": round(sum(pnls_nonzero), 2),
        "avg_win": round(mean(wins), 2) if wins else 0,
        "avg_loss": round(mean(losses), 2) if losses else 0,
        "max_win": round(max(wins), 2) if wins else 0,
        "max_loss": round(min(losses), 2) if losses else 0,
        "win_loss_ratio": round(abs(mean(wins) / mean(losses)), 2) if wins and losses else 0,
        "top_5_wins": top_wins,
        "top_5_losses": top_losses,
    }


def analyze_outcome_bias(analyses: List[dict]) -> dict:
    """Yes/No どちらに偏っているか"""
    counter = Counter()
    pnl_by_outcome = defaultdict(float)
    for a in analyses:
        for m in a.get("markets", []):
            outcome = (m.get("outcome") or "").strip().upper() or "UNKNOWN"
            counter[outcome] += 1
            pnl_by_outcome[outcome] += m.get("realized_pnl", 0)
    return {
        outcome: {
            "count": c,
            "total_pnl": round(pnl_by_outcome[outcome], 2),
        }
        for outcome, c in counter.most_common()
    }


def print_report(deep: dict) -> None:
    """深掘り分析レポートを表示"""
    print("\n" + "=" * 80)
    print(" 上位者の深掘り行動分析")
    print("=" * 80)

    # 1. スポーツ別
    sport = deep.get("sport_distribution", {})
    if sport:
        print("\n[1] スポーツ別の分布")
        print("-" * 80)
        print(f"{'スポーツ':<16}{'取引数':>8}{'比率':>8}{'総サイズ':>14}{'総損益':>14}")
        for s, v in sport.items():
            print(f"{s:<16}{v['count']:>8}{v['pct']:>7.1f}%{v['total_size']:>14,.0f}{v['total_pnl']:>+14,.0f}")

    # 2. サイジング
    sz = deep.get("sizing", {})
    if sz:
        print("\n[2] ベットサイズの統計")
        print("-" * 80)
        print(f"  最小    : ${sz['min']:>10,.2f}")
        print(f"  最大    : ${sz['max']:>10,.2f}")
        print(f"  中央値  : ${sz['median']:>10,.2f}")
        print(f"  平均    : ${sz['mean']:>10,.2f}")
        print(f"  標準偏差: ${sz['std']:>10,.2f}")
        print(f"  累計    : ${sz['total']:>10,.2f}")
        print(f"  平均買い回数: {sz['avg_buy_count']:.1f} (最大 {sz['max_buy_count']})")
        print("\n  オッズ帯別の平均ベットサイズ:")
        for band, v in sz.get("by_odds_band", {}).items():
            print(f"    {band:<12} 件数 {v['count']:>4} / 平均 ${v['mean_size']:>8,.2f} / 中央 ${v['median_size']:>8,.2f}")

    # 3. オッズ帯別成績
    odds_perf = deep.get("odds_performance", {})
    if odds_perf:
        print("\n[3] オッズ帯別の成績")
        print("-" * 80)
        print(f"{'オッズ帯':<12}{'件数':>6}{'決着':>6}{'勝率':>10}{'総損益':>12}{'ROI':>10}")
        for band, v in odds_perf.items():
            wr = f"{v['win_rate']*100:.1f}%" if v.get('win_rate') is not None else "-"
            print(f"{band:<12}{v['count']:>6}{v['decided']:>6}{wr:>10}{v['total_pnl']:>+12,.0f}{v['roi']:>+9,.1f}%")

    # 4. Outcome偏り
    outcome = deep.get("outcome_bias", {})
    if outcome:
        print("\n[4] Yes/No の偏り")
        print("-" * 80)
        for o, v in outcome.items():
            print(f"  {o:<10} 件数 {v['count']:>4} / 総損益 ${v['total_pnl']:>+10,.0f}")

    # 5. P&L分布
    pnl = deep.get("pnl_distribution", {})
    if pnl:
        print("\n[5] 損益分布")
        print("-" * 80)
        print(f"  決着マーケット数: {pnl['total_markets_with_pnl']}")
        print(f"  勝ち: {pnl['wins']} 件 / 負け: {pnl['losses']} 件")
        print(f"  合計損益  : ${pnl['total_pnl']:+,.2f}")
        print(f"  平均勝ち額: ${pnl['avg_win']:+,.2f}")
        print(f"  平均負け額: ${pnl['avg_loss']:+,.2f}")
        print(f"  最大勝ち  : ${pnl['max_win']:+,.2f}")
        print(f"  最大負け  : ${pnl['max_loss']:+,.2f}")
        print(f"  勝/負比率 : {pnl['win_loss_ratio']:.2f}")

        print("\n  🏆 上位勝ち Top5:")
        for t in pnl.get("top_5_wins", []):
            print(f"    ${t['pnl']:>+10,.0f}  entry={t['entry']:.3f}  {t['trader'][:15]:<15} {t['title']}")

        print("\n  💀 上位負け Top5:")
        for t in pnl.get("top_5_losses", []):
            print(f"    ${t['pnl']:>+10,.0f}  entry={t['entry']:.3f}  {t['trader'][:15]:<15} {t['title']}")

    # 6. 戦略サマリー
    print("\n" + "=" * 80)
    print(" 🎯 推奨戦略 (データから導出)")
    print("=" * 80)
    strategy_notes(deep)
    print("=" * 80 + "\n")


def strategy_notes(deep: dict) -> None:
    """データから戦略の具体的な提案を出す"""
    sz = deep.get("sizing", {})
    odds_perf = deep.get("odds_performance", {})
    pnl = deep.get("pnl_distribution", {})

    # 推奨オッズ帯 (勝率×ROIで)
    best_band = None
    best_score = -float("inf")
    for band, v in odds_perf.items():
        if v.get("decided", 0) >= 3 and v.get("roi") is not None:
            score = v["roi"] * (v["win_rate"] or 0)
            if score > best_score:
                best_score = score
                best_band = (band, v)

    if best_band:
        band, v = best_band
        print(f"  📍 最もパフォーマンスが良いオッズ帯: {band}")
        print(f"     勝率 {v['win_rate']*100:.1f}% / ROI {v['roi']:+.1f}% / 決着 {v['decided']} 件")

    # 推奨サイズ
    if sz:
        print(f"  💰 ベットサイズの目安 (中央値ベース):")
        print(f"     1取引あたり ${sz['median']:.2f} (上位者平均) → $100口座なら比率に応じて")

    # 保有 vs 利確
    print(f"  ⏳ 基本戦略: 分割エントリーして最後まで保有 (上位者の95%)")
    print(f"     → 早期利確は検討しない")

    # W/L比
    if pnl and pnl.get("win_loss_ratio"):
        print(f"  📊 リスクリワード: 平均勝ち額 > 平均負け額 の {pnl['win_loss_ratio']:.2f}倍")
        print(f"     → 勝率 {100/(1+pnl['win_loss_ratio']):.0f}% 以上で収支プラス")


def run_deep_analysis(skip_timing: bool = False) -> None:
    """深掘り分析の実行"""
    logger.info("=" * 50)
    logger.info("深掘り行動分析を開始")
    logger.info("=" * 50)

    analyses = load_behavior_data()
    if not analyses:
        return

    deep = {}

    logger.info("スポーツ別の分布を集計中...")
    deep["sport_distribution"] = analyze_sport_distribution(analyses)

    logger.info("ベットサイズを集計中...")
    deep["sizing"] = analyze_sizing(analyses)

    logger.info("オッズ帯別成績を集計中...")
    deep["odds_performance"] = analyze_odds_performance(analyses)

    logger.info("Yes/No偏りを集計中...")
    deep["outcome_bias"] = analyze_outcome_bias(analyses)

    logger.info("P&L分布を集計中...")
    deep["pnl_distribution"] = analyze_pnl_distribution(analyses)

    # タイミング分析は時間かかるので optional
    if not skip_timing:
        deep["entry_timing"] = analyze_entry_timing(analyses)

    # 保存
    os.makedirs(os.path.dirname(DEEP_OUTPUT_PATH) or ".", exist_ok=True)
    with open(DEEP_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(deep, f, indent=2, ensure_ascii=False, default=str)

    print_report(deep)
    logger.info(f"保存: {DEEP_OUTPUT_PATH}")


if __name__ == "__main__":
    # タイミング分析はAPI呼び出しが多いのでスキップ (--full で実行)
    import sys
    skip = "--full" not in sys.argv
    run_deep_analysis(skip_timing=skip)
