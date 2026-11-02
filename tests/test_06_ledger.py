# tests/test_06_ledger.py
import pytest
from backend.services.ledger import (
    ensure_genesis,
    append_block,
    verify_chain,
    append_correction,
    get_ledger_collection
)
from backend.db.mock_store import mock_db

def test_five_block_chain_and_verify_pass():
    """Prompt 6: Build a 5-block chain and verify pass."""
    ensure_genesis()
    for i in range(1, 5):
        append_block(
            block_type="SALE",
            registry_id=f"reg_test_{i}",
            plot_id=f"plot_test_{i}",
            seller_id=f"seller_{i}",
            buyer_id=f"buyer_{i}",
            sale_price=5000000.0 + (i * 100000.0)
        )

    res = verify_chain()
    assert res["verified"] is True
    assert res["blocks_checked"] >= 5
    assert res["first_bad_block"] is None

def test_tamper_detected_and_exact_block_reported():
    """Prompt 6: Tamper with one field via admin Mongo connection and verify exact block is reported."""
    ensure_genesis()
    col = mock_db.get_mongo_admin_client()["landregistry"]["ledger_transaction_block"]
    target = col.find_one({"block_number": 2})
    assert target is not None

    orig_price = target.get("sale_price")
    # Tamper with block #2 price
    col.update_one({"block_number": 2}, {"$set": {"sale_price": 99999999.0}})

    res = verify_chain()
    assert res["verified"] is False
    assert res["first_bad_block"] == 2
    assert "Tampered block content" in res["error"]

    # Restore original price
    col.update_one({"block_number": 2}, {"$set": {"sale_price": orig_price}})
    assert verify_chain()["verified"] is True

def test_fork_attempt_rejected():
    """Prompt 6: Fork attempt (duplicate block_number or duplicate prev_tx_hash) is rejected."""
    ensure_genesis()
    col = get_ledger_collection()
    tip = col.find_one(sort=[("block_number", -1)])

    # Attempt to insert competing block with same block_number
    duplicate_block = {
        "block_number": tip["block_number"],
        "prev_tx_hash": tip["prev_tx_hash"],
        "block_type": "SALE",
        "registry_id": "reg_fork",
        "plot_id": "plot_fork",
        "seller_id": "s_fork",
        "buyer_id": "b_fork",
        "sale_price": 1000.0,
        "timestamp": "2026-10-29T12:00:00Z",
        "merkle_root": "0" * 64,
        "nonce": 0,
        "tx_id": "a" * 64
    }

    with pytest.raises(Exception) as exc:
        col.insert_one(duplicate_block)
    assert "duplicate key error" in str(exc.value).lower()

def test_self_approved_correction_rejected():
    """Prompt 6: Correction requested and approved by the same user is rejected."""
    with pytest.raises(ValueError) as exc:
        append_correction(
            original_tx_id="dummy_tx_id",
            plot_id="plot_01",
            registry_id="reg_01",
            new_data={"sale_price": 6000000.0},
            requested_by="admin_alice",
            approved_by="admin_alice"
        )
    assert "Dual approval violation" in str(exc.value)
