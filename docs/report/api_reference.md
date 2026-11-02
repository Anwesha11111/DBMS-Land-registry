# Land Exchange: REST API Reference Documentation

**Course:** DBMS CD252IA, RVCE (2026)  
**Implementation Source:** [`backend/routes/`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/)

---

## 1. Authentication & Identity Management ([`backend/routes/auth.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/auth.py))

### `POST /auth/register`
- **Access:** Public
- **Description:** Registers a new user account. For `buyer` or `owner_seller`, creates an owner record, computes salted KYC hash, generates a wallet with simulated balance, and registers the browser-generated ECDSA P-256 public key.
- **Request Body:**
  ```json
  {
    "email": "rohan@rvce.edu.in",
    "password": "Password123!",
    "role": "owner_seller",
    "full_name": "Rohan Deshmukh",
    "contact": "+91-9876543210",
    "document_no": "AADH-9876-5432",
    "public_key": "-----BEGIN PUBLIC KEY-----\nMFkwEw...",
    "initial_wallet": 10000000.00
  }
  ```
- **Response (201 Created):**
  ```json
  {
    "message": "User registered successfully.",
    "user_id": "user_a1b2c3d4",
    "email": "rohan@rvce.edu.in",
    "role": "owner_seller",
    "owner_id": "own_e5f6g7h8",
    "token": "eyJhbGciOiJIUzI1Ni..."
  }
  ```

### `POST /auth/login`
- **Access:** Public
- **Description:** Authenticates user credentials via bcrypt verification. Enforces TOTP MFA token verification for privileged roles (`registry_admin`, `court`, `sys_admin`). Returns JWT bearer token.
- **Request Body:**
  ```json
  {
    "email": "admin@rvce.gov.in",
    "password": "AdminPassword123!",
    "mfa_token": "123456"
  }
  ```

### `GET /auth/me`
- **Access:** Authenticated
- **Description:** Returns profile metadata, role permissions, and active wallet balance for current user.

---

## 2. Parcel Geometry & Market View ([`backend/routes/plots.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/plots.py))

### `GET /plots`
- **Access:** Public
- **Description:** Returns all land parcels formatted from the `v_plot_market` SQL view for the Three.js 3D viewer. Includes GeoJSON geometry, legal status, best ask, best bid, and area in square feet.

### `POST /plots`
- **Access:** `registry_admin`, `sys_admin`
- **Description:** Registers a newly surveyed land parcel. Validates GeoJSON Polygon validity (`ST_IsValid`) and enforces the spatial overlap rule (`ST_Intersects AND NOT ST_Touches`). Creates associated `registry_entry` with initial status `Pending`.
- **Request Body:**
  ```json
  {
    "plot_id": "plot_blr_101",
    "street_address": "80 Feet Road, Indiranagar",
    "city": "Bengaluru",
    "state": "Karnataka",
    "zip": "560038",
    "length_m": 40.0,
    "width_m": 30.0,
    "current_owner_id": "own_e5f6g7h8",
    "boundary": {
      "type": "Polygon",
      "coordinates": [[[77.640, 12.970], [77.642, 12.970], [77.642, 12.972], [77.640, 12.972], [77.640, 12.970]]]
    }
  }
  ```

### `GET /plots/stream`
- **Access:** Public
- **Description:** Server-Sent Events (SSE) streaming endpoint publishing real-time market order events, status transitions, and plot updates directly to the 3D client without polling.

---

## 3. Title Registry & Status Management ([`backend/routes/registry.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/registry.py))

### `PATCH /registry/<registry_id>/status`
- **Access:** `registry_admin`, `court`, `sys_admin`
- **Description:** Transitions a plot's title deed status between `Clear`, `Pending`, and `Disputed`. Triggers `fn_log_registry_status_history()` to log immutable audit history.
- **Request Body:**
  ```json
  {
    "status": "Clear",
    "reason": "Title documents verified by municipal authority."
  }
  ```

---

## 4. Judicial Injunctions ([`backend/routes/injunctions.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/injunctions.py))

### `POST /injunctions`
- **Access:** `court`, `sys_admin`
- **Description:** Issues a formal judicial stay order on a plot. Sets `registry_entry.legal_status` to `Disputed` and locks all active bids and asks on the parcel to `On_Hold`.
- **Request Body:**
  ```json
  {
    "plot_id": "plot_blr_001",
    "court_case_no": "HC-KAR-2026/894",
    "court_name": "High Court of Karnataka",
    "injunction_order_details": "Stay on secondary transfer pending boundary dispute trial."
  }
  ```

### `POST /injunctions/<injunction_id>/release`
- **Access:** `court`, `sys_admin`
- **Description:** Lifts court injunction upon judicial resolution. Restores parcel status to `Clear` and returns frozen orders back to `Open`.

---

## 5. Order Book & P2P Trading ([`backend/routes/orders.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/orders.py))

### `POST /orders`
- **Access:** `buyer`, `owner_seller`
- **Description:** Submits a cryptographically signed limit order (`BID` or `ASK`). Verifies trader's ECDSA P-256 signature against canonical JSON payload. Enforces partial unique index (only 1 open Ask per plot). Escrows funds for Bids. Triggers automated matching engine.
- **Request Body:**
  ```json
  {
    "plot_id": "plot_blr_001",
    "order_type": "BID",
    "price": 12500000.00,
    "nonce": 0,
    "timestamp": "2026-10-29T10:00:00Z",
    "signature": "30440220... (DER-encoded hex)"
  }
  ```

### `GET /orders/book/<plot_id>`
- **Access:** Public
- **Description:** Retrieves real-time depth table of open Bids (sorted price DESC, time ASC) and the active Ask for a parcel.

### `DELETE /orders/<order_id>`
- **Access:** Order Owner
- **Description:** Cancels an open order. If cancelling a Bid, releases held escrow funds back to available wallet balance.

---

## 6. Public Verification Portal ([`backend/routes/public.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/public.py))

### `GET /public/verify/<plot_id>`
- **Access:** Public (No login required)
- **Description:** Runs cryptographic verification across the entire append-only ledger (`verify_chain()`). Checks all SHA-256 block hashes, Merkle roots, and prev-block pointers. Returns large `PASS` or `FAIL` badge within seconds.
- **Response:**
  ```json
  {
    "plot_id": "plot_blr_001",
    "result": "PASS",
    "verified": true,
    "blocks_audited": 4,
    "current_owner": "own_blr_003",
    "timestamp": "2026-10-29T14:40:00Z"
  }
  ```

### `GET /public/title-chain/<plot_id>`
- **Access:** Public (No login required)
- **Description:** Returns sequential title ownership history from Genesis block to current tip. Strictly redacts sensitive personal KYC data.

---

## 7. Reports & Search ([`backend/routes/reports.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/reports.py), [`backend/routes/search.py`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/backend/routes/search.py))

### `GET /reports/plot/<plot_id>/history?format=pdf|csv`
- **Access:** Public
- **Description:** Streams certified ownership history report as a downloadable binary PDF or CSV, stamped with official generation timestamp and cryptographic audit verification badge.

### `GET /search?q=<query>`
- **Access:** Public / Role-Gated
- **Description:** Searches across parcels, plot IDs, addresses, and owner accounts. Automatically redacts owner names for unauthorized roles to preserve privacy.
