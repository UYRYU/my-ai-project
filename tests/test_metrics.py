from src.metrics import Metrics


def test_counter_increments():
    m = Metrics()
    m.inc("requests")
    m.inc("requests", by=3)
    assert "bot_requests 4" in m.render()


def test_gauge_replaces():
    m = Metrics()
    m.set("pnl_usd", 10.0)
    m.set("pnl_usd", 25.5)
    assert "bot_pnl_usd 25.5" in m.render()


def test_render_includes_uptime():
    m = Metrics()
    out = m.render()
    assert "uptime=" in out


def test_render_sorted_keys():
    m = Metrics()
    m.inc("z_last")
    m.inc("a_first")
    out = m.render()
    assert out.index("bot_a_first") < out.index("bot_z_last")
