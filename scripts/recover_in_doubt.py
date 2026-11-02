# scripts/recover_in_doubt.py
"""
Recovery script for dangling PostgreSQL prepared transactions.
DECISION 5: Resolves in-doubt gids by checking whether a ledger block with that gid exists in MongoDB.
- Ledger block exists -> COMMIT PREPARED
- Ledger block missing -> ROLLBACK PREPARED
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.services.settlement import recover_in_doubt_transactions

def main():
    print("=" * 60)
    print("Executing 2PC In-Doubt Prepared Transactions Recovery")
    print("=" * 60)
    res = recover_in_doubt_transactions()
    print("Recovery result:", res)
    print("=" * 60)

if __name__ == "__main__":
    main()
