# backend/routes/auth.py
import uuid
import hashlib
# pyrefly: ignore [missing-import]
from flask import Blueprint, request, jsonify
from backend.services.auth import (
    hash_password,
    check_password,
    generate_jwt,
    generate_mfa_secret,
    verify_totp,
    get_user_by_email,
    get_user_by_id,
    create_user,
    require_roles,
    get_current_user,
    ROLES_REQUIRING_MFA,
    VALID_ROLES
)
from backend.services.audit import log_audit_event
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    role = data.get("role", "buyer").strip()
    full_name = data.get("full_name", "").strip()
    contact = data.get("contact", "").strip()
    document_no = data.get("document_no", "").strip()
    public_key = data.get("public_key", "").strip()
    initial_wallet = float(data.get("initial_wallet", 5000000.00))

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    if role not in VALID_ROLES or role == "public":
        return jsonify({"error": f"Invalid role '{role}'. Allowed: {list(VALID_ROLES - {'public'})}"}), 400

    if get_user_by_email(email):
        return jsonify({"error": "User with this email already exists."}), 409

    owner_id = None
    mfa_secret = generate_mfa_secret() if role in ROLES_REQUIRING_MFA else None

    # For buyer and owner_seller, create owner record and wallet
    if role in ("buyer", "owner_seller"):
        if not full_name:
            full_name = email.split("@")[0].capitalize()
        if not contact:
            contact = "+91-9876543210"
        if not document_no:
            document_no = f"DOC_{uuid.uuid4().hex[:8]}"
        
        # DECISION 10: KYC stored only as a hash (SHA-256 of document number + salt)
        salt = "RVCE_LAND_EXCHANGE_SALT_2026"
        kyc_hash = hashlib.sha256(f"{document_no}_{salt}".encode('utf-8')).hexdigest()
        
        owner_id = f"own_{uuid.uuid4().hex[:10]}"
        wallet_address = f"0x{uuid.uuid4().hex}"

        if not public_key:
            # Fallback public key placeholder if not generated in browser yet
            public_key = f"TEST_PUBKEY_{owner_id}"

            if is_mock_mode():
                # Check kyc_hash uniqueness
                for o in mock_db.owners.values():
                    if o.get("kyc_hash") == kyc_hash:
                        return jsonify({"error": "Duplicate KYC document hash detected."}), 409

            mock_db.owners[owner_id] = {
                "owner_id": owner_id,
                "full_name": full_name,
                "contact": contact,
                "kyc_hash": kyc_hash,
                "public_key": public_key,
                "wallet_address": wallet_address
            }
            mock_db.wallets[owner_id] = {
                "owner_id": owner_id,
                "balance_available": initial_wallet,
                "balance_held": 0.00
            }
        else:
            try:
                with get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO owner (owner_id, full_name, contact, kyc_hash, public_key, wallet_address)
                            VALUES (%s, %s, %s, %s, %s, %s);
                            """,
                            (owner_id, full_name, contact, kyc_hash, public_key, wallet_address)
                        )
                        cur.execute(
                            """
                            INSERT INTO wallet (owner_id, balance_available, balance_held)
                            VALUES (%s, %s, 0.00);
                            """,
                            (owner_id, initial_wallet)
                        )
                    conn.commit()
            except Exception as e:
                if "kyc_hash" in str(e).lower() or "unique" in str(e).lower():
                    return jsonify({"error": "Duplicate KYC document hash detected."}), 409
                return jsonify({"error": f"Failed to register owner: {str(e)}"}), 500

    user = create_user(email, password, role, owner_id=owner_id, mfa_secret=mfa_secret)
    log_audit_event("USER_REGISTERED", "users", user["user_id"], {"email": email, "role": role})

    token = generate_jwt(user["user_id"], user["email"], user["role"], owner_id)

    resp = {
        "message": "User registered successfully.",
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"],
        "owner_id": owner_id,
        "token": token
    }
    if mfa_secret:
        resp["mfa_secret"] = mfa_secret
        resp["mfa_uri"] = pyotp.totp.TOTP(mfa_secret).provisioning_uri(name=email, issuer_name="LandExchange")

    return jsonify(resp), 201

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    totp_code = data.get("mfa_code", "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    user = get_user_by_email(email)
    if not user or not check_password(password, user["password_hash"]):
        log_audit_event("LOGIN_FAILED", "auth", None, {"email": email, "reason": "Invalid credentials"})
        return jsonify({"error": "Invalid email or password."}), 401

    if not user.get("is_active", True):
        return jsonify({"error": "Account is deactivated."}), 403

    # Check MFA if role requires it
    if user["role"] in ROLES_REQUIRING_MFA:
        secret = user.get("mfa_secret")
        if not secret:
            secret = generate_mfa_secret()
            user["mfa_secret"] = secret

        if not totp_code:
            return jsonify({
                "mfa_required": True,
                "message": f"MFA code required for role '{user['role']}'."
            }), 403

        if not verify_totp(secret, totp_code):
            log_audit_event("MFA_FAILED", "auth", user["user_id"], {"email": email})
            return jsonify({"error": "Invalid TOTP MFA verification code."}), 401

    token = generate_jwt(user["user_id"], user["email"], user["role"], user.get("owner_id"))
    log_audit_event("LOGIN_SUCCESS", "auth", user["user_id"], {"email": email, "role": user["role"]})

    return jsonify({
        "message": "Login successful.",
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"],
        "owner_id": user.get("owner_id"),
        "token": token
    }), 200

@auth_bp.route("/me", methods=["GET"])
def me():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    wallet_data = None
    owner_data = None
    owner_id = user.get("owner_id")

    if owner_id:
        if is_mock_mode():
            owner_data = mock_db.owners.get(owner_id)
            wallet_data = mock_db.wallets.get(owner_id)
        else:
            try:
                with get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT owner_id, full_name, contact, wallet_address, public_key FROM owner WHERE owner_id = %s;", (owner_id,))
                        orow = cur.fetchone()
                        if orow:
                            owner_data = {
                                "owner_id": orow[0],
                                "full_name": orow[1],
                                "contact": orow[2],
                                "wallet_address": orow[3],
                                "public_key": orow[4]
                            }
                        cur.execute("SELECT balance_available, balance_held FROM wallet WHERE owner_id = %s;", (owner_id,))
                        wrow = cur.fetchone()
                        if wrow:
                            wallet_data = {
                                "balance_available": float(wrow[0]),
                                "balance_held": float(wrow[1])
                            }
            except Exception:
                pass

    return jsonify({
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"],
        "owner": owner_data,
        "wallet": wallet_data
    }), 200
