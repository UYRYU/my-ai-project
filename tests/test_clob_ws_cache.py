from src.clob_ws import OrderbookCache


def test_cache_applies_snapshot():
    c = OrderbookCache()
    c.apply_snapshot("tok1", {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "100"}]})
    book = c.get("tok1")
    assert book is not None
    assert book["bids"][0]["price"] == "0.49"
    assert book["asks"][0]["price"] == "0.51"


def test_cache_applies_delta_update():
    c = OrderbookCache()
    c.apply_snapshot("tok1", {"asks": [{"price": "0.50", "size": "100"}]})
    c.apply_delta("tok1", [{"side": "ask", "price": "0.50", "size": "50"}])
    book = c.get("tok1")
    assert book["asks"][0]["size"] == "50"


def test_cache_delta_removes_level_on_zero_size():
    c = OrderbookCache()
    c.apply_snapshot("tok1", {"asks": [{"price": "0.50", "size": "100"}]})
    c.apply_delta("tok1", [{"side": "ask", "price": "0.50", "size": "0"}])
    book = c.get("tok1")
    assert book["asks"] == []


def test_cache_miss_returns_none():
    c = OrderbookCache()
    assert c.get("nonexistent") is None
