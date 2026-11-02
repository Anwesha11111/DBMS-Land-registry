# tests/test_02_database_rules.py
import pytest
from shapely.geometry import Polygon, mapping
from backend.services.spatial import validate_geojson_polygon, check_plot_overlap
from backend.db.mock_store import mock_db
from backend.services.auth import create_user, generate_jwt

def test_overlap_rejected_and_touching_accepted():
    """Prompt 2: Overlap rejected, touching accepted."""
    # Plot A: [0,0] to [2,2]
    poly_a = Polygon([(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)])
    mock_db.plots["plot_A"] = {
        "plot_id": "plot_A",
        "geojson": mapping(poly_a)
    }

    # Plot B: [1,1] to [3,3] -> Intersects interior
    poly_b_overlap = Polygon([(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)])
    has_overlap, conflict_id = check_plot_overlap(poly_b_overlap)
    assert has_overlap is True
    assert conflict_id == "plot_A"

    # Plot C: [2,0] to [4,2] -> Touches eastern edge of Plot A
    poly_c_touch = Polygon([(2, 0), (4, 0), (4, 2), (2, 2), (2, 0)])
    has_overlap_touch, conflict_touch = check_plot_overlap(poly_c_touch)
    assert has_overlap_touch is False
    assert conflict_touch is None

def test_invalid_geometry_rejected():
    """Prompt 2: Invalid polygon geometry rejected."""
    # Self-intersecting bow-tie polygon
    bowtie_geojson = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]
    }
    is_valid, err, _ = validate_geojson_polygon(bowtie_geojson)
    assert is_valid is False
    assert "Invalid polygon geometry" in err

def test_duplicate_kyc_rejected(client):
    """Prompt 2: Duplicate KYC hash rejected."""
    doc_num = "PASSPORT_K1234567"
    res1 = client.post("/auth/register", json={
        "email": "user1@example.com",
        "password": "Password123!",
        "role": "buyer",
        "document_no": doc_num
    })
    assert res1.status_code == 201

    res2 = client.post("/auth/register", json={
        "email": "user2@example.com",
        "password": "Password123!",
        "role": "buyer",
        "document_no": doc_num
    })
    assert res2.status_code == 409
    assert "Duplicate KYC" in res2.get_json()["error"]

def test_second_open_ask_rejected(client):
    """Prompt 2: Partial unique index prevents a second Open Ask on the same plot."""
    plot_id = "plot_ask_test"
    owner_id = "own_ask_test"
    mock_db.plots[plot_id] = {"plot_id": plot_id, "city": "Bengaluru", "geojson": {}}
    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": owner_id,
        "legal_status": "Clear"
    }
    mock_db.owners[owner_id] = {
        "owner_id": owner_id,
        "public_key": "TEST_PUBKEY_ASK"
    }
    token = generate_jwt("user_ask", "ask@rvce.edu", "owner_seller", owner_id=owner_id)

    # First Ask -> Success
    res1 = client.post("/orders", json={
        "plot_id": plot_id,
        "order_type": "ASK",
        "price": 5000000.0,
        "signature": "SIG_1"
    }, headers={"Authorization": f"Bearer {token}"})
    assert res1.status_code == 201

    # Second Ask -> Rejected
    res2 = client.post("/orders", json={
        "plot_id": plot_id,
        "order_type": "ASK",
        "price": 5500000.0,
        "signature": "SIG_2"
    }, headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code == 409
    assert "already has an active Open Ask" in res2.get_json()["error"]

def test_orders_on_disputed_plot_rejected(client):
    """Prompt 2: Orders on Disputed plot are rejected."""
    plot_id = "plot_disputed_test"
    owner_id = "own_disp"
    buyer_id = "own_buyer_disp"
    mock_db.plots[plot_id] = {"plot_id": plot_id, "city": "Bengaluru", "geojson": {}}
    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": owner_id,
        "legal_status": "Disputed"
    }
    mock_db.owners[buyer_id] = {"owner_id": buyer_id, "public_key": "TEST_PUBKEY_BUYER"}
    mock_db.wallets[buyer_id] = {"owner_id": buyer_id, "balance_available": 10000000.0, "balance_held": 0.0}

    token = generate_jwt("user_b", "buyer@rvce.edu", "buyer", owner_id=buyer_id)
    res = client.post("/orders", json={
        "plot_id": plot_id,
        "order_type": "BID",
        "price": 4000000.0,
        "signature": "SIG_BUY"
    }, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400
    assert "not Clear" in res.get_json()["error"]

def test_mongo_update_delete_denied_for_app_user():
    """Prompt 2 & DECISION 9: Mongo app user denied update and delete on ledger."""
    app_col = mock_db.get_mongo_client()["landregistry"]["ledger_transaction_block"]
    with pytest.raises(Exception) as exc_update:
        app_col.update_one({"block_number": 0}, {"$set": {"nonce": 999}})
    assert "Unauthorized" in str(exc_update.value)

    with pytest.raises(Exception) as exc_delete:
        app_col.delete_one({"block_number": 0})
    assert "Unauthorized" in str(exc_delete.value)
