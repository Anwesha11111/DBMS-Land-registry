# backend/services/settlement.py
"""
Two-Phase Commit (2PC) Settlement Service.
Coordinates Delivery-versus-Payment (DvP) between PostgreSQL/PostGIS (Phase 1 prepare)
and MongoDB cryptographic ledger (Seal), concluding with Phase 2 (Commit/Rollback).
Includes fault-injection hooks for failure mode verification and automated crash recovery.
"""
import os
import uuid
import logging
from typing import Dict, Any, Optional
from backend.db.connection import get_pg_connection, get_mongo_db, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.ledger import append_block
from backend.services.audit import log_audit_event

logger = logging.getLogger(__name__)

class FaultInjectionException(Exception):
    pass

def log_coordinator_phase(gid: str, trade_id: str, phase: str, decision: str):
    """Logs phase and decision in tx_coordinator_log using an independent autocommit connection."""
    if is_mock_mode():
        mock_db.coordinator_logs[gid] = {
            "gid": gid,
            "trade_id": trade_id,
            "phase": phase,
            "decision": decision
        }
        return

    try:
        with get_pg_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tx_coordinator_log (gid, trade_id, phase, decision, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (gid) DO UPDATE
                    SET phase = EXCLUDED.phase, decision = EXCLUDED.decision, updated_at = CURRENT_TIMESTAMP;
                    """,
                    (gid, trade_id, phase, decision)
                )
    except Exception as e:
        logger.error(f"Failed to record coordinator log for {gid}: {e}")

def settle_trade_2pc(
    trade_id: str,
    buyer_id: str,
    seller_id: str,
    plot_id: str,
    price: float,
    bid_order_id: str,
    ask_order_id: str,
    seller_signature: Optional[str] = None,
    buyer_signature: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes cross-database Two-Phase Commit settlement.
    """
    gid = f"tx_{trade_id}"
    log_coordinator_phase(gid, trade_id, "INITIATING", "PENDING")

    # Fault injection flags
    crash_after_prepare = os.getenv("FAULT_CRASH_AFTER_PREPARE", "false").lower() in ("true", "1")
    fail_seal = os.getenv("FAULT_FAIL_SEAL", "false").lower() in ("true", "1")
    crash_after_seal = os.getenv("FAULT_CRASH_AFTER_SEAL", "false").lower() in ("true", "1")

    # =========================================================================
    # PHASE 1: PREPARE (PostgreSQL)
    # =========================================================================
    try:
        if is_mock_mode():
            # In mock mode, emulate atomic prepare
            plot_reg = None
            for r in mock_db.registry.values():
                if r["plot_id"] == plot_id:
                    plot_reg = r
                    break

            if not plot_reg or plot_reg["legal_status"] != "Clear":
                raise ValueError(f"Plot {plot_id} is not in Clear legal status.")
            if plot_reg["current_owner_id"] != seller_id:
                raise ValueError(f"Seller {seller_id} is not the current owner of plot {plot_id}.")

            # Check buyer held balance
            buyer_wallet = mock_db.wallets.get(buyer_id)
            if not buyer_wallet or buyer_wallet["balance_held"] < price:
                raise ValueError(f"Buyer {buyer_id} does not have held escrow balance of {price}.")

            seller_wallet = mock_db.wallets.get(seller_id)
            if not seller_wallet:
                seller_wallet = {"owner_id": seller_id, "balance_available": 0.0, "balance_held": 0.0}
                mock_db.wallets[seller_id] = seller_wallet

            # Prepare state changes in memory
            buyer_wallet["balance_held"] -= price
            seller_wallet["balance_available"] += price
            plot_reg["current_owner_id"] = buyer_id

            if bid_order_id in mock_db.order_book:
                mock_db.order_book[bid_order_id]["status"] = "Matched"
            if ask_order_id in mock_db.order_book:
                mock_db.order_book[ask_order_id]["status"] = "Matched"

            mock_db.prepared_xacts[gid] = {
                "gid": gid,
                "trade_id": trade_id,
                "plot_id": plot_id,
                "buyer_id": buyer_id,
                "seller_id": seller_id,
                "price": price,
                "registry_id": plot_reg["registry_id"]
            }
        else:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    # Row-lock registry_entry FOR UPDATE
                    cur.execute(
                        """
                        SELECT registry_id, current_owner_id, legal_status
                        FROM registry_entry
                        WHERE plot_id = %s
                        FOR UPDATE;
                        """,
                        (plot_id,)
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ValueError(f"Plot {plot_id} not registered.")
                    reg_id, current_owner, status = row[0], row[1], row[2]

                    if status != 'Clear':
                        raise ValueError(f"Plot {plot_id} legal status is {status}, cannot settle.")
                    if current_owner != seller_id:
                        raise ValueError(f"Seller {seller_id} does not match current owner {current_owner}.")

                    # Move wallet funds (buyer held -> seller available)
                    cur.execute(
                        """
                        UPDATE wallet
                        SET balance_held = balance_held - %s, updated_at = CURRENT_TIMESTAMP
                        WHERE owner_id = %s;
                        """,
                        (price, buyer_id)
                    )
                    cur.execute(
                        """
                        UPDATE wallet
                        SET balance_available = balance_available + %s, updated_at = CURRENT_TIMESTAMP
                        WHERE owner_id = %s;
                        """,
                        (price, seller_id)
                    )

                    # Update current_owner_id in registry_entry
                    cur.execute(
                        """
                        UPDATE registry_entry
                        SET current_owner_id = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE plot_id = %s;
                        """,
                        (buyer_id, plot_id)
                    )

                    # Mark orders Matched
                    cur.execute(
                        "UPDATE order_book SET status = 'Matched' WHERE order_id IN (%s, %s);",
                        (bid_order_id, ask_order_id)
                    )

                    # Execute PREPARE TRANSACTION
                    cur.execute(f"PREPARE TRANSACTION '{gid}';")

        log_coordinator_phase(gid, trade_id, "PREPARED", "COMMIT_INTENDED")
        log_audit_event("2PC_PHASE1_PREPARED", "settlement", buyer_id, {"gid": gid, "trade_id": trade_id})

    except Exception as e:
        logger.error(f"Phase 1 Prepare failed: {e}")
        log_coordinator_phase(gid, trade_id, "PREPARE_FAILED", "ABORTED")
        return {"status": "Failed", "error": f"Phase 1 prepare failed: {str(e)}"}

    if crash_after_prepare:
        logger.warning(f"[FAULT INJECTION] Crashing after prepare for gid {gid}")
        raise FaultInjectionException(f"Simulated node crash after prepare for {gid}")

    # =========================================================================
    # SEAL: INSERT LEDGER BLOCK (MongoDB)
    # =========================================================================
    sealed_block = None
    try:
        if fail_seal:
            raise FaultInjectionException("Simulated seal failure in MongoDB")

        registry_id = f"reg_{plot_id}"
        sealed_block = append_block(
            block_type="SALE",
            registry_id=registry_id,
            plot_id=plot_id,
            seller_id=seller_id,
            buyer_id=buyer_id,
            sale_price=price,
            seller_signature=seller_signature,
            buyer_signature=buyer_signature,
            gid=gid
        )
        log_coordinator_phase(gid, trade_id, "SEALED", "COMMITTED")
        log_audit_event("2PC_SEALED", "ledger", seller_id, {"gid": gid, "tx_id": sealed_block["tx_id"]})

    except Exception as e:
        logger.error(f"Ledger block seal failed: {e}. Executing ROLLBACK PREPARED.")
        # Rollback prepared Postgres transaction
        try:
            if is_mock_mode():
                if gid in mock_db.prepared_xacts:
                    # Revert mock state
                    buyer_wallet = mock_db.wallets.get(buyer_id)
                    seller_wallet = mock_db.wallets.get(seller_id)
                    if buyer_wallet:
                        buyer_wallet["balance_held"] += price
                    if seller_wallet:
                        seller_wallet["balance_available"] -= price
                    for r in mock_db.registry.values():
                        if r["plot_id"] == plot_id:
                            r["current_owner_id"] = seller_id
                            break
                    del mock_db.prepared_xacts[gid]
            else:
                with get_pg_connection() as conn:
                    conn.autocommit = True
                    with conn.cursor() as cur:
                        cur.execute(f"ROLLBACK PREPARED '{gid}';")
            log_coordinator_phase(gid, trade_id, "ABORTED", "ROLLED_BACK")
        except Exception as rollback_err:
            logger.error(f"Error rolling back prepared transaction: {rollback_err}")

        return {"status": "Failed", "error": f"Cryptographic seal failed: {str(e)}"}

    if crash_after_seal:
        logger.warning(f"[FAULT INJECTION] Crashing after seal for gid {gid}")
        raise FaultInjectionException(f"Simulated node crash after seal for {gid}")

    # =========================================================================
    # PHASE 2: COMMIT PREPARED (PostgreSQL)
    # =========================================================================
    try:
        if is_mock_mode():
            if gid in mock_db.prepared_xacts:
                del mock_db.prepared_xacts[gid]
            for r in mock_db.registry.values():
                if r["plot_id"] == plot_id:
                    r["last_block_height"] = sealed_block["block_number"]
                    r["last_block_hash"] = sealed_block["tx_id"]
                    break
            if trade_id in mock_db.trades:
                mock_db.trades[trade_id]["status"] = "Settled"
            if bid_order_id in mock_db.order_book:
                mock_db.order_book[bid_order_id]["status"] = "Settled"
            if ask_order_id in mock_db.order_book:
                mock_db.order_book[ask_order_id]["status"] = "Settled"
        else:
            with get_pg_connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f"COMMIT PREPARED '{gid}';")
                    cur.execute(
                        """
                        UPDATE registry_entry
                        SET last_block_height = %s, last_block_hash = %s
                        WHERE plot_id = %s;
                        """,
                        (sealed_block["block_number"], sealed_block["tx_id"], plot_id)
                    )
                    cur.execute("UPDATE trade SET status = 'Settled' WHERE trade_id = %s;", (trade_id,))
                    cur.execute(
                        "UPDATE order_book SET status = 'Settled' WHERE order_id IN (%s, %s);",
                        (bid_order_id, ask_order_id)
                    )

        log_coordinator_phase(gid, trade_id, "COMMITTED", "SUCCESS")
        log_audit_event("2PC_PHASE2_COMMITTED", "settlement", buyer_id, {
            "gid": gid,
            "trade_id": trade_id,
            "block_number": sealed_block["block_number"],
            "tx_id": sealed_block["tx_id"]
        })

        return {
            "status": "Settled",
            "trade_id": trade_id,
            "gid": gid,
            "block_number": sealed_block["block_number"],
            "tx_id": sealed_block["tx_id"],
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "price": price
        }

    except Exception as e:
        logger.error(f"Phase 2 Commit error: {e}")
        return {"status": "InDoubt", "error": f"Prepared committed partially: {str(e)}", "gid": gid}

def recover_in_doubt_transactions() -> Dict[str, Any]:
    """
    DECISION 5: Recovery job resolves in-doubt gids by checking whether
    a ledger block with that gid exists in MongoDB.
    Block exists -> COMMIT PREPARED. Missing -> ROLLBACK PREPARED.
    """
    resolved_commits = []
    resolved_rollbacks = []

    db = get_mongo_db()
    col = db["ledger_transaction_block"]

    if is_mock_mode():
        gids = list(mock_db.prepared_xacts.keys())
        for gid in gids:
            block = col.find_one({"gid": gid})
            if block:
                # Commit prepared
                del mock_db.prepared_xacts[gid]
                resolved_commits.append(gid)
                log_coordinator_phase(gid, block.get("gid", gid), "RECOVERY_COMMITTED", "COMMITTED")
            else:
                # Rollback prepared
                del mock_db.prepared_xacts[gid]
                resolved_rollbacks.append(gid)
                log_coordinator_phase(gid, gid, "RECOVERY_ROLLEDBACK", "ABORTED")

        return {
            "status": "Recovery completed",
            "committed_gids": resolved_commits,
            "rolled_back_gids": resolved_rollbacks
        }

    try:
        with get_pg_connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT gid, prepared FROM pg_prepared_xacts;")
                pending = cur.fetchall()

                for row in pending:
                    gid = row[0]
                    # Check if sealed in MongoDB
                    block = col.find_one({"gid": gid})
                    if block:
                        cur.execute(f"COMMIT PREPARED '{gid}';")
                        resolved_commits.append(gid)
                        log_coordinator_phase(gid, gid, "RECOVERY_COMMITTED", "COMMITTED")
                        logger.info(f"[RECOVERY] Committed in-doubt gid {gid} (Ledger block found).")
                    else:
                        cur.execute(f"ROLLBACK PREPARED '{gid}';")
                        resolved_rollbacks.append(gid)
                        log_coordinator_phase(gid, gid, "RECOVERY_ROLLEDBACK", "ABORTED")
                        logger.info(f"[RECOVERY] Rolled back in-doubt gid {gid} (No ledger block).")

        return {
            "status": "Recovery completed",
            "committed_gids": resolved_commits,
            "rolled_back_gids": resolved_rollbacks
        }
    except Exception as e:
        logger.error(f"Error during in-doubt recovery: {e}")
        return {"status": "Error", "error": str(e)}
