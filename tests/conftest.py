"""Integration tests use disposable SQLite/files and never read production secrets."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_temporary = tempfile.TemporaryDirectory(prefix="freight-mvp-tests-")
os.environ["FREIGHT_DATA_DIR"] = _temporary.name
os.environ["FREIGHT_LLM_DISABLED"] = "1"
os.environ["KB_LLM_PROVIDER"] = ""
os.environ["KB_LLM_API_KEY"] = ""

from fastapi.testclient import TestClient
from freight_recon import auth, db
from freight_recon.web import app


@pytest.fixture
def client():
    async def reset():
        async with db.engine.begin() as connection:
            await connection.run_sync(db.Base.metadata.drop_all)
        await db.engine.dispose()
    asyncio.run(reset())
    auth._sessions.clear()
    with TestClient(app) as test_client:
        yield test_client


def login(client, username="recon", password="recon123"):
    result = client.post("/api/login", json={"username": username, "password": password})
    assert result.status_code == 200, result.text
    return result
