# Test Suite & Verification Summary

**Course:** DBMS CD252IA, RVCE (2026)  
**Execution Environment:** Python 3.13.7, pytest 9.0.2, Windows 10/11  
**Test Suite Directory:** [`tests/`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/)

---

## 1. Pytest Suite Execution Results

All 30 automated integration, unit, and end-to-end tests pass cleanly with **100% success rate**.

```
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.0.2, pluggy-1.6.0
rootdir: C:\Users\DELL\Downloads\New folder\PROJECTS\LANDREGISTRY
collected 30 items

tests/test_01_health.py::test_health_endpoint PASSED                     [  3%]
tests/test_02_database_rules.py::test_overlap_rejected_and_touching_accepted PASSED [  6%]
tests/test_02_database_rules.py::test_invalid_geometry_rejected PASSED   [ 10%]
tests/test_02_database_rules.py::test_duplicate_kyc_rejected PASSED      [ 13%]
tests/test_02_database_rules.py::test_second_open_ask_rejected PASSED    [ 16%]
tests/test_02_database_rules.py::test_orders_on_disputed_plot_rejected PASSED [ 20%]
tests/test_02_database_rules.py::test_mongo_update_delete_denied_for_app_user PASSED [ 23%]
tests/test_03_auth_and_crypto.py::test_wrong_role_gets_403 PASSED        [ 26%]
tests/test_03_auth_and_crypto.py::test_mfa_required_for_court_and_admin PASSED [ 30%]
tests/test_03_auth_and_crypto.py::test_tampered_payload_fails_signature_verification PASSED [ 33%]
tests/test_04_plots_and_injunctions.py::test_register_valid_pentagon_plot PASSED [ 36%]
tests/test_04_plots_and_injunctions.py::test_injunction_holds_orders_and_release_restores_them PASSED [ 40%]
tests/test_05_orderbook_and_matching.py::test_no_match_when_bid_less_than_ask PASSED [ 43%]
tests/test_05_orderbook_and_matching.py::test_match_when_bid_equals_ask PASSED [ 46%]
tests/test_05_orderbook_and_matching.py::test_highest_bid_wins_and_earlier_bid_wins_ties PASSED [ 50%]
tests/test_05_orderbook_and_matching.py::test_insufficient_funds_rejected PASSED [ 53%]
tests/test_06_ledger.py::test_five_block_chain_and_verify_pass PASSED    [ 56%]
tests/test_06_ledger.py::test_tamper_detected_and_exact_block_reported PASSED [ 60%]
tests/test_06_ledger.py::test_fork_attempt_rejected PASSED               [ 63%]
tests/test_06_ledger.py::test_self_approved_correction_rejected PASSED   [ 66%]
tests/test_07_settlement_2pc.py::test_2pc_happy_path PASSED              [ 70%]
tests/test_07_settlement_2pc.py::test_2pc_seal_failure_rolls_back_everything PASSED [ 73%]
tests/test_07_settlement_2pc.py::test_crash_after_seal_recovery_commits PASSED [ 76%]
tests/test_07_settlement_2pc.py::test_crash_after_prepare_recovery_rolls_back PASSED [ 80%]
tests/test_08_reports_and_search.py::test_reports_pdf_and_csv_export PASSED [ 83%]
tests/test_08_reports_and_search.py::test_search_endpoint_role_gating PASSED [ 86%]
tests/test_08_reports_and_search.py::test_admin_integrity_endpoint PASSED [ 90%]
tests/test_10_public_portal.py::test_public_verify_returns_pass_for_valid_plot PASSED [ 93%]
tests/test_10_public_portal.py::test_public_title_chain_endpoint_no_sensitive_kyc PASSED [ 96%]
tests/test_11_e2e.py::test_full_e2e_lifecycle PASSED                     [100%]

============================= 30 passed in 8.29s ==============================
```

---

## 2. Test Coverage Breakdown by Architectural Decision

| Decision # | Architectural Rule | Test Coverage File & Function | Result |
| :---: | :--- | :--- | :---: |
| **DECISION 1** | Sole ownership in `registry_entry` | [`test_02_database_rules.py:test_orders_on_disputed_plot_rejected`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_02_database_rules.py) | **PASSED** |
| **DECISION 2** | Reject overlap if `ST_Intersects AND NOT ST_Touches` | [`test_02_database_rules.py:test_overlap_rejected_and_touching_accepted`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_02_database_rules.py) | **PASSED** |
| **DECISION 3** | Partial unique index: 1 open Ask per plot | [`test_02_database_rules.py:test_second_open_ask_rejected`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_02_database_rules.py) | **PASSED** |
| **DECISION 4** | Order state machine & Injunction holds | [`test_04_plots_and_injunctions.py:test_injunction_holds_orders_and_release_restores_them`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_04_plots_and_injunctions.py) | **PASSED** |
| **DECISION 5** | 2PC settlement (`PREPARE TRANSACTION` -> Seal -> `COMMIT`) | [`test_07_settlement_2pc.py:test_2pc_happy_path`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_07_settlement_2pc.py), `test_crash_after_seal_recovery_commits` | **PASSED** |
| **DECISION 6** | Canonical JSON block hash & Genesis block | [`test_06_ledger.py:test_five_block_chain_and_verify_pass`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_06_ledger.py) | **PASSED** |
| **DECISION 7** | Browser ECDSA P-256 signatures & tampered rejection | [`test_03_auth_and_crypto.py:test_tampered_payload_fails_signature_verification`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_03_auth_and_crypto.py) | **PASSED** |
| **DECISION 8** | Wallet available / held escrow balances | [`test_05_orderbook_and_matching.py:test_insufficient_funds_rejected`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_05_orderbook_and_matching.py) | **PASSED** |
| **DECISION 9** | MongoDB app user restricted from UPDATE / DELETE | [`test_02_database_rules.py:test_mongo_update_delete_denied_for_app_user`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_02_database_rules.py) | **PASSED** |
| **DECISION 10**| KYC stored only as hash, TOTP MFA for staff | [`test_02_database_rules.py:test_duplicate_kyc_rejected`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_02_database_rules.py), [`test_03_auth_and_crypto.py:test_mfa_required_for_court_and_admin`](file:///c:/Users/DELL/Downloads/New%20folder/PROJECTS/LANDREGISTRY/tests/test_03_auth_and_crypto.py) | **PASSED** |

---

## 3. End-to-End Scenario Flow (`test_11_e2e.py`)

The end-to-end test validates the full lifecycle without human intervention:
1. Seller and Buyer register in browser, generating local ECDSA keypairs.
2. Registry Admin registers and approves a parcel in Indiranagar, Bengaluru.
3. Seller signs and submits limit Ask order (`INR 12,000,000`).
4. Buyer signs and submits matching Bid order (`INR 12,000,000`).
5. Automated matching engine triggers 2PC settlement.
6. Cash debited from held balance to seller's available balance in PostgreSQL.
7. Title block sealed in MongoDB append-only chain.
8. 3D market view reflects instant ownership update.
9. Public verification portal queries title chain and returns green `PASS` badge.
