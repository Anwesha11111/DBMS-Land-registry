# Land Exchange: Entity-Relationship (ER) Architecture

**Course:** DBMS CD252IA, RVCE (2026)  
**Project:** Decentralized Land Registry & Peer-to-Peer Real Estate Exchange  
**Implementation Source:** [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql), [`scripts/mongo_init.js`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/mongo_init.js)

---

## 1. Hybrid Polyglot Persistence Architecture

The Land Exchange uses a hybrid database design:
1. **Relational / Spatial Store (PostgreSQL 16 + PostGIS):** Manages relational integrity, user identities, wallets, parcel spatial geometry, current legal state, injunctions, and the real-time order book.
2. **Document / Ledger Store (MongoDB 7.0):** Acts as an immutable, append-only cryptographic ledger of title events and sale settlements.

---

## 2. PostgreSQL Relational & Spatial Entity-Relationship Diagram

```mermaid
erDiagram
    USERS ||--o| OWNER : "links to profile"
    OWNER ||--|| WALLET : "holds"
    OWNER ||--o{ REGISTRY_ENTRY : "currently owns"
    OWNER ||--o{ ORDER_BOOK : "places"
    OWNER ||--o{ TRADE : "buys or sells in"
    
    PLOT ||--|| REGISTRY_ENTRY : "governed by (1:1)"
    REGISTRY_ENTRY ||--o{ REGISTRY_STATUS_HISTORY : "tracks transitions"
    REGISTRY_ENTRY ||--o{ INJUNCTION : "encumbered by"
    REGISTRY_ENTRY ||--o{ ORDER_BOOK : "traded through"
    
    ORDER_BOOK ||--o{ TRADE : "matched into"
    TRADE ||--o| TX_COORDINATOR_LOG : "coordinated by"

    USERS {
        uuid user_id PK
        varchar email UK
        text password_hash
        user_role role
        varchar mfa_secret
        boolean is_active
        timestamp created_at
    }

    OWNER {
        varchar owner_id PK
        varchar full_name
        varchar contact
        varchar kyc_hash UK
        text public_key
        varchar wallet_address UK
        timestamp created_at
    }

    WALLET {
        varchar owner_id PK, FK
        numeric balance_available
        numeric balance_held
        timestamp updated_at
    }

    PLOT {
        varchar plot_id PK
        geometry boundary "Polygon SRID 4326"
        numeric length_m
        numeric width_m
        numeric area_sqft
        text street_address
        varchar city
        varchar state
        varchar zip
        timestamp created_at
    }

    REGISTRY_ENTRY {
        varchar registry_id PK
        varchar plot_id UK, FK
        varchar current_owner_id FK
        legal_status_enum legal_status
        bigint last_block_height
        char last_block_hash
        timestamp updated_at
    }

    REGISTRY_STATUS_HISTORY {
        bigserial history_id PK
        varchar registry_id FK
        legal_status_enum old_status
        legal_status_enum new_status
        text reason
        varchar changed_by FK
        timestamp changed_at
    }

    INJUNCTION {
        varchar injunction_id PK
        varchar registry_id FK
        varchar court_case_no
        text court_name
        text injunction_order_details
        varchar issued_by FK
        timestamp issued_at
        varchar lifted_by FK
        timestamp lifted_at
        boolean is_active
    }

    ORDER_BOOK {
        varchar order_id PK
        varchar plot_id FK
        varchar trader_id FK
        order_type_enum order_type
        numeric price
        order_status_enum status
        int nonce
        text signature
        timestamp order_timestamp
        timestamp created_at
    }

    TRADE {
        varchar trade_id PK
        varchar plot_id FK
        varchar seller_id FK
        varchar buyer_id FK
        varchar bid_order_id FK
        varchar ask_order_id FK
        numeric trade_price
        trade_status_enum status
        timestamp executed_at
    }

    TX_COORDINATOR_LOG {
        bigserial log_id PK
        varchar gid UK
        varchar trade_id FK
        varchar phase
        text details
        timestamp logged_at
    }

    AUDIT_LOG {
        bigserial audit_id PK
        varchar actor_user_id
        varchar action
        varchar entity_type
        varchar entity_id
        jsonb metadata
        timestamp logged_at
    }
```

---

## 3. MongoDB Cryptographic Ledger Collection Schema

The append-only ledger collection [`ledger_transaction_block`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/scripts/mongo_init.js) models sequential title deed transactions sealed with ECDSA P-256 signatures:

```mermaid
classDiagram
    class LedgerTransactionBlock {
        +int block_number (Unique)
        +string prev_tx_hash (Unique)
        +string block_type ("GENESIS" | "SALE" | "CORRECTION")
        +string registry_id
        +string plot_id
        +string seller_id
        +string buyer_id
        +double sale_price
        +string seller_signature (ECDSA P-256 DER)
        +string buyer_signature (ECDSA P-256 DER)
        +string timestamp (ISO 8601 UTC)
        +string merkle_root (SHA-256)
        +int nonce (0)
        +string gid (2PC Transaction GID)
        +string tx_id (SHA-256 Canonical JSON)
        +string original_tx_id (CORRECTION blocks only)
        +string requested_by (CORRECTION blocks only)
        +string approved_by (CORRECTION blocks only)
    }
```

---

## 4. Cross-Store Linkage

The bridge between PostgreSQL and MongoDB maintains complete data consistency without dual-master fragility:
1. `registry_entry.last_block_height` points to `ledger_transaction_block.block_number`.
2. `registry_entry.last_block_hash` mirrors `ledger_transaction_block.tx_id`.
3. `tx_coordinator_log.gid` matches `ledger_transaction_block.gid` for two-phase commit DvP (Delivery vs Payment) atomicity.
4. If an in-doubt state occurs during network partitions, PostgreSQL queries MongoDB by `gid` to resolve whether to `COMMIT PREPARED` or `ROLLBACK PREPARED`.
