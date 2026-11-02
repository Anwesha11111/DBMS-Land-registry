# tests/test_07_settlement_2pc.py
import os
import pytest
from backend.services.settlement import (
    settle_trade_2pc,
    recover_in_doubt_transactions,
    FaultInjectionException
)
from backend.db.mock_store import mock_db

def test_2pc_happy_path():
    """Prompt 7: 2PC happy path - funds transferred, owner changed, ledger block sealed."""
    plot_id = "plot_2pc_happy"
    seller_id = "own_s_2pc"
    buyer_id = "own_b_2pc"
    price = 6500000.0

    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": seller_id,
        "legal_status": "Clear",
        "last_block_height": 0,
        "last_block_hash": "0" * 64
    }
    mock_db.wallets[buyer_id] = {"owner_id": buyer_id, "balance_available": 1000000.0, "balance_held": price}
    mock_db.wallets[seller_id] = {"owner_id": seller_id, "balance_available": 2000000.0, "balance_held": 0.0}

    res = settle_trade_2pc(
        trade_id="trd_happy_01",
        buyer_id=buyer_id,
        seller_id=seller_id,
        plot_id=plot_id,
        price=price,
        bid_order_id="bid_happy",
        ask_order_id="ask_happy"
    )

    assert res["status"] == "Settled"
    assert mock_db.registry[f"reg_{plot_id}"]["current_owner_id"] == buyer_id
    assert mock_db.wallets[buyer_id]["balance_held"] == 0.0
    assert mock_db.wallets[seller_id]["balance_available"] == 2000000.0 + price

def test_2pc_seal_failure_rolls_back_everything():
    """Prompt 7: When Mongo block seal fails, transaction rolls back cleanly without state change."""
    plot_id = "plot_fail_seal"
    seller_id = "s_fail"
    buyer_id = "b_fail"
    price = 4000000.0

    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": seller_id,
        "legal_status": "Clear",
        "last_block_height": 0,
        "last_block_hash": "0" * 64
    }
    mock_db.wallets[buyer_id] = {"owner_id": buyer_id, "balance_available": 0.0, "balance_held": price}
    mock_db.wallets[seller_id] = {"owner_id": seller_id, "balance_available": 1000000.0, "balance_held": 0.0}

    # Enable fault injection
    os.environ["FAULT_FAIL_SEAL"] = "true"
    try:
        res = settle_trade_2pc(
            trade_id="trd_fail_seal",
            buyer_id=buyer_id,
            seller_id=seller_id,
            plot_id=plot_id,
            price=price,
            bid_order_id="bid_f",
            ask_order_id="ask_f"
        )
        assert res["status"] == "Failed"
        assert "seal failed" in res["error"].lower()

        # Confirm rollback: seller is still owner and funds were not debited
        assert mock_db.registry[f"reg_{plot_id}"]["current_owner_id"] == seller_id
        assert mock_db.wallets[buyer_id]["balance_held"] == price
        assert mock_db.wallets[seller_id]["balance_available"] == 1000000.0
    finally:
        os.environ["FAULT_FAIL_SEAL"] = "false"

def test_crash_after_seal_recovery_commits():
    """Prompt 7: Crash after MongoDB seal -> recovery job finds ledger block and commits."""
    gid = "tx_crash_after_seal"
    plot_id = "plot_crash_seal"

    mock_db.prepared_xacts[gid] = {
        "gid": gid,
        "plot_id": plot_id,
        "buyer_id": "b_rec",
        "seller_id": "s_rec"
    }

    # Seed block into MongoDB for this gid
    col = mock_db.get_mongo_client()["landregistry"]["ledger_transaction_block"]
    col.insert_one({
        "block_number": 998,
        "prev_tx_hash": "a" * 64,
        "block_type": "SALE",
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "seller_id": "s_rec",
        "buyer_id": "b_rec",
        "sale_price": 5000000.0,
        "timestamp": "2026-10-29T10:00:00Z",
        "merkle_root": "0" * 64,
        "nonce": 0,
        "tx_id": "b" * 64,
        "gid": gid
    })

    rec = recover_in_doubt_transactions()
    assert gid in rec["committed_gids"]
    assert gid not in mock_db.prepared_xacts

    # Clean up test block with admin client so it does not affect verify_chain in later tests
    mock_db.get_mongo_admin_client()["landregistry"]["ledger_transaction_block"].delete_one({"gid": gid})

def test_crash_after_prepare_recovery_rolls_back():
    """Prompt 7: Crash after Postgres prepare (before seal) -> recovery job sees missing block and rolls back."""
    gid = "tx_crash_after_prep"
    mock_db.prepared_xacts[gid] = {
        "gid": gid,
        "plot_id": "plot_unsealed"
    }

    rec = recover_in_doubt_transactions()
    assert gid in rec["rolled_back_gids"]
    assert gid not in mock_db.prepared_xacts
