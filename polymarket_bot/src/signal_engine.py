"""Signal detection engine for mispricing and arbitrage opportunities."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Optional

from .config import Config
from .models import Market, SignalResult, TradeAction

logger = logging.getLogger("polymarket_bot")


class PriceHistory:
    """Tracks price history for momentum calculation."""

    def __init__(self, window_sec: int = 60) -> None:
        self.window_sec = window_sec
        # token_id -> deque of (timestamp, price)
        self._history: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=1000)
        )

    def record(self, token_id: str, price: float) -> None:
        self._history[token_id].append((time.time(), price))

    def get_change_rate(self, token_id: str) -> Optional[float]:
        """Return price change rate over the window. None if insufficient data."""
        history = self._history.get(token_id)
        if not history or len(history) < 2:
            return None

        now = time.time()
        cutoff = now - self.window_sec

        # Find oldest price within window
        oldest_price = None
        for ts, price in history:
            if ts >= cutoff:
                oldest_price = price
                break

        if oldest_price is None or oldest_price == 0:
            return None

        latest_price = history[-1][1]
        return (latest_price - oldest_price) / oldest_price

    def cleanup(self) -> None:
        """Remove entries older than the window."""
        now = time.time()
        cutoff = now - self.window_sec * 2  # Keep 2x window for safety
        for token_id in list(self._history.keys()):
            q = self._history[token_id]
            while q and q[0][0] < cutoff:
                q.popleft()


class SignalEngine:
    """Compute signals for each market and produce confidence scores."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.price_history = PriceHistory(window_sec=config.momentum_window_sec)

    def record_price(self, token_id: str, price: float) -> None:
        """Record a price tick for momentum tracking."""
        self.price_history.record(token_id, price)

    def evaluate(self, market: Market) -> Optional[SignalResult]:
        """Evaluate a market and return a SignalResult if it passes filters."""
        yes = market.yes_token
        no = market.no_token
        if not yes or not no:
            return None

        yes_book = yes.order_book
        no_book = no.order_book

        # Need valid order books
        if yes_book.best_ask is None or no_book.best_ask is None:
            return None
        if yes_book.best_bid is None or no_book.best_bid is None:
            return None

        # 1. Mispricing score
        mispricing = self._calc_mispricing(
            yes_book.best_bid, yes_book.best_ask,
            no_book.best_bid, no_book.best_ask,
        )

        # 2. Spread score (0=wide/bad, 1=tight/good)
        spread = self._calc_spread_score(
            yes_book.spread, no_book.spread
        )
        if spread is None:
            return None

        # Filter: spread too wide
        yes_spread = yes_book.spread or 0
        no_spread = no_book.spread or 0
        if yes_spread > self.config.spread_max or no_spread > self.config.spread_max:
            logger.debug("Market %s excluded: spread too wide (yes=%.4f, no=%.4f)",
                         market.condition_id[:8], yes_spread, no_spread)
            return None

        # 3. Liquidity score
        liquidity = self._calc_liquidity_score(
            yes_book.best_bid_size, yes_book.best_ask_size,
            no_book.best_bid_size, no_book.best_ask_size,
        )

        # Filter: liquidity too thin
        min_size = min(
            yes_book.best_bid_size, yes_book.best_ask_size,
            no_book.best_bid_size, no_book.best_ask_size,
        )
        if min_size < self.config.liquidity_min_size:
            logger.debug("Market %s excluded: liquidity too thin (min=%.2f)",
                         market.condition_id[:8], min_size)
            return None

        # 4. Momentum filter
        momentum, momentum_label = self._calc_momentum(yes.token_id, no.token_id)

        # 5. Confidence score (0-100)
        confidence = self._calc_confidence(mispricing, spread, liquidity, momentum)

        # Determine recommended action and edge
        action, edge, reason = self._determine_action(
            market, mispricing, confidence
        )

        result = SignalResult(
            market=market,
            mispricing_score=mispricing,
            spread_score=spread,
            liquidity_score=liquidity,
            momentum_score=momentum,
            momentum_label=momentum_label,
            confidence_score=confidence,
            recommended_action=action,
            expected_edge=edge,
            reason=reason,
        )

        if confidence >= self.config.confidence_threshold:
            logger.info(
                "SIGNAL: %s | confidence=%.1f | mispricing=%.4f | action=%s | edge=%.4f",
                market.question[:60],
                confidence,
                mispricing,
                action.value if action else "NONE",
                edge,
            )

        return result

    def _calc_mispricing(
        self,
        yes_bid: float, yes_ask: float,
        no_bid: float, no_ask: float,
    ) -> float:
        """Calculate mispricing score.

        In a fair binary market, yes_ask + no_ask should equal ~1.0
        and yes_bid + no_bid should equal ~1.0.
        Deviation from 1.0 indicates mispricing opportunity.
        """
        ask_sum = yes_ask + no_ask
        bid_sum = yes_bid + no_bid

        # Overround: ask_sum > 1.0 means market maker edge
        # Underround: ask_sum < 1.0 means arb opportunity
        ask_deviation = abs(1.0 - ask_sum)
        bid_deviation = abs(1.0 - bid_sum)

        # Score is the max deviation (higher = more mispriced)
        return max(ask_deviation, bid_deviation)

    def _calc_spread_score(
        self,
        yes_spread: Optional[float],
        no_spread: Optional[float],
    ) -> Optional[float]:
        """Calculate spread score (0=wide, 1=tight)."""
        if yes_spread is None or no_spread is None:
            return None

        max_spread = self.config.spread_max
        avg_spread = (yes_spread + no_spread) / 2

        # Normalize: 0 spread = score 1.0, max_spread = score 0.0
        score = max(0.0, 1.0 - (avg_spread / max_spread)) if max_spread > 0 else 0.0
        return score

    def _calc_liquidity_score(
        self,
        yes_bid_size: float, yes_ask_size: float,
        no_bid_size: float, no_ask_size: float,
    ) -> float:
        """Calculate liquidity score (0=thin, 1=deep)."""
        min_size = min(yes_bid_size, yes_ask_size, no_bid_size, no_ask_size)
        target = self.config.liquidity_min_size * 5  # 5x minimum = perfect score

        score = min(1.0, min_size / target) if target > 0 else 0.0
        return score

    def _calc_momentum(
        self, yes_token_id: str, no_token_id: str
    ) -> tuple[float, str]:
        """Calculate momentum score and label.

        Returns (score 0-1, label).
        Score near 1.0 = stable, near 0.0 = high volatility.
        """
        yes_change = self.price_history.get_change_rate(yes_token_id)
        no_change = self.price_history.get_change_rate(no_token_id)

        if yes_change is None and no_change is None:
            return 0.5, "unknown"  # Neutral if no data

        max_change = max(abs(yes_change or 0), abs(no_change or 0))
        threshold = self.config.momentum_max_change

        if max_change > threshold:
            score = max(0.0, 1.0 - (max_change / threshold))
            return score, "volatile"
        else:
            score = 1.0 - (max_change / threshold) if threshold > 0 else 1.0
            return score, "normal"

    def _calc_confidence(
        self,
        mispricing: float,
        spread: float,
        liquidity: float,
        momentum: float,
    ) -> float:
        """Weighted combination of all scores, scaled to 0-100."""
        cfg = self.config

        # Normalize mispricing: higher deviation = higher score
        # Scale so that threshold = 50 points contribution
        mispricing_norm = min(1.0, mispricing / (cfg.mispricing_threshold * 2))

        raw = (
            cfg.weight_mispricing * mispricing_norm
            + cfg.weight_spread * spread
            + cfg.weight_liquidity * liquidity
            + cfg.weight_momentum * momentum
        )

        return round(raw * 100, 2)

    def _determine_action(
        self,
        market: Market,
        mispricing: float,
        confidence: float,
    ) -> tuple[Optional[TradeAction], float, str]:
        """Determine the recommended trade action."""
        yes = market.yes_token
        no = market.no_token
        if not yes or not no:
            return None, 0.0, "Missing tokens"

        yes_ask = yes.order_book.best_ask or 0
        no_ask = no.order_book.best_ask or 0
        ask_sum = yes_ask + no_ask

        if confidence < self.config.confidence_threshold:
            return None, 0.0, f"Confidence {confidence:.1f} below threshold"

        # If ask_sum < 1.0, we can buy both sides for < $1 and guarantee $1 payout
        if ask_sum < 1.0:
            edge = 1.0 - ask_sum
            # Buy the cheaper side
            if yes_ask <= no_ask:
                return TradeAction.BUY_YES, edge, f"Arb: ask_sum={ask_sum:.4f} < 1.0, buy YES at {yes_ask:.4f}"
            else:
                return TradeAction.BUY_NO, edge, f"Arb: ask_sum={ask_sum:.4f} < 1.0, buy NO at {no_ask:.4f}"

        # If one side looks underpriced relative to deviation
        if mispricing > self.config.mispricing_threshold:
            if yes_ask < no_ask:
                edge = mispricing / 2
                return TradeAction.BUY_YES, edge, f"Mispricing: YES underpriced (ask={yes_ask:.4f})"
            else:
                edge = mispricing / 2
                return TradeAction.BUY_NO, edge, f"Mispricing: NO underpriced (ask={no_ask:.4f})"

        return None, 0.0, "No clear opportunity"
