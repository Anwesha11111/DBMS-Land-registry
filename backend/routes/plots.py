# backend/routes/plots.py
import uuid
import json
from flask import Blueprint, request, jsonify, g
from shapely.geometry import shape, mapping
from backend.services.auth import require_roles, get_current_user
from backend.services.spatial import validate_geojson_polygon, check_plot_overlap, calculate_area_sqft
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

plots_bp = Blueprint("plots", __name__, url_prefix="/plots")

@plots_bp.route("", methods=["POST"], strict_slashes=False)
@plots_bp.route("/", methods=["POST"], strict_slashes=False)
@require_roles(["registry_admin", "sys_admin"])
def register_plot():
    data = request.get_json() or {}
    street_address = data.get("street_address", "").strip()
    city = data.get("city", "").strip()
    state = data.get("state", "").strip()
    zip_code = data.get("zip", "").strip()
    length_m = data.get("length_m")
    width_m = data.get("width_m")
    owner_id = data.get("current_owner_id")
    geojson_geom = data.get("boundary") or data.get("geometry")

    if not all([street_address, city, state, zip_code, length_m, width_m, owner_id, geojson_geom]):
        return jsonify({"error": "Missing required fields: address, city, state, zip, length_m, width_m, current_owner_id, boundary."}), 400

    try:
        length_m = float(length_m)
        width_m = float(width_m)
    except ValueError:
        return jsonify({"error": "length_m and width_m must be positive numeric values."}), 400

    # 1. Validate GeoJSON polygon
    is_valid, val_err, poly = validate_geojson_polygon(geojson_geom)
    if not is_valid:
        return jsonify({"error": f"Invalid plot boundary: {val_err}"}), 400

    # 2. Check Overlap Rule (DECISION 2: reject if ST_Intersects AND NOT ST_Touches)
    has_overlap, conflict_id = check_plot_overlap(poly)
    if has_overlap:
        return jsonify({
            "error": f"Spatial overlap violation: plot boundary intersects with existing plot_id '{conflict_id}' without touching at border.",
            "conflicting_plot_id": conflict_id
        }), 409

    plot_id = data.get("plot_id") or f"plot_{uuid.uuid4().hex[:8]}"
    registry_id = f"reg_{plot_id}"
    area_sqft = calculate_area_sqft(poly)

    # 3. Create plot + registry_entry (status Pending) in one transaction
    if is_mock_mode():
        # Verify owner exists
        if owner_id not in mock_db.owners:
            return jsonify({"error": f"Owner '{owner_id}' not found."}), 404

        mock_db.plots[plot_id] = {
            "plot_id": plot_id,
            "street_address": street_address,
            "city": city,
            "state": state,
            "zip": zip_code,
            "length_m": length_m,
            "width_m": width_m,
            "geojson": mapping(poly),
            "area_sqft": area_sqft
        }
        mock_db.registry[registry_id] = {
            "registry_id": registry_id,
            "plot_id": plot_id,
            "current_owner_id": owner_id,
            "legal_status": "Pending",
            "last_block_height": 0,
            "last_block_hash": "0" * 64
        }
    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    # Check owner
                    cur.execute("SELECT owner_id FROM owner WHERE owner_id = %s;", (owner_id,))
                    if not cur.fetchone():
                        conn.rollback()
                        return jsonify({"error": f"Owner '{owner_id}' does not exist."}), 404

                    # Insert plot
                    geojson_str = json.dumps(mapping(poly))
                    cur.execute(
                        """
                        INSERT INTO plot (plot_id, street_address, city, state, zip, length_m, width_m, boundary)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326));
                        """,
                        (plot_id, street_address, city, state, zip_code, length_m, width_m, geojson_str)
                    )

                    # Insert registry_entry (DECISION 1: only place holding current owner)
                    cur.execute(
                        """
                        INSERT INTO registry_entry (registry_id, plot_id, current_owner_id, legal_status)
                        VALUES (%s, %s, %s, 'Pending');
                        """,
                        (registry_id, plot_id, owner_id)
                    )
                conn.commit()
        except Exception as e:
            if "overlap" in str(e).lower() or "23P01" in str(e):
                return jsonify({"error": str(e)}), 409
            return jsonify({"error": f"Failed to register plot: {str(e)}"}), 500

    log_audit_event("PLOT_REGISTERED", "plot", g.current_user["user_id"], {
        "plot_id": plot_id,
        "owner_id": owner_id,
        "status": "Pending",
        "area_sqft": area_sqft
    })

    return jsonify({
        "message": "Plot and registry entry created successfully in Pending status.",
        "plot_id": plot_id,
        "registry_id": registry_id,
        "legal_status": "Pending",
        "area_sqft": area_sqft
    }), 201

@plots_bp.route("", methods=["GET"], strict_slashes=False)
@plots_bp.route("/", methods=["GET"], strict_slashes=False)
def list_plots():
    city_filter = request.args.get("city")
    state_filter = request.args.get("state")
    status_filter = request.args.get("status")
    owner_filter = request.args.get("owner")

    if is_mock_mode():
        results = []
        for pid, pdata in mock_db.plots.items():
            reg = next((r for r in mock_db.registry.values() if r["plot_id"] == pid), None)
            status = reg["legal_status"] if reg else "Pending"
            owner_id = reg["current_owner_id"] if reg else None

            if city_filter and pdata["city"].lower() != city_filter.lower():
                continue
            if state_filter and pdata["state"].lower() != state_filter.lower():
                continue
            if status_filter and status != status_filter:
                continue
            if owner_filter and owner_id != owner_filter:
                continue

            # Compute best bid and active ask
            bids = [float(o["price"]) for o in mock_db.order_book.values() if o["plot_id"] == pid and o["order_type"] == "BID" and o["status"] == "Open"]
            asks = [float(o["price"]) for o in mock_db.order_book.values() if o["plot_id"] == pid and o["order_type"] == "ASK" and o["status"] == "Open"]

            results.append({
                "plot_id": pid,
                "street_address": pdata["street_address"],
                "city": pdata["city"],
                "state": pdata["state"],
                "zip": pdata["zip"],
                "length_m": pdata["length_m"],
                "width_m": pdata["width_m"],
                "area_sqft": pdata.get("area_sqft", 0),
                "owner_id": owner_id,
                "status": status,
                "best_bid": max(bids) if bids else None,
                "active_ask": min(asks) if asks else None,
                "geojson": pdata["geojson"]
            })
        return jsonify({"plots": results, "count": len(results)}), 200

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                query = "SELECT plot_id, street_address, city, state, zip, length_m, width_m, area_sqft, owner_id, owner_name, status, best_bid, active_ask, geojson FROM v_plot_market WHERE 1=1"
                params = []
                if city_filter:
                    query += " AND LOWER(city) = LOWER(%s)"
                    params.append(city_filter)
                if state_filter:
                    query += " AND LOWER(state) = LOWER(%s)"
                    params.append(state_filter)
                if status_filter:
                    query += " AND status = %s"
                    params.append(status_filter)
                if owner_filter:
                    query += " AND owner_id = %s"
                    params.append(owner_filter)

                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                results = []
                for r in rows:
                    results.append({
                        "plot_id": r[0],
                        "street_address": r[1],
                        "city": r[2],
                        "state": r[3],
                        "zip": r[4],
                        "length_m": float(r[5]),
                        "width_m": float(r[6]),
                        "area_sqft": float(r[7]),
                        "owner_id": r[8],
                        "owner_name": r[9],
                        "status": r[10],
                        "best_bid": float(r[11]) if r[11] is not None else None,
                        "active_ask": float(r[12]) if r[12] is not None else None,
                        "geojson": json.loads(r[13]) if isinstance(r[13], str) else r[13]
                    })
        return jsonify({"plots": results, "count": len(results)}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to fetch plots: {str(e)}"}), 500

@plots_bp.route("/<plot_id>", methods=["GET"])
def get_plot(plot_id: str):
    if is_mock_mode():
        pdata = mock_db.plots.get(plot_id)
        if not pdata:
            return jsonify({"error": "Plot not found"}), 404
        reg = next((r for r in mock_db.registry.values() if r["plot_id"] == plot_id), None)
        return jsonify({
            **pdata,
            "status": reg["legal_status"] if reg else "Unknown",
            "owner_id": reg["current_owner_id"] if reg else None,
            "registry_id": reg["registry_id"] if reg else None
        }), 200

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT plot_id, street_address, city, state, zip, length_m, width_m, area_sqft, owner_id, owner_name, status, best_bid, active_ask, geojson FROM v_plot_market WHERE plot_id = %s;",
                    (plot_id,)
                )
                r = cur.fetchone()
                if not r:
                    return jsonify({"error": "Plot not found"}), 404
                return jsonify({
                    "plot_id": r[0],
                    "street_address": r[1],
                    "city": r[2],
                    "state": r[3],
                    "zip": r[4],
                    "length_m": float(r[5]),
                    "width_m": float(r[6]),
                    "area_sqft": float(r[7]),
                    "owner_id": r[8],
                    "owner_name": r[9],
                    "status": r[10],
                    "best_bid": float(r[11]) if r[11] is not None else None,
                    "active_ask": float(r[12]) if r[12] is not None else None,
                    "geojson": json.loads(r[13]) if isinstance(r[13], str) else r[13]
                }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
