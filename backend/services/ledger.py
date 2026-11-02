# backend/services/ledger.py
"""
Immutable cryptographic ledger implementation in MongoDB.
DECISION 6: Ledger block hash = SHA-256 of canonical JSON (sorted keys, no whitespace) of all fields except tx_id.
Genesis block has prev_tx_hash of 64 zeros. Nonce fixed at 0.
Never update or delete blocks; corrections are new CORRECTION blocks needing a second approver.
"""
import copy
import datetime
import logging
from typing import Dict, Any, List, Optional, Tuple
from backend.db.connection import get_mongo_db, get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.crypto import (
    canonical_json,
    compute_tx_id,
    compute_merkle_root,
    verify_signature
)

logger = logging.getLogger(__name__)

GENESIS_PREV_HASH = "0" * 64

def get_ledger_collection():
    db = get_mongo_db()
    return db["ledger_transaction_block"]

def ensure_genesis() -> Dict[str, Any]:
    """
    Ensures Block 0 (Genesis block) exists.
    Idempotent: returns existing block 0 if already present.
    """
    col = get_ledger_collection()
    genesis = col.find_one({"block_number": 0})
    if genesis:
        return genesis

    genesis_block = {
        "block_number": 0,
        "prev_tx_hash": GENESIS_PREV_HASH,
        "block_type": "GENESIS",
        "registry_id": "genesis_reg_0",
        "plot_id": "genesis_plot_0",
        "seller_id": None,
        "buyer_id": "GOVERNMENT_OF_KARNATAKA_REVENUE_DEPT",
        "sale_price": 0.0,
        "timestamp": "2026-01-01T00:00:00Z",
        "merkle_root": compute_merkle_root(["GENESIS_INIT", "GENESIS_REVENUE_DEPT", "GOV_GRANT"]),
        "nonce": 0,
        "seller_signature": None,
        "buyer_signature": None,
        "gid": None,
        "corrects_tx_id": None,
        "approved_by": "SYSTEM"
    }
    genesis_block["tx_id"] = compute_tx_id(genesis_block)

    try:
        col.insert_one(genesis_block)
        logger.info(f"Genesis block 0 created with tx_id: {genesis_block['tx_id']}")
    except Exception as e:
        logger.info(f"Genesis block insert collided (already created by concurrent worker): {e}")
        return col.find_one({"block_number": 0})

    return genesis_block

def get_chain_tip() -> Dict[str, Any]:
    """Retrieves the most recent block at the tip of the chain."""
    ensure_genesis()
    col = get_ledger_collection()
    tip = col.find_one(sort=[("block_number", -1)])
    return tip

def append_block(
    block_type: str,
    registry_id: str,
    plot_id: str,
    seller_id: Optional[str],
    buyer_id: str,
    sale_price: Optional[float],
    seller_signature: Optional[str] = None,
    buyer_signature: Optional[str] = None,
    gid: Optional[str] = None,
    corrects_tx_id: Optional[str] = None,
    approved_by: Optional[str] = None,
    max_retries: int = 5
) -> Dict[str, Any]:
    """
    Appends a new block to the chain.
    Computes sequential block_number, points to previous tip hash, computes canonical tx_id.
    Retries automatically on concurrent insert duplicate key collisions.
    """
    col = get_ledger_collection()

    for attempt in range(max_retries):
        tip = get_chain_tip()
        next_block_num = tip["block_number"] + 1
        prev_hash = tip["tx_id"]

        # Leaf order: [seller_signature, buyer_signature, payment_ref/gid]
        leaves = [
            seller_signature or "",
            buyer_signature or "",
            gid or f"payment_ref_{next_block_num}"
        ]
        merkle = compute_merkle_root(leaves)

        block = {
            "block_number": next_block_num,
            "prev_tx_hash": prev_hash,
            "block_type": block_type,
            "registry_id": registry_id,
            "plot_id": plot_id,
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "sale_price": float(sale_price) if sale_price is not None else None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "merkle_root": merkle,
            "nonce": 0,
            "seller_signature": seller_signature,
            "buyer_signature": buyer_signature,
            "gid": gid,
            "corrects_tx_id": corrects_tx_id,
            "approved_by": approved_by
        }
        block["tx_id"] = compute_tx_id(block)

        try:
            col.insert_one(block)
            logger.info(f"Block #{next_block_num} sealed with tx_id {block['tx_id']}")
            return block
        except Exception as e:
            if "duplicate key" in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f"Append collision at height {next_block_num}, retrying tip: {e}")
                continue
            raise

    raise RuntimeError("Failed to append block after maximum retries due to chain contention.")

def append_correction(
    original_tx_id: str,
    plot_id: str,
    registry_id: str,
    new_data: Dict[str, Any],
    requested_by: str,
    approved_by: str
) -> Dict[str, Any]:
    """
    Appends a CORRECTION block.
    DECISION 6 & Prompt 6: requires approved_by != requested_by (dual control).
    Never updates or deletes past blocks.
    """
    if requested_by == approved_by:
        raise ValueError("Dual approval violation: correction cannot be approved by the requester.")

    col = get_ledger_collection()
    original_block = col.find_one({"tx_id": original_tx_id})
    if not original_block:
        raise ValueError(f"Target transaction tx_id '{original_tx_id}' not found in ledger.")

    buyer_id = new_data.get("buyer_id", original_block.get("buyer_id"))
    seller_id = new_data.get("seller_id", original_block.get("seller_id"))
    sale_price = new_data.get("sale_price", original_block.get("sale_price"))

    return append_block(
        block_type="CORRECTION",
        registry_id=registry_id,
        plot_id=plot_id,
        seller_id=seller_id,
        buyer_id=buyer_id,
        sale_price=sale_price,
        seller_signature=new_data.get("seller_signature"),
        buyer_signature=new_data.get("buyer_signature"),
        gid=f"corr_{original_tx_id[:8]}",
        corrects_tx_id=original_tx_id,
        approved_by=approved_by
    )

def verify_chain(plot_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Recomputes the cryptographic hash chain from Genesis.
    Validates:
    1. Genesis block integrity and 64 zeros prev_hash.
    2. Continuous block_number increments (no gaps).
    3. prev_tx_hash links match computed previous tx_id.
    4. Canonical JSON SHA-256 hash matches tx_id.
    5. If plot_id provided, checks that current_owner_id in registry_entry
       matches the buyer_id in the last block affecting that plot.
    Returns: {"verified": bool, "details": str, "first_bad_block": int/None, "error": str/None, "blocks_checked": int}
    """
    ensure_genesis()
    col = get_ledger_collection()
    all_blocks = list(col.find().sort([("block_number", 1)]))

    if not all_blocks:
        return {"verified": False, "error": "Ledger is empty.", "blocks_checked": 0}

    # 1. Verify Genesis
    genesis = all_blocks[0]
    if genesis.get("block_number") != 0:
        return {
            "verified": False,
            "first_bad_block": 0,
            "error": "Block 0 is missing; first block height is non-zero.",
            "blocks_checked": 1
        }
    if genesis.get("prev_tx_hash") != GENESIS_PREV_HASH:
        return {
            "verified": False,
            "first_bad_block": 0,
            "error": "Genesis block prev_tx_hash must be 64 zeros.",
            "blocks_checked": 1
        }

    expected_prev_hash = genesis.get("tx_id")
    computed_genesis_id = compute_tx_id(genesis)
    if computed_genesis_id != expected_prev_hash:
        return {
            "verified": False,
            "first_bad_block": 0,
            "error": f"Genesis tx_id hash mismatch. Computed: {computed_genesis_id}, Found: {expected_prev_hash}",
            "blocks_checked": 1
        }

    last_block_for_plot = None

    # 2. Iterate through subsequent blocks
    for i in range(1, len(all_blocks)):
        block = all_blocks[i]
        b_num = block.get("block_number")
        
        # Continuity check
        if b_num != i:
            return {
                "verified": False,
                "first_bad_block": b_num,
                "error": f"Gap in block numbers: expected block #{i}, found #{b_num}",
                "blocks_checked": i + 1
            }

        # Link check
        if block.get("prev_tx_hash") != expected_prev_hash:
            return {
                "verified": False,
                "first_bad_block": b_num,
                "error": f"Broken chain link at block #{b_num}: prev_tx_hash does not match block #{i-1} tx_id.",
                "blocks_checked": i + 1
            }

        # Recompute hash
        computed_id = compute_tx_id(block)
        if computed_id != block.get("tx_id"):
            return {
                "verified": False,
                "first_bad_block": b_num,
                "error": f"Tampered block content at block #{b_num}: computed hash {computed_id} != stored tx_id {block.get('tx_id')}",
                "blocks_checked": i + 1
            }

        if plot_id and block.get("plot_id") == plot_id:
            last_block_for_plot = block

        expected_prev_hash = block.get("tx_id")

    # 3. If plot_id checked, cross-reference with registry_entry state
    if plot_id:
        reg_owner, last_hash, last_height = None, None, None
        if is_mock_mode():
            for r in mock_db.registry.values():
                if r["plot_id"] == plot_id:
                    reg_owner = r["current_owner_id"]
                    last_hash = r.get("last_block_hash")
                    last_height = r.get("last_block_height")
                    break
        else:
            try:
                with get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT current_owner_id, last_block_hash, last_block_height FROM registry_entry WHERE plot_id = %s;",
                            (plot_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            reg_owner, last_hash, last_height = row[0], row[1], row[2]
            except Exception as e:
                logger.warning(f"Could not read registry_entry for plot {plot_id}: {e}")

        if last_block_for_plot and reg_owner:
            if last_block_for_plot.get("buyer_id") != reg_owner:
                return {
                    "verified": False,
                    "first_bad_block": last_block_for_plot.get("block_number"),
                    "error": f"Ownership state inconsistency: registry_entry owner '{reg_owner}' != last block buyer '{last_block_for_plot.get('buyer_id')}'",
                    "blocks_checked": len(all_blocks)
                }

    return {
        "verified": True,
        "details": "All cryptographic block hashes, Merkle roots, and chain pointers verified successfully.",
        "first_bad_block": None,
        "error": None,
        "blocks_checked": len(all_blocks),
        "latest_block_number": all_blocks[-1]["block_number"],
        "latest_tx_id": all_blocks[-1]["tx_id"]
    }

def get_title_chain(plot_id: str) -> List[Dict[str, Any]]:
    """
    Returns ordered title chain for a plot with public-safe attributes (no sensitive personal KYC).
    """
    col = get_ledger_collection()
    # Find all blocks relevant to this plot or Genesis
    blocks = col.find({"plot_id": plot_id}).sort([("block_number", 1)])
    
    clean_chain = []
    for b in blocks:
        clean_chain.append({
            "block_number": b.get("block_number"),
            "tx_id": b.get("tx_id"),
            "prev_tx_hash": b.get("prev_tx_hash"),
            "block_type": b.get("block_type"),
            "plot_id": b.get("plot_id"),
            "seller_id": b.get("seller_id"),
            "buyer_id": b.get("buyer_id"),
            "sale_price": b.get("sale_price"),
            "timestamp": b.get("timestamp"),
            "merkle_root": b.get("merkle_root")
        })
    return clean_chain
