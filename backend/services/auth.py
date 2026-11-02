# backend/services/auth.py
import os
import datetime
import functools
import bcrypt
import jwt
import pyotp
from typing import Optional, Dict, Any, List
from flask import request, jsonify, g
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.audit import log_audit_event

SECRET_KEY = os.getenv("SECRET_KEY", "dev_jwt_secret_key_change_in_production_rvce_land_exchange_2026")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", 24))

ROLES_REQUIRING_MFA = {"registry_admin", "court"}
VALID_ROLES = {"owner_seller", "buyer", "registry_admin", "court", "public", "sys_admin"}

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def generate_jwt(user_id: str, email: str, role: str, owner_id: Optional[str] = None) -> str:
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "owner_id": owner_id,
        "exp": exp,
        "iat": datetime.datetime.now(datetime.timezone.utc)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None

def generate_mfa_secret() -> str:
    return pyotp.random_base32()

def verify_totp(secret: str, code: str) -> bool:
    if not secret:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)

def get_current_user() -> Optional[Dict[str, Any]]:
    """Retrieves authenticated user from Authorization header Bearer token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    return decode_jwt(token)

def require_roles(allowed_roles: List[str]):
    """Decorator ensuring request caller has one of the allowed roles."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Authentication required. Missing or invalid Bearer token."}), 401

            user_role = user.get("role")
            if user_role not in allowed_roles and "sys_admin" != user_role:
                log_audit_event("UNAUTHORIZED_ACCESS_ATTEMPT", "auth", user.get("user_id"), {
                    "role": user_role,
                    "endpoint": request.path,
                    "required_roles": allowed_roles
                })
                return jsonify({
                    "error": f"Forbidden: role '{user_role}' does not have permission. Required: {allowed_roles}"
                }), 403

            g.current_user = user
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if is_mock_mode():
        for u in mock_db.users.values():
            if u["email"].lower() == email.lower():
                return u
        return None

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, email, password_hash, role, mfa_secret, owner_id, is_active FROM users WHERE email = %s;",
                    (email.lower(),)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "email": row[1],
                        "password_hash": row[2],
                        "role": row[3],
                        "mfa_secret": row[4],
                        "owner_id": row[5],
                        "is_active": row[6]
                    }
        return None
    except Exception:
        # Fallback to mock
        for u in mock_db.users.values():
            if u["email"].lower() == email.lower():
                return u
        return None

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    if is_mock_mode():
        return mock_db.users.get(user_id)

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id, email, password_hash, role, mfa_secret, owner_id, is_active FROM users WHERE user_id = %s;",
                    (user_id,)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "email": row[1],
                        "password_hash": row[2],
                        "role": row[3],
                        "mfa_secret": row[4],
                        "owner_id": row[5],
                        "is_active": row[6]
                    }
        return None
    except Exception:
        return mock_db.users.get(user_id)

def create_user(
    email: str,
    password: str,
    role: str,
    owner_id: Optional[str] = None,
    mfa_secret: Optional[str] = None
) -> Dict[str, Any]:
    import uuid
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    pwd_hash = hash_password(password)

    if role in ROLES_REQUIRING_MFA and not mfa_secret:
        mfa_secret = generate_mfa_secret()

    user_data = {
        "user_id": user_id,
        "email": email.lower(),
        "password_hash": pwd_hash,
        "role": role,
        "mfa_secret": mfa_secret,
        "owner_id": owner_id,
        "is_active": True
    }

    if is_mock_mode():
        mock_db.users[user_id] = user_data
        return user_data

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, password_hash, role, mfa_secret, owner_id, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (user_id, email.lower(), pwd_hash, role, mfa_secret, owner_id, True)
                )
            conn.commit()
        return user_data
    except Exception:
        mock_db.users[user_id] = user_data
        return user_data
