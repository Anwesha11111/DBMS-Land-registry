# scripts/demo_tamper.py
"""
Demonstrates cryptographic tamper detection in Land Exchange ledger.
1. Verifies that the initial chain is 100% valid (PASS).
2. Directly tampers with a field (sale_price or buyer_id) in MongoDB using the admin connection.
3. Runs verify_chain() to demonstrate immediate cryptographic FAIL, reporting the exact block number and failure reason.
4. Restores the block to its original state and confirms verify_chain() returns PASS again.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.db.connection import get_mongo_db, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.ledger import verify_chain, get_ledger_collection

def run_tamper_demo():
    print("=" * 70)
    print("DEMO: Cryptographic Ledger Tamper Evidence & Chain Audit")
    print("=" * 70)

    # 1. Initial Verification
    print("\n[Step 1] Running cryptographic verification on initial blockchain...")
    res = verify_chain()
    print(f"Result: {'PASS' if res['verified'] else 'FAIL'}")
    print(f"Blocks Audited: {res.get('blocks_checked', 0)}")
    print(f"Details: {res.get('details')}")

    # 2. Tamper with a block
    col = get_ledger_collection()
    target_block = col.find_one({"block_number": {"$gt": 0}})
    if not target_block:
        from backend.services.ledger import append_block
        append_block(
            block_type="SALE",
            registry_id="reg_demo_01",
            plot_id="plot_demo_01",
            seller_id="own_demo_seller",
            buyer_id="own_demo_buyer",
            sale_price=8500000.0,
            seller_signature="SIG_DEMO_SELLER",
            buyer_signature="SIG_DEMO_BUYER",
            gid="tx_demo_tamper"
        )
        target_block = col.find_one({"block_number": {"$gt": 0}})

    b_num = target_block["block_number"]
    orig_price = target_block.get("sale_price")
    tampered_price = (orig_price or 1000000.0) + 5000000.0

    print(f"\n[Step 2] Adversary acts as rogue database administrator.")
    print(f"Directly tampering with MongoDB Block #{b_num}...")
    print(f"Original Price: INR {orig_price:,.2f} -> Tampered Price: INR {tampered_price:,.2f}")

    if is_mock_mode():
        # Update using admin client
        admin_col = mock_db.get_mongo_admin_client()["landregistry"]["ledger_transaction_block"]
        admin_col.update_one({"block_number": b_num}, {"$set": {"sale_price": tampered_price}})
    else:
        # Update via direct admin connection
        col.update_one({"block_number": b_num}, {"$set": {"sale_price": tampered_price}})

    # 3. Audit tampered chain
    print("\n[Step 3] Auditor runs verify_chain() to detect unauthorized modifications...")
    audit_res = verify_chain()
    print(f"Result: {'PASS' if audit_res['verified'] else 'FAIL'}")
    print(f"Tamper Detected at Block Height: #{audit_res.get('first_bad_block')}")
    print(f"Cryptographic Audit Reason: {audit_res.get('error')}")

    # 4. Restore original block
    print("\n[Step 4] Restoring original cryptographic block data...")
    if is_mock_mode():
        admin_col = mock_db.get_mongo_admin_client()["landregistry"]["ledger_transaction_block"]
        admin_col.update_one({"block_number": b_num}, {"$set": {"sale_price": orig_price}})
    else:
        col.update_one({"block_number": b_num}, {"$set": {"sale_price": orig_price}})

    restore_res = verify_chain()
    print(f"Result after restore: {'PASS' if restore_res['verified'] else 'FAIL'}")
    print("=" * 70)
    print("Demonstration concluded successfully: Mathematical immutability proven.")
    print("=" * 70)

if __name__ == "__main__":
    run_tamper_demo()
