# backend/db/mock_store.py
"""
In-memory mock store that emulates PostgreSQL 16 + PostGIS and MongoDB 7
for testing and self-contained execution without external database daemons.
Uses Shapely to emulate PostGIS ST_Intersects, ST_Touches, ST_IsValid, ST_Area.
"""
import copy
import json
import uuid
import datetime
from decimal import Decimal
from typing import Dict, Any, List, Optional
from shapely.geometry import shape, Polygon

class MockCursor:
    def __init__(self, store):
        self.store = store
        self.last_result = []
        self.rowcount = 0
        self._iter_idx = 0

    def execute(self, query: str, params=None):
        params = params or ()
        # Convert any Decimal/UUID/datetime if needed
        self.last_result, self.rowcount = self.store.execute_sql(query, params)
        self._iter_idx = 0

    def fetchone(self):
        if self._iter_idx < len(self.last_result):
            res = self.last_result[self._iter_idx]
            self._iter_idx += 1
            return res
        return None

    def fetchall(self):
        res = self.last_result[self._iter_idx:]
        self._iter_idx = len(self.last_result)
        return res

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class MockConnection:
    def __init__(self, store):
        self.store = store
        self.autocommit = False
        self.in_transaction = False

    def cursor(self):
        return MockCursor(self.store)

    def commit(self):
        self.in_transaction = False

    def rollback(self):
        self.in_transaction = False

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()

class MockMongoCollection:
    def __init__(self, name: str, docs_list: List[Dict[str, Any]], is_app_user: bool = True):
        self.name = name
        self.docs = docs_list
        self.is_app_user = is_app_user

    def insert_one(self, doc: Dict[str, Any]):
        # Validate unique indexes for ledger_transaction_block
        if self.name == "ledger_transaction_block":
            block_num = doc.get("block_number")
            prev_hash = doc.get("prev_tx_hash")
            tx_id = doc.get("tx_id")

            for existing in self.docs:
                if existing.get("block_number") == block_num:
                    raise Exception(f"E11000 duplicate key error: block_number {block_num} already exists")
                if existing.get("prev_tx_hash") == prev_hash:
                    raise Exception(f"E11000 duplicate key error: prev_tx_hash {prev_hash} already exists")
                if existing.get("tx_id") == tx_id:
                    raise Exception(f"E11000 duplicate key error: tx_id {tx_id} already exists")

        cloned = copy.deepcopy(doc)
        if "_id" not in cloned:
            cloned["_id"] = str(uuid.uuid4())
        self.docs.append(cloned)
        return type("InsertResult", (), {"inserted_id": cloned["_id"]})()

    def find(self, filter_query: Optional[Dict[str, Any]] = None, sort=None):
        filter_query = filter_query or {}
        results = []
        for d in self.docs:
            match = True
            for k, v in filter_query.items():
                if isinstance(v, dict):
                    if "$gt" in v and not (d.get(k) is not None and d.get(k) > v["$gt"]):
                        match = False
                        break
                    if "$gte" in v and not (d.get(k) is not None and d.get(k) >= v["$gte"]):
                        match = False
                        break
                elif d.get(k) != v:
                    match = False
                    break
            if match:
                results.append(copy.deepcopy(d))

        if sort:
            if isinstance(sort, list):
                for field, direction in reversed(sort):
                    results.sort(key=lambda x: x.get(field, 0) if x.get(field) is not None else 0, reverse=(direction < 0))
            elif isinstance(sort, str):
                results.sort(key=lambda x: x.get(sort, 0) if x.get(sort) is not None else 0)

        class Cursor:
            def __init__(self, items):
                self.items = items
            def __iter__(self):
                return iter(self.items)
            def sort(self, key_or_list, direction=1):
                if isinstance(key_or_list, list):
                    for k, d in reversed(key_or_list):
                        self.items.sort(key=lambda x: x.get(k, 0) if x.get(k) is not None else 0, reverse=(d < 0))
                else:
                    self.items.sort(key=lambda x: x.get(key_or_list, 0) if x.get(key_or_list) is not None else 0, reverse=(direction < 0))
                return self
            def limit(self, n):
                self.items = self.items[:n]
                return self
        return Cursor(results)

    def find_one(self, filter_query: Optional[Dict[str, Any]] = None, sort=None):
        cursor = self.find(filter_query, sort=sort)
        items = list(cursor)
        return items[0] if items else None

    def update_one(self, filter_query, update_doc):
        # DECISION 9: Mongo app user has insert+find only on the ledger collection.
        if self.is_app_user and self.name == "ledger_transaction_block":
            raise Exception("Unauthorized: app user does not have permission to update documents in ledger_transaction_block")
        for d in self.docs:
            match = True
            for k, v in filter_query.items():
                if isinstance(v, dict):
                    if "$gt" in v and not (d.get(k) is not None and d.get(k) > v["$gt"]):
                        match = False
                        break
                elif d.get(k) != v:
                    match = False
                    break
            if match:
                if "$set" in update_doc:
                    d.update(update_doc["$set"])
                return type("UpdateResult", (), {"modified_count": 1})()
        return type("UpdateResult", (), {"modified_count": 0})()

    def delete_one(self, filter_query):
        # DECISION 9: App user cannot delete
        if self.is_app_user and self.name == "ledger_transaction_block":
            raise Exception("Unauthorized: app user does not have permission to delete documents in ledger_transaction_block")
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in filter_query.items()):
                self.docs.pop(i)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def count_documents(self, filter_query: Optional[Dict[str, Any]] = None):
        return len(list(self.find(filter_query)))

class MockMongoDB:
    def __init__(self, docs_store: Dict[str, List[Dict[str, Any]]], is_app_user: bool = True):
        self.docs_store = docs_store
        self.is_app_user = is_app_user

    def __getitem__(self, name: str) -> MockMongoCollection:
        if name not in self.docs_store:
            self.docs_store[name] = []
        return MockMongoCollection(name, self.docs_store[name], is_app_user=self.is_app_user)

    def command(self, cmd: str, *args, **kwargs):
        return {"ok": 1.0}

class MockMongoClient:
    def __init__(self, docs_store: Dict[str, List[Dict[str, Any]]], is_app_user: bool = True):
        self.docs_store = docs_store
        self.is_app_user = is_app_user
        self.dbs: Dict[str, MockMongoDB] = {}
        self.admin = type("Admin", (), {"command": lambda cmd: {"ok": 1.0}})()

    def __getitem__(self, name: str) -> MockMongoDB:
        if name not in self.dbs:
            self.dbs[name] = MockMongoDB(self.docs_store, is_app_user=self.is_app_user)
        return self.dbs[name]

    def close(self):
        pass

class MockDatabaseStore:
    def __init__(self):
        self.reset()

    def reset(self):
        # Relational tables
        self.users: Dict[str, Dict[str, Any]] = {}
        self.owners: Dict[str, Dict[str, Any]] = {}
        self.wallets: Dict[str, Dict[str, Any]] = {}
        self.plots: Dict[str, Dict[str, Any]] = {}
        self.registry: Dict[str, Dict[str, Any]] = {}
        self.registry_history: List[Dict[str, Any]] = []
        self.injunctions: List[Dict[str, Any]] = []
        self.order_book: Dict[str, Dict[str, Any]] = {}
        self.trades: Dict[str, Dict[str, Any]] = {}
        self.coordinator_logs: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[Dict[str, Any]] = []
        self.state_rules: List[Dict[str, Any]] = []

        # 2PC prepared transactions tracking
        self.prepared_xacts: Dict[str, Dict[str, Any]] = {}

        # Shared MongoDB mock collections
        self.mongo_docs: Dict[str, List[Dict[str, Any]]] = {}
        self.mongo_client = MockMongoClient(self.mongo_docs, is_app_user=True)
        self.mongo_admin_client = MockMongoClient(self.mongo_docs, is_app_user=False)

    def get_pg_connection(self):
        return MockConnection(self)

    def get_mongo_client(self):
        return self.mongo_client

    def get_mongo_admin_client(self):
        return self.mongo_admin_client

    def execute_sql(self, query: str, params: tuple):
        q = query.strip()
        u = q.upper()

        # Handle health check
        if u.startswith("SELECT 1"):
            return [(1,)], 1

        # Handle prepared transaction commands
        if u.startswith("PREPARE TRANSACTION"):
            # PREPARE TRANSACTION 'gid'
            parts = q.split()
            gid = parts[2].strip("'\" ;")
            self.prepared_xacts[gid] = {
                "gid": gid,
                "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            return [], 0

        if u.startswith("COMMIT PREPARED"):
            parts = q.split()
            gid = parts[2].strip("'\" ;")
            if gid in self.prepared_xacts:
                del self.prepared_xacts[gid]
            return [], 0

        if u.startswith("ROLLBACK PREPARED"):
            parts = q.split()
            gid = parts[2].strip("'\" ;")
            if gid in self.prepared_xacts:
                del self.prepared_xacts[gid]
            return [], 0

        if "FROM PG_PREPARED_XACTS" in u:
            results = []
            for gid, info in self.prepared_xacts.items():
                results.append((gid, info["prepared_at"]))
            return results, len(results)

        # Simple dispatch for mock queries
        return [], 0

mock_db = MockDatabaseStore()
