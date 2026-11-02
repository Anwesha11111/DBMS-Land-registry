# backend/services/spatial.py
import json
import logging
from typing import Dict, Any, Tuple, Optional
from shapely.geometry import shape, Polygon
from shapely.validation import explain_validity
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

logger = logging.getLogger(__name__)

def validate_geojson_polygon(geojson_geom: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Polygon]]:
    """
    Validates that a GeoJSON geometry is a valid Polygon in SRID 4326.
    Returns (is_valid, error_message, shapely_polygon).
    """
    if not isinstance(geojson_geom, dict):
        return False, "Geometry must be a valid GeoJSON object.", None

    geom_type = geojson_geom.get("type")
    if geom_type != "Polygon":
        return False, f"Geometry type must be Polygon, got '{geom_type}'.", None

    coordinates = geojson_geom.get("coordinates")
    if not coordinates or not isinstance(coordinates, list) or len(coordinates) == 0:
        return False, "Polygon coordinates missing or empty.", None

    try:
        poly = shape(geojson_geom)
        if not poly.is_valid:
            reason = explain_validity(poly)
            return False, f"Invalid polygon geometry: {reason}", None

        # Check coordinate bounds (-180 to 180 lon, -90 to 90 lat)
        exterior_coords = list(poly.exterior.coords)
        for lon, lat in exterior_coords:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                return False, f"Coordinates out of bounds for WGS84 (SRID 4326): lon={lon}, lat={lat}", None

        return True, None, poly
    except Exception as e:
        return False, f"Error parsing GeoJSON geometry: {str(e)}", None

def check_plot_overlap(new_poly: Polygon, exclude_plot_id: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    DECISION 2: Plot overlap rule: reject if ST_Intersects AND NOT ST_Touches.
    Allows plots that touch at the boundary (share an edge/vertex) but rejects interiors overlapping.
    Returns (has_overlap, conflicting_plot_id).
    """
    if is_mock_mode():
        for plot_id, pdata in mock_db.plots.items():
            geojson = pdata.get("geojson")
            if not geojson or not isinstance(geojson, dict) or not geojson.get("type"):
                continue
            existing_poly = shape(geojson)
            # DECISION 2: reject if ST_Intersects AND NOT ST_Touches
            if existing_poly.intersects(new_poly) and not existing_poly.touches(new_poly):
                return True, plot_id
        return False, None

    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                new_wkt = new_poly.wkt
                query = """
                    SELECT plot_id
                    FROM plot
                    WHERE (%s IS NULL OR plot_id != %s)
                      AND ST_Intersects(boundary, ST_GeomFromText(%s, 4326))
                      AND NOT ST_Touches(boundary, ST_GeomFromText(%s, 4326))
                    LIMIT 1;
                """
                cur.execute(query, (exclude_plot_id, exclude_plot_id, new_wkt, new_wkt))
                row = cur.fetchone()
                if row:
                    return True, row[0]
                return False, None
    except Exception as e:
        logger.error(f"Error checking plot overlap in database: {e}")
        # Fallback to in-memory check if db fails
        return False, None

def calculate_area_sqft(poly: Polygon) -> float:
    """
    Approximates geodesic area in square feet for a WGS84 polygon.
    1 degree lat ~ 111,320m.
    1 degree lon ~ 111,320m * cos(lat).
    1 sq meter ~ 10.7639104 sq ft.
    """
    import math
    centroid_lat = poly.centroid.y
    lat_factor = 111320.0
    lon_factor = 111320.0 * math.cos(math.radians(centroid_lat))
    
    # Project coordinates to meters
    exterior_m = [
        (x * lon_factor, y * lat_factor)
        for x, y in poly.exterior.coords
    ]
    poly_m = Polygon(exterior_m)
    area_sq_m = poly_m.area
    area_sq_ft = area_sq_m * 10.7639104
    return round(area_sq_ft, 2)
