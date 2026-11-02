# tests/test_03_auth_and_crypto.py
import pyotp
from backend.services.auth import generate_jwt
from backend.services.crypto import (
    generate_test_ecdsa_keypair,
    sign_payload_with_private_key,
    verify_signature,
    canonical_json
)

def test_wrong_role_gets_403(client):
    """Prompt 3: User with buyer role cannot register plots (requires registry_admin)."""
    token = generate_jwt("u_buyer", "buyer@test.com", "buyer")
    res = client.post("/plots", json={
        "street_address": "Test Street",
        "city": "Bengaluru",
        "state": "Karnataka",
        "zip": "560001",
        "length_m": 30,
        "width_m": 20,
        "current_owner_id": "own_1",
        "boundary": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    }, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert "Forbidden" in res.get_json()["error"]

def test_mfa_required_for_court_and_admin(client):
    """Prompt 3: MFA code mandatory during login for registry_admin and court."""
    secret = pyotp.random_base32()
    reg_res = client.post("/auth/register", json={
        "email": "admin_mfa@test.com",
        "password": "Password123!",
        "role": "registry_admin"
    })
    assert reg_res.status_code == 201

    # Login without MFA code
    login_fail = client.post("/auth/login", json={
        "email": "admin_mfa@test.com",
        "password": "Password123!"
    })
    assert login_fail.status_code == 403
    assert login_fail.get_json()["mfa_required"] is True

    # Login with valid TOTP code
    mfa_secret = reg_res.get_json()["mfa_secret"]
    valid_totp = pyotp.TOTP(mfa_secret).now()
    login_success = client.post("/auth/login", json={
        "email": "admin_mfa@test.com",
        "password": "Password123!",
        "mfa_code": valid_totp
    })
    assert login_success.status_code == 200
    assert "token" in login_success.get_json()

def test_tampered_payload_fails_signature_verification():
    """Prompt 3: Digital signature verification fails if payload bytes are altered."""
    priv_key, pub_pem, _ = generate_test_ecdsa_keypair()
    original_payload = {"plot_id": "plot_01", "order_type": "BID", "price": 5000000.0, "nonce": 0}
    canonical_bytes = canonical_json(original_payload).encode('utf-8')
    sig = sign_payload_with_private_key(priv_key, canonical_bytes)

    # 1. Original payload verifies
    assert verify_signature(pub_pem, canonical_bytes, sig) is True

    # 2. Tampered price fails verification
    tampered_payload = {"plot_id": "plot_01", "order_type": "BID", "price": 9999999.0, "nonce": 0}
    tampered_bytes = canonical_json(tampered_payload).encode('utf-8')
    assert verify_signature(pub_pem, tampered_bytes, sig) is False
