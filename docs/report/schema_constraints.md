# Database Schema & Constraint Justifications

**Course:** DBMS CD252IA, RVCE (2026)  
**Implementation Source:** [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql), [`sql/002_triggers.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/002_triggers.sql)

---

## 1. Schema Constraints & Design Rationale

| Table / Collection | Column / Attribute | Constraint Type | Justification & Architectural Rule |
| :--- | :--- | :--- | :--- |
| **`plot`** | `plot_id` | `PRIMARY KEY` | Globally unique identifier for land parcels (`plot_...`). |
| **`plot`** | `boundary` | `NOT NULL`, `CHECK(ST_IsValid(boundary))`, `CHECK(ST_GeometryType(boundary) = 'ST_Polygon')` | Enforces SRID 4326 2D Polygon topology per DECISION 2. Rejects multipolygons, self-intersecting bow-ties, or open line-strings. |
| **`plot`** | `boundary` | `GiST Index (idx_plot_boundary)` | PostGIS R-Tree bounding-box index required for sub-millisecond 2D intersection (`&&`) and spatial relationship filtering (`ST_Intersects`). |
| **`plot`** | `area_sqft` | `CHECK(area_sqft > 0)` | Prevents zero or negative parcel sizes. |
| **`registry_entry`** | `plot_id` | `UNIQUE`, `FOREIGN KEY REFERENCES plot(plot_id) ON DELETE RESTRICT` | **DECISION 1:** `registry_entry` is the sole source of truth for land ownership. `plot` has no owner column. `UNIQUE` guarantees strict 1:1 relationship between parcel and registry title deed. |
| **`registry_entry`** | `current_owner_id`| `NOT NULL`, `FOREIGN KEY REFERENCES owner(owner_id)` | Prevents unowned zombie plots. Guarantees referential integrity with KYC-verified owners. |
| **`registry_entry`** | `legal_status` | `ENUM('Clear', 'Pending', 'Disputed')` | Strictly governs market tradeability. Plots with `Pending` or `Disputed` statuses cannot accept buy/sell orders. |
| **`registry_entry`** | `last_block_hash` | `CHAR(64)` | Stores exact SHA-256 hash pointer to the tip of the MongoDB title block chain. |
| **`owner`** | `kyc_hash` | `UNIQUE NOT NULL` | **DECISION 10:** Real government ID numbers (Aadhaar, Passport) are never stored in plaintext. Hashing with cryptographic salt prevents duplicate registrations while guaranteeing privacy. |
| **`owner`** | `public_key` | `NOT NULL` | ECDSA P-256 public key used to verify trader signatures on all submitted bids and asks. |
| **`owner`** | `wallet_address`| `UNIQUE NOT NULL` | Hex-encoded simulated on-chain wallet destination. |
| **`wallet`** | `balance_available`| `NUMERIC(18, 2)`, `CHECK(balance_available >= 0)` | **DECISION 8:** Prevents overdrafts. Guarantees mathematical solvency across simulated settlement. |
| **`wallet`** | `balance_held` | `NUMERIC(18, 2)`, `CHECK(balance_held >= 0)` | Escrows cash during active Bid placement. Funds are held so buyers cannot double-spend cash across multiple bids. |
| **`order_book`** | `idx_one_open_ask_per_plot` | `CREATE UNIQUE INDEX ... WHERE (order_type = 'ASK' AND status = 'Open')` | **DECISION 3:** Prevents an owner from placing competing asks on the same parcel. Enforces single resting ask per parcel. |
| **`order_book`** | `price` | `CHECK(price > 0)` | Rejects negative or zero asset valuations. |
| **`order_book`** | `status` | `ENUM('Open', 'Matched', 'Cancelled', 'On_Hold', 'Settled')` | **DECISION 4:** State machine for limit orders. |
| **`trade`** | `trade_price` | `CHECK(trade_price > 0)` | Trade price matches the price of the resting order per price-time priority rules. |
| **`injunction`** | `registry_id` | `FOREIGN KEY REFERENCES registry_entry(registry_id)` | Links legal court dispute orders directly to the land title. |
| **`ledger_transaction_block`** | `block_number` | `UNIQUE` (MongoDB Index) | Prevents chain forks or duplicate block height allocations. |
| **`ledger_transaction_block`** | `prev_tx_hash` | `UNIQUE` (MongoDB Index) | Guarantees single linear cryptographic chain without branching. |
| **`ledger_transaction_block`** | `tx_id` | `UNIQUE` (MongoDB Index) | Prevents replay of identical canonical transaction hashes. |

---

## 2. Trigger Enforcements

PostgreSQL procedural triggers implemented in [`sql/002_triggers.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/002_triggers.sql):

1. **`trg_check_plot_overlap`:**
   - **Trigger:** `BEFORE INSERT OR UPDATE ON plot FOR EACH ROW EXECUTE FUNCTION fn_check_plot_overlap();`
   - **Enforcement:** Enforces **DECISION 2**: Rejects if `ST_Intersects(boundary, NEW.boundary) AND NOT ST_Touches(boundary, NEW.boundary)`. Allows adjacent parcels sharing borders to coexist while raising `SQLSTATE 'P0002'` on interior encroaching parcels.
2. **`trg_block_orders_on_disputed_plot`:**
   - **Trigger:** `BEFORE INSERT ON order_book FOR EACH ROW EXECUTE FUNCTION fn_block_orders_on_disputed_plot();`
   - **Enforcement:** Inspects `registry_entry.legal_status` before an order is placed. If status is `Disputed` or `Pending`, order insertion is immediately aborted with `SQLSTATE 'P0003'`.
3. **`trg_registry_status_history`:**
   - **Trigger:** `AFTER UPDATE OF legal_status ON registry_entry FOR EACH ROW EXECUTE FUNCTION fn_log_registry_status_history();`
   - **Enforcement:** Automatically appends an immutable entry to `registry_status_history` with the old status, new status, and audit timestamp.
