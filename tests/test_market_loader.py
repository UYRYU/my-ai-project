"""Tests for market_loader parsing against Gamma-shaped fixtures.

Fixtures mirror the real Gamma schema: outcomes/clobTokenIds/outcomePrices
are JSON-encoded strings (not native arrays), and markets are nested
under events.
"""

from __future__ import annotations

import json

import pytest

from bs_edge.market_loader import (
    _extract_reference_price,
    _extract_resolved_outcome,
    _match_tokens,
    _parse_market,
    _parse_string_array,
)


def _sample_market(**overrides):
    base = {
        "id": "mkt-1",
        "conditionId": "0xabc",
        "slug": "bitcoin-up-or-down-march-29-1am-et",
        "question": "Bitcoin Up or Down - March 29, 1AM ET",
        "description": "Will Bitcoin be up at 1AM ET on March 29?",
        "groupItemTitle": "Up at $68,712.80",
        "outcomes": json.dumps(["Up", "Down"]),
        "clobTokenIds": json.dumps(["tok_up", "tok_down"]),
        "outcomePrices": json.dumps(["0.6", "0.4"]),
        "startDate": "2025-03-28T20:00:00Z",
        "endDate": "2025-03-29T05:00:00Z",
        "closed": False,
        "active": True,
    }
    base.update(overrides)
    return base


def test_parse_string_array_handles_json_encoded_string():
    assert _parse_string_array('["Up","Down"]') == ["Up", "Down"]


def test_parse_string_array_handles_native_list():
    assert _parse_string_array(["a", "b"]) == ["a", "b"]


def test_parse_string_array_handles_none_and_garbage():
    assert _parse_string_array(None) == []
    assert _parse_string_array("not json") == []


def test_match_tokens_by_label():
    up, down = _match_tokens(["Up", "Down"], ["u", "d"])
    assert (up, down) == ("u", "d")
    up, down = _match_tokens(["Yes", "No"], ["u", "d"])
    assert (up, down) == ("u", "d")


def test_match_tokens_positional_fallback():
    up, down = _match_tokens(["Foo", "Bar"], ["u", "d"])
    assert (up, down) == ("u", "d")


def test_extract_reference_price_from_group_item_title():
    assert _extract_reference_price({"groupItemTitle": "Up at $68,712.80"}) == 68712.80


def test_extract_reference_price_ignores_plain_integers():
    # "7712" without $ or decimal should NOT be treated as a strike.
    assert _extract_reference_price({"description": "7712 traders signed up"}) is None


def test_extract_reference_price_from_threshold_field():
    assert _extract_reference_price({"groupItemThreshold": "68712.80"}) == 68712.80


def test_parse_market_happy_path():
    m = _parse_market(_sample_market())
    assert m is not None
    assert m.condition_id == "0xabc"
    assert m.up_token_id == "tok_up"
    assert m.down_token_id == "tok_down"
    assert m.reference_price == 68712.80
    assert m.open_ts < m.close_ts
    assert m.resolved is False


def test_parse_market_rejects_non_bitcoin():
    raw = _sample_market(question="ETH Up or Down", slug="eth-up-or-down")
    assert _parse_market(raw) is None


def test_parse_market_detects_resolution():
    raw = _sample_market(
        closed=True,
        umaResolutionStatus="resolved",
        outcomePrices=json.dumps(["1", "0"]),
    )
    m = _parse_market(raw)
    assert m is not None
    assert m.resolved is True
    assert m.resolved_outcome == "UP"


def test_parse_market_detects_down_resolution():
    raw = _sample_market(
        closed=True,
        umaResolutionStatus="resolved",
        outcomePrices=json.dumps(["0", "1"]),
    )
    m = _parse_market(raw)
    assert m is not None
    assert m.resolved_outcome == "DOWN"


def test_parse_market_unresolved_still_returns():
    raw = _sample_market(closed=False)
    m = _parse_market(raw)
    assert m is not None
    assert m.resolved is False
    assert m.resolved_outcome is None


def test_extract_resolved_outcome_ambiguous_returns_none():
    # Mid-market, both sides ~0.5 -- not a final resolution.
    assert _extract_resolved_outcome(["Up", "Down"], ["0.45", "0.55"]) is None


def test_parse_ts_handles_iso_with_and_without_z():
    from bs_edge.market_loader import _parse_ts

    ts_z = _parse_ts("2025-04-07T04:05:00Z")
    ts_plain = _parse_ts("2025-04-07T04:05:00+00:00")
    assert ts_z == ts_plain
