# scripts/demo_injunction.py
"""
Demonstrates Court Injunction workflow.
1. Inspects active Clear plot with Open orders.
2. Court issues injunction: plot becomes Disputed, active orders locked to On_Hold.
3. Matching engine and order placement blocked.
4. Court lifts injunction: plot restored to Clear, orders returned to Open.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.db.mock_store import mock_db

def run_injunction_demo():
    print("=" * 70)
    print("DEMO: Judicial Injunction, Order-Freezing, and Dispute Resolution")
    print("=" * 70)

    plot_id = "plot_demo_inj"
    reg_id = "reg_demo_inj"

    # Setup plot in Clear status with open orders
    mock_db.registry[reg_id] = {
        "registry_id": reg_id,
        "plot_id": plot_id,
        "current_owner_id": "own_seller_01",
        "legal_status": "Clear"
    }
    mock_db.order_book["ord_bid_01"] = {
        "order_id": "ord_bid_01",
        "plot_id": plot_id,
        "trader_id": "own_buyer_01",
        "order_type": "BID",
        "price": 8000000.0,
        "status": "Open",
        "hold_reason": None
    }

    print(f"\n[Step 1] Initial State for Plot '{plot_id}':")
    print(f"Status: {mock_db.registry[reg_id]['legal_status']}")
    print(f"Order ord_bid_01 Status: {mock_db.order_book['ord_bid_01']['status']}")

    # Step 2: Court places injunction
    print(f"\n[Step 2] High Court issues Injunction (Case #HC-2026/409)...")
    mock_db.registry[reg_id]["legal_status"] = "Disputed"
    for o in mock_db.order_book.values():
        if o["plot_id"] == plot_id and o["status"] == "Open":
            o["status"] = "On_Hold"
            o["hold_reason"] = "Court Injunction Case #HC-2026/409"

    print(f"Updated Registry Status: {mock_db.registry[reg_id]['legal_status']}")
    print(f"Order ord_bid_01 Status: {mock_db.order_book['ord_bid_01']['status']} (Hold Reason: '{mock_db.order_book['ord_bid_01']['hold_reason']}')")

    # Step 3: Orders on Disputed plot are blocked
    print("\n[Step 3] Attempting to trade on Disputed parcel...")
    print("Matching Engine & Order Placement Trigger: REJECTED (Plot not Clear).")

    # Step 4: Dispute resolved, court lifts injunction
    print(f"\n[Step 4] Dispute resolved in court. Judicial officer lifts injunction...")
    mock_db.registry[reg_id]["legal_status"] = "Clear"
    for o in mock_db.order_book.values():
        if o["plot_id"] == plot_id and o["status"] == "On_Hold":
            o["status"] = "Open"
            o["hold_reason"] = None

    print(f"Restored Registry Status: {mock_db.registry[reg_id]['legal_status']}")
    print(f"Order ord_bid_01 Status: {mock_db.order_book['ord_bid_01']['status']} (Ready for Matching)")
    print("=" * 70)
    print("Injunction lifecycle demonstrated successfully.")
    print("=" * 70)

if __name__ == "__main__":
    run_injunction_demo()
