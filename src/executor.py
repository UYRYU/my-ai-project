"""Thin execution layer. Defaults to dry-run printing.

Real order placement requires py-clob-client with a funded Polygon wallet.
Signing is done locally; the private key never leaves your machine.
"""

from .arbitrage import Opportunity
from .config import Config


def execute(opp: Opportunity, cfg: Config) -> None:
    if cfg.dry_run:
        print(f"[DRY] {opp.kind} edge={opp.edge:.4f} — {opp.market.question}")
        for token_id, price in opp.legs:
            print(f"  leg token={token_id[:8]}... price={price:.4f}")
        return

    # Lazy import so dry-run doesn't require the heavy dep.
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    client = ClobClient(
        cfg.polymarket_host,
        key=cfg.polymarket_private_key,
        chain_id=137,
        signature_type=1,
        funder=cfg.polymarket_funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())

    # Position-sized across all legs so losing-leg losses can't exceed budget.
    per_leg_usd = cfg.max_position_usd / max(len(opp.legs), 1)

    for token_id, price in opp.legs:
        size = round(per_leg_usd / max(price, 0.01), 4)
        order_args = OrderArgs(price=price, size=size, side=BUY, token_id=token_id)
        signed = client.create_order(order_args)
        resp = client.post_order(signed, OrderType.GTC)
        print(f"[LIVE] posted token={token_id[:8]}... size={size} resp={resp}")
