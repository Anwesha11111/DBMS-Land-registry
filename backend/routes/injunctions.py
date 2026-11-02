# backend/routes/injunctions.py
import datetime
from flask import Blueprint, request, jsonify, g
from backend.services.auth import require_roles, get_current_user
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

injunctions_bp = Blueprint("injunctions", __name__, url_prefix="/injunctions")

@injunctions_bp.route("", methods=["POST"])
@require_roles(["court", "sys_admin"])
def place_injunction():
    data = request.get_json() or {}
    registry_id = data.get("registry_id")
    plot_id = data.get("plot_id")
    case_ref = data.get("case_ref", "").strip()

    if not case_ref or (not registry_id and not plot_id):
        return jsonify({"error": "case_ref and either registry_id or plot_id are required."}), 400

    user = g.current_user

    if is_mock_mode():
        # Find registry entry
        target_reg = None
        if registry_id and registry_id in mock_db.registry:
            target_reg = mock_db.registry[registry_id]
        elif plot_id:
            for r in mock_db.registry.values():
                if r["plot_id"] == plot_id:
                    target_reg = r
                    break

        if not target_reg:
            return jsonify({"error": "Registry entry not found."}), 404

        reg_id = target_reg["registry_id"]
        p_id = target_reg["plot_id"]
        old_status = target_reg["legal_status"]

        # Update status to Disputed
        target_reg["legal_status"] = "Disputed"

        # Log history
        mock_db.registry_history.append({
            "id": len(mock_db.registry_history) + 1,
            "registry_id": reg_id,
            "old_status": old_status,
            "new_status": "Disputed",
            "changed_by": user["user_id"],
            "reason": f"Court Injunction: {case_ref}"
        })

        # Set Open orders on that plot to On_Hold
        held_count = 0
        for o in mock_db.order_book.values():
            if o["plot_id"] == p_id and o["status"] == "Open":
                o["status"] = "On_Hold"
                o["hold_reason"] = f"Court Injunction case {case_ref}"
                held_count += 1

        inj_id = len(mock_db.injunctions) + 1
        inj_record = {
            "id": inj_id,
            "registry_id": reg_id,
            "court_user_id": user["user_id"],
            "case_ref": case_ref,
            "placed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "lifted_at": None
        }
        mock_db.injunctions.append(inj_record)

    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    if not registry_id and plot_id:
                        cur.execute("SELECT registry_id FROM registry_entry WHERE plot_id = %s;", (plot_id,))
                        r = cur.fetchone()
                        if not r:
                            conn.rollback()
                            return jsonify({"error": "Plot not registered."}), 404
                        registry_id = r[0]

                    # 1. Place injunction record
                    cur.execute(
                        """
                        INSERT INTO injunction (registry_id, court_user_id, case_ref)
                        VALUES (%s, %s, %s)
                        RETURNING id;
                        """,
                        (registry_id, user["user_id"], case_ref)
                    )
                    inj_id = cur.fetchone()[0]

                    # 2. Update legal_status to Disputed
                    cur.execute(f"SET LOCAL landregistry.current_user = '{user['user_id']}';")
                    cur.execute("SET LOCAL landregistry.status_reason = %s;", (f"Court Injunction: {case_ref}",))
                    cur.execute(
                        "UPDATE registry_entry SET legal_status = 'Disputed', updated_at = CURRENT_TIMESTAMP WHERE registry_id = %s RETURNING plot_id;",
                        (registry_id,)
                    )
                    plot_id_res = cur.fetchone()[0]

                    # 3. Put all Open orders on hold
                    cur.execute(
                        """
                        UPDATE order_book
                        SET status = 'On_Hold', hold_reason = %s
                        WHERE plot_id = %s AND status = 'Open';
                        """,
                        (f"Court Injunction case {case_ref}", plot_id_res)
                    )
                    held_count = cur.rowcount
                conn.commit()
        except Exception as e:
            return jsonify({"error": f"Failed to place injunction: {str(e)}"}), 500

    log_audit_event("INJUNCTION_PLACED", "injunction", user["user_id"], {
        "injunction_id": inj_id,
        "registry_id": registry_id or reg_id,
        "case_ref": case_ref,
        "orders_held": held_count
    })

    return jsonify({
        "message": "Injunction successfully placed. Plot marked Disputed; active orders placed On_Hold.",
        "injunction_id": inj_id,
        "registry_id": registry_id or reg_id,
        "status": "Disputed",
        "orders_placed_on_hold": held_count
    }), 201

@injunctions_bp.route("/<int:injunction_id>/lift", methods=["POST", "PATCH"])
@require_roles(["court", "sys_admin"])
def lift_injunction(injunction_id: int):
    user = g.current_user

    if is_mock_mode():
        inj = next((i for i in mock_db.injunctions if i["id"] == injunction_id), None)
        if not inj:
            return jsonify({"error": "Injunction not found."}), 404
        if inj["lifted_at"]:
            return jsonify({"error": "Injunction already lifted."}), 400

        inj["lifted_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        reg = mock_db.registry.get(inj["registry_id"])
        if reg:
            old_status = reg["legal_status"]
            reg["legal_status"] = "Clear"
            p_id = reg["plot_id"]
            mock_db.registry_history.append({
                "id": len(mock_db.registry_history) + 1,
                "registry_id": reg["registry_id"],
                "old_status": old_status,
                "new_status": "Clear",
                "changed_by": user["user_id"],
                "reason": f"Court lifted injunction {injunction_id}"
            })
            # Re-open held orders
            reopened = 0
            for o in mock_db.order_book.values():
                if o["plot_id"] == p_id and o["status"] == "On_Hold":
                    o["status"] = "Open"
                    o["hold_reason"] = None
                    reopened += 1

    else:
        try:
            with get_pg_connection() as conn:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE injunction
                        SET lifted_at = CURRENT_TIMESTAMP
                        WHERE id = %s AND lifted_at IS NULL
                        RETURNING registry_id;
                        """,
                        (injunction_id,)
                    )
                    row = cur.fetchone()
                    if not row:
                        conn.rollback()
                        return jsonify({"error": "Injunction not found or already lifted."}), 404
                    reg_id = row[0]

                    # Restore status to Clear
                    cur.execute(f"SET LOCAL landregistry.current_user = '{user['user_id']}';")
                    cur.execute("SET LOCAL landregistry.status_reason = %s;", (f"Injunction {injunction_id} lifted by court",))
                    cur.execute(
                        "UPDATE registry_entry SET legal_status = 'Clear', updated_at = CURRENT_TIMESTAMP WHERE registry_id = %s RETURNING plot_id;",
                        (reg_id,)
                    )
                    plot_id = cur.fetchone()[0]

                    # Re-open held orders
                    cur.execute(
                        """
                        UPDATE order_book
                        SET status = 'Open', hold_reason = NULL
                        WHERE plot_id = %s AND status = 'On_Hold';
                        """,
                        (plot_id,)
                    )
                    reopened = cur.rowcount
                conn.commit()
        except Exception as e:
            return jsonify({"error": f"Failed to lift injunction: {str(e)}"}), 500

    log_audit_event("INJUNCTION_LIFTED", "injunction", user["user_id"], {
        "injunction_id": injunction_id,
        "orders_reopened": reopened
    })

    return jsonify({
        "message": "Injunction lifted. Plot restored to Clear status and held orders re-opened.",
        "injunction_id": injunction_id,
        "legal_status": "Clear",
        "orders_reopened": reopened
    }), 200
