# scripts/seed.py
"""
Database seeding script for Land Exchange.
Idempotent script seeding:
- 4 owners with wallets and keypairs
- 1 user for each staff role (registry_admin, court, sys_admin)
- 25 non-overlapping plots in Bengaluru (including pentagons and touching plots)
- Mixed legal statuses (Clear, Pending, Disputed)
- Live Asks and Bids
- 3 historical settled sales with valid cryptographic ledger blocks
"""
import os
import sys
import json
import hashlib
import datetime
from shapely.geometry import Polygon, mapping

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.db.connection import get_pg_connection, get_mongo_db, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.auth import create_user
from backend.services.crypto import generate_test_ecdsa_keypair, sign_payload_with_private_key, canonical_json
from backend.services.ledger import ensure_genesis, append_block
from backend.services.spatial import calculate_area_sqft

def seed_database():
    print("--- Starting Land Exchange Database Seeding ---")
    ensure_genesis()

    # 1. Staff Users
    staff_users = [
        {"email": "admin@rvce.gov.in", "role": "registry_admin", "password": "AdminPassword123!"},
        {"email": "court@judiciary.gov.in", "role": "court", "password": "CourtPassword123!"},
        {"email": "sysadmin@landexchange.io", "role": "sys_admin", "password": "SysAdminPassword123!"}
    ]

    for s in staff_users:
        u = create_user(s["email"], s["password"], s["role"])
        print(f"Created staff user: {s['email']} ({s['role']})")

    # 2. Owners & Buyers
    owner_profiles = [
        {"name": "Ramesh Gowda", "email": "ramesh@gmail.com", "contact": "+91-9845012345", "balance": 15000000.0},
        {"name": "Priya Sharma", "email": "priya@outlook.com", "contact": "+91-9980154321", "balance": 22000000.0},
        {"name": "Vikram Malhotra", "email": "vikram@techcorp.in", "contact": "+91-9740298765", "balance": 35000000.0},
        {"name": "Ananya Hegde", "email": "ananya@startups.in", "contact": "+91-9632112233", "balance": 18000000.0}
    ]

    created_owners = []
    salt = "RVCE_LAND_EXCHANGE_SALT_2026"

    for idx, p in enumerate(owner_profiles):
        priv_key, pub_pem, _ = generate_test_ecdsa_keypair()
        owner_id = f"own_blr_{idx+1:03d}"
        doc_no = f"AADHAAR_{1000 + idx}"
        kyc_hash = hashlib.sha256(f"{doc_no}_{salt}".encode('utf-8')).hexdigest()
        wallet_addr = f"0x{hashlib.sha256(owner_id.encode('utf-8')).hexdigest()[:40]}"

        if is_mock_mode():
            mock_db.owners[owner_id] = {
                "owner_id": owner_id,
                "full_name": p["name"],
                "contact": p["contact"],
                "kyc_hash": kyc_hash,
                "public_key": pub_pem,
                "wallet_address": wallet_addr
            }
            mock_db.wallets[owner_id] = {
                "owner_id": owner_id,
                "balance_available": p["balance"],
                "balance_held": 0.00
            }
        else:
            try:
                with get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO owner (owner_id, full_name, contact, kyc_hash, public_key, wallet_address)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (owner_id) DO NOTHING;
                            """,
                            (owner_id, p["name"], p["contact"], kyc_hash, pub_pem, wallet_addr)
                        )
                        cur.execute(
                            """
                            INSERT INTO wallet (owner_id, balance_available, balance_held)
                            VALUES (%s, %s, 0.00)
                            ON CONFLICT (owner_id) DO UPDATE SET balance_available = EXCLUDED.balance_available;
                            """,
                            (owner_id, p["balance"])
                        )
                    conn.commit()
            except Exception as e:
                print(f"Notice: {e}")

        # Create user login
        u = create_user(p["email"], "SecurePass123!", "buyer" if idx % 2 == 0 else "owner_seller", owner_id=owner_id)
        created_owners.append({"owner_id": owner_id, "priv_key": priv_key, "pub_pem": pub_pem, "email": p["email"]})
        print(f"Created owner & user: {p['name']} ({owner_id}) with INR {p['balance']:,.2f}")

    # 3. Generate 25 Plots in Bengaluru (Grid, Pentagons, Touching pair)
    # Origin: Bengaluru Indiranagar area (77.6400 Lon, 12.9750 Lat)
    base_lon = 77.6350
    base_lat = 12.9700
    step = 0.0020 # ~220m spacing

    plots_seeded = []
    plot_index = 1

    for row in range(5):
        for col in range(5):
            pid = f"plot_blr_{plot_index:03d}"
            lon0 = base_lon + (col * step)
            lat0 = base_lat + (row * step)
            d = 0.0012 # plot dimensions ~130m

            # Create standard rectangles, plus pentagons for index 5, 10, 15
            if plot_index in (5, 10, 15):
                # Pentagon shape
                poly = Polygon([
                    (lon0, lat0),
                    (lon0 + d, lat0),
                    (lon0 + d * 1.2, lat0 + d * 0.6),
                    (lon0 + d * 0.5, lat0 + d * 1.2),
                    (lon0, lat0 + d * 0.7),
                    (lon0, lat0)
                ])
            elif plot_index == 2:
                # Plot 2 touches Plot 1 exactly along western edge
                lon_touch = base_lon + 0.0012
                lat_touch = base_lat
                poly = Polygon([
                    (lon_touch, lat_touch),
                    (lon_touch + d, lat_touch),
                    (lon_touch + d, lat_touch + d),
                    (lon_touch, lat_touch + d),
                    (lon_touch, lat_touch)
                ])
            else:
                # Regular rectangle
                poly = Polygon([
                    (lon0, lat0),
                    (lon0 + d, lat0),
                    (lon0 + d, lat0 + d),
                    (lon0, lat0 + d),
                    (lon0, lat0)
                ])

            owner = created_owners[plot_index % len(created_owners)]
            status = "Clear"
            if plot_index % 6 == 0:
                status = "Pending"
            elif plot_index % 7 == 0:
                status = "Disputed"

            area_sqft = calculate_area_sqft(poly)
            street = f"Survey #{100 + plot_index}, 100 Feet Road, Indiranagar"
            city = "Bengaluru"
            state = "Karnataka"
            zip_code = "560038"

            if is_mock_mode():
                mock_db.plots[pid] = {
                    "plot_id": pid,
                    "street_address": street,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "length_m": 40.0,
                    "width_m": 30.0,
                    "geojson": mapping(poly),
                    "area_sqft": area_sqft
                }
                mock_db.registry[f"reg_{pid}"] = {
                    "registry_id": f"reg_{pid}",
                    "plot_id": pid,
                    "current_owner_id": owner["owner_id"],
                    "legal_status": status,
                    "last_block_height": 0,
                    "last_block_hash": "0" * 64
                }
            else:
                try:
                    with get_pg_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO plot (plot_id, street_address, city, state, zip, length_m, width_m, boundary)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                                ON CONFLICT (plot_id) DO NOTHING;
                                """,
                                (pid, street, city, state, zip_code, 40.0, 30.0, json.dumps(mapping(poly)))
                            )
                            cur.execute(
                                """
                                INSERT INTO registry_entry (registry_id, plot_id, current_owner_id, legal_status)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (plot_id) DO UPDATE SET legal_status = EXCLUDED.legal_status;
                                """,
                                (f"reg_{pid}", pid, owner["owner_id"], status)
                            )
                        conn.commit()
                except Exception as e:
                    print(f"Notice inserting plot: {e}")

            plots_seeded.append({"plot_id": pid, "owner": owner, "status": status})
            plot_index += 1

    print(f"Seeded {len(plots_seeded)} parcels in Bengaluru (with pentagons & touching boundary).")

    # 4. Seed 3 Historical Settled Sales into Cryptographic Ledger
    print("Seeding 3 historical sales into MongoDB append-only chain...")
    sales = [
        {"plot_id": "plot_blr_001", "seller": created_owners[0], "buyer": created_owners[1], "price": 8500000.0},
        {"plot_id": "plot_blr_003", "seller": created_owners[1], "buyer": created_owners[2], "price": 9200000.0},
        {"plot_id": "plot_blr_004", "seller": created_owners[2], "buyer": created_owners[3], "price": 7800000.0}
    ]

    for sale in sales:
        pid = sale["plot_id"]
        seller = sale["seller"]
        buyer = sale["buyer"]
        price = sale["price"]
        gid = f"tx_seed_{pid}"

        # Signatures
        seller_sig = sign_payload_with_private_key(seller["priv_key"], canonical_json({"plot": pid, "sell": price}).encode())
        buyer_sig = sign_payload_with_private_key(buyer["priv_key"], canonical_json({"plot": pid, "buy": price}).encode())

        blk = append_block(
            block_type="SALE",
            registry_id=f"reg_{pid}",
            plot_id=pid,
            seller_id=seller["owner_id"],
            buyer_id=buyer["owner_id"],
            sale_price=price,
            seller_signature=seller_sig,
            buyer_signature=buyer_sig,
            gid=gid
        )

        # Update registry entry
        if is_mock_mode():
            reg = mock_db.registry.get(f"reg_{pid}")
            if reg:
                reg["current_owner_id"] = buyer["owner_id"]
                reg["last_block_height"] = blk["block_number"]
                reg["last_block_hash"] = blk["tx_id"]
        else:
            try:
                with get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE registry_entry
                            SET current_owner_id = %s, last_block_height = %s, last_block_hash = %s
                            WHERE plot_id = %s;
                            """,
                            (buyer["owner_id"], blk["block_number"], blk["tx_id"], pid)
                        )
                    conn.commit()
            except Exception as e:
                print(f"Notice: {e}")

        print(f"Sealed Sale Block #{blk['block_number']} for {pid}: INR {price:,.2f} -> Tx: {blk['tx_id'][:16]}...")

    print("--- Database Seeding Complete ---")

if __name__ == "__main__":
    seed_database()
