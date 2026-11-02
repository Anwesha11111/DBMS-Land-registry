# tests/test_11_e2e.py
"""
End-to-End lifecycle test covering the complete story:
1. Register Seller and Buyer with WebCrypto keypairs and wallets.
2. Register Plot as Admin (Pending -> Clear).
3. Seller lists plot (Ask order).
4. Buyer places Bid (sufficient funds held in escrow).
5. Automated matching engine triggers 2PC settlement.
6. Ownership transferred atomically, funds credited, MongoDB block sealed.
7. Public verification portal confirms title chain PASS.
"""
from backend.services.crypto import generate_test_ecdsa_keypair, sign_payload_with_private_key, canonical_json
from backend.services.ledger import ensure_genesis

def test_full_e2e_lifecycle(client):
    ensure_genesis()

    # Step 1: Register Seller & Buyer
    seller_key, seller_pub, _ = generate_test_ecdsa_keypair()
    buyer_key, buyer_pub, _ = generate_test_ecdsa_keypair()

    s_res = client.post("/auth/register", json={
        "email": "seller_e2e@rvce.edu.in",
        "password": "Password123!",
        "role": "owner_seller",
        "full_name": "Rohan Deshmukh",
        "document_no": "DOC_E2E_SELLER",
        "public_key": seller_pub,
        "initial_wallet": 1000000.0
    })
    assert s_res.status_code == 201
    seller_data = s_res.get_json()
    seller_token = seller_data["token"]
    seller_owner_id = seller_data["owner_id"]

    b_res = client.post("/auth/register", json={
        "email": "buyer_e2e@rvce.edu.in",
        "password": "Password123!",
        "role": "buyer",
        "full_name": "Sneha Patil",
        "document_no": "DOC_E2E_BUYER",
        "public_key": buyer_pub,
        "initial_wallet": 20000000.0
    })
    assert b_res.status_code == 201
    buyer_data = b_res.get_json()
    buyer_token = buyer_data["token"]
    buyer_owner_id = buyer_data["owner_id"]

    # Step 2: Admin registers Plot & sets status Clear
    admin_res = client.post("/auth/register", json={
        "email": "admin_e2e@rvce.gov.in",
        "password": "AdminPassword123!",
        "role": "registry_admin"
    })
    admin_token = admin_res.get_json()["token"]

    plot_id = "plot_e2e_bengaluru_01"
    reg_plot = client.post("/plots", json={
        "plot_id": plot_id,
        "street_address": "45 Defense Colony, Indiranagar",
        "city": "Bengaluru",
        "state": "Karnataka",
        "zip": "560038",
        "length_m": 40.0,
        "width_m": 30.0,
        "current_owner_id": seller_owner_id,
        "boundary": {
            "type": "Polygon",
            "coordinates": [[[77.640, 12.970], [77.642, 12.970], [77.642, 12.972], [77.640, 12.972], [77.640, 12.970]]]
        }
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert reg_plot.status_code == 201

    # Admin approves plot to Clear
    stat_res = client.patch(f"/registry/reg_{plot_id}/status", json={
        "status": "Clear",
        "reason": "Initial title deed verified"
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert stat_res.status_code == 200

    # Step 3: Seller lists Ask order (₹12,000,000)
    ask_payload = {
        "plot_id": plot_id,
        "order_type": "ASK",
        "price": 12000000.0,
        "nonce": 0,
        "timestamp": "2026-10-29T10:00:00Z"
    }
    ask_sig = sign_payload_with_private_key(seller_key, canonical_json(ask_payload).encode())
    ask_res = client.post("/orders", json={
        **ask_payload,
        "signature": ask_sig
    }, headers={"Authorization": f"Bearer {seller_token}"})
    assert ask_res.status_code == 201

    # Step 4: Buyer places matching Bid (₹12,000,000)
    bid_payload = {
        "plot_id": plot_id,
        "order_type": "BID",
        "price": 12000000.0,
        "nonce": 0,
        "timestamp": "2026-10-29T10:05:00Z"
    }
    bid_sig = sign_payload_with_private_key(buyer_key, canonical_json(bid_payload).encode())
    bid_res = client.post("/orders", json={
        **bid_payload,
        "signature": bid_sig
    }, headers={"Authorization": f"Bearer {buyer_token}"})
    assert bid_res.status_code == 201
    bid_data = bid_res.get_json()

    # Step 5 & 6: Automated matching & 2PC settlement verified
    assert bid_data["match"] is not None
    assert bid_data["match"]["matched"] is True
    assert bid_data["match"]["settlement"]["status"] == "Settled"

    # Step 7: Check 3D Market data reflects ownership change
    plot_view = client.get(f"/plots/{plot_id}")
    assert plot_view.status_code == 200
    assert plot_view.get_json()["owner_id"] == buyer_owner_id

    # Step 8: Public Title Verification returns PASS
    public_ver = client.get(f"/public/verify/{plot_id}")
    assert public_ver.status_code == 200
    assert public_ver.get_json()["result"] == "PASS"
    assert public_ver.get_json()["verified"] is True
