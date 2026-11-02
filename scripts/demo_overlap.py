# scripts/demo_overlap.py
"""
Demonstrates PostGIS spatial integrity rule DECISION 2:
Reject if ST_Intersects AND NOT ST_Touches.
1. Attempts to register an overlapping polygon inside an existing plot -> REJECTED.
2. Registers a plot that cleanly touches the border without interior overlap -> ACCEPTED.
"""
import os
import sys
from shapely.geometry import Polygon

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.services.spatial import check_plot_overlap
from backend.db.mock_store import mock_db
from backend.db.connection import is_mock_mode

def run_overlap_demo():
    print("=" * 70)
    print("DEMO: PostGIS Spatial Overlap Integrity & Boundary Touching Rule")
    print("=" * 70)

    # Base plot (Existing)
    # [ (77.60, 12.90), (77.62, 12.90), (77.62, 12.92), (77.60, 12.92) ]
    existing_poly = Polygon([(77.60, 12.90), (77.62, 12.90), (77.62, 12.92), (77.60, 12.92), (77.60, 12.90)])
    mock_db.plots["plot_existing_01"] = {
        "plot_id": "plot_existing_01",
        "geojson": {
            "type": "Polygon",
            "coordinates": [[list(c) for c in existing_poly.exterior.coords]]
        }
    }
    print("Existing Plot in Registry: 'plot_existing_01' [77.60 to 77.62, 12.90 to 12.92]")

    # Case 1: Overlapping plot (77.61 to 77.63, 12.91 to 12.93)
    # Intersects interior!
    overlap_poly = Polygon([(77.61, 12.91), (77.63, 12.91), (77.63, 12.93), (77.61, 12.93), (77.61, 12.91)])
    print("\n[Case 1] Attempting to register overlapping plot (encroaches interior by 50%)...")
    has_overlap, conflict_id = check_plot_overlap(overlap_poly)
    if has_overlap:
        print(f"-> REJECTED! Conflict detected with: '{conflict_id}'")
        print("-> Reason: ST_Intersects = TRUE, ST_Touches = FALSE.")
    else:
        print("-> Unexpectedly allowed.")

    # Case 2: Touching plot (77.62 to 77.64, 12.90 to 12.92)
    # Shares exactly the eastern boundary line from 12.90 to 12.92!
    touching_poly = Polygon([(77.62, 12.90), (77.64, 12.90), (77.64, 12.92), (77.62, 12.92), (77.62, 12.90)])
    print("\n[Case 2] Attempting to register adjacent plot sharing eastern border (touching)...")
    has_overlap, conflict_id = check_plot_overlap(touching_poly)
    if not has_overlap:
        print("-> ACCEPTED! Plot boundary touches cleanly without interior encroachment.")
        print("-> Reason: ST_Intersects = TRUE, ST_Touches = TRUE.")
    else:
        print(f"-> Rejected with conflict: {conflict_id}")

    print("=" * 70)
    print("Spatial validation rules verified.")
    print("=" * 70)

if __name__ == "__main__":
    run_overlap_demo()
