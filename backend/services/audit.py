# backend/services/audit.py
import json
import logging
from typing import Optional, Dict, Any
from flask import request
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

logger = logging.getLogger(__name__)

def log_audit_event(
    action: str,
    entity: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None
):
    """
    Writes an audit entry to PostgreSQL audit_log table.
    DECISION 10: Every login, order, signature, status change goes to audit_log.
    """
    details = details or {}
    if not ip:
        try:
            ip = request.remote_addr if request else "127.0.0.1"
        except Exception:
            ip = "127.0.0.1"

    if is_mock_mode():
        entry = {
            "audit_id": len(mock_db.audit_logs) + 1,
            "user_id": user_id,
            "action": action,
            "entity": entity,
            "details": details,
            "ip": ip
        }
        mock_db.audit_logs.append(entry)
        logger.info(f"[AUDIT MOCK] action={action} entity={entity} user={user_id}")
        return

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (user_id, action, entity, details, ip)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (user_id, action, entity, json.dumps(details), ip)
                )
            conn.commit()
            logger.info(f"[AUDIT] action={action} entity={entity} user={user_id}")
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")
