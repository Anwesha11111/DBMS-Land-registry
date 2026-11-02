# tests/test_05_orderbook_and_matching.py
from backend.services.matching import attempt_match_for_plot
from backend.db.mock_store import mock_db
from backend.services.auth import generate_jwt

def test_no_match_when_bid_less_than_ask():
    """Prompt 5: No match when best Bid < Ask."""
    plot_id = "plot_match_low"
    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": "own_s",
        "legal_status": "Clear"
    }
    mock_db.order_book["ask_low"] = {
        "order_id": "ask_low",
        "plot_id": plot_id,
        "trader_id": "own_s",
        "order_type": "ASK",
        "price": 10000000.0,
        "order_timestamp": "2026-10-29T10:00:00Z",
        "status": "Open",
        "signature": "SIG"
    }
    mock_db.order_book["bid_low"] = {
        "order_id": "bid_low",
        "plot_id": plot_id,
        "trader_id": "own_b",
        "order_type": "BID",
        "price": 9000000.0,
        "order_timestamp": "2026-10-29T10:05:00Z",
        "status": "Open",
        "signature": "SIG"
    }

    match = attempt_match_for_plot(plot_id)
    assert match is None
    assert mock_db.order_book["ask_low"]["status"] == "Open"
    assert mock_db.order_book["bid_low"]["status"] == "Open"

def test_match_when_bid_equals_ask():
    """Prompt 5: Matches when Bid == Ask."""
    plot_id = "plot_match_eq"
    seller = "own_s_eq"
    buyer = "own_b_eq"

    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": seller,
        "legal_status": "Clear",
        "last_block_height": 0,
        "last_block_hash": "0" * 64
    }
    mock_db.wallets[buyer] = {"owner_id": buyer, "balance_available": 0.0, "balance_held": 8000000.0}
    mock_db.wallets[seller] = {"owner_id": seller, "balance_available": 0.0, "balance_held": 0.0}

    mock_db.order_book["ask_eq"] = {
        "order_id": "ask_eq",
        "plot_id": plot_id,
        "trader_id": seller,
        "order_type": "ASK",
        "price": 8000000.0,
        "order_timestamp": "2026-10-29T10:00:00Z",
        "status": "Open",
        "signature": "SIG_ASK"
    }
    mock_db.order_book["bid_eq"] = {
        "order_id": "bid_eq",
        "plot_id": plot_id,
        "trader_id": buyer,
        "order_type": "BID",
        "price": 8000000.0,
        "order_timestamp": "2026-10-29T10:02:00Z",
        "status": "Open",
        "signature": "SIG_BID"
    }

    match = attempt_match_for_plot(plot_id)
    assert match is not None
    assert match["matched"] is True
    assert match["trade_price"] == 8000000.0
    assert mock_db.registry[f"reg_{plot_id}"]["current_owner_id"] == buyer

def test_highest_bid_wins_and_earlier_bid_wins_ties():
    """Prompt 5: Highest bid wins; earlier bid wins ties (price-time priority)."""
    plot_id = "plot_priority"
    seller = "own_s_prio"

    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": seller,
        "legal_status": "Clear",
        "last_block_height": 0,
        "last_block_hash": "0" * 64
    }
    mock_db.wallets["b1"] = {"owner_id": "b1", "balance_available": 0.0, "balance_held": 10000000.0}
    mock_db.wallets["b2"] = {"owner_id": "b2", "balance_available": 0.0, "balance_held": 12000000.0}
    mock_db.wallets["b3"] = {"owner_id": "b3", "balance_available": 0.0, "balance_held": 12000000.0}
    mock_db.wallets[seller] = {"owner_id": seller, "balance_available": 0.0, "balance_held": 0.0}

    # Ask at 9,000,000
    mock_db.order_book["ask_prio"] = {
        "order_id": "ask_prio",
        "plot_id": plot_id,
        "trader_id": seller,
        "order_type": "ASK",
        "price": 9000000.0,
        "order_timestamp": "2026-10-29T10:00:00Z",
        "status": "Open",
        "signature": "SIG"
    }

    # Bid 1: 10,000,000 at 10:01
    mock_db.order_book["bid_1"] = {
        "order_id": "bid_1", "plot_id": plot_id, "trader_id": "b1",
        "order_type": "BID", "price": 10000000.0, "order_timestamp": "2026-10-29T10:01:00Z",
        "status": "Open", "signature": "SIG"
    }
    # Bid 2: 12,000,000 at 10:02 (Tied price with Bid 3, but earlier)
    mock_db.order_book["bid_2"] = {
        "order_id": "bid_2", "plot_id": plot_id, "trader_id": "b2",
        "order_type": "BID", "price": 12000000.0, "order_timestamp": "2026-10-29T10:02:00Z",
        "status": "Open", "signature": "SIG"
    }
    # Bid 3: 12,000,000 at 10:03 (Later than Bid 2)
    mock_db.order_book["bid_3"] = {
        "order_id": "bid_3", "plot_id": plot_id, "trader_id": "b3",
        "order_type": "BID", "price": 12000000.0, "order_timestamp": "2026-10-29T10:03:00Z",
        "status": "Open", "signature": "SIG"
    }

    match = attempt_match_for_plot(plot_id)
    assert match is not None
    # Bid 2 must win because it has highest price (12M) and earlier timestamp (10:02 < 10:03)
    assert mock_db.order_book["bid_2"]["status"] in ("Matched", "Settled")
    assert mock_db.order_book["bid_3"]["status"] == "Open"
    assert mock_db.order_book["bid_1"]["status"] == "Open"
    assert mock_db.registry[f"reg_{plot_id}"]["current_owner_id"] == "b2"

def test_insufficient_funds_rejected(client):
    """Prompt 5: Bids with insufficient available funds in wallet are rejected."""
    buyer_id = "own_poor"
    mock_db.owners[buyer_id] = {"owner_id": buyer_id, "public_key": "TEST_PUBKEY_POOR"}
    mock_db.wallets[buyer_id] = {"owner_id": buyer_id, "balance_available": 1000.0, "balance_held": 0.0}
    mock_db.plots["plot_blr_001"] = {"plot_id": "plot_blr_001", "city": "Bengaluru", "geojson": {}}
    mock_db.registry["reg_plot_blr_001"] = {
        "registry_id": "reg_plot_blr_001",
        "plot_id": "plot_blr_001",
        "current_owner_id": "own_rich_seller",
        "legal_status": "Clear"
    }
    token = generate_jwt("u_poor", "poor@rvce.edu", "buyer", owner_id=buyer_id)

    res = client.post("/orders", json={
        "plot_id": "plot_blr_001",
        "order_type": "BID",
        "price": 5000000.0,
        "signature": "SIG_POOR"
    }, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400
    assert "Insufficient" in res.get_json()["error"]
