# Cross-Database Two-Phase Commit (2PC) Settlement Architecture

**Course:** DBMS CD252IA, RVCE (2026)  
**Implementation Source:** [`backend/services/settlement.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/settlement.py), [`scripts/recover_in_doubt.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/recover_in_doubt.py)

---

## 1. Architectural Problem: Cross-Database DvP (Delivery vs Payment)

In traditional centralized exchanges, payment and asset transfer occur within a single database transaction. In the Land Exchange:
- **Cash Balances & Relational Ownership:** Maintained in PostgreSQL (`wallet`, `registry_entry`).
- **Append-Only Title Deed Blockchain:** Maintained in MongoDB (`ledger_transaction_block`).

Without distributed transaction coordination, network failures or process crashes could lead to:
1. **Money transferred in PostgreSQL, but title block lost in MongoDB** (Buyer loses money without deed).
2. **Title block sealed in MongoDB, but PostgreSQL transaction rolled back** (Seller loses land without payment).

To guarantee **Atomicity and Consistency across heterogeneous storage engines**, the settlement engine implements a **Two-Phase Commit (2PC)** protocol utilizing PostgreSQL's native prepared transactions (`PREPARE TRANSACTION`) paired with an immutable coordinator ledger.

---

## 2. 2PC Settlement Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Engine as Matching Engine
    participant Coord as Settlement Coordinator
    participant PG as PostgreSQL (State & Wallet)
    participant Mongo as MongoDB (Append-Only Ledger)
    participant CoordLog as Coordinator Log (Autocommit)

    Engine->>Coord: settle_trade_2pc(trade_id, buyer, seller, plot_id, price)
    
    rect rgb(240, 248, 255)
        Note over Coord,PG: Phase 1: Prepare & Lock
        Coord->>PG: BEGIN TRANSACTION
        Coord->>PG: SELECT * FROM registry_entry WHERE plot_id = $1 FOR UPDATE
        Coord->>PG: Verify status = 'Clear' AND current_owner_id = seller_id
        Coord->>PG: Move wallet: buyer.held -= price; seller.available += price
        Coord->>PG: Update registry_entry: current_owner_id = buyer_id
        Coord->>PG: Update orders: status = 'Matched'
        Coord->>PG: PREPARE TRANSACTION 'tx_<trade_id>'
        Coord->>CoordLog: INSERT tx_coordinator_log (gid, phase='PREPARED')
    end

    rect rgb(255, 250, 240)
        Note over Coord,Mongo: Distributed Barrier: Ledger Seal
        Coord->>Mongo: append_block(SALE, plot_id, seller, buyer, price, signatures, gid)
        alt Block Sealed Successfully
            Mongo-->>Coord: Block #N sealed (tx_id = HASH)
            Coord->>CoordLog: UPDATE tx_coordinator_log (phase='SEALED')
        else Block Seal Failed / Network Error
            Mongo-->>Coord: Error / Constraint Collision
            Coord->>PG: ROLLBACK PREPARED 'tx_<trade_id>'
            Coord->>CoordLog: UPDATE tx_coordinator_log (phase='ROLLED_BACK')
            Coord-->>Engine: Settlement Failed (Clean State)
        end
    end

    rect rgb(240, 255, 240)
        Note over Coord,PG: Phase 2: Commit Prepared
        Coord->>PG: COMMIT PREPARED 'tx_<trade_id>'
        Coord->>PG: UPDATE registry_entry (last_block_height=N, last_block_hash=HASH)
        Coord->>PG: UPDATE trade & orders: status = 'Settled'
        Coord->>CoordLog: UPDATE tx_coordinator_log (phase='COMMITTED')
        Coord-->>Engine: Settlement Complete (Settled)
    end
```

---

## 3. Failure Mode & Recovery Matrix

| Crash / Failure Point | System State at Moment of Crash | Resolution Protocol (`recover_in_doubt_transactions()`) | Final Outcome |
| :--- | :--- | :--- | :--- |
| **Crash during Phase 1** (Before `PREPARE TRANSACTION`) | PostgreSQL connection drops; transaction has not been prepared. | PostgreSQL server automatically aborts and rolls back uncommitted in-flight queries. Locks on `registry_entry` and `wallet` are released immediately. | **Zero state change.** No funds moved, no block created. |
| **Crash after `PREPARE TRANSACTION`, before MongoDB Seal** | PostgreSQL transaction is locked in `pg_prepared_xacts` with identifier `tx_<trade_id>`. Coordinator has logged `PREPARED`. | 1. Recovery job queries `pg_prepared_xacts`.<br>2. Queries MongoDB `ledger_transaction_block` where `gid = 'tx_<trade_id>'`.<br>3. Block is **MISSING**.<br>4. Recovery executes `ROLLBACK PREPARED 'tx_<trade_id>'`. | **Clean Rollback.** Locks released; funds returned to buyer's available balance; seller remains owner. |
| **Failure during MongoDB Seal** (Duplicate block, MongoDB crash, or validator rejection) | `PREPARE TRANSACTION` succeeded, but `append_block` raised an exception. | Coordinator catches exception, executes `ROLLBACK PREPARED 'tx_<trade_id>'`, marks `tx_coordinator_log` as `ROLLED_BACK`. | **Clean Rollback.** Atomic consistency maintained. |
| **Crash after MongoDB Seal, before `COMMIT PREPARED`** | MongoDB block is permanently sealed with cryptographic `tx_id`. PostgreSQL transaction is hanging in `pg_prepared_xacts`. | 1. Recovery job inspects in-doubt transactions in `pg_prepared_xacts`.<br>2. Queries MongoDB where `gid = 'tx_<trade_id>'`.<br>3. Block is **FOUND**.<br>4. Recovery executes `COMMIT PREPARED 'tx_<trade_id>'` and syncs block height/hash to `registry_entry`. | **Committed.** Deed and funds successfully finalized. No human intervention required. |
| **Crash after `COMMIT PREPARED`** | Both PostgreSQL and MongoDB committed successfully. | Recovery finds no dangling transactions in `pg_prepared_xacts`. | **Settled.** System in consistent steady state. |

---

## 4. Recovery Routine Verification

The recovery procedure is exposed via [`scripts/recover_in_doubt.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/recover_in_doubt.py) and executes automatically on backend application startup in [`backend/app/__init__.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/app/__init__.py):

```python
# PostgreSQL In-Doubt Resolution Query
SELECT gid FROM pg_prepared_xacts WHERE gid LIKE 'tx_%';

# MongoDB Proof-of-Seal Check
block = ledger_collection.find_one({"gid": gid})
if block:
    cur.execute(f"COMMIT PREPARED '{gid}';")
else:
    cur.execute(f"ROLLBACK PREPARED '{gid}';")
```

This guarantees that the **append-only ledger in MongoDB is the ultimate arbiter of truth**: if the cryptographic block exists, the transaction must commit; if the block was not sealed, the database transaction is rolled back.
