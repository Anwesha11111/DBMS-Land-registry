# tests/conftest.py
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure mock mode is active for tests if live db is not running
os.environ["USE_MOCK_DB"] = "true"
os.environ["FLASK_ENV"] = "testing"

import pytest
from backend.app import create_app
from backend.db.connection import set_mock_mode
from backend.db.mock_store import mock_db
from backend.services.ledger import ensure_genesis

@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    set_mock_mode(True)
    mock_db.reset()
    ensure_genesis()
    yield
    mock_db.reset()

@pytest.fixture
def app():
    application = create_app({"TESTING": True})
    return application

@pytest.fixture
def client(app):
    return app.test_client()
