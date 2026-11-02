-- 003_views.sql: Market view for 3D spatial viewer and trading engine

CREATE OR REPLACE VIEW v_plot_market AS
SELECT 
    p.plot_id,
    p.street_address,
    p.city,
    p.state,
    p.zip,
    p.length_m,
    p.width_m,
    ROUND((ST_Area(p.boundary::geography) * 10.7639104)::numeric, 2) AS area_sqft,
    r.registry_id,
    r.current_owner_id AS owner_id,
    o.full_name AS owner_name,
    r.legal_status AS status,
    r.last_block_height,
    r.last_block_hash,
    (
        SELECT MAX(price)
        FROM order_book ob
        WHERE ob.plot_id = p.plot_id
          AND ob.order_type = 'BID'
          AND ob.status = 'Open'
    ) AS best_bid,
    (
        SELECT MIN(price)
        FROM order_book ob
        WHERE ob.plot_id = p.plot_id
          AND ob.order_type = 'ASK'
          AND ob.status = 'Open'
    ) AS active_ask,
    ST_AsGeoJSON(p.boundary) AS geojson
FROM plot p
JOIN registry_entry r ON p.plot_id = r.plot_id
LEFT JOIN owner o ON r.current_owner_id = o.owner_id;
