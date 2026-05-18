from src.event_grouper import event_key, group_by_event
from src.polymarket import Market, MarketOutcome


def _m(slug: str, end: str = "2026-04-19T23:00:00Z") -> Market:
    return Market("c", "Q?", slug, end, "sports",
                  (MarketOutcome("t0", "Yes", 0.5, 0.5), MarketOutcome("t1", "No", 0.5, 0.5)))


def test_event_key_pairs_teams_orderless():
    a = _m("nba-lakers-vs-celtics-2026-04-19")
    b = _m("nba-celtics-vs-lakers-2026-04-19")
    assert event_key(a) == event_key(b)


def test_event_key_includes_date():
    a = _m("nba-lakers-vs-celtics-2026-04-19")
    b = _m("nba-lakers-vs-celtics-2026-04-20")
    assert event_key(a) != event_key(b)


def test_event_key_none_for_non_game_market():
    assert event_key(_m("will-bitcoin-hit-100k-by-april")) is None


def test_group_by_event_drops_singletons():
    markets = [
        _m("nba-lakers-vs-celtics-2026-04-19-moneyline"),
        _m("nba-lakers-vs-celtics-2026-04-19-spread-5"),
        _m("nba-warriors-vs-suns-2026-04-19-moneyline"),  # only one — dropped
    ]
    groups = group_by_event(markets)
    assert len(groups) == 1
    assert "celtics-vs-lakers" in next(iter(groups))
