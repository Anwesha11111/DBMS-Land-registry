# Software Requirement Specification: Land Exchange

## 1. System Overview & Core Requirements
Land Exchange is a decentralized, blockchain-inspired land registry system paired with a peer-to-peer real estate exchange. 

### 1.1 Stakeholders & Roles
- **Public:** Unauthenticated users can view public plots, inspect the full cryptographic title chain, and run automated chain integrity verifications.
- **Buyer:** Verified users with simulated wallets who place Bids on available plots.
- **Owner/Seller:** Landholders verified via KYC hash who can list plots (Ask), accept trades, and sign title transfer deeds.
- **Registry Admin:** Civil authority who registers new plots, verifies KYC hashes, approves Initial Land Deeds, and initiates correction blocks.
- **Court Authority:** Judicial officer empowered to place injunctions on disputed plots (locking order books) and lift injunctions upon dispute resolution.
- **System Admin:** Maintains coordinator recovery logs and system health.

## 2. Functional Requirements
### 2.1 Spatial Registry
- Plot boundaries must be stored as PostGIS `geometry(Polygon, 4326)`.
- Boundary polygons must be valid (`ST_IsValid`).
- Overlaps between plots are strictly forbidden: An insert/update is rejected if `ST_Intersects AND NOT ST_Touches` against any existing plot.
- Shared edges (`ST_Touches`) are permitted to allow adjacent plots.

### 2.2 Ownership & State
- Current ownership is tracked strictly in `registry_entry(plot_id, current_owner_id, legal_status, last_block_height, last_block_hash)`.
- Legal statuses: `Clear`, `Pending`, `Disputed`.
- Only plots with `Clear` status can have active asks or be matched in trades.

### 2.3 Trading & Matching Engine
- At most one Open Ask per plot (enforced via partial unique index).
- Any verified buyer with sufficient wallet balance can place Bids.
- Orders must be cryptographically signed by the user's browser-generated private key.
- Engine matches when `best Bid >= Ask`. Trade price equals the resting order's price.
- Zero commission charged.

### 2.4 Cryptographic Ledger & Two-Phase Commit (2PC)
- MongoDB stores immutable blocks in `ledger_transaction_block`.
- Phase 1 (Prepare): Lock registry entry, transfer funds in wallet (escrow/hold), set orders Matched, execute `PREPARE TRANSACTION 'gid'`.
- Phase 2 (Commit): Insert block into MongoDB with canonical hash and signatures; on success execute `COMMIT PREPARED 'gid'`, on failure `ROLLBACK PREPARED 'gid'`.
- Recovery worker resolves any dangling in-doubt transactions.
