import os
import pytest
from pymongo import MongoClient


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient(os.environ["MONGODB_URI"])
    yield client
    client.close()


@pytest.fixture
def test_db(mongo_client):
    # Use a dedicated test database, never the real one
    db = mongo_client["hex_test"]
    yield db
    # Clean up all collections after each test
    for name in db.list_collection_names():
        db.drop_collection(name)
