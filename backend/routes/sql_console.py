# backend/routes/sql_console.py
"""
SQL Problem Solver & Evaluator Console Blueprint.
Allows students, teachers, and evaluators to execute SQL queries directly against
the Land Registry database (PostgreSQL or Mock Store) and view tabular results,
schema reference, execution times, and pre-built problem challenge statements.
"""

import time
import re
from typing import Dict, Any, List
from flask import Blueprint, request, jsonify
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

sql_console_bp = Blueprint("sql_console", __name__, url_prefix="/api/sql")

CHALLENGES = [
    {
        "id": "challenge_1",
        "title": "Problem 1: High-Value Residential Parcels",
        "description": "Retrieve the plot_id, street_address, area_sqft, and length_m of all plots that have an area strictly greater than 8,000 sq ft, ordered by area descending.",
        "difficulty": "Easy",
        "category": "Parcels & Spatial Attributes",
        "hint": "SELECT plot_id, street_address, area_sqft, length_m FROM plot WHERE area_sqft > 8000 ORDER BY area_sqft DESC;",
        "default_query": "SELECT plot_id, street_address, area_sqft, length_m\nFROM plot\nWHERE area_sqft > 8000\nORDER BY area_sqft DESC;"
    },
    {
        "id": "challenge_2",
        "title": "Problem 2: Verified Title Clear Plots",
        "description": "Find all plots whose legal_status is 'Clear' in the title registry. Include plot_id, current_owner_id, legal_status, and last_block_height.",
        "difficulty": "Easy",
        "category": "Registry & Title",
        "hint": "SELECT plot_id, current_owner_id, legal_status, last_block_height FROM registry_entry WHERE legal_status = 'Clear';",
        "default_query": "SELECT plot_id, current_owner_id, legal_status, last_block_height\nFROM registry_entry\nWHERE legal_status = 'Clear'\nORDER BY last_block_height DESC;"
    },
    {
        "id": "challenge_3",
        "title": "Problem 3: Court Injunctions & Disputed Parcels",
        "description": "List all parcels currently tied to an active court injunction or marked as 'Disputed'. Retrieve the plot_id, case_number, court_name, and reason.",
        "difficulty": "Medium",
        "category": "Court & Legal Enforcement",
        "hint": "SELECT plot_id, case_number, court_name, reason, is_active FROM injunction WHERE is_active = TRUE;",
        "default_query": "SELECT plot_id, case_number, court_name, reason, is_active\nFROM injunction\nWHERE is_active = TRUE;"
    },
    {
        "id": "challenge_4",
        "title": "Problem 4: Active Buy Orders (Bid Depth)",
        "description": "Find all Open 'BID' orders across all plots. Return plot_id, trader_id, price, and order_timestamp, ordered by price descending (highest bid first).",
        "difficulty": "Medium",
        "category": "Exchange & Order Book",
        "hint": "SELECT plot_id, trader_id, price, status, order_timestamp FROM order_book WHERE order_type = 'BID' AND status = 'Open' ORDER BY price DESC;",
        "default_query": "SELECT plot_id, trader_id, price, status, order_timestamp\nFROM order_book\nWHERE order_type = 'BID' AND status = 'Open'\nORDER BY price DESC;"
    },
    {
        "id": "challenge_5",
        "title": "Problem 5: Trader Liquidity & Available Wallets",
        "description": "Show the balance sheet for all traders: return trader_id, available_balance, held_balance, and calculate total_equity = available_balance + held_balance.",
        "difficulty": "Medium",
        "category": "Financial Wallets & DvP",
        "hint": "SELECT trader_id, available_balance, held_balance, (available_balance + held_balance) AS total_equity FROM wallet ORDER BY total_equity DESC;",
        "default_query": "SELECT trader_id, available_balance, held_balance,\n       (available_balance + held_balance) AS total_equity\nFROM wallet\nORDER BY total_equity DESC;"
    },
    {
        "id": "challenge_6",
        "title": "Problem 6: Spatial Touch & Overlap Evaluation (PostGIS)",
        "description": "Verify PostGIS polygon validity and check for boundary intersection against a reference test coordinate.",
        "difficulty": "Hard (PostGIS)",
        "category": "Spatial & Cadastre",
        "hint": "SELECT plot_id, ST_IsValid(boundary) AS is_valid, ST_Area(boundary::geography) AS area_sqm FROM plot LIMIT 5;",
        "default_query": "SELECT plot_id, street_address, ST_IsValid(boundary) AS is_valid\nFROM plot\nLIMIT 10;"
    }
]

TABLE_SCHEMAS = {
    "plot": [
        {"column": "plot_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "street_address", "type": "VARCHAR(255)", "constraint": "NOT NULL"},
        {"column": "city", "type": "VARCHAR(100)", "constraint": "DEFAULT 'Bengaluru'"},
        {"column": "state", "type": "VARCHAR(100)", "constraint": "DEFAULT 'Karnataka'"},
        {"column": "zip", "type": "VARCHAR(20)", "constraint": "NOT NULL"},
        {"column": "length_m", "type": "NUMERIC(10,2)", "constraint": "NOT NULL"},
        {"column": "width_m", "type": "NUMERIC(10,2)", "constraint": "NOT NULL"},
        {"column": "area_sqft", "type": "NUMERIC(12,2)", "constraint": "NOT NULL"},
        {"column": "boundary", "type": "GEOMETRY(Polygon, 4326)", "constraint": "GIST INDEX"}
    ],
    "registry_entry": [
        {"column": "registry_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "plot_id", "type": "VARCHAR(64)", "constraint": "UNIQUE REFERENCES plot"},
        {"column": "current_owner_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "legal_status", "type": "VARCHAR(32)", "constraint": "Clear | Pending | Disputed"},
        {"column": "last_block_height", "type": "INTEGER", "constraint": "NOT NULL"},
        {"column": "last_block_hash", "type": "VARCHAR(64)", "constraint": "NOT NULL"}
    ],
    "owner": [
        {"column": "owner_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "full_name", "type": "VARCHAR(255)", "constraint": "NOT NULL"},
        {"column": "email", "type": "VARCHAR(255)", "constraint": "UNIQUE"},
        {"column": "phone", "type": "VARCHAR(32)", "constraint": "NOT NULL"},
        {"column": "kyc_hash", "type": "VARCHAR(64)", "constraint": "UNIQUE (SHA-256)"},
        {"column": "public_key", "type": "TEXT", "constraint": "ECDSA P-256"}
    ],
    "wallet": [
        {"column": "trader_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "available_balance", "type": "NUMERIC(18,2)", "constraint": ">= 0"},
        {"column": "held_balance", "type": "NUMERIC(18,2)", "constraint": ">= 0"}
    ],
    "order_book": [
        {"column": "order_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "plot_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "trader_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "order_type", "type": "VARCHAR(8)", "constraint": "BID | ASK"},
        {"column": "price", "type": "NUMERIC(18,2)", "constraint": "NOT NULL"},
        {"column": "status", "type": "VARCHAR(16)", "constraint": "Open | Matched | Cancelled | On_Hold | Settled"},
        {"column": "order_timestamp", "type": "TIMESTAMP", "constraint": "DEFAULT NOW()"}
    ],
    "injunction": [
        {"column": "injunction_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "plot_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "case_number", "type": "VARCHAR(128)", "constraint": "NOT NULL"},
        {"column": "court_name", "type": "VARCHAR(255)", "constraint": "NOT NULL"},
        {"column": "reason", "type": "TEXT", "constraint": "NOT NULL"},
        {"column": "is_active", "type": "BOOLEAN", "constraint": "DEFAULT TRUE"}
    ],
    "trade": [
        {"column": "trade_id", "type": "VARCHAR(64)", "constraint": "PRIMARY KEY"},
        {"column": "plot_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "bid_order_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "ask_order_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "buyer_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "seller_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "price", "type": "NUMERIC(18,2)", "constraint": "NOT NULL"},
        {"column": "settlement_gid", "type": "VARCHAR(128)", "constraint": "2PC GID"}
    ],
    "audit_log": [
        {"column": "log_id", "type": "BIGINT", "constraint": "PRIMARY KEY AUTO_INCREMENT"},
        {"column": "action", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "entity_type", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "actor_id", "type": "VARCHAR(64)", "constraint": "NOT NULL"},
        {"column": "timestamp", "type": "TIMESTAMP", "constraint": "DEFAULT NOW()"}
    ]
}


@sql_console_bp.route("/challenges", methods=["GET"])
def get_challenges():
    """Returns the list of practice problems/challenges for students."""
    return jsonify({
        "status": "success",
        "challenges": CHALLENGES,
        "schemas": TABLE_SCHEMAS
    }), 200


@sql_console_bp.route("/execute", methods=["POST"])
def execute_query():
    """
    Executes a student's SQL query.
    Enforces security (prevents destructive commands like DROP DATABASE, SHUTDOWN).
    Works against live PostgreSQL when available or against MockStore tables.
    """
    body = request.get_json() or {}
    raw_query = body.get("query", "").strip()

    if not raw_query:
        return jsonify({"error": "Empty query provided."}), 400

    # Safety checks
    forbidden_patterns = [
        r"\bDROP\s+DATABASE\b",
        r"\bTRUNCATE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
        r"\bSHUTDOWN\b",
        r"\bALTER\s+SYSTEM\b"
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, raw_query, re.IGNORECASE):
            return jsonify({
                "error": "Destructive or administrative statement is disabled in the SQL workbench."
            }), 403

    start_time = time.time()

    if not is_mock_mode():
        # Live PostgreSQL Execution
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(raw_query)
                    exec_time_ms = round((time.time() - start_time) * 1000, 2)
                    if cur.description:
                        columns = [col[0] for col in cur.description]
                        rows = cur.fetchall()
                        # Format rows into serializable JSON
                        formatted_rows = []
                        for row in rows:
                            formatted_rows.append([
                                str(val) if val is not None else None
                                for val in row
                            ])
                        return jsonify({
                            "status": "success",
                            "columns": columns,
                            "rows": formatted_rows,
                            "row_count": len(formatted_rows),
                            "execution_time_ms": exec_time_ms,
                            "engine": "PostgreSQL 16 + PostGIS"
                        }), 200
                    else:
                        conn.commit()
                        return jsonify({
                            "status": "success",
                            "columns": ["Result"],
                            "rows": [[f"Statement executed successfully. Affected rows: {cur.rowcount}"]],
                            "row_count": cur.rowcount,
                            "execution_time_ms": exec_time_ms,
                            "engine": "PostgreSQL 16 + PostGIS"
                        }), 200
        except Exception as e:
            exec_time_ms = round((time.time() - start_time) * 1000, 2)
            return jsonify({
                "status": "error",
                "error": str(e),
                "execution_time_ms": exec_time_ms,
                "engine": "PostgreSQL 16 + PostGIS"
            }), 400

    # Fallback to Mock Store Query Evaluator
    try:
        columns, rows = _eval_mock_query(raw_query)
        exec_time_ms = round((time.time() - start_time) * 1000, 2)
        return jsonify({
            "status": "success",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": exec_time_ms,
            "engine": "In-Memory Simulation Store"
        }), 200
    except Exception as e:
        exec_time_ms = round((time.time() - start_time) * 1000, 2)
        return jsonify({
            "status": "error",
            "error": str(e),
            "execution_time_ms": exec_time_ms,
            "engine": "In-Memory Simulation Store"
        }), 400


def _eval_mock_query(sql: str):
    """
    Simulates standard SQL queries on mock_db in-memory dictionaries.
    Handles SELECT from plot, registry_entry, owner, wallet, order_book, injunction, trade, audit_log.
    """
    clean_sql = " ".join(sql.strip().split())
    upper_sql = clean_sql.upper()

    # Identify target table
    table_match = re.search(r"\bFROM\s+([a-zA-Z0-9_]+)", upper_sql)
    if not table_match:
        # Default or scalar query e.g. SELECT 1;
        if "SELECT 1" in upper_sql:
            return ["?column?"], [[1]]
        return ["Result"], [["Mock SQL Executor Ready"]]

    table_name = table_match.group(1).lower()
    
    # Map to mock_db stores
    data_source = []
    if table_name in ("plot", "parcels"):
        for p in mock_db.plots.values():
            data_source.append({
                "plot_id": p.get("plot_id"),
                "street_address": p.get("street_address"),
                "city": p.get("city", "Bengaluru"),
                "state": p.get("state", "Karnataka"),
                "zip": p.get("zip", "560001"),
                "length_m": p.get("length_m"),
                "width_m": p.get("width_m"),
                "area_sqft": p.get("area_sqft"),
                "boundary": p.get("boundary", "")[:30] + "..." if p.get("boundary") else None,
                "is_valid": True
            })
    elif table_name in ("registry_entry", "registry"):
        for r in mock_db.registry.values():
            data_source.append({
                "registry_id": r.get("registry_id"),
                "plot_id": r.get("plot_id"),
                "current_owner_id": r.get("current_owner_id"),
                "legal_status": r.get("legal_status"),
                "last_block_height": r.get("last_block_height"),
                "last_block_hash": r.get("last_block_hash")
            })
    elif table_name in ("owner", "users", "trader"):
        for o in mock_db.owners.values():
            data_source.append({
                "owner_id": o.get("owner_id"),
                "full_name": o.get("full_name"),
                "email": o.get("email"),
                "phone": o.get("phone"),
                "kyc_hash": o.get("kyc_hash"),
                "public_key": (o.get("public_key") or "")[:20] + "..."
            })
    elif table_name == "wallet":
        for w in mock_db.wallets.values():
            avail = float(w.get("available_balance", 0.0))
            held = float(w.get("held_balance", 0.0))
            data_source.append({
                "trader_id": w.get("trader_id"),
                "available_balance": avail,
                "held_balance": held,
                "total_equity": avail + held
            })
    elif table_name == "order_book":
        for o in mock_db.order_book.values():
            data_source.append({
                "order_id": o.get("order_id"),
                "plot_id": o.get("plot_id"),
                "trader_id": o.get("trader_id"),
                "order_type": o.get("order_type"),
                "price": float(o.get("price", 0.0)),
                "status": o.get("status"),
                "order_timestamp": o.get("order_timestamp")
            })
    elif table_name == "injunction":
        for inj in mock_db.injunctions:
            data_source.append({
                "injunction_id": inj.get("injunction_id"),
                "plot_id": inj.get("plot_id"),
                "case_number": inj.get("case_number"),
                "court_name": inj.get("court_name"),
                "reason": inj.get("reason"),
                "is_active": inj.get("is_active", True)
            })
    elif table_name == "trade":
        for t in mock_db.trades.values():
            data_source.append({
                "trade_id": t.get("trade_id"),
                "plot_id": t.get("plot_id"),
                "buyer_id": t.get("buyer_id"),
                "seller_id": t.get("seller_id"),
                "price": float(t.get("price", 0.0)),
                "settlement_gid": t.get("settlement_gid")
            })
    elif table_name == "audit_log":
        for a in mock_db.audit_logs:
            data_source.append({
                "log_id": a.get("log_id"),
                "action": a.get("action"),
                "entity_type": a.get("entity_type"),
                "actor_id": a.get("actor_id"),
                "timestamp": a.get("timestamp")
            })
    else:
        raise ValueError(f"Table '{table_name}' does not exist in schema.")

    if not data_source:
        # Empty table
        if table_name in TABLE_SCHEMAS:
            cols = [col["column"] for col in TABLE_SCHEMAS[table_name]]
            return cols, []
        return ["id"], []

    # Extract requested columns from SELECT ... FROM
    select_match = re.search(r"SELECT\s+(.*?)\s+FROM", upper_sql, re.IGNORECASE)
    select_cols_raw = select_match.group(1).strip() if select_match else "*"

    # Apply Basic WHERE filtering
    filtered_rows = data_source
    if "WHERE" in upper_sql:
        where_clause = clean_sql[upper_sql.find("WHERE") + 5 :]
        if "ORDER BY" in where_clause.upper():
            where_clause = where_clause[: where_clause.upper().find("ORDER BY")]
        if "LIMIT" in where_clause.upper():
            where_clause = where_clause[: where_clause.upper().find("LIMIT")]
        where_clause = where_clause.strip()

        # Simple condition checks
        filtered_rows = []
        for row in data_source:
            match = True
            # Numeric condition check: col > val or col >= val or col < val
            num_cond = re.search(r"([a-zA-Z0-9_]+)\s*(>=|<=|>|<|=)\s*([0-9\.]+)", where_clause)
            if num_cond:
                col_name, op, val_str = num_cond.group(1), num_cond.group(2), float(num_cond.group(3))
                val = float(row.get(col_name, 0.0) or 0.0)
                if op == ">" and not (val > val_str): match = False
                elif op == ">=" and not (val >= val_str): match = False
                elif op == "<" and not (val < val_str): match = False
                elif op == "<=" and not (val <= val_str): match = False
                elif op == "=" and not (val == val_str): match = False

            # String equality check: col = 'value'
            str_cond = re.search(r"([a-zA-Z0-9_]+)\s*=\s*'([^']+)'", where_clause)
            if str_cond:
                col_name, val_str = str_cond.group(1), str_cond.group(2)
                if str(row.get(col_name)) != val_str:
                    match = False

            # Boolean check: col = TRUE or col = FALSE
            bool_cond = re.search(r"([a-zA-Z0-9_]+)\s*=\s*(TRUE|FALSE)", where_clause, re.IGNORECASE)
            if bool_cond:
                col_name, b_val = bool_cond.group(1), bool_cond.group(2).upper() == "TRUE"
                if row.get(col_name) != b_val:
                    match = False

            if match:
                filtered_rows.append(row)

    # Apply Basic ORDER BY
    if "ORDER BY" in upper_sql:
        order_clause = clean_sql[upper_sql.find("ORDER BY") + 8 :]
        if "LIMIT" in order_clause.upper():
            order_clause = order_clause[: order_clause.upper().find("LIMIT")]
        order_parts = order_clause.strip().split()
        if order_parts:
            sort_col = order_parts[0].strip(",")
            desc = "DESC" in [p.upper() for p in order_parts]
            filtered_rows.sort(key=lambda r: (r.get(sort_col) is None, r.get(sort_col)), reverse=desc)

    # Apply Basic LIMIT
    if "LIMIT" in upper_sql:
        limit_match = re.search(r"LIMIT\s+([0-9]+)", upper_sql)
        if limit_match:
            limit_val = int(limit_match.group(1))
            filtered_rows = filtered_rows[:limit_val]

    # Project Columns
    if select_cols_raw == "*":
        cols = list(data_source[0].keys())
    else:
        # Split by comma (ignoring expressions)
        raw_items = [c.strip() for c in select_cols_raw.split(",")]
        cols = []
        for item in raw_items:
            # Handle AS alias
            if " AS " in item.upper():
                alias = item.upper().split(" AS ")[1].strip()
                cols.append(alias.lower())
            elif "." in item:
                cols.append(item.split(".")[1].strip().lower())
            else:
                # check functions like ST_IsValid(boundary)
                if "(" in item and ")" in item:
                    func_name = item[: item.find("(")].strip().lower()
                    cols.append(func_name)
                else:
                    cols.append(item.lower())

    results = []
    for r in filtered_rows:
        row_vals = []
        for c in cols:
            val = r.get(c)
            if val is None:
                # Try finding in keys case-insensitively
                for k, v in r.items():
                    if k.lower() == c.lower():
                        val = v
                        break
            row_vals.append(str(val) if val is not None else None)
        results.append(row_vals)

    return cols, results
