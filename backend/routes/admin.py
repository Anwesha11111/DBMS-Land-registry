# backend/routes/admin.py
from flask import Blueprint, request, jsonify, g
from backend.services.auth import require_roles, get_current_user
from backend.services.ledger import verify_chain, append_correction, get_ledger_collection
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Pending corrections proposal store
_pending_corrections = {}

@admin_bp.route("/integrity", methods=["GET"])
@require_roles(["registry_admin", "court", "sys_admin"])
def full_integrity_check():
    """
    Runs verify_chain() across the entire blockchain and all registered plots.
    Detects any block tampering or database-ledger desynchronization.
    """
    overall_verification = verify_chain()
    
    # Check all plots
    plot_ids = []
    if is_mock_mode():
        plot_ids = list(mock_db.plots.keys())
    else:
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT plot_id FROM plot;")
                    plot_ids = [r[0] for r in cur.fetchall()]
        except Exception:
            pass

    plot_reports = []
    failures = []
    for pid in plot_ids:
        p_res = verify_chain(plot_id=pid)
        item = {
            "plot_id": pid,
            "status": "PASS" if p_res["verified"] else "FAIL",
            "details": p_res.get("details") or p_res.get("error"),
            "first_bad_block": p_res.get("first_bad_block")
        }
        plot_reports.append(item)
        if not p_res["verified"]:
            failures.append(item)

    return jsonify({
        "chain_overall": "PASS" if overall_verification["verified"] else "FAIL",
        "blocks_checked": overall_verification.get("blocks_checked", 0),
        "total_plots_audited": len(plot_ids),
        "failures_count": len(failures),
        "failures": failures,
        "plot_reports": plot_reports
    }), 200

@admin_bp.route("/corrections/propose", methods=["POST"])
@require_roles(["registry_admin", "sys_admin"])
def propose_correction():
    """
    Proposes a correction block to rectify erroneous historical block data.
    DECISION 6 & Prompt 6: Must be approved by a different user before taking effect.
    """
    data = request.get_json() or {}
    original_tx_id = data.get("original_tx_id")
    plot_id = data.get("plot_id")
    registry_id = data.get("registry_id") or f"reg_{plot_id}"
    reason = data.get("reason", "").strip()
    new_data = data.get("new_data") or {}

    if not original_tx_id or not plot_id or not reason:
        return jsonify({"error": "original_tx_id, plot_id, and reason are required."}), 400

    col = get_ledger_collection()
    orig = col.find_one({"tx_id": original_tx_id})
    if not orig:
        return jsonify({"error": f"Original transaction tx_id '{original_tx_id}' not found in ledger."}), 404

    proposal_id = f"prop_{len(_pending_corrections) + 1}"
    _pending_corrections[proposal_id] = {
        "proposal_id": proposal_id,
        "original_tx_id": original_tx_id,
        "plot_id": plot_id,
        "registry_id": registry_id,
        "reason": reason,
        "new_data": new_data,
        "requested_by": g.current_user["user_id"],
        "status": "Pending_Approval"
    }

    log_audit_event("CORRECTION_PROPOSED", "ledger", g.current_user["user_id"], {
        "proposal_id": proposal_id,
        "original_tx_id": original_tx_id
    })

    return jsonify({
        "message": "Correction proposed successfully. Requires approval by a second authorized user.",
        "proposal_id": proposal_id,
        "details": _pending_corrections[proposal_id]
    }), 201

@admin_bp.route("/corrections/approve", methods=["POST"])
@require_roles(["registry_admin", "court", "sys_admin"])
def approve_correction():
    """
    Approves and seals a proposed correction block in the ledger.
    DECISION 6: approved_by != requested_by strictly enforced.
    """
    data = request.get_json() or {}
    proposal_id = data.get("proposal_id")
    if not proposal_id or proposal_id not in _pending_corrections:
        return jsonify({"error": "Invalid or missing proposal_id."}), 404

    prop = _pending_corrections[proposal_id]
    approver = g.current_user["user_id"]

    if approver == prop["requested_by"]:
        return jsonify({"error": "Dual-control violation: correction cannot be approved by the same user who proposed it."}), 403

    try:
        correction_block = append_correction(
            original_tx_id=prop["original_tx_id"],
            plot_id=prop["plot_id"],
            registry_id=prop["registry_id"],
            new_data=prop["new_data"],
            requested_by=prop["requested_by"],
            approved_by=approver
        )
        prop["status"] = "Approved"
        prop["sealed_block"] = correction_block["block_number"]

        log_audit_event("CORRECTION_APPROVED", "ledger", approver, {
            "proposal_id": proposal_id,
            "block_number": correction_block["block_number"],
            "tx_id": correction_block["tx_id"]
        })

        return jsonify({
            "message": "Correction block successfully appended to the ledger.",
            "block_number": correction_block["block_number"],
            "tx_id": correction_block["tx_id"],
            "proposal": prop
        }), 200

    except Exception as e:
        return jsonify({"error": f"Failed to append correction: {str(e)}"}), 500
