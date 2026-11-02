# Database Normalization Analysis (1NF to 3NF / BCNF)

**Course:** DBMS CD252IA, RVCE (2026)  
**Implementation Source:** [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql)

---

## 1. Normalization Overview

The Land Exchange relational schema is normalized to **Third Normal Form (3NF)** and **Boyce-Codd Normal Form (BCNF)** to eliminate update, insertion, and deletion anomalies while maintaining referential integrity across relational entities.

---

## 2. Table-by-Table Normalization & Functional Dependencies

### A. Table: `users`
- **Attributes:** `{user_id, email, password_hash, role, mfa_secret, is_active, created_at}`
- **Candidate Keys:** `{user_id}`, `{email}`
- **Functional Dependencies (FDs):**
  - `user_id -> email, password_hash, role, mfa_secret, is_active, created_at`
  - `email -> user_id, password_hash, role, mfa_secret, is_active, created_at`
- **1NF Verification:** All attributes contain atomic values (scalars).
- **2NF Verification:** Both candidate keys are simple (single-attribute); therefore, no partial key dependencies exist.
- **3NF Verification:** Every determinant is a candidate key. No non-prime attribute determines another non-prime attribute (no transitive dependencies).
- **BCNF Verification:** For every functional dependency $X \to Y$, $X$ is a superkey. **Satisfies BCNF.**

---

### B. Table: `owner`
- **Attributes:** `{owner_id, full_name, contact, kyc_hash, public_key, wallet_address, created_at}`
- **Candidate Keys:** `{owner_id}`, `{kyc_hash}`, `{wallet_address}`
- **Functional Dependencies (FDs):**
  - `owner_id -> full_name, contact, kyc_hash, public_key, wallet_address, created_at`
  - `kyc_hash -> owner_id, full_name, contact, public_key, wallet_address, created_at`
  - `wallet_address -> owner_id, full_name, contact, kyc_hash, public_key, created_at`
- **Analysis:**
  - Separating `owner` from `users` ensures that staff roles (`registry_admin`, `court`, `sys_admin`) do not leave null owner attributes.
  - No transitive dependencies exist. Every determinant is a superkey. **Satisfies BCNF.**

---

### C. Table: `wallet`
- **Attributes:** `{owner_id, balance_available, balance_held, updated_at}`
- **Candidate Key:** `{owner_id}`
- **Functional Dependencies (FDs):**
  - `owner_id -> balance_available, balance_held, updated_at`
- **Analysis:**
  - Decomposed from `owner` to isolate high-frequency financial write transactions from static profile metadata.
  - Every non-prime attribute depends directly and solely on `{owner_id}`. **Satisfies BCNF.**

---

### D. Table: `plot`
- **Attributes:** `{plot_id, boundary, length_m, width_m, area_sqft, street_address, city, state, zip, created_at}`
- **Candidate Key:** `{plot_id}`
- **Functional Dependencies (FDs):**
  - `plot_id -> boundary, length_m, width_m, area_sqft, street_address, city, state, zip, created_at`
- **Architectural Decision Rationale (DECISION 1):**
  - Noticeably, `plot` contains **no owner column**.
  - Placing `current_owner_id` on `plot` would introduce update anomalies during secondary market trading and dual-master conflicts with the title registry.
  - By strictly decoupling physical geography (`plot`) from legal ownership (`registry_entry`), `plot` data remains immutable after survey validation.
- **Transitive Dependency Considerations:**
  - While in general postal addresses `zip -> city, state` may exist, in statutory municipal land governance, boundary polygons and survey numbers define legal jurisdiction, where postal codes can span municipal sub-boundaries. To prevent anomalies from external postal revisions, address attributes are treated as physical locational descriptors determined solely by `{plot_id}`. **Satisfies 3NF/BCNF.**

---

### E. Table: `registry_entry`
- **Attributes:** `{registry_id, plot_id, current_owner_id, legal_status, last_block_height, last_block_hash, updated_at}`
- **Candidate Keys:** `{registry_id}`, `{plot_id}`
- **Functional Dependencies (FDs):**
  - `registry_id -> plot_id, current_owner_id, legal_status, last_block_height, last_block_hash, updated_at`
  - `plot_id -> registry_id, current_owner_id, legal_status, last_block_height, last_block_hash, updated_at`
- **Analysis:**
  - Represents the single legal authority over a plot's title deed.
  - Since `{plot_id}` is unique in this table, each parcel has exactly one active registry entry.
  - Every determinant is a candidate key. **Satisfies BCNF.**

---

### F. Table: `order_book`
- **Attributes:** `{order_id, plot_id, trader_id, order_type, price, status, nonce, signature, order_timestamp, created_at}`
- **Candidate Key:** `{order_id}`
- **Functional Dependencies (FDs):**
  - `order_id -> plot_id, trader_id, order_type, price, status, nonce, signature, order_timestamp, created_at`
- **Analysis:**
  - Contains no repeating groups or composite attribute lists.
  - All order terms (price, type, timestamp, cryptographic signature) are functionally determined solely by the unique order ID. **Satisfies BCNF.**

---

### G. Table: `trade`
- **Attributes:** `{trade_id, plot_id, seller_id, buyer_id, bid_order_id, ask_order_id, trade_price, status, executed_at}`
- **Candidate Key:** `{trade_id}`
- **Functional Dependencies (FDs):**
  - `trade_id -> plot_id, seller_id, buyer_id, bid_order_id, ask_order_id, trade_price, status, executed_at`
- **Analysis:**
  - Formed as a resolution entity joining a buyer's `BID` and a seller's `ASK`.
  - Fully normalized with no transitive dependencies. **Satisfies BCNF.**

---

### H. Table: `injunction`
- **Attributes:** `{injunction_id, registry_id, court_case_no, court_name, injunction_order_details, issued_by, issued_at, lifted_by, lifted_at, is_active}`
- **Candidate Key:** `{injunction_id}`
- **Functional Dependencies (FDs):**
  - `injunction_id -> registry_id, court_case_no, court_name, injunction_order_details, issued_by, issued_at, lifted_by, lifted_at, is_active`
- **Analysis:**
  - Separated from `registry_entry` to allow multiple historical court proceedings on a parcel while preserving a single current boolean flag on legal status. **Satisfies BCNF.**

---

## 3. Summary of Normal Form Compliance

| Entity Name | Primary Key | Highest Normal Form | Justification |
| :--- | :--- | :--- | :--- |
| `users` | `user_id` | **BCNF** | All determinants are candidate keys. No transitive FDs. |
| `owner` | `owner_id` | **BCNF** | Unique KYC hash and wallet addresses are alternative candidate keys. |
| `wallet` | `owner_id` | **BCNF** | Atomic numerical balances determined by PK. |
| `plot` | `plot_id` | **BCNF** | Geographic boundary and parcel dimensions depend on PK only. |
| `registry_entry` | `registry_id` | **BCNF** | `{registry_id}` and `{plot_id}` are minimal superkeys. |
| `order_book` | `order_id` | **BCNF** | Uniquely models individual signed limit orders. |
| `trade` | `trade_id` | **BCNF** | Matched execution record dependent only on trade ID. |
| `injunction` | `injunction_id` | **BCNF** | Independent legal record linked via FK to registry. |
