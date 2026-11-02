# tests/test_10_public_portal.py
from backend.services.ledger import ensure_genesis, append_block

def test_public_verify_returns_pass_for_valid_plot(client):
    """Prompt 10: GET /public/verify/<plot_id> returns PASS for valid plot chain."""
    ensure_genesis()
    plot_id = "plot_pub_ver_01"
    append_block(
        block_type="SALE",
        registry_id=f"reg_{plot_id}",
        plot_id=plot_id,
        seller_id="own_pub_s",
        buyer_id="own_pub_b",
        sale_price=8000000.0
    )

    res = client.get(f"/public/verify/{plot_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["result"] == "PASS"
    assert data["verified"] is True
    assert data["blocks_checked"] >= 2
    assert data["first_bad_block"] is None

def test_public_title_chain_endpoint_no_sensitive_kyc(client):
    """Prompt 10: GET /public/title-chain/<plot_id> returns public-safe title blocks."""
    plot_id = "plot_chain_pub"
    append_block(
        block_type="SALE",
        registry_id=f"reg_{plot_id}",
        plot_id=plot_id,
        seller_id="s_safe",
        buyer_id="b_safe",
        sale_price=5500000.0
    )

    res = client.get(f"/public/title-chain/{plot_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert "chain" in data
    assert len(data["chain"]) > 0

    block = data["chain"][0]
    # Verify no personal contact/kyc info leaked
    assert "contact" not in block
    assert "kyc_hash" not in block
    assert "email" not in block
    assert "tx_id" in block
    assert "prev_tx_hash" in block
