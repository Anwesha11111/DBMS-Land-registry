-- 001_schema.sql: Extensions, ENUM types, and core tables

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- ENUM Types
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('owner_seller', 'buyer', 'registry_admin', 'court', 'public', 'sys_admin');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE legal_status_enum AS ENUM ('Clear', 'Pending', 'Disputed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE order_type_enum AS ENUM ('BID', 'ASK');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE order_status_enum AS ENUM ('Open', 'Matched', 'Cancelled', 'On_Hold', 'Settled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE trade_status_enum AS ENUM ('Pending', 'Settled', 'Failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Table: owner
CREATE TABLE IF NOT EXISTS owner (
    owner_id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    contact VARCHAR(100) NOT NULL,
    kyc_hash VARCHAR(64) UNIQUE NOT NULL,
    public_key TEXT NOT NULL,
    wallet_address VARCHAR(64) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: users
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role user_role NOT NULL,
    mfa_secret VARCHAR(64),
    owner_id VARCHAR(64) REFERENCES owner(owner_id) ON DELETE SET NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: wallet
CREATE TABLE IF NOT EXISTS wallet (
    owner_id VARCHAR(64) PRIMARY KEY REFERENCES owner(owner_id) ON DELETE CASCADE,
    balance_available NUMERIC(16, 2) NOT NULL DEFAULT 0.00 CHECK (balance_available >= 0),
    balance_held NUMERIC(16, 2) NOT NULL DEFAULT 0.00 CHECK (balance_held >= 0),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: plot
CREATE TABLE IF NOT EXISTS plot (
    plot_id VARCHAR(64) PRIMARY KEY,
    street_address TEXT NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    zip VARCHAR(20) NOT NULL,
    length_m NUMERIC(10, 2) NOT NULL CHECK (length_m > 0),
    width_m NUMERIC(10, 2) NOT NULL CHECK (width_m > 0),
    boundary GEOMETRY(Polygon, 4326) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_valid_boundary CHECK (ST_IsValid(boundary)),
    CONSTRAINT check_polygon_type CHECK (ST_GeometryType(boundary) = 'ST_Polygon')
);

CREATE INDEX IF NOT EXISTS idx_plot_boundary_gist ON plot USING GIST (boundary);

-- Table: registry_entry
-- DECISION 1: registry_entry is the single source of truth holding current owner.
CREATE TABLE IF NOT EXISTS registry_entry (
    registry_id VARCHAR(64) PRIMARY KEY,
    plot_id VARCHAR(64) UNIQUE NOT NULL REFERENCES plot(plot_id) ON DELETE RESTRICT,
    current_owner_id VARCHAR(64) NOT NULL REFERENCES owner(owner_id) ON DELETE RESTRICT,
    legal_status legal_status_enum NOT NULL DEFAULT 'Pending',
    last_block_height BIGINT NOT NULL DEFAULT 0,
    last_block_hash VARCHAR(64) NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_registry_entry_owner ON registry_entry(current_owner_id);
CREATE INDEX IF NOT EXISTS idx_registry_entry_status ON registry_entry(legal_status);

-- Table: registry_status_history
CREATE TABLE IF NOT EXISTS registry_status_history (
    id SERIAL PRIMARY KEY,
    registry_id VARCHAR(64) NOT NULL REFERENCES registry_entry(registry_id) ON DELETE CASCADE,
    old_status legal_status_enum,
    new_status legal_status_enum NOT NULL,
    changed_by VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: injunction
CREATE TABLE IF NOT EXISTS injunction (
    id SERIAL PRIMARY KEY,
    registry_id VARCHAR(64) NOT NULL REFERENCES registry_entry(registry_id) ON DELETE CASCADE,
    court_user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
    case_ref VARCHAR(100) NOT NULL,
    placed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    lifted_at TIMESTAMP WITH TIME ZONE
);

-- Table: order_book
CREATE TABLE IF NOT EXISTS order_book (
    order_id VARCHAR(64) PRIMARY KEY,
    plot_id VARCHAR(64) NOT NULL REFERENCES plot(plot_id) ON DELETE CASCADE,
    trader_id VARCHAR(64) NOT NULL REFERENCES owner(owner_id) ON DELETE CASCADE,
    order_type order_type_enum NOT NULL,
    price NUMERIC(16, 2) NOT NULL CHECK (price > 0),
    order_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status order_status_enum NOT NULL DEFAULT 'Open',
    signature TEXT NOT NULL,
    hold_reason TEXT
);

-- DECISION 3: At most one Open Ask per plot
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_ask_per_plot 
ON order_book(plot_id) 
WHERE (order_type = 'ASK' AND status = 'Open');

CREATE INDEX IF NOT EXISTS idx_order_book_lookup 
ON order_book(plot_id, order_type, status, price, order_timestamp);

-- Table: trade
CREATE TABLE IF NOT EXISTS trade (
    trade_id VARCHAR(64) PRIMARY KEY,
    bid_order_id VARCHAR(64) NOT NULL REFERENCES order_book(order_id),
    ask_order_id VARCHAR(64) NOT NULL REFERENCES order_book(order_id),
    plot_id VARCHAR(64) NOT NULL REFERENCES plot(plot_id),
    price NUMERIC(16, 2) NOT NULL CHECK (price > 0),
    status trade_status_enum NOT NULL DEFAULT 'Pending',
    gid VARCHAR(128) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: tx_coordinator_log
CREATE TABLE IF NOT EXISTS tx_coordinator_log (
    gid VARCHAR(128) PRIMARY KEY,
    trade_id VARCHAR(64) NOT NULL REFERENCES trade(trade_id),
    phase VARCHAR(32) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table: audit_log
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id SERIAL PRIMARY KEY,
    user_id VARCHAR(64),
    action VARCHAR(64) NOT NULL,
    entity VARCHAR(64) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip VARCHAR(45),
    ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts DESC);

-- Table: state_rules
CREATE TABLE IF NOT EXISTS state_rules (
    state VARCHAR(100) NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    value JSONB NOT NULL,
    effective_from TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (state, rule_type, effective_from)
);
