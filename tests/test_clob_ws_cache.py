from src.clob_ws import CLOBWebSocket, OrderbookCache, subscription_message


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


def test_subscription_uses_documented_market_channel_type():
    assert subscription_message(["tok1", "tok2"]) == {
        "type": "market",
        "assets_ids": ["tok1", "tok2"],
    }


def test_current_price_change_payload_updates_each_asset():
    c = OrderbookCache()
    ws = CLOBWebSocket(c)
    ws._handle({
        "event_type": "book",
        "asset_id": "tok1",
        "bids": [{"price": "0.49", "size": "100"}],
        "asks": [{"price": "0.51", "size": "100"}],
    })
    ws._handle({
        "event_type": "price_change",
        "market": "condition-id",
        "price_changes": [{
            "asset_id": "tok1",
            "price": "0.50",
            "size": "25",
            "side": "SELL",
        }],
    })
    book = c.get("tok1")
    assert book is not None
    assert book["asks"][0] == {"price": "0.50", "size": "25"}
    assert c.get("condition-id") is None


def test_stale_book_is_not_tradeable():
    c = OrderbookCache()
    c.apply_snapshot("tok1", {"asks": [{"price": "0.50", "size": "100"}]})
    c._books["tok1"].updated_at = 0
    assert c.get("tok1", max_age_seconds=5.0) is None
