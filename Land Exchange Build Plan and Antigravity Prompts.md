# Land Exchange: Build Plan and Antigravity Prompts

Blockchain-style land registry and zero-brokerage P2P exchange with 3D viewer. DBMS (CD252IA), RVCE. Prepared for Anwesha Mohapatra and Abdul Mateen Nandgadi.

## 1. What I analysed

- **Synopsis + Requirement Specification (Land Exchange):** your project. Hybrid design: PostgreSQL/PostGIS for current state, MongoDB for an append-only SHA-256 hash-linked ledger, Flask consensus engine doing Two-Phase Commit, Bid/Ask matching, Three.js 3D viewer, public verification portal.
- **Schema diagram:** Zone A (owner, plot, registry\_entry, order\_book) and Zone B (ledger\_transaction\_block).
- **DBMS\_Requirement\_Specification.docx is a different project** (Manufacturing Defect Genealogy, other students, Node/React). Do not give it to Antigravity. It is only useful as a format reference.

## 2. Gaps and conflicts to settle before coding

These are places where your documents disagree or are incomplete. The prompts below already assume the decisions in bold.

1. **Owner stored twice.** The diagram has current\_owner\_id in both plot and registry\_entry, and registry\_entry has no plot\_id. **Decision:** registry\_entry has plot\_id (UNIQUE FK) and current\_owner\_id; plot has no owner column. One source of truth for current state.
2. **Plot attributes.** The spec lists ZIP and dimensions; the diagram does not. **Decision:** add zip, length\_m, width\_m; compute area\_sqft from the geometry with PostGIS.
3. **Ledger fields.** The spec has registry\_id and nonce; the diagram has block\_number, merkle\_root and digital\_signature. **Decision:** include all. No mining: nonce is fixed at 0 and kept for spec compliance. Merkle root is computed over the block's signatures and payment reference.
4. **Order status.** The diagram has Open/Matched/Cancelled; the spec needs orders put on hold by court injunctions. **Decision:** add On\_Hold and Settled.
5. **Missing tables.** The spec needs users, audit\_log, status history, injunctions, correction blocks, state rules. The diagram has none of them. **Decision:** added (section 4).
6. **Two-Phase Commit between Postgres and MongoDB.** There is no native cross-database XA. **Decision:** use Postgres PREPARE TRANSACTION as phase 1, seal the MongoDB block, then COMMIT PREPARED. A recovery job decides in-doubt transactions by checking whether the ledger block exists. Details in section 3.
7. **"Payment" for DvP.** Banking is out of scope, but DvP needs something to settle. **Decision:** a simulated wallet table with escrow hold on Bids; debit, credit and ownership change happen in the same Postgres transaction.
8. **Private keys.** The spec says only the user keeps their private key, but the backend is Python. **Decision:** keys are generated and signing happens in the browser (WebCrypto ECDSA P-256); Flask only verifies.
9. **A plot is a unique asset.** A normal order book assumes fungible units. **Decision:** at most one Open Ask per plot (partial unique index), many Bids; match when best Bid >= Ask; trade price is the resting order's price; price-time priority.
10. **Append-only is a promise, not enforcement.** **Decision:** the app's MongoDB user gets insert and find only, plus a JSON-schema validator and unique indexes on block\_number and prev\_tx\_hash.
11. **Adjacent plots.** A strict non-overlap check would reject plots that share a border. **Decision:** reject when ST\_Intersects is true and ST\_Touches is false.

## 3. Architecture

**Components:** Browser (Three.js viewer, trading UI, WebCrypto signing) -> Flask API (auth, RBAC, matching engine, consensus coordinator, ledger service, verifier) -> PostgreSQL/PostGIS and MongoDB.

**Settlement flow (2PC):**

1. Matching engine finds Bid >= Ask on a Clear plot and creates a trade row (Pending) plus a coordinator log entry.
2. **Phase 1 (prepare):** in Postgres, BEGIN; SELECT the registry\_entry FOR UPDATE; confirm Clear; move wallet funds buyer -> seller; set registry\_entry.current\_owner\_id; mark orders Matched; PREPARE TRANSACTION with a gid. Nothing is visible yet.
3. Build the block (prev hash, canonical JSON, SHA-256, merkle root, both signatures) and insert it into MongoDB. This is the cryptographic seal.
4. **Phase 2:** seal succeeded -> COMMIT PREPARED, update last\_block\_height/hash, trade Settled. Seal failed -> ROLLBACK PREPARED, trade Failed.
5. **Recovery job:** for any prepared transaction left over after a crash, look for a ledger block carrying that gid. Block exists -> commit. Missing -> roll back. The ledger is the tie-breaker.

**Hash rule:** tx\_id = SHA-256 of the canonical JSON (sorted keys, no whitespace) of every block field except tx\_id. Verification recomputes from the genesis block, checks prev\_tx\_hash links, block\_number continuity, signatures, and that the last block's buyer equals registry\_entry.current\_owner\_id.

## 4. Schema blueprint

**PostgreSQL/PostGIS**

- users(user\_id, email, password\_hash, role, mfa\_secret, owner\_id FK null, is\_active)
- owner(owner\_id, full\_name, contact, kyc\_hash UNIQUE, public\_key, wallet\_address UNIQUE)
- wallet(owner\_id PK/FK, balance\_available, balance\_held, both CHECK >= 0)
- plot(plot\_id, street\_address, city, state, zip, length\_m, width\_m, boundary geometry(Polygon,4326), GiST index, CHECK ST\_IsValid)
- registry\_entry(registry\_id, plot\_id UNIQUE FK, current\_owner\_id FK, legal\_status ENUM Clear/Pending/Disputed, last\_block\_height, last\_block\_hash)
- registry\_status\_history(id, registry\_id, old\_status, new\_status, changed\_by, reason, changed\_at)
- injunction(id, registry\_id, court\_user\_id, case\_ref, placed\_at, lifted\_at)
- order\_book(order\_id, plot\_id, trader\_id, order\_type BID/ASK, price, order\_timestamp, status Open/Matched/Cancelled/On\_Hold/Settled, signature, hold\_reason)
- trade(trade\_id, bid\_order\_id, ask\_order\_id, plot\_id, price, status, gid)
- tx\_coordinator\_log(gid, trade\_id, phase, decision, updated\_at)
- audit\_log(audit\_id, user\_id, action, entity, details jsonb, ip, ts)
- state\_rules(state, rule\_type, value jsonb, effective\_from): editable stamp duty and fees

**MongoDB ledger\_transaction\_block:** tx\_id, block\_number (unique), prev\_tx\_hash (unique), block\_type (GENESIS/SALE/CORRECTION), registry\_id, plot\_id, seller\_id, buyer\_id, sale\_price, timestamp, merkle\_root, nonce, seller\_signature, buyer\_signature, gid, corrects\_tx\_id, approved\_by.

## 5. Build order

| Phase | Output |
| --- | --- |
| 0 | Repo, Docker, AGENTS.md |
| 1 | SQL schema, triggers, Mongo setup |
| 2 | Auth, RBAC, MFA, keys, audit log |
| 3 | Owners, plots, spatial validation, registry status, injunctions |
| 4 | Order book and matching engine |
| 5 | Ledger service and verifier |
| 6 | 2PC settlement and recovery |
| 7 | Corrections, search, reports |
| 8 | 3D viewer and trading UI |
| 9 | Public portal |
| 10 | Seed data, tests, tamper demo |
| 11 | Docs for the report and viva |

Phases 8 and 9 only need the API contract from phase 3 to 6, so in Manager view they can run in parallel with phases 6 and 7.

## 6. How to work with Antigravity

- Create the repo with a /docs folder holding the synopsis, requirement spec and the schema PNG (not the other team's spec). Reference them with @ in prompts.
- Project rules go in AGENTS.md at the repo root (GEMINI.md overrides it in Antigravity). Keep the file well under 12,000 characters. Prompt 0 below gives you one.
- Use Planning mode for each phase. Read the implementation plan artifact and check it against section 2 before approving. Use Fast mode only for small fixes.
- One phase per conversation. Commit to Git after each phase passes its acceptance checks. If an agent drifts, restart it with the phase prompt and a pointer to AGENTS.md.
- Always end a phase by asking the agent to run the tests and show the output.

## 7. The prompts

Paste them in order. Each one is self-contained.

### Prompt 0: AGENTS.md (create this file first)

```
Create AGENTS.md in the repo root with exactly these project rules.

# Project: Land Exchange (DBMS CD252IA, RVCE)
Decentralized blockchain-style land registry + zero-brokerage P2P real estate exchange with 3D viewer.
Source of truth for requirements: /docs (synopsis, requirement spec, schema diagram PNG). If code and docs conflict, follow the DECISIONS below, then the docs.

## Stack
- PostgreSQL 16 + PostGIS (current state, spatial). MongoDB 7 (append-only ledger).
- Python 3.12, Flask, psycopg2, PyMongo, bcrypt, PyJWT, cryptography, pytest.
- Frontend: plain HTML/CSS/JS ES modules, Three.js (no React). WebCrypto for signing in-browser.
- Local infra via docker-compose (postgis/postgis image, mongo:7). Prepared transactions enabled (max_prepared_transactions=10).

## DECISIONS (do not change without asking)
1. registry_entry(plot_id UNIQUE, current_owner_id, legal_status Clear|Pending|Disputed, last_block_height, last_block_hash) is the only place holding current owner. plot has no owner column.
2. Plot overlap rule: reject if ST_Intersects AND NOT ST_Touches. SRID 4326, Polygon only, ST_IsValid required.
3. One Open Ask per plot (partial unique index); many Bids. Match when best Bid >= Ask. Trade price = price of the earlier (resting) order. Price-time priority. Zero commission.
4. Order statuses: Open, Matched, Cancelled, On_Hold, Settled.
5. Settlement is Two-Phase Commit: Postgres PREPARE TRANSACTION -> insert ledger block in MongoDB -> COMMIT PREPARED (or ROLLBACK PREPARED). Recovery job resolves in-doubt gids by checking whether a ledger block with that gid exists.
6. Ledger block hash = SHA-256 of canonical JSON (sorted keys, no whitespace) of all fields except tx_id. Genesis block has prev_tx_hash of 64 zeros. Nonce fixed at 0. Never update or delete blocks; corrections are new CORRECTION blocks needing a second approver.
7. Private keys are generated and used only in the browser (ECDSA P-256). Server stores public keys and verifies signatures.
8. Payment is simulated by a wallet table (available/held). Bids hold funds. Debit/credit/ownership change occur in the same Postgres transaction.
9. Mongo app user has insert+find only on the ledger collection. Validator and unique indexes on block_number and prev_tx_hash.
10. KYC stored only as a hash. Passwords bcrypt. JWT sessions. Every login, order, signature, status change goes to audit_log.

## Conventions
- Layout: /backend (app/, routes/, services/, db/), /frontend, /sql (numbered migrations), /tests, /docs, /scripts.
- All SQL in /sql as numbered files; no ad-hoc schema changes.
- Every endpoint: role check, input validation, JSON errors. Type hints and docstrings on services.
- Write pytest tests for every service. Run them before declaring a task done and show the output.
- Never hardcode secrets; use .env and provide .env.example.
- Small commits with clear messages. Ask before adding dependencies not listed above.
```

### Prompt 1: Repo, infra and project skeleton

```
Read @docs and AGENTS.md. Set up the project skeleton.
1. Create the folder layout from AGENTS.md.
2. docker-compose.yml: postgis/postgis (16) with max_prepared_transactions=10 and an init mount of /sql; mongo:7 with a named volume. Healthchecks for both.
3. Flask app factory in backend/app with config from .env, a /health endpoint that checks both databases, a Postgres connection helper (psycopg2 pool) and a Mongo client helper.
4. requirements.txt, .env.example, README with run steps for Windows 10/11 (Docker Desktop) and a Makefile or scripts/*.ps1 for start, reset-db and test.
5. pytest setup with a test that hits /health.
Acceptance: docker compose up works, /health returns both DBs OK, pytest passes.
```

### Prompt 2: Database schema

```
Using the DECISIONS in AGENTS.md and the schema in @docs (diagram PNG + requirement spec "Data Storage Requirements"), write the full relational schema as numbered files in /sql.
Tables: users, owner, wallet, plot, registry_entry, registry_status_history, injunction, order_book, trade, tx_coordinator_log, audit_log, state_rules.
Requirements:
- ENUM types for role, legal_status, order_type, order_status, trade_status.
- PK/FK/UNIQUE (owner.kyc_hash, registry_entry.plot_id), CHECKs (price > 0, wallet balances >= 0, ST_IsValid, SRID 4326, geometry type Polygon).
- GiST index on plot.boundary. Partial unique index: one Open Ask per plot.
- Trigger on plot insert/update rejecting boundaries where ST_Intersects AND NOT ST_Touches against any other plot.
- Trigger writing registry_status_history on legal_status change.
- Trigger blocking order inserts on a plot whose status is not Clear.
- A view v_plot_market(plot_id, owner, status, best_bid, active_ask, geojson) for the 3D viewer.
Also add scripts/mongo_init.js: ledger_transaction_block collection with JSON-schema validator, unique indexes on block_number and prev_tx_hash, an app role with insert+find only.
Write pytest tests proving: overlap rejected, touching accepted, invalid geometry rejected, duplicate KYC rejected, second Open Ask rejected, orders on Disputed plot rejected, Mongo update/delete denied for the app user.
```

### Prompt 3: Auth, roles, keys, audit

```
Implement authentication and RBAC.
- Roles: owner_seller, buyer, registry_admin, court, public (no login), sys_admin.
- POST /auth/register, /auth/login (bcrypt, JWT with role claim and expiry), TOTP MFA mandatory for registry_admin and court (pyotp), /auth/me.
- A @require_roles decorator used on every endpoint.
- Public key registration: the browser generates an ECDSA P-256 key pair with WebCrypto and sends only the public key. Provide frontend/js/crypto.js with generateKeyPair, exportPublicKey, signPayload, and a note that the private key is kept in IndexedDB (non-extractable) or downloaded by the user.
- Server helper verify_signature(public_key, payload_bytes, signature) using the cryptography library, with a canonical JSON function shared by all signing code.
- audit_log service called on every login, failed login, order, signature and status change.
- Seed users for each role (dev only).
Tests: wrong role gets 403, MFA required for court/admin, tampered payload fails signature verification.
```

### Prompt 4: Owners, plots and registry

```
Implement owner, plot and registry modules.
- registry_admin approves owner KYC (store only kyc_hash = SHA-256 of the document number + salt), creates the owner's wallet and registers the public key.
- POST /plots (registry_admin): accepts GeoJSON Polygon, address, city, state, zip, length_m, width_m. Validate, run the overlap check, return a clear error naming the conflicting plot_id. Create plot + registry_entry (status Pending) in one transaction; admin PATCHes status to Clear.
- PATCH /registry/<id>/status with reason; Pending/Clear by registry_admin, Disputed only by court.
- Court: POST /injunctions places Disputed, sets all Open orders on that plot to On_Hold; lifting restores status and re-opens held orders. Each action writes history and audit rows.
- GET /plots (filters: city, state, status, owner), GET /plots/<id> including area_sqft from ST_Area(boundary::geography) converted to sq ft.
Tests: overlap, valid pentagon, injunction holds orders then release restores them.
```

### Prompt 5: Order book and matching engine

```
Implement the exchange.
- POST /orders: Ask (only by the current owner of a Clear plot) or Bid (any verified buyer, not the owner). The payload must carry a signature over canonical JSON {plot_id, order_type, price, nonce, timestamp}; verify it against the user's public key. Bids move price from wallet.available to wallet.held; cancelling releases it.
- DELETE /orders/<id> cancel. GET /plots/<id>/orderbook (live depth). Add Server-Sent Events at /stream/orderbook so the UI updates in real time.
- Matching engine service, triggered after every order insert, in one DB transaction with row locks: price-time priority, match only if plot is Clear and best Bid >= Ask, trade price = resting order price, self-trade prevented, zero commission. On match insert a trade (Pending) and hand it to the settlement service (stub for now that returns Pending).
Tests: no match when Bid < Ask, match when Bid == Ask, highest bid wins, earlier bid wins ties, no match on Disputed plot, insufficient funds rejected, two concurrent matches on one plot produce exactly one trade.
```

### Prompt 6: Ledger service and verifier

```
Implement the immutable ledger in backend/services/ledger.py.
- canonical_json(), compute_tx_id(block) per AGENTS.md rule 6, merkle_root over [seller_signature, buyer_signature, payment_ref] (document the exact leaf order).
- ensure_genesis() creating block 0.
- append_block(block_type, ...) that reads the current chain tip, sets block_number and prev_tx_hash, computes hashes and inserts. Rely on the unique indexes so two concurrent appends cannot fork the chain (retry on duplicate key).
- verify_chain(plot_id=None): recompute from genesis, report the first bad block with the reason (hash mismatch, broken link, gap in block_number, invalid signature), and confirm the last block's buyer_id equals registry_entry.current_owner_id and last_block_hash matches. Return a pass/fail JSON.
- get_title_chain(plot_id) returning blocks in order with only the fields allowed for the public (no personal data).
- Correction blocks: append_correction(original_tx_id, new_data, requested_by, approved_by) requiring approved_by != requested_by.
Tests: build a 5-block chain and verify pass; tamper with one field via the admin Mongo connection and verify the exact block is reported; fork attempt rejected; self-approved correction rejected.
```

### Prompt 7: Two-Phase Commit settlement

```
Implement backend/services/settlement.py exactly per DECISION 5.
Phase 1: BEGIN; SELECT registry_entry FOR UPDATE; confirm Clear and that the seller is still the current owner; move wallet funds (buyer held -> seller available), release other bidders' holds only if the Ask is fulfilled; update current_owner_id; set both orders Matched; PREPARE TRANSACTION 'tx_<trade_id>' and log phase=PREPARED in tx_coordinator_log (separate autocommit connection).
Seal: ledger.append_block(SALE, ..., gid) with both signatures. 
Phase 2: on success COMMIT PREPARED, update last_block_height/hash, trades Settled, orders Settled; on failure ROLLBACK PREPARED, trade Failed, funds released. Log every phase.
Recovery: scripts/recover_in_doubt.py and a startup hook that lists pg_prepared_xacts and commits those whose gid has a ledger block, else rolls back.
Add fault-injection hooks via an env flag (crash after prepare, crash after seal, fail seal) for tests.
Tests: happy path (owner changed, block exists, funds moved); seal fails -> nothing changed; crash after seal -> recovery commits; crash after prepare -> recovery rolls back; double-sell race -> exactly one succeeds.
```

### Prompt 8: Corrections, search, reports

```
Add: (1) correction workflow endpoints (propose by registry_admin, approve by a different registry_admin or court user) that call ledger.append_correction; (2) GET /search?q= across plot, owner (name only for authorised roles), transaction and registry entry; (3) GET /reports/plot/<id>/history exporting the ownership history as PDF and CSV (reportlab), including the verify_chain result and report generation timestamp; (4) admin endpoint /admin/integrity that runs verify_chain for all plots and lists failures. Add tests.
```

### Prompt 9: 3D viewer and trading UI

```
Build the frontend in /frontend (plain ES modules, Three.js, no framework).
3D viewer:
- Fetch GeoJSON from v_plot_market. Project lon/lat to local metres around the centroid (equirectangular). Build each plot with THREE.Shape + ExtrudeGeometry (works for pentagons and any polygon), with edge outlines.
- Colours by real-time state: green = Clear with active Ask, blue = Clear not listed, amber = Pending, red = Disputed, white outline for plots owned by me. Update via the SSE stream without reloading.
- OrbitControls zoom/pan/rotate, raycaster hover tooltip, click opens a side panel: address, area, owner (role-limited), status, best bid, ask, order book depth, and the Bid/Ask form which signs the order in the browser with crypto.js.
Other screens: login/register, my plots and orders, owner wallet, registry admin console (register plot by drawing/pasting GeoJSON with live preview, status changes), court console, correction approvals.
Clean modern UI, dark mode, responsive, WebGL2 check with a friendly fallback message.
Acceptance: seeded plots render, a Bid placed in one browser tab appears in another tab within 2 seconds.
```

### Prompt 10: Public verification portal

```
Build frontend/public (no login). Page 1: enter a plot ID and see the full title chain from the genesis block as a vertical timeline (block number, date, seller and buyer as owner IDs only, price, short hash with copy button, linked-hash visual) and a large PASS/FAIL result from GET /public/verify/<plot_id>, which runs ledger.verify_chain within 10 seconds. If FAIL, highlight the first broken block and the reason. Page 2: a read-only mini 3D view of the plot. No personal data beyond what the chain needs. Rate-limit the endpoint. Add tests for the API and a screenshot of the PASS and FAIL states.
```

### Prompt 11: Seed data, end-to-end tests, tamper demo

```
Create scripts/seed.py (idempotent): 4 owners with wallets and keys, 1 of each staff role, about 25 non-overlapping plots in a grid near Bengaluru including several pentagons and one pair of touching plots, mixed statuses, some Asks and Bids, 3 historical settled sales with a valid chain.
Write tests/e2e covering the full story: register owner, register plot, list Ask, Bid, auto-match, 2PC settlement, 3D colour change data, public verification PASS.
Write scripts/demo_tamper.py that edits one block directly in MongoDB with the admin account, then runs verify_chain showing the exact FAIL, then restores the data. Also scripts/demo_overlap.py, demo_injunction.py and demo_double_sell.py. Each prints clear step-by-step output suitable for a live demo.
Also add backup scripts (pg_dump and mongodump) and a restore test.
```

### Prompt 12: Report and viva documentation

```
From the finished code generate /docs/report: (1) final ER diagram in Mermaid for both stores, (2) schema listing with constraints and why each exists, (3) normalisation analysis to 3NF/BCNF per table, (4) 2PC sequence diagram and failure-mode table, (5) API reference, (6) the five most important SQL queries (overlap check, order matching, ownership consistency, title chain, order book depth) with EXPLAIN ANALYZE output and index justification, (7) test summary, (8) a 12-question viva Q&A. Cite file paths for every claim.
```

## 8. Viva points to rehearse

- Why polyglot persistence: SQL for current state and spatial integrity, NoSQL for append-only history.
- Why PREPARE TRANSACTION and how a crash between phases is resolved (the ledger decides).
- Why touching plots are allowed but overlapping plots are not.
- Why a Mongo update-privilege-free user matters: tamper evidence by hash chain plus tamper resistance by permissions.
- What this prototype does not do: no real consensus network, no real payments, no statutory registration.
