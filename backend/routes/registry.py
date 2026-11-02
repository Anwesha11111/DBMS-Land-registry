# backend/routes/registry.py
from flask import Blueprint, request, jsonify, g
from backend.services.auth import require_roles, get_current_user
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

registry_bp = Blueprint("registry", __name__, url_prefix="/registry")

@registry_bp.route("/<registry_id>/status", methods=["PATCH"])
def update_status(registry_id: str):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_status = data.get("status")
    reason = data.get("reason", "Administrative status update").strip()

    if new_status not in ("Clear", "Pending", "Disputed"):
        return jsonify({"error": f"Invalid status '{new_status}'. Allowed: Clear, Pending, Disputed"}), 400

    user_role = user.get("role")
    # RBAC rules:
    # Disputed can only be placed by court (or sys_admin)
    if new_status == "Disputed" and user_role not in ("court", "sys_admin"):
        return jsonify({"error": "Only court authorities can place a plot in Disputed status."}), 403
    # Pending/Clear by registry_admin (or sys_admin)
    if new_status in ("Clear", "Pending") and user_role not in ("registry_admin", "sys_admin"):
        return jsonify({"error": "Only registry administrators can set status to Clear or Pending."}), 403

    if is_mock_mode():
        reg = mock_db.registry.get(registry_id)
        if not reg:
            return jsonify({"error": f"Registry entry '{registry_id}' not found."}), 404
        old_status = reg["legal_status"]
        reg["legal_status"] = new_status
        # Log to history
        mock_db.registry_history.append({
            "id": len(mock_db.registry_history) + 1,
            "registry_id": registry_id,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": user["user_id"],
            "reason": reason
        })
    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    # Set session parameters for trigger
                    cur.execute(f"SET LOCAL landregistry.current_user = '{user['user_id']}';")
                    cur.execute(f"SET LOCAL landregistry.status_reason = %s;", (reason,))
                    cur.execute(
                        "UPDATE registry_entry SET legal_status = %s, updated_at = CURRENT_TIMESTAMP WHERE registry_id = %s RETURNING legal_status;",
                        (new_status, registry_id)
                    )
                    res = cur.fetchone()
                    if not res:
                        conn.rollback()
                        return jsonify({"error": f"Registry entry '{registry_id}' not found."}), 404
                conn.commit()
        except Exception as e:
            return jsonify({"error": f"Failed to update registry status: {str(e)}"}), 500

    log_audit_event("REGISTRY_STATUS_CHANGED", "registry_entry", user["user_id"], {
        "registry_id": registry_id,
        "new_status": new_status,
        "reason": reason
    })

    return jsonify({
        "message": f"Registry entry status updated to {new_status}.",
        "registry_id": registry_id,
        "legal_status": new_status,
        "reason": reason
    }), 200
