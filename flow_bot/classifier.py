"""Unusual Options Flow Classifier - フロー強度を分類"""

from scanner import OptionFlow
import config


# 分類ラベル
GOLDEN_SWEEP = "GOLDEN_SWEEP"
STRONG = "STRONG"
MODERATE = "MODERATE"


def classify(flow: OptionFlow) -> str:
    """フローの強度を分類する

    GOLDEN_SWEEP: Vol/OI比 10倍以上 かつ プレミアム $500k以上
    STRONG:       Vol/OI比 8倍以上 または プレミアム $300k以上
    MODERATE:     それ以外（検出条件は満たしている）
    """
    if flow.volume_oi_ratio >= 10.0 and flow.premium >= 500_000:
        return GOLDEN_SWEEP
    if flow.volume_oi_ratio >= 8.0 or flow.premium >= 300_000:
        return STRONG
    return MODERATE


def format_alert(flow: OptionFlow, level: str) -> str:
    """アラートをターミナル表示用にフォーマット"""
    # レベル別の色付けとアイコン
    indicators = {
        GOLDEN_SWEEP: "\033[33m🔥 GOLDEN SWEEP\033[0m",
        STRONG:       "\033[31m⚡ STRONG\033[0m",
        MODERATE:     "\033[36m📊 MODERATE\033[0m",
    }
    indicator = indicators.get(level, level)

    premium_k = flow.premium / 1000
    return (
        f"\n{'='*60}\n"
        f"  {indicator}\n"
        f"  {flow.ticker} | {flow.strike}C | Exp: {flow.expiration} (DTE {flow.dte})\n"
        f"  Vol: {flow.volume:,} | OI: {flow.open_interest:,} | "
        f"Vol/OI: {flow.volume_oi_ratio}x\n"
        f"  Premium: ${premium_k:,.1f}K\n"
        f"  Contract: {flow.contract}\n"
        f"{'='*60}"
    )
