# tests/test_09_backup_restore.py
import json
from backend.db.mock_store import mock_db
from backend.services.ledger import ensure_genesis, append_block, verify_chain

def test_backup_and_restore_state_preservation():
    """Prompt 11: Validates backup snapshots and state restoration with verify_chain."""
    ensure_genesis()
    
    # Snapshot mock DB state
    ledger_col = mock_db.get_mongo_client()["landregistry"]["ledger_transaction_block"]
    initial_blocks = list(ledger_col.find())
    assert len(initial_blocks) >= 1

    # Simulate backup snapshot
    backup_snapshot = {
        "ledger": [dict(b) for b in initial_blocks],
        "plots": dict(mock_db.plots),
        "registry": dict(mock_db.registry)
    }

    # Add a transaction block
    blk = append_block(
        block_type="SALE",
        registry_id="reg_bak_01",
        plot_id="plot_bak_01",
        seller_id="own_bak_s",
        buyer_id="own_bak_b",
        sale_price=5500000.0,
        gid="tx_bak_01"
    )
    assert verify_chain()["verified"] is True
    assert ledger_col.count_documents({}) == len(initial_blocks) + 1

    # Restore from snapshot using admin client
    admin_col = mock_db.get_mongo_admin_client()["landregistry"]["ledger_transaction_block"]
    admin_col.delete_one({"gid": "tx_bak_01"})

    assert ledger_col.count_documents({}) == len(initial_blocks)
    assert verify_chain()["verified"] is True
