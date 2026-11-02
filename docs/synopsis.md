# Project Synopsis: Land Exchange

**Course:** Database Management Systems (CD252IA), RVCE  
**Prepared For:** Anwesha Mohapatra and Abdul Mateen Nandgadi  
**Title:** Decentralized Blockchain-Style Land Registry + Zero-Brokerage P2P Real Estate Exchange with 3D Viewer

## 1. Abstract
The traditional land registry and real estate transfer system suffers from fraud, opaque transaction histories, predatory brokerage fees, and fragmented spatial record keeping. **Land Exchange** presents a hybrid, polyglot persistence architecture combining PostgreSQL/PostGIS and an append-only, SHA-256 hash-linked cryptographic ledger in MongoDB. The system enforces strict spatial boundary rules (zero unauthorized overlaps, valid geometric polygons), guarantees Delivery-versus-Payment (DvP) via Two-Phase Commit (2PC) between relational state and cryptographic ledger blocks, implements a price-time priority matching engine for zero-brokerage trading, and offers an interactive Three.js 3D spatial viewer and public verification portal.

## 2. Objectives
1. **Cryptographic Land Registry:** Prevent double-selling and title tampering via append-only hash chains with WebCrypto ECDSA P-256 digital signatures.
2. **Spatial Integrity:** Guarantee plot validity and reject overlaps using PostGIS spatial triggers (allowing shared boundary touches while strictly prohibiting polygon intersections).
3. **Atomic 2PC Settlement:** Coordinate cross-database state transition using PostgreSQL prepared transactions (`PREPARE TRANSACTION`) and MongoDB block creation.
4. **Zero-Brokerage Exchange:** Facilitate P2P land trading using an in-memory & relational order book with automated price-time matching.
5. **Interactive 3D Visualizer & Public Portal:** Provide intuitive 3D spatial rendering of land parcels color-coded by real-time status, alongside transparent title chain verification for public citizens without authentication.
