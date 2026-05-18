"""Execution layer. Defaults to dry-run.

Atomic basket semantics: we place all legs, and if ANY leg fails to
fully fill within a tight window, we unwind the filled legs (sell back
at best-bid) so we never end up with directional exposure.

Real live execution requires py-clob-client with a funded Polygon
wallet. Dry-run mocks the fills so the paper PnL mirrors what live
would produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from . import trade_log
from .arbitrage import Opportunity
from .config import Config
from .orderbook import FillQuote
from .positions import Book


@dataclass
class LegResult:
    token_id: str
    requested_size: float
    filled_size: float
    avg_price: float
    error: str | None = None

    @property
    def filled_fully(self) -> bool:
        return self.error is None and self.filled_size >= self.requested_size - 1e-6


def _size_for_leg(target_payout_usd: float) -> float:
    """Each winning share pays $1. Size = target payout in $.

    Note: sized so the WINNING leg pays target_payout_usd. Cost is less.
    """
    return round(target_payout_usd, 4)


def execute(
    opp: Opportunity,
    cfg: Config,
    book: Book,
    quotes: list[FillQuote] | None = None,
) -> None:
    """Place orders for an arbitrage basket with atomic semantics.

    Dry-run: mock the fills into the paper book.
    Live: place IOC orders, unwind if any leg is short-filled.
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
        _dry_run_fill(legs, cfg, book)
        return

    results = _live_place(legs, cfg, book)
    _maybe_unwind(results, cfg, book)


def _dry_run_fill(legs: list[tuple[str, float]], cfg: Config, book: Book) -> None:
    per_leg_usd = cfg.max_position_usd / max(len(legs), 1)
    print(f"[DRY] basket cost ~${sum(p for _, p in legs) * (per_leg_usd / max(legs[0][1], 0.01)):.2f}")
    for token_id, price in legs:
        shares = round(per_leg_usd / max(price, 0.01), 4)
        print(f"  leg token={token_id[:10]}... price={price:.4f} size={shares}")
        book.record_fill(token_id, shares, price)


def _live_place(
    legs: list[tuple[str, float]], cfg: Config, book: Book
) -> list[LegResult]:
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
    if cfg.polymarket_api_key and cfg.polymarket_api_secret and cfg.polymarket_api_passphrase:
        from py_clob_client.clob_types import ApiCreds
        client.set_api_creds(ApiCreds(
            api_key=cfg.polymarket_api_key,
            api_secret=cfg.polymarket_api_secret,
            api_passphrase=cfg.polymarket_api_passphrase,
        ))
    else:
        client.set_api_creds(client.create_or_derive_api_creds())

    per_leg_usd = cfg.max_position_usd / max(len(legs), 1)
    results: list[LegResult] = []

    for token_id, price in legs:
        size = round(per_leg_usd / max(price, 0.01), 4)
        try:
            order_args = OrderArgs(price=price, size=size, side=BUY, token_id=token_id)
            signed = client.create_order(order_args)
            resp = client.post_order(signed, OrderType.FOK)  # fill-or-kill
            filled_size = float(resp.get("takingAmount", 0.0)) if isinstance(resp, dict) else 0.0
            avg = float(resp.get("makingAmount", 0.0)) / filled_size if filled_size > 0 else price
            results.append(LegResult(token_id, size, filled_size, avg))
            if filled_size > 0:
                book.record_fill(token_id, filled_size, avg)
            trade_log.write("fill", token_id=token_id, req=size, got=filled_size, price=avg)
        except Exception as e:
            results.append(LegResult(token_id, size, 0.0, price, error=str(e)))
            trade_log.write("fill_error", token_id=token_id, err=str(e))
    return results


def _maybe_unwind(results: list[LegResult], cfg: Config, book: Book) -> None:
    """If any leg didn't fully fill, sell back the filled legs at market.

    Partial fill = directional exposure. Unwinding at a small loss is
    better than holding a one-sided basket.
    """
    if all(r.filled_fully for r in results):
        return

    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import SELL

    client = ClobClient(
        cfg.polymarket_host,
        key=cfg.polymarket_private_key,
        chain_id=137,
        signature_type=1,
        funder=cfg.polymarket_funder,
    )
    if cfg.polymarket_api_key and cfg.polymarket_api_secret and cfg.polymarket_api_passphrase:
        from py_clob_client.clob_types import ApiCreds
        client.set_api_creds(ApiCreds(
            api_key=cfg.polymarket_api_key,
            api_secret=cfg.polymarket_api_secret,
            api_passphrase=cfg.polymarket_api_passphrase,
        ))
    else:
        client.set_api_creds(client.create_or_derive_api_creds())

    for r in results:
        if r.filled_size <= 0:
            continue
        # Accept whatever the top bid is right now — we want out
        try:
            order_args = OrderArgs(
                price=max(r.avg_price - 0.02, 0.01),  # aggressive sell
                size=r.filled_size,
                side=SELL,
                token_id=r.token_id,
            )
            signed = client.create_order(order_args)
            resp = client.post_order(signed, OrderType.FOK)
            trade_log.write("unwind", token_id=r.token_id, size=r.filled_size, resp=str(resp))
            print(f"[UNWIND] token={r.token_id[:10]}... size={r.filled_size}")
        except Exception as e:
            trade_log.write("unwind_error", token_id=r.token_id, err=str(e))
            print(f"[UNWIND FAILED] token={r.token_id[:10]}... err={e}")
