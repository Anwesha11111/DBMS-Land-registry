# backend/routes/public.py
from flask import Blueprint, request, jsonify
from backend.services.ledger import verify_chain, get_title_chain
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db
import json

public_bp = Blueprint("public", __name__, url_prefix="/public")

# Simple rate limiter (in-memory sliding count per IP)
_ip_request_counts = {}

def is_rate_limited(ip: str, limit: int = 120, window_sec: int = 60) -> bool:
    import time
    now = time.time()
    if ip not in _ip_request_counts:
        _ip_request_counts[ip] = []
    # Prune old timestamps
    _ip_request_counts[ip] = [t for t in _ip_request_counts[ip] if now - t < window_sec]
    if len(_ip_request_counts[ip]) >= limit:
        return True
    _ip_request_counts[ip].append(now)
    return False

@public_bp.before_request
def check_public_rate_limit():
    ip = request.remote_addr or "127.0.0.1"
    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit exceeded. Please wait before making more public requests."}), 429

@public_bp.route("/plots", methods=["GET"])
def get_public_plots():
    """Unauthenticated public market feed for 3D viewer."""
    if is_mock_mode():
        plots_list = []
        for pid, p in mock_db.plots.items():
            reg = next((r for r in mock_db.registry.values() if r["plot_id"] == pid), None)
            plots_list.append({
                "plot_id": pid,
                "street_address": p.get("street_address"),
                "city": p.get("city"),
                "status": reg["legal_status"] if reg else "Pending",
                "area_sqft": p.get("area_sqft", 0),
                "geojson": p.get("geojson")
            })
        return jsonify({"plots": plots_list}), 200

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT plot_id, street_address, city, state, zip, area_sqft, status, best_bid, active_ask, geojson FROM v_plot_market;"
                )
                rows = cur.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "plot_id": r[0],
                        "street_address": r[1],
                        "city": r[2],
                        "state": r[3],
                        "zip": r[4],
                        "area_sqft": float(r[5]),
                        "status": r[6],
                        "best_bid": float(r[7]) if r[7] is not None else None,
                        "active_ask": float(r[8]) if r[8] is not None else None,
                        "geojson": json.loads(r[9]) if isinstance(r[9], str) else r[9]
                    })
        return jsonify({"plots": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@public_bp.route("/verify/<plot_id>", methods=["GET"])
def verify_plot_public(plot_id: str):
    """
    Public cryptographic chain verification.
    Recomputes hash pointers from Genesis, verifies all blocks,
    and returns PASS / FAIL with detailed tamper explanation if failed.
    """
    res = verify_chain(plot_id=plot_id)
    return jsonify({
        "plot_id": plot_id,
        "result": "PASS" if res["verified"] else "FAIL",
        "verified": res["verified"],
        "details": res["details"] if res["verified"] else res.get("error"),
        "first_bad_block": res.get("first_bad_block"),
        "blocks_checked": res.get("blocks_checked", 0),
        "latest_block_number": res.get("latest_block_number"),
        "latest_tx_id": res.get("latest_tx_id")
    }), 200

@public_bp.route("/title-chain/<plot_id>", methods=["GET"])
def get_public_title_chain(plot_id: str):
    """Returns the ordered title history containing only public-safe transaction attributes."""
    chain = get_title_chain(plot_id)
    return jsonify({
        "plot_id": plot_id,
        "chain_length": len(chain),
        "chain": chain
    }), 200
