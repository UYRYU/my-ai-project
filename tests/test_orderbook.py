from src.orderbook import average_fill_cost


def test_vwap_walks_levels():
    book = {
        "asks": [
            {"price": "0.50", "size": "10"},
            {"price": "0.52", "size": "10"},
            {"price": "0.55", "size": "100"},
        ]
    }
    q = average_fill_cost(book, "asks", target_size=15)
    assert q is not None
    # 10@0.50 + 5@0.52 = 5.0 + 2.6 = 7.6 over 15 = 0.5067
    assert abs(q.avg_price - (7.6 / 15)) < 1e-9
    assert q.levels_used == 2
    assert q.limit_price == 0.52


def test_returns_none_when_insufficient_depth():
    book = {"asks": [{"price": "0.5", "size": "1"}]}
    assert average_fill_cost(book, "asks", target_size=10) is None


def test_returns_none_on_empty_book():
    assert average_fill_cost({"asks": []}, "asks", target_size=1) is None
    assert average_fill_cost({}, "asks", target_size=1) is None
