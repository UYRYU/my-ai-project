"""Execution layer. Defaults to dry-run."""

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


@dataclass(frozen=True)
class ExecutionLeg:
    token_id: str
    limit_price: float
    size: float
    expected_price: float


def _size_for_leg(target_payout_usd: float) -> float:
    """Each outcome must use the same share count to preserve the hedge."""
    return round(target_payout_usd, 4)


def _build_execution_legs(
    opp: Opportunity,
    cfg: Config,
    quotes: list[FillQuote] | None,
) -> list[ExecutionLeg]:
    if quotes:
        target_size = _size_for_leg(min(q.filled_size for q in quotes))
        if target_size <= 0:
            raise ValueError("quotes must contain positive fill sizes")
        return [
            ExecutionLeg(
                token_id=q.token_id,
                limit_price=q.limit_price or q.avg_price,
                size=target_size,
                expected_price=q.avg_price,
            )
            for q in quotes
        ]

    target_size = _size_for_leg(cfg.max_position_usd)
    return [
        ExecutionLeg(token_id, price, target_size, price)
        for token_id, price in opp.legs
    ]


def execute(
    opp: Opportunity,
    cfg: Config,
    book: Book,
    quotes: list[FillQuote] | None = None,
) -> None:
    """Place equal-share orders for every outcome in an arbitrage basket."""
    legs = _build_execution_legs(opp, cfg, quotes)

    trade_log.write(
        "opportunity",
        kind=opp.kind,
        edge=opp.edge,
        question=opp.market.question,
        slug=opp.market.slug,
        legs=[{
            "token_id": leg.token_id,
            "size": leg.size,
            "limit_price": leg.limit_price,
            "expected_price": leg.expected_price,
        } for leg in legs],
        dry_run=cfg.dry_run,
    )

    if cfg.dry_run:
        _dry_run_fill(legs, book)
        return

    results = _live_place(legs, cfg, book)
    _maybe_unwind(results, cfg, book)


def _dry_run_fill(legs: list[ExecutionLeg], book: Book) -> None:
    basket_cost = sum(leg.expected_price * leg.size for leg in legs)
    print(f"[DRY] basket cost ~${basket_cost:.2f}")
    for leg in legs:
        print(
            f"  leg token={leg.token_id[:10]}... price={leg.expected_price:.4f} "
            f"size={leg.size}"
        )
        book.record_fill(leg.token_id, leg.size, leg.expected_price)


def _live_place(
    legs: list[ExecutionLeg], cfg: Config, book: Book
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

    results: list[LegResult] = []
    for leg in legs:
        try:
            order_args = OrderArgs(
                price=leg.limit_price,
                size=leg.size,
                side=BUY,
                token_id=leg.token_id,
            )
            signed = client.create_order(order_args)
            resp = client.post_order(signed, OrderType.FOK)
            filled_size = (
                float(resp.get("takingAmount", 0.0))
                if isinstance(resp, dict)
                else 0.0
            )
            avg = (
                float(resp.get("makingAmount", 0.0)) / filled_size
                if filled_size > 0
                else leg.expected_price
            )
            results.append(LegResult(leg.token_id, leg.size, filled_size, avg))
            if filled_size > 0:
                book.record_fill(leg.token_id, filled_size, avg)
            trade_log.write(
                "fill",
                token_id=leg.token_id,
                req=leg.size,
                got=filled_size,
                price=avg,
            )
        except Exception as e:
            results.append(
                LegResult(leg.token_id, leg.size, 0.0, leg.expected_price, error=str(e))
            )
            trade_log.write("fill_error", token_id=leg.token_id, err=str(e))
    return results


def _maybe_unwind(results: list[LegResult], cfg: Config, book: Book) -> None:
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
        try:
            order_args = OrderArgs(
                price=max(r.avg_price - 0.02, 0.01),
                size=r.filled_size,
                side=SELL,
                token_id=r.token_id,
            )
            signed = client.create_order(order_args)
            resp = client.post_order(signed, OrderType.FOK)
            trade_log.write(
                "unwind", token_id=r.token_id, size=r.filled_size, resp=str(resp)
            )
            print(f"[UNWIND] token={r.token_id[:10]}... size={r.filled_size}")
        except Exception as e:
            trade_log.write("unwind_error", token_id=r.token_id, err=str(e))
            print(f"[UNWIND FAILED] token={r.token_id[:10]}... err={e}")
