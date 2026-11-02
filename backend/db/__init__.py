# backend/db/__init__.py
from .connection import (
    get_pg_connection,
    get_mongo_client,
    get_mongo_db,
    check_health,
    init_db_pools,
    close_db_pools,
    is_mock_mode
)

__all__ = [
    "get_pg_connection",
    "get_mongo_client",
    "get_mongo_db",
    "check_health",
    "init_db_pools",
    "close_db_pools",
    "is_mock_mode"
]
