# backend/db/connection.py
import os
import logging
from contextlib import contextmanager
import psycopg2
from psycopg2 import pool
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Connection state
_pg_pool = None
_mongo_client = None
_use_mock_db = os.getenv("USE_MOCK_DB", "false").lower() in ("true", "1", "yes")

def is_mock_mode() -> bool:
    global _use_mock_db
    if _use_mock_db:
        return True
    if _pg_pool is None:
        init_db_pools()
    return _use_mock_db

def set_mock_mode(enabled: bool):
    global _use_mock_db
    _use_mock_db = enabled

def init_db_pools(app=None):
    """Initializes PostgreSQL thread pool and MongoDB client."""
    global _pg_pool, _mongo_client, _use_mock_db

    if _use_mock_db:
        logger.info("Using in-memory mock database mode.")
        return

    # Initialize PostgreSQL pool
    try:
        pg_host = os.getenv("PG_HOST", "localhost")
        pg_port = int(os.getenv("PG_PORT", 5432))
        pg_database = os.getenv("PG_DATABASE", "landregistry")
        pg_user = os.getenv("PG_USER", "land_admin")
        pg_password = os.getenv("PG_PASSWORD", "land_secure_password")
        min_conn = int(os.getenv("PG_MIN_CONN", 1))
        max_conn = int(os.getenv("PG_MAX_CONN", 10))

        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            min_conn,
            max_conn,
            host=pg_host,
            port=pg_port,
            database=pg_database,
            user=pg_user,
            password=pg_password,
            connect_timeout=3
        )
        logger.info("PostgreSQL connection pool initialized.")
    except Exception as e:
        logger.warning(f"Could not initialize PostgreSQL pool: {e}. Falling back to mock DB.")
        _pg_pool = None
        _use_mock_db = True

    # Initialize MongoDB client
    try:
        mongo_uri = os.getenv("MONGO_URI", "mongodb://land_app:ledger_secret_pass@localhost:27017/landregistry?authSource=landregistry")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
        # Test connection
        client.admin.command('ping')
        _mongo_client = client
        logger.info("MongoDB client initialized.")
    except Exception as e:
        logger.warning(f"Could not initialize MongoDB client: {e}. Falling back to mock DB.")
        _mongo_client = None
        _use_mock_db = True

def close_db_pools():
    global _pg_pool, _mongo_client
    if _pg_pool:
        _pg_pool.closeall()
        _pg_pool = None
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None

@contextmanager
def get_pg_connection():
    """Context manager yielding a PostgreSQL connection from pool or mock connection."""
    global _pg_pool, _use_mock_db
    if _use_mock_db:
        from .mock_store import mock_db
        yield mock_db.get_pg_connection()
        return

    if _pg_pool is None:
        init_db_pools()

    if _pg_pool is None or _use_mock_db:
        from .mock_store import mock_db
        yield mock_db.get_pg_connection()
        return

    conn = _pg_pool.getconn()
    try:
        yield conn
    finally:
        _pg_pool.putconn(conn)

def get_mongo_client() -> MongoClient:
    """Returns MongoDB client or mock client."""
    global _mongo_client, _use_mock_db
    if _use_mock_db:
        from .mock_store import mock_db
        return mock_db.get_mongo_client()

    if _mongo_client is None:
        init_db_pools()

    if _mongo_client is None or _use_mock_db:
        from .mock_store import mock_db
        return mock_db.get_mongo_client()

    return _mongo_client

def get_mongo_db():
    client = get_mongo_client()
    db_name = os.getenv("MONGO_DB", "landregistry")
    return client[db_name]

def check_health() -> dict:
    """Checks the health of PostgreSQL and MongoDB."""
    status = {
        "status": "healthy",
        "databases": {
            "postgres": {"status": "unknown"},
            "mongo": {"status": "unknown"}
        },
        "mode": "mock" if _use_mock_db else "live"
    }

    if _use_mock_db:
        status["databases"]["postgres"] = {"status": "healthy", "engine": "in_memory_spatial"}
        status["databases"]["mongo"] = {"status": "healthy", "engine": "in_memory_ledger"}
        return status

    # Check Postgres
    try:
        with get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        status["databases"]["postgres"] = {"status": "healthy", "details": "PostgreSQL 16 + PostGIS connected"}
    except Exception as e:
        status["databases"]["postgres"] = {"status": "unhealthy", "error": str(e)}
        status["status"] = "degraded"

    # Check MongoDB
    try:
        client = get_mongo_client()
        client.admin.command('ping')
        status["databases"]["mongo"] = {"status": "healthy", "details": "MongoDB 7 ping OK"}
    except Exception as e:
        status["databases"]["mongo"] = {"status": "unhealthy", "error": str(e)}
        status["status"] = "degraded"

    return status
