# tests/test_04_plots_and_injunctions.py
from shapely.geometry import Polygon, mapping
from backend.services.auth import generate_jwt
from backend.db.mock_store import mock_db

def test_register_valid_pentagon_plot(client):
    """Prompt 4: Pentagon plot is accepted and stored with computed area."""
    token = generate_jwt("admin_1", "admin@rvce.gov.in", "registry_admin")
    owner_id = "own_pentagon"
    mock_db.owners[owner_id] = {"owner_id": owner_id, "full_name": "Pentagon Owner"}

    pentagon_coords = [
        [77.6500, 12.9800],
        [77.6515, 12.9800],
        [77.6520, 12.9810],
        [77.6508, 12.9820],
        [77.6495, 12.9812],
        [77.6500, 12.9800]
    ]

    res = client.post("/plots", json={
        "plot_id": "plot_pentagon_01",
        "street_address": "Pentagon Avenue, Indiranagar",
        "city": "Bengaluru",
        "state": "Karnataka",
        "zip": "560038",
        "length_m": 45.0,
        "width_m": 35.0,
        "current_owner_id": owner_id,
        "boundary": {
            "type": "Polygon",
            "coordinates": [pentagon_coords]
        }
    }, headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 201
    data = res.get_json()
    assert data["legal_status"] == "Pending"
    assert data["area_sqft"] > 0

def test_injunction_holds_orders_and_release_restores_them(client):
    """Prompt 4: Injunction marks plot Disputed and holds orders; lifting restores Clear and reopens orders."""
    court_token = generate_jwt("court_judge", "judge@court.gov.in", "court")
    plot_id = "plot_inj_cycle"
    owner_id = "own_inj_test"

    mock_db.plots[plot_id] = {"plot_id": plot_id, "city": "Bengaluru", "geojson": {}}
    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": owner_id,
        "legal_status": "Clear"
    }
    mock_db.order_book["ord_held_01"] = {
        "order_id": "ord_held_01",
        "plot_id": plot_id,
        "trader_id": "trader_1",
        "order_type": "BID",
        "price": 5000000.0,
        "status": "Open",
        "hold_reason": None
    }

    # 1. Place injunction
    inj_res = client.post("/injunctions", json={
        "plot_id": plot_id,
        "case_ref": "OS-1234/2026"
    }, headers={"Authorization": f"Bearer {court_token}"})
    assert inj_res.status_code == 201
    inj_id = inj_res.get_json()["injunction_id"]

    assert mock_db.registry[f"reg_{plot_id}"]["legal_status"] == "Disputed"
    assert mock_db.order_book["ord_held_01"]["status"] == "On_Hold"
    assert "OS-1234/2026" in mock_db.order_book["ord_held_01"]["hold_reason"]

    # 2. Lift injunction
    lift_res = client.post(f"/injunctions/{inj_id}/lift", headers={"Authorization": f"Bearer {court_token}"})
    assert lift_res.status_code == 200

    assert mock_db.registry[f"reg_{plot_id}"]["legal_status"] == "Clear"
    assert mock_db.order_book["ord_held_01"]["status"] == "Open"
    assert mock_db.order_book["ord_held_01"]["hold_reason"] is None
