# backend/routes/search.py
from flask import Blueprint, request, jsonify
from backend.services.auth import get_current_user
from backend.db.connection import get_pg_connection, get_mongo_db, is_mock_mode
from backend.db.mock_store import mock_db

search_bp = Blueprint("search", __name__, url_prefix="/search")

@search_bp.route("", methods=["GET"])
def global_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"results": {"plots": [], "owners": [], "transactions": [], "registry": []}}), 200

    user = get_current_user()
    is_authorized_for_owner_names = user and user.get("role") in ("registry_admin", "court", "sys_admin")

    matched_plots = []
    matched_owners = []
    matched_registry = []
    matched_transactions = []

    q_lower = query.lower()

    if is_mock_mode():
        # Search plots
        for pid, p in mock_db.plots.items():
            if (q_lower in pid.lower() or 
                q_lower in p.get("street_address", "").lower() or 
                q_lower in p.get("city", "").lower() or
                q_lower in p.get("zip", "").lower()):
                matched_plots.append({
                    "plot_id": pid,
                    "address": f"{p.get('street_address')}, {p.get('city')}",
                    "zip": p.get("zip")
                })

        # Search owners
        for oid, o in mock_db.owners.items():
            if q_lower in oid.lower() or (is_authorized_for_owner_names and q_lower in o.get("full_name", "").lower()):
                matched_owners.append({
                    "owner_id": oid,
                    "full_name": o.get("full_name") if is_authorized_for_owner_names else "REDACTED",
                    "wallet_address": o.get("wallet_address")
                })

        # Search registry
        for rid, r in mock_db.registry.items():
            if q_lower in rid.lower() or q_lower in r.get("plot_id", "").lower():
                matched_registry.append(r)

    else:
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    # Plots
                    cur.execute(
                        """
                        SELECT plot_id, street_address, city, zip FROM plot
                        WHERE plot_id ILIKE %s OR street_address ILIKE %s OR city ILIKE %s OR zip ILIKE %s
                        LIMIT 10;
                        """,
                        (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")
                    )
                    for r in cur.fetchall():
                        matched_plots.append({"plot_id": r[0], "address": f"{r[1]}, {r[2]}", "zip": r[3]})

                    # Owners
                    if is_authorized_for_owner_names:
                        cur.execute(
                            "SELECT owner_id, full_name, wallet_address FROM owner WHERE owner_id ILIKE %s OR full_name ILIKE %s LIMIT 10;",
                            (f"%{query}%", f"%{query}%")
                        )
                        for r in cur.fetchall():
                            matched_owners.append({"owner_id": r[0], "full_name": r[1], "wallet_address": r[2]})
                    else:
                        cur.execute(
                            "SELECT owner_id, wallet_address FROM owner WHERE owner_id ILIKE %s LIMIT 10;",
                            (f"%{query}%",)
                        )
                        for r in cur.fetchall():
                            matched_owners.append({"owner_id": r[0], "full_name": "REDACTED", "wallet_address": r[1]})

                    # Registry
                    cur.execute(
                        "SELECT registry_id, plot_id, legal_status, current_owner_id FROM registry_entry WHERE registry_id ILIKE %s OR plot_id ILIKE %s LIMIT 10;",
                        (f"%{query}%", f"%{query}%")
                    )
                    for r in cur.fetchall():
                        matched_registry.append({"registry_id": r[0], "plot_id": r[1], "legal_status": r[2], "current_owner_id": r[3]})

        except Exception:
            pass

    # Search transactions in MongoDB ledger
    try:
        col = get_mongo_db()["ledger_transaction_block"]
        tx_cursor = col.find({
            "$or": [
                {"tx_id": {"$regex": query, "$options": "i"}},
                {"plot_id": {"$regex": query, "$options": "i"}},
                {"gid": {"$regex": query, "$options": "i"}}
            ]
        }).limit(10)
        for t in tx_cursor:
            matched_transactions.append({
                "block_number": t.get("block_number"),
                "tx_id": t.get("tx_id"),
                "plot_id": t.get("plot_id"),
                "block_type": t.get("block_type"),
                "timestamp": t.get("timestamp")
            })
    except Exception:
        pass

    return jsonify({
        "query": query,
        "results": {
            "plots": matched_plots,
            "owners": matched_owners,
            "registry": matched_registry,
            "transactions": matched_transactions
        }
    }), 200
