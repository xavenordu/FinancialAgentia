import os
import sys
import pytest
from fastapi.testclient import TestClient
import importlib


@pytest.fixture(autouse=True)
def set_backend_api_key(monkeypatch):
    # Set a test backend API key for the duration of tests
    monkeypatch.setenv("BACKEND_API_KEY", "testkey")
    yield


def _import_app_module():
    # Ensure python-backend directory is on sys.path so packages import correctly
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    # Import the FastAPI app module
    return importlib.import_module("app.main")


def test_health():
    main_mod = _import_app_module()
    client = TestClient(main_mod.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_query_requires_api_key():
    main_mod = _import_app_module()
    client = TestClient(main_mod.app)
    r = client.post("/query", json={"prompt": "hello"})
    # Should be unauthorized because header missing
    assert r.status_code == 401


def test_query_streams(monkeypatch):
    # Monkeypatch the call_llm_stream on the imported module to yield deterministic chunks
    async def fake_stream(prompt):
        yield "hello "
        yield "world"

    main_mod = _import_app_module()
    monkeypatch.setattr(main_mod, "call_llm_stream", fake_stream)

    client = TestClient(main_mod.app)
    r = client.post("/query", headers={"x-api-key": "testkey"}, json={"prompt": "hi"}, stream=True)
    assert r.status_code == 200
    # Read stream content
    content = b""
    for chunk in r.iter_content(chunk_size=None):
        content += chunk
    # SSE framed, so should contain 'data: hello' and 'data: world'
    text = content.decode('utf-8')
    assert "data: hello" in text
    assert "data: world" in text
