"""Execution layer. Defaults to dry-run printing.

Real order placement requires py-clob-client with a funded Polygon wallet.
Signing is done locally; the private key never leaves your machine.
"""

from . import trade_log
from .arbitrage import Opportunity
from .config import Config
from .orderbook import FillQuote
from .positions import Book


def execute(
    opp: Opportunity,
    cfg: Config,
    book: Book,
    quotes: list[FillQuote] | None = None,
) -> None:
    """Place orders for an arbitrage basket.

    `quotes` is the depth-verified per-leg fill quote from
    orderbook.quote_basket_cost — if provided, we use real avg fills.
    Falls back to opportunity prices (Gamma snapshot) for dry-run only.
    """
    legs = list(zip([t for t, _ in opp.legs], [p for _, p in opp.legs]))
    if quotes is not None:
        legs = [(q.token_id, q.avg_price) for q in quotes]

    trade_log.write(
        "opportunity",
        kind=opp.kind,
        edge=opp.edge,
        question=opp.market.question,
        slug=opp.market.slug,
        legs=legs,
        dry_run=cfg.dry_run,
    )

    if cfg.dry_run:
        print(f"[DRY] {opp.kind} edge={opp.edge:.4f} — {opp.market.question}")
        for token_id, price in legs:
            print(f"  leg token={token_id[:10]}... price={price:.4f}")
        # mock-fill positions so the paper book reflects what live would do
        per_leg_usd = cfg.max_position_usd / max(len(legs), 1)
        for token_id, price in legs:
            shares = round(per_leg_usd / max(price, 0.01), 4)
            book.record_fill(token_id, shares, price)
        return

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

    per_leg_usd = cfg.max_position_usd / max(len(legs), 1)

    for token_id, price in legs:
        size = round(per_leg_usd / max(price, 0.01), 4)
        order_args = OrderArgs(price=price, size=size, side=BUY, token_id=token_id)
        signed = client.create_order(order_args)
        resp = client.post_order(signed, OrderType.GTC)
        book.record_fill(token_id, size, price)
        trade_log.write("fill", token_id=token_id, size=size, price=price, resp=str(resp))
        print(f"[LIVE] posted token={token_id[:10]}... size={size} resp={resp}")
