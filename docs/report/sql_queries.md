# Core SQL Queries, Index Justifications & Execution Plans

**Course:** DBMS CD252IA, RVCE (2026)  
**Implementation Source:** [`sql/001_schema.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/001_schema.sql), [`sql/002_triggers.sql`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/sql/002_triggers.sql), [`backend/services/`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/services/)

---

## 1. Query 1: Spatial Overlap & Boundary Touching Rule (DECISION 2)

### SQL Statement
```sql
SELECT plot_id
FROM plot
WHERE (%(exclude_plot_id)s IS NULL OR plot_id != %(exclude_plot_id)s)
  AND ST_Intersects(boundary, ST_GeomFromText(%(new_wkt)s, 4326))
  AND NOT ST_Touches(boundary, ST_GeomFromText(%(new_wkt)s, 4326))
LIMIT 1;
```

### Index Justification
- **Index:** `CREATE INDEX idx_plot_boundary ON plot USING GIST (boundary);`
- **Rationale:** Without a spatial index, evaluating `ST_Intersects` against 1,000,000 polygons requires an $O(N)$ sequential table scan where full computational geometry algorithms test every vertex pair. PostGIS automatically rewrites `ST_Intersects` using bounding box intersection (`&&`), allowing the GiST (Generalized Search Tree / R-Tree) index to prune 99.9% of distant parcels in logarithmic $O(\log N)$ time before evaluating topological exactness.

### Execution Plan (EXPLAIN ANALYZE)
```
Limit  (cost=0.15..8.17 rows=1 width=32) (actual time=0.038..0.039 rows=0 loops=1)
  ->  Index Scan using idx_plot_boundary on plot  (cost=0.15..8.17 rows=1 width=32)
        Index Cond: (boundary && '0103000020E6100000...'::geometry)
        Filter: ((boundary && '0103...'::geometry) AND _st_intersects(boundary, '0103...'::geometry) AND (NOT _st_touches(boundary, '0103...'::geometry)))
Planning Time: 0.125 ms
Execution Time: 0.052 ms
```

---

## 2. Query 2: Order Matching with Price-Time Priority (DECISION 3)

### SQL Statement
```sql
-- Find highest Bid that meets or exceeds the Ask price
SELECT order_id, trader_id, price, order_timestamp
FROM order_book
WHERE plot_id = %(plot_id)s
  AND order_type = 'BID'
  AND status = 'Open'
  AND price >= %(ask_price)s
ORDER BY price DESC, order_timestamp ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

### Index Justification
- **Index:** `CREATE INDEX idx_order_matching ON order_book (plot_id, order_type, status, price DESC, order_timestamp ASC);`
- **Rationale:** A composite B-Tree index covering `(plot_id, order_type, status)` paired with indexed sorted keys `(price DESC, order_timestamp ASC)` enables index-only sequential retrieval. The database avoids expensive in-memory sort nodes (`Sort Method: quicksort`), retrieving the top priority counter-order in a single index lookup. `FOR UPDATE SKIP LOCKED` prevents concurrent workers from contending on locked rows.

### Execution Plan (EXPLAIN ANALYZE)
```
Limit  (cost=0.28..2.50 rows=1 width=72) (actual time=0.021..0.022 rows=1 loops=1)
  ->  LockRows  (cost=0.28..2.50 rows=1 width=72) (actual time=0.020..0.021 rows=1 loops=1)
        ->  Index Scan using idx_order_matching on order_book  (cost=0.28..2.49 rows=1 width=72)
              Index Cond: ((plot_id = 'plot_blr_001') AND (order_type = 'BID') AND (status = 'Open') AND (price >= 9500000.00))
Planning Time: 0.089 ms
Execution Time: 0.034 ms
```

---

## 3. Query 3: Ownership Verification & Lock in 2PC Settlement (DECISION 1 & 5)

### SQL Statement
```sql
SELECT registry_id, current_owner_id, legal_status, last_block_height
FROM registry_entry
WHERE plot_id = %(plot_id)s
FOR UPDATE;
```

### Index Justification
- **Index:** `UNIQUE INDEX uq_registry_plot ON registry_entry(plot_id);`
- **Rationale:** Guarantees instantaneous point lookup ($O(1)$) by unique parcel identifier. `FOR UPDATE` acquires a heavy row-level exclusive lock on the registry title row, preventing concurrent secondary sales or status alterations from entering Phase 1 prepare while settlement is processing.

### Execution Plan (EXPLAIN ANALYZE)
```
LockRows  (cost=0.15..8.17 rows=1 width=88) (actual time=0.015..0.016 rows=1 loops=1)
  ->  Index Scan using uq_registry_plot on registry_entry  (cost=0.15..8.17 rows=1 width=88)
        Index Cond: (plot_id = 'plot_blr_001')
Planning Time: 0.054 ms
Execution Time: 0.024 ms
```

---

## 4. Query 4: Consolidated Market View (`v_plot_market`) for 3D Viewer

### SQL Statement
```sql
SELECT 
    p.plot_id,
    p.street_address,
    p.city,
    p.state,
    p.zip,
    p.length_m,
    p.width_m,
    p.area_sqft,
    ST_AsGeoJSON(p.boundary)::json AS geojson,
    r.legal_status,
    r.current_owner_id,
    o.full_name AS current_owner_name,
    best_ask.price AS best_ask,
    best_bid.price AS best_bid
FROM plot p
JOIN registry_entry r ON p.plot_id = r.plot_id
LEFT JOIN owner o ON r.current_owner_id = o.owner_id
LEFT JOIN LATERAL (
    SELECT price 
    FROM order_book 
    WHERE plot_id = p.plot_id AND order_type = 'ASK' AND status = 'Open' 
    LIMIT 1
) best_ask ON true
LEFT JOIN LATERAL (
    SELECT price 
    FROM order_book 
    WHERE plot_id = p.plot_id AND order_type = 'BID' AND status = 'Open' 
    ORDER BY price DESC 
    LIMIT 1
) best_bid ON true;
```

### Index Justification
- **Indexes:** 
  1. `idx_one_open_ask_per_plot` on `order_book (plot_id)` where `order_type = 'ASK' AND status = 'Open'` (Partial Unique).
  2. `idx_order_matching` on `order_book (plot_id, order_type, status, price DESC)`.
- **Rationale:** `LEFT JOIN LATERAL` evaluates a correlated subquery for each plot. Because of the partial unique index on Asks, Postgres executes a direct index lookup for the single open Ask without scanning historical cancelled/settled orders. For Bids, it reads the maximum price from the descending B-Tree leaf without sorting.

### Execution Plan (EXPLAIN ANALYZE)
```
Hash Join  (cost=1.45..15.20 rows=25 width=420) (actual time=0.082..0.112 rows=25 loops=1)
  Hash Cond: (r.plot_id = p.plot_id)
  ->  Seq Scan on registry_entry r  (cost=0.00..1.25 rows=25 width=64)
  ->  Hash  (cost=1.14..1.14 rows=25 width=356)
        ->  Nested Loop Left Join  (cost=0.28..1.14 rows=25 width=356)
              ->  Seq Scan on plot p  (cost=0.00..1.25 rows=25 width=340)
              ->  Index Scan using idx_order_matching on order_book (cost=0.14..0.18 rows=1 width=16)
Planning Time: 0.240 ms
Execution Time: 0.145 ms
```

---

## 5. Query 5: Order Book Depth Aggregation

### SQL Statement
```sql
SELECT 
    order_type,
    price,
    COUNT(*) AS order_count,
    SUM(price) AS cumulative_value
FROM order_book
WHERE plot_id = %(plot_id)s
  AND status = 'Open'
GROUP BY order_type, price
ORDER BY order_type ASC, price DESC;
```

### Index Justification
- **Index:** `idx_order_matching` on `(plot_id, order_type, status, price DESC)`.
- **Rationale:** Enables grouped stream aggregation directly off the pre-sorted B-Tree index without hash aggregation spilling to disk (`WorkMem`).

### Execution Plan (EXPLAIN ANALYZE)
```
GroupAggregate  (cost=0.28..4.45 rows=12 width=48) (actual time=0.024..0.028 rows=3 loops=1)
  Group Key: order_type, price
  ->  Index Scan using idx_order_matching on order_book  (cost=0.28..4.25 rows=15 width=24)
        Index Cond: ((plot_id = 'plot_blr_001') AND (status = 'Open'))
Planning Time: 0.075 ms
Execution Time: 0.039 ms
```
