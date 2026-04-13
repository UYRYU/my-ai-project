"""Domain-agnostic arbitrage detection framework.

Core abstractions extracted from the Polymarket arbitrage detector
(arXiv:2508.03474). These patterns generalise to any domain where:

  1. A set of outcomes should satisfy a price/probability constraint
  2. Semantic relationships between instruments create cross-market constraints
  3. Resolution vectors define possible joint outcomes for portfolio analysis
"""
