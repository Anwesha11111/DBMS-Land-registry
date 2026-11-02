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
