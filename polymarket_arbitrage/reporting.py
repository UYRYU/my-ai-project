"""Reporting and summary output for arbitrage results."""

from __future__ import annotations

from polymarket_arbitrage.models.market import (
    ArbitrageOpportunity,
    ArbitrageType,
)


def summarize(opportunities: list[ArbitrageOpportunity]) -> str:
    """Generate a human-readable summary of detected arbitrage opportunities."""
    if not opportunities:
        return "No arbitrage opportunities detected."

    lines: list[str] = []

    # Group by type
    by_type: dict[ArbitrageType, list[ArbitrageOpportunity]] = {}
    for opp in opportunities:
        by_type.setdefault(opp.arb_type, []).append(opp)

    total_profitable = sum(1 for o in opportunities if o.is_profitable)

    lines.append("=" * 70)
    lines.append("ARBITRAGE DETECTION REPORT")
    lines.append("=" * 70)
    lines.append(f"Total opportunities found: {len(opportunities)}")
    lines.append(f"Profitable (after fees):   {total_profitable}")
    lines.append("")

    type_labels = {
        ArbitrageType.SINGLE_CONDITION: "Single-Condition (YES+NO != $1)",
        ArbitrageType.NEGRISK_INTRA: "NegRisk Intra-Event (sum(YES) != $1)",
        ArbitrageType.COMBINATORIAL: "Combinatorial (Inter-Market)",
    }

    for arb_type in ArbitrageType:
        opps = by_type.get(arb_type, [])
        if not opps:
            continue

        lines.append("-" * 70)
        lines.append(f"{type_labels.get(arb_type, arb_type.value)}: {len(opps)} opportunities")
        lines.append("-" * 70)

        # Sort by net profit descending
        opps.sort(key=lambda o: o.net_profit_per_dollar, reverse=True)

        # Summary stats
        profits = [o.net_profit_per_dollar for o in opps if o.is_profitable]
        if profits:
            lines.append(
                f"  Net profit per $1: "
                f"max={max(profits):.4f}, "
                f"avg={sum(profits)/len(profits):.4f}, "
                f"min={min(profits):.4f}"
            )

        long_count = sum(1 for o in opps if o.direction.value == "long")
        short_count = len(opps) - long_count
        lines.append(f"  Long: {long_count}, Short: {short_count}")
        lines.append("")

        # Top 10 opportunities
        for i, opp in enumerate(opps[:10], 1):
            lines.append(f"  #{i} [{opp.direction.value.upper()}] {opp.description}")
            lines.append(
                f"      Price sum: {opp.price_sum:.4f} | "
                f"Raw profit: ${opp.raw_profit_per_dollar:.4f} | "
                f"Net profit: ${opp.net_profit_per_dollar:.4f}"
            )
            lines.append("")

        if len(opps) > 10:
            lines.append(f"  ... and {len(opps) - 10} more")
            lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def to_json_serializable(
    opportunities: list[ArbitrageOpportunity],
) -> list[dict]:
    """Convert opportunities to JSON-serializable dicts."""
    results = []
    for opp in opportunities:
        results.append({
            "type": opp.arb_type.value,
            "direction": opp.direction.value,
            "markets": [
                {"id": m.id, "question": m.question, "yes_price": m.yes_price, "no_price": m.no_price}
                for m in opp.markets
            ],
            "price_sum": opp.price_sum,
            "raw_profit_per_dollar": opp.raw_profit_per_dollar,
            "net_profit_per_dollar": opp.net_profit_per_dollar,
            "is_profitable": opp.is_profitable,
            "description": opp.description,
            "timestamp": opp.timestamp.isoformat() if opp.timestamp else None,
        })
    return results
