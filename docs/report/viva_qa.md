# Land Exchange: Comprehensive Viva Voce Questions & Answers

**Course:** DBMS CD252IA, RVCE (2026)  
**Project:** Decentralized Land Registry & Peer-to-Peer Real Estate Exchange  
**Implementation Source:** [`AGENTS.md`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/AGENTS.md), [`backend/`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/), [`sql/`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/)

---

### Q1. Why did your team adopt a polyglot persistence architecture (PostgreSQL + MongoDB) rather than a single database?
**Answer:**
A land exchange has two diametrically opposed data access profiles:
1. **Dynamic, Relational, and Spatial Current State:** Requires strict ACID transactional locking, referential integrity between orders/wallets, and PostGIS R-Tree computational geometry to reject overlapping polygons (`ST_Intersects AND NOT ST_Touches`). PostgreSQL 16 is optimal for this.
2. **Append-Only, Historical Title Chain:** Land deed history must be structurally immutable, hash-linked, and tamper-evident. Storing history in standard SQL tables leaves it vulnerable to unnoticed `UPDATE` or `DELETE` statements by administrators. MongoDB 7.0 is configured with collection-level role restrictions where the application user has `insert` and `find` privileges only (no `update` or `delete`). This creates an unmodifiable cryptographic chain where any tampering immediately invalidates SHA-256 block hashes.  
*(Citations: [`AGENTS.md`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/AGENTS.md), [`scripts/mongo_init.js`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/mongo_init.js))*

---

### Q2. How do you guarantee atomic Delivery versus Payment (DvP) when money moves in PostgreSQL and the deed is sealed in MongoDB?
**Answer:**
We implement **Two-Phase Commit (2PC)** utilizing PostgreSQL's native prepared transactions:
- **Phase 1 (Prepare):** In PostgreSQL, row-level locks are taken on `registry_entry` (`FOR UPDATE`), wallet funds are transferred from held balance to seller's available balance, and `PREPARE TRANSACTION 'tx_<trade_id>'` is executed. The coordinator logs `phase='PREPARED'` in an independent autocommit connection.
- **Distributed Barrier (Seal):** The block is sealed into MongoDB with both trader signatures.
- **Phase 2 (Commit / Abort):** If MongoDB confirms block insertion, PostgreSQL executes `COMMIT PREPARED 'tx_<trade_id>'`. If MongoDB fails (e.g., duplicate block height or network partition), PostgreSQL executes `ROLLBACK PREPARED 'tx_<trade_id>'`, releasing all locks and restoring held funds.  
*(Citations: [`backend/services/settlement.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/settlement.py), [`docs/report/2pc_settlement.md`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/docs/report/2pc_settlement.md))*

---

### Q3. What happens if the server crashes right between PostgreSQL `PREPARE TRANSACTION` and MongoDB block insertion?
**Answer:**
When the system recovers, the startup recovery hook [`scripts/recover_in_doubt.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/recover_in_doubt.py) queries PostgreSQL's `pg_prepared_xacts` system view to find all in-doubt `gid`s. For each `gid`:
1. It queries MongoDB for a sealed block with that `gid`.
2. Because the crash occurred *before* the MongoDB write, no block exists in the ledger.
3. Recovery executes `ROLLBACK PREPARED '<gid>'`.  
PostgreSQL aborts the prepared state, returning held money to the buyer's balance and preserving the seller's ownership. The ledger is the single arbiter of truth: **No block = No sale**.  
*(Citations: [`backend/services/settlement.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/settlement.py#L180-L240))*

---

### Q4. Explain DECISION 2: Why are overlapping plots rejected, but touching plots permitted?
**Answer:**
Land parcels naturally abut each other; adjacent properties share legal boundaries (common fence lines or survey edges).
- In PostGIS, `ST_Touches(A, B)` is true if the boundaries intersect but the interiors do NOT intersect ($A^\circ \cap B^\circ = \emptyset$).
- `ST_Intersects(A, B)` is true if *any* point is shared (either interior or boundary).
- Therefore, checking `ST_Intersects AND NOT ST_Touches` isolates **interior encroachments** while correctly permitting legitimate neighboring parcels sharing a survey line.  
*(Citations: [`sql/002_triggers.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/002_triggers.sql#L10-L30), [`backend/services/spatial.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/spatial.py#L44-L82))*

---

### Q5. Why does the `plot` table have NO `owner` column (DECISION 1)?
**Answer:**
Placing `current_owner_id` on the `plot` table would violate separation of concerns and introduce dangerous update anomalies:
- A land parcel's physical geometry (coordinates, boundary, area) is immutable after statutory survey.
- Ownership is dynamic and changes across market trades.
- If `plot` held ownership while `registry_entry` also held ownership, any failed synchronization would produce a split-brain state.
By making `registry_entry(plot_id UNIQUE, current_owner_id, legal_status, last_block_height, last_block_hash)` the **sole source of truth**, we enforce strict 1:1 integrity with zero redundancy.  
*(Citations: [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql#L45-L65))*

---

### Q6. How is double-selling prevented when two buyers concurrently place matching bids on the same Ask?
**Answer:**
Double-selling is prevented at two distinct database layers:
1. **Application Engine Row-Level Lock:** When matching, PostgreSQL executes `SELECT * FROM registry_entry WHERE plot_id = $1 FOR UPDATE`. The first transaction acquires an exclusive row lock. The concurrent transaction is serialized and waits.
2. **Post-Lock Invariant Check:** When the second transaction acquires the lock, it immediately checks `WHERE current_owner_id = seller_id`. Since the first trade already reassigned `current_owner_id = buyer1_id`, the check fails and the second trade is cleanly rejected without moving funds.  
*(Citations: [`scripts/demo_double_sell.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/demo_double_sell.py), [`backend/services/matching.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/matching.py))*

---

### Q7. How does the partial unique index enforce the "One Open Ask per Plot" rule (DECISION 3)?
**Answer:**
In [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql#L90-L95), we created:
```sql
CREATE UNIQUE INDEX idx_one_open_ask_per_plot 
ON order_book (plot_id) 
WHERE (order_type = 'ASK' AND status = 'Open');
```
A standard unique index on `plot_id` would prevent historical or cancelled asks. A **partial unique index** filters index entries using the `WHERE` predicate. This allows thousands of historical cancelled or settled asks to exist in `order_book`, while guaranteeing at the database storage engine level that no seller can list two concurrent active Asks for the same parcel.

---

### Q8. How are private keys managed, and how does the server verify order authenticity (DECISION 7)?
**Answer:**
Trader private keys are generated purely client-side in the browser using the **W3C WebCrypto API** (`ECDSA P-256`, curve `secp256r1`). Private keys are stored in IndexedDB and **never transmitted over the network**.
When placing an order:
1. The browser serializes order terms into canonical JSON (sorted keys, no whitespace).
2. The browser signs the UTF-8 digest with its private key, producing an IEEE P1363 / DER signature.
3. The server receives the payload + signature and uses the trader's stored public key to verify `cryptography.hazmat.primitives.asymmetric.ec`. Any modification of price, plot ID, or timestamp causes mathematical verification failure (`HTTP 400`).  
*(Citations: [`frontend/js/crypto.js`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/frontend/js/crypto.js), [`backend/services/crypto.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/crypto.py))*

---

### Q9. How does your system detect if a rogue database administrator tampers with historical sales directly in MongoDB?
**Answer:**
Each block in MongoDB contains:
- `prev_tx_hash`: Hash pointer to the prior block.
- `merkle_root`: SHA-256 hash of block contents.
- `tx_id`: SHA-256 of canonical JSON over all block fields except `tx_id`.
If an admin directly modifies `sale_price` or `buyer_id` in MongoDB (as demonstrated in [`scripts/demo_tamper.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/demo_tamper.py)), the hash recomputed over canonical JSON will not match the stored `tx_id`. Furthermore, the subsequent block's `prev_tx_hash` pointer will break. The public audit function `verify_chain()` detects this discrepancy in $O(N)$ sequential verification, returning `FAIL` and reporting the exact block number.  
*(Citations: [`backend/services/ledger.py:verify_chain`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/ledger.py#L180-L240))*

---

### Q10. How does the system handle legitimate title deed corrections without mutating historical blocks (DECISION 6)?
**Answer:**
Modifying or deleting blocks is strictly prohibited by MongoDB permissions and cryptographic chaining.
When a clerical error occurs:
1. A `registry_admin` submits a correction proposal citing `original_tx_id` and new attributes.
2. The correction **requires a second approver** (another `registry_admin` or `court` officer). Dual authorization is enforced: `approved_by != requested_by`.
3. A new `CORRECTION` block is appended to the chain tip containing references to the original transaction ID and both approvers' signatures. Historical data remains intact, creating a transparent, auditable trail.  
*(Citations: [`backend/services/ledger.py:append_correction`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/ledger.py#L140-L175))*

---

### Q11. How does the judicial injunction workflow affect active marketplace orders (DECISION 4)?
**Answer:**
When a judicial officer issues an injunction:
1. `injunction` record is created with court case details.
2. `registry_entry.legal_status` is updated to `Disputed`.
3. The database trigger `fn_block_orders_on_disputed_plot` blocks all subsequent order placements.
4. All existing `Open` bids and asks on the parcel are transitioned to `On_Hold`.
5. When the court resolves the litigation and releases the injunction, parcel status returns to `Clear` and orders return to `Open` without traders having to resubmit or re-sign their orders.  
*(Citations: [`backend/routes/injunctions.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/injunctions.py), [`scripts/demo_injunction.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/demo_injunction.py))*

---

### Q12. What are the known limitations and non-goals of this academic prototype?
**Answer:**
Per project design constraints:
1. **Consensus Network:** Does not implement Byzantine Fault Tolerant (BFT) consensus across independent nodes (e.g., Raft, PBFT); immutability is achieved via cryptographic chaining and database permission restrictions.
2. **Real-Money Banking Rails:** Real estate payments are simulated using atomic balance reservations in a `wallet` table rather than live RBI / NEFT / RTGS settlement gateways.
3. **Statutory Registration:** Does not replace municipal sub-registrar stamp duty filings, but serves as the technical blueprint for zero-brokerage transparent secondary real estate exchanges.  
*(Citations: [`docs/synopsis.md`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/docs/synopsis.md), [`docs/requirement_spec.md`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/docs/requirement_spec.md))*
