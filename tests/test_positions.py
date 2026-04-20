from src.positions import Book


def test_record_and_settle_winner():
    book = Book()
    book.record_fill("t1", shares=10, price=0.30)
    pnl = book.settle("t1", payout_per_share=1.0)
    # cost 3.0, proceeds 10.0 → +7.0
    assert pnl == 7.0
    assert book.realized_pnl == 7.0


def test_settle_loser_returns_negative_cost():
    book = Book()
    book.record_fill("t1", shares=10, price=0.30)
    pnl = book.settle("t1", payout_per_share=0.0)
    assert pnl == -3.0


def test_full_basket_locks_in_edge():
    book = Book()
    book.record_fill("a", shares=10, price=0.45)  # 4.5
    book.record_fill("b", shares=10, price=0.50)  # 5.0
    # cost = 9.5; one will pay 10.0
    pnl_a = book.settle("a", payout_per_share=1.0)  # +5.5
    pnl_b = book.settle("b", payout_per_share=0.0)  # -5.0
    assert abs((pnl_a + pnl_b) - 0.5) < 1e-9


def test_gross_exposure_sums_cost_basis():
    book = Book()
    book.record_fill("a", 10, 0.40)
    book.record_fill("b", 10, 0.55)
    assert abs(book.gross_exposure_usd() - 9.5) < 1e-9
