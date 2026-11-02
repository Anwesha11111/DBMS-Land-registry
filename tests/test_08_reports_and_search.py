# tests/test_08_reports_and_search.py
from backend.services.auth import generate_jwt
from backend.db.mock_store import mock_db
from backend.services.ledger import append_block

def test_reports_pdf_and_csv_export(client):
    """Prompt 8: Reports export ownership history as PDF and CSV with verify_chain result."""
    plot_id = "plot_report_test"
    mock_db.plots[plot_id] = {
        "plot_id": plot_id,
        "street_address": "80 Feet Road, Indiranagar",
        "city": "Bengaluru",
        "zip": "560038"
    }
    mock_db.registry[f"reg_{plot_id}"] = {
        "registry_id": f"reg_{plot_id}",
        "plot_id": plot_id,
        "current_owner_id": "own_report",
        "legal_status": "Clear"
    }

    # CSV Export
    csv_res = client.get(f"/reports/plot/{plot_id}/history?format=csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.content_type
    assert b"Plot ID,plot_report_test" in csv_res.data
    assert b"Cryptographic Integrity,PASS" in csv_res.data

    # PDF Export
    pdf_res = client.get(f"/reports/plot/{plot_id}/history?format=pdf")
    assert pdf_res.status_code == 200
    assert "application/pdf" in pdf_res.content_type
    assert pdf_res.data.startswith(b"%PDF")

def test_search_endpoint_role_gating(client):
    """Prompt 8: Global search endpoint redacts owner names for unauthorized roles."""
    mock_db.plots["plot_srch"] = {"plot_id": "plot_srch", "street_address": "Koramangala 4th Block", "city": "Bengaluru", "zip": "560034"}
    mock_db.owners["own_srch"] = {"owner_id": "own_srch", "full_name": "Siddharth Rao", "wallet_address": "0x1234"}

    # Public unauthenticated user
    pub_res = client.get("/search?q=Siddharth")
    assert pub_res.status_code == 200
    owners = pub_res.get_json()["results"]["owners"]
    if owners:
        assert owners[0]["full_name"] == "REDACTED"

    # Authorized admin user
    admin_token = generate_jwt("admin_srch", "admin@rvce.gov.in", "registry_admin")
    admin_res = client.get("/search?q=Siddharth", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    admin_owners = admin_res.get_json()["results"]["owners"]
    assert len(admin_owners) > 0
    assert admin_owners[0]["full_name"] == "Siddharth Rao"

def test_admin_integrity_endpoint(client):
    """Prompt 8: Admin integrity endpoint runs verify_chain across all plots."""
    admin_token = generate_jwt("admin_audit", "admin@rvce.gov.in", "registry_admin")
    res = client.get("/admin/integrity", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["chain_overall"] in ("PASS", "FAIL")
    assert "total_plots_audited" in data
    assert "failures" in data
