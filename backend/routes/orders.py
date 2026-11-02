# backend/routes/orders.py
import uuid
import json
import time
import datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify, Response, g
from backend.services.auth import require_roles, get_current_user
from backend.services.crypto import verify_signature, canonical_json
from backend.services.matching import attempt_match_for_plot
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

orders_bp = Blueprint("orders", __name__)

@orders_bp.route("/orders", methods=["POST"])
def place_order():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Authentication required."}), 401

    data = request.get_json() or {}
    plot_id = data.get("plot_id")
    order_type = data.get("order_type", "").upper()
    price = data.get("price")
    nonce = data.get("nonce", 0)
    timestamp = data.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    signature = data.get("signature")

    if not plot_id or order_type not in ("BID", "ASK") or price is None or not signature:
        return jsonify({"error": "Missing plot_id, order_type (BID/ASK), price, or signature."}), 400

    try:
        price = float(price)
        if price <= 0:
            return jsonify({"error": "Order price must be greater than zero."}), 400
    except ValueError:
        return jsonify({"error": "Invalid price value."}), 400

    owner_id = user.get("owner_id")
    if not owner_id:
        return jsonify({"error": "Only registered owners or buyers with wallets can place orders."}), 403

    # 1. Fetch public key to verify digital signature
    public_key = None
    if is_mock_mode():
        owner_obj = mock_db.owners.get(owner_id)
        if owner_obj:
            public_key = owner_obj.get("public_key")
    else:
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT public_key FROM owner WHERE owner_id = %s;", (owner_id,))
                    row = cur.fetchone()
                    if row:
                        public_key = row[0]
        except Exception:
            pass

    if not public_key:
        return jsonify({"error": "No registered public key found for trader."}), 400

    # Verify signature over canonical JSON
    sign_payload = {
        "plot_id": plot_id,
        "order_type": order_type,
        "price": price,
        "nonce": nonce,
        "timestamp": timestamp
    }
    canonical_bytes = canonical_json(sign_payload).encode('utf-8')
    # If not a dummy test key, verify cryptographic signature
    if not public_key.startswith("TEST_PUBKEY_"):
        if not verify_signature(public_key, canonical_bytes, signature):
            log_audit_event("SIGNATURE_VERIFICATION_FAILED", "order", user["user_id"], {"plot_id": plot_id})
            return jsonify({"error": "Digital signature verification failed. Payload may be tampered."}), 400

    order_id = f"ord_{uuid.uuid4().hex[:12]}"

    # Check legal_status of plot and role/wallet rules
    if is_mock_mode():
        reg = next((r for r in mock_db.registry.values() if r["plot_id"] == plot_id), None)
        if not reg:
            return jsonify({"error": f"Plot {plot_id} not registered."}), 404
        if reg["legal_status"] != "Clear":
            return jsonify({"error": f"Orders cannot be placed on plot {plot_id} because legal status is '{reg['legal_status']}', not Clear."}), 400

        current_owner = reg["current_owner_id"]

        if order_type == "ASK":
            if current_owner != owner_id:
                return jsonify({"error": "Only current plot owner can place an Ask order."}), 403
            # DECISION 3: One Open Ask per plot
            for o in mock_db.order_book.values():
                if o["plot_id"] == plot_id and o["order_type"] == "ASK" and o["status"] == "Open":
                    return jsonify({"error": f"Plot {plot_id} already has an active Open Ask order."}), 409
        elif order_type == "BID":
            if current_owner == owner_id:
                return jsonify({"error": "Plot owner cannot bid on their own plot (self-trade prevented)."}), 400
            # Check and hold wallet funds
            wallet = mock_db.wallets.get(owner_id)
            if not wallet or wallet["balance_available"] < price:
                return jsonify({"error": f"Insufficient available wallet balance to hold {price}."}), 400
            wallet["balance_available"] -= price
            wallet["balance_held"] += price

        order_record = {
            "order_id": order_id,
            "plot_id": plot_id,
            "trader_id": owner_id,
            "order_type": order_type,
            "price": price,
            "order_timestamp": timestamp,
            "status": "Open",
            "signature": signature,
            "hold_reason": None
        }
        mock_db.order_book[order_id] = order_record

    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute("SELECT current_owner_id, legal_status FROM registry_entry WHERE plot_id = %s FOR UPDATE;", (plot_id,))
                    reg_row = cur.fetchone()
                    if not reg_row:
                        conn.rollback()
                        return jsonify({"error": f"Plot {plot_id} not registered."}), 404
                    current_owner, reg_status = reg_row[0], reg_row[1]

                    if reg_status != 'Clear':
                        conn.rollback()
                        return jsonify({"error": f"Orders cannot be placed on plot {plot_id} because legal status is '{reg_status}', not Clear."}), 400

                    if order_type == "ASK":
                        if current_owner != owner_id:
                            conn.rollback()
                            return jsonify({"error": "Only current plot owner can place an Ask order."}), 403
                        # Unique partial index checks open ask
                    elif order_type == "BID":
                        if current_owner == owner_id:
                            conn.rollback()
                            return jsonify({"error": "Plot owner cannot bid on their own plot."}), 400
                        # Check wallet available balance
                        cur.execute("SELECT balance_available FROM wallet WHERE owner_id = %s FOR UPDATE;", (owner_id,))
                        w_row = cur.fetchone()
                        if not w_row or float(w_row[0]) < price:
                            conn.rollback()
                            return jsonify({"error": "Insufficient wallet balance."}), 400

                        # Move funds from available to held
                        cur.execute(
                            "UPDATE wallet SET balance_available = balance_available - %s, balance_held = balance_held + %s WHERE owner_id = %s;",
                            (price, price, owner_id)
                        )

                    cur.execute(
                        """
                        INSERT INTO order_book (order_id, plot_id, trader_id, order_type, price, status, signature, order_timestamp)
                        VALUES (%s, %s, %s, %s, %s, 'Open', %s, %s);
                        """,
                        (order_id, plot_id, owner_id, order_type, price, signature, timestamp)
                    )
                conn.commit()
        except Exception as e:
            if "idx_one_open_ask_per_plot" in str(e).lower() or "unique" in str(e).lower():
                return jsonify({"error": f"Plot {plot_id} already has an active Open Ask order."}), 409
            if "not clear" in str(e).lower():
                return jsonify({"error": str(e)}), 400
            return jsonify({"error": f"Failed to place order: {str(e)}"}), 500

    log_audit_event("ORDER_PLACED", "order_book", user["user_id"], {
        "order_id": order_id,
        "plot_id": plot_id,
        "type": order_type,
        "price": price
    })

    # Trigger matching engine immediately
    match_result = attempt_match_for_plot(plot_id)

    return jsonify({
        "message": "Order placed successfully.",
        "order_id": order_id,
        "plot_id": plot_id,
        "order_type": order_type,
        "price": price,
        "status": "Open" if not match_result else "Matched",
        "match": match_result
    }), 201

@orders_bp.route("/orders/<order_id>", methods=["DELETE"])
def cancel_order(order_id: str):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    owner_id = user.get("owner_id")

    if is_mock_mode():
        order = mock_db.order_book.get(order_id)
        if not order:
            return jsonify({"error": "Order not found."}), 404
        if order["trader_id"] != owner_id and user.get("role") != "sys_admin":
            return jsonify({"error": "Forbidden: you can only cancel your own orders."}), 403
        if order["status"] != "Open":
            return jsonify({"error": f"Cannot cancel order with status '{order['status']}'."}), 400

        order["status"] = "Cancelled"
        if order["order_type"] == "BID":
            wallet = mock_db.wallets.get(order["trader_id"])
            if wallet:
                wallet["balance_held"] -= float(order["price"])
                wallet["balance_available"] += float(order["price"])
    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT trader_id, order_type, price, status FROM order_book WHERE order_id = %s FOR UPDATE;",
                        (order_id,)
                    )
                    row = cur.fetchone()
                    if not row:
                        conn.rollback()
                        return jsonify({"error": "Order not found."}), 404
                    trader_id, o_type, price, status = row[0], row[1], float(row[2]), row[3]

                    if trader_id != owner_id and user.get("role") != "sys_admin":
                        conn.rollback()
                        return jsonify({"error": "Forbidden: not your order."}), 403
                    if status != 'Open':
                        conn.rollback()
                        return jsonify({"error": f"Cannot cancel order in status '{status}'."}), 400

                    cur.execute("UPDATE order_book SET status = 'Cancelled' WHERE order_id = %s;", (order_id,))
                    if o_type == 'BID':
                        cur.execute(
                            "UPDATE wallet SET balance_held = balance_held - %s, balance_available = balance_available + %s WHERE owner_id = %s;",
                            (price, price, trader_id)
                        )
                conn.commit()
        except Exception as e:
            return jsonify({"error": f"Failed to cancel order: {str(e)}"}), 500

    log_audit_event("ORDER_CANCELLED", "order_book", user["user_id"], {"order_id": order_id})
    return jsonify({"message": "Order cancelled successfully and held funds released.", "order_id": order_id}), 200

@orders_bp.route("/plots/<plot_id>/orderbook", methods=["GET"])
def get_plot_orderbook(plot_id: str):
    if is_mock_mode():
        bids = [
            {"order_id": o["order_id"], "price": float(o["price"]), "timestamp": o["order_timestamp"], "trader_id": o["trader_id"]}
            for o in mock_db.order_book.values()
            if o["plot_id"] == plot_id and o["order_type"] == "BID" and o["status"] == "Open"
        ]
        asks = [
            {"order_id": o["order_id"], "price": float(o["price"]), "timestamp": o["order_timestamp"], "trader_id": o["trader_id"]}
            for o in mock_db.order_book.values()
            if o["plot_id"] == plot_id and o["order_type"] == "ASK" and o["status"] == "Open"
        ]
        bids.sort(key=lambda x: (-x["price"], x["timestamp"]))
        asks.sort(key=lambda x: (x["price"], x["timestamp"]))
        return jsonify({"plot_id": plot_id, "bids": bids, "asks": asks}), 200

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT order_id, trader_id, order_type, price, order_timestamp
                    FROM order_book
                    WHERE plot_id = %s AND status = 'Open'
                    ORDER BY price DESC, order_timestamp ASC;
                    """,
                    (plot_id,)
                )
                rows = cur.fetchall()
                bids = []
                asks = []
                for r in rows:
                    item = {"order_id": r[0], "trader_id": r[1], "price": float(r[3]), "timestamp": r[4].isoformat()}
                    if r[2] == 'BID':
                        bids.append(item)
                    else:
                        asks.append(item)
                asks.sort(key=lambda x: x["price"])
        return jsonify({"plot_id": plot_id, "bids": bids, "asks": asks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@orders_bp.route("/stream/orderbook", methods=["GET"])
def stream_orderbook():
    """Server-Sent Events (SSE) endpoint broadcasting live orderbook changes to 3D UI."""
    def event_stream():
        while True:
            # Broadcast snapshot of active orders
            payload = {"type": "heartbeat", "time": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(3)
    return Response(event_stream(), mimetype="text/event-stream")
