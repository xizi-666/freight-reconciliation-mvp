import asyncio
import hashlib
import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import inspect, select, text

from conftest import login
from freight_recon import db
from freight_recon.core import explanations
from freight_recon.core.reconciliation import canonical
from freight_recon.knowledge import retrieval


def test_five_tables_and_seed_idempotence(client):
    async def inspect_db():
        async with db.engine.connect() as connection:
            return await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    assert set(client.portal.call(inspect_db)) == {"users", "documents", "knowledge_chunks", "shipments", "reconciliation_runs"}
    login(client, "admin", "admin123")
    assert len(client.get("/api/knowledge/documents").json()) == 10
    assert len(client.get("/api/shipments").json()) == 10
    client.portal.call(db.init_db)
    assert len(client.get("/api/knowledge/documents").json()) == 10


def test_login_cookie_logout_and_guards(client):
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.post("/api/ask", json={"question": "重量"}).status_code == 401
    assert client.post("/api/audit/demo").status_code == 401
    assert client.post("/api/login", json={"username": "recon", "password": "wrong"}).status_code == 401
    response = login(client)
    assert client.get("/api/me").json()["role"] == "reconciler"
    assert "httponly" in response.headers["set-cookie"].lower()
    cookie = client.cookies.get("freight_session")
    assert client.get("/knowledge").status_code == 403
    assert client.delete("/api/knowledge/documents/1").status_code == 403
    assert client.post("/api/logout").status_code == 200
    client.cookies.set("freight_session", cookie)
    assert client.get("/api/me").status_code == 401
    client.cookies.clear()
    login(client, "admin", "admin123")
    assert client.get("/reconcile").status_code == 403
    assert client.post("/api/reconcile", json={"shipment_id": 1}).status_code == 403


def test_cross_origin_post_rejected(client):
    assert client.post("/api/login", headers={"Origin": "https://other.example"}, json={"username": "admin", "password": "admin123"}).status_code == 403


@pytest.mark.parametrize("shipment_id,status,difference,reason", [
    (1, "matched", "0.00", None), (2, "matched", "0.00", None),
    (3, "needs_review", "-10.00", None), (4, "needs_review", "5.00", None),
    (5, "needs_review", "60.00", None), (6, "needs_review", "18.00", None),
    (7, "pending_manual", None, "TIME_BASIS_CONFLICT"),
    (8, "pending_manual", None, "MID_MONTH_RATE_CHANGE"),
    (9, "pending_manual", None, "MISSING_EVIDENCE"),
    (10, "pending_manual", None, "VERSION_CONFLICT"),
])
def test_ten_reconciliation_cases(client, shipment_id, status, difference, reason):
    login(client)
    response = client.post("/api/reconcile", json={"shipment_id": shipment_id})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == status, run["snapshot_data"]["manual_reasons"]
    assert run["difference"] == difference
    if reason:
        assert reason in {item["code"] for item in run["snapshot_data"]["manual_reasons"]}
        assert run["calculated_amount"] is None
        assert run["snapshot_data"]["audit_result"] is None
    if shipment_id in (5, 6):
        assert "计费重量" in run["explanation"]
    references = {ref["id"]: ref for ref in run["references_json"]}
    for fact in run["snapshot_data"]["ai"]["facts"]:
        assert fact["quote"] in references[fact["reference_id"]]["text"]
    for source in run["snapshot_data"]["sources"].values():
        assert source["data_label"] == "模拟数据"


def test_unavailable_system_and_invalid_amount_are_manual(client):
    login(client)
    path = db.DATA_DIR / "samples" / "snapshots" / "WB-SIM-001_erp.json"
    original = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(original)
        payload["system_status"] = "unavailable"
        path.write_text(json.dumps(payload), encoding="utf-8")
        run = client.post("/api/reconcile", json={"shipment_id": 1}).json()
        assert run["status"] == "pending_manual"
        assert "SYSTEM_UNAVAILABLE" in {item["code"] for item in run["snapshot_data"]["manual_reasons"]}
        payload["system_status"] = "ok"
        payload["amount"] = "NaN"
        path.write_text(json.dumps(payload), encoding="utf-8")
        run = client.post("/api/reconcile", json={"shipment_id": 1}).json()
        assert run["status"] == "pending_manual"
        assert run["calculated_amount"] is None
    finally:
        path.write_text(original, encoding="utf-8")


def test_upload_search_duplicate_delete_and_restart(client):
    login(client, "admin", "admin123")
    fields = {"document_code": "test-contract", "title": "测试原文", "document_type": "contract", "version": "v1"}
    raw = "# 测试原文\n\nUNICORNFREIGHT 唯一条款：必须保留称重凭证。"
    files = {"file": ("test.md", raw.encode("utf-8"), "text/markdown")}
    response = client.post("/api/knowledge/upload", data=fields, files=files)
    assert response.status_code == 201, response.text
    document_id = response.json()["id"]
    assert any(row["document_id"] == document_id for row in retrieval.load_chunks())
    assert "UNICORNFREIGHT" in client.post("/api/ask", json={"question": "UNICORNFREIGHT"}).json()["answer"]
    assert client.post("/api/knowledge/upload", data=fields, files=files).status_code == 409
    assert client.post("/api/knowledge/upload", data={**fields, "version": "v2"}, files=files).status_code == 201
    assert client.delete(f"/api/knowledge/documents/{document_id}").status_code == 200
    assert all(row["document_id"] != document_id for row in retrieval.load_chunks())
    # Bootstrap must not resurrect a deleted original document.
    original_id = client.get("/api/knowledge/documents").json()[0]["id"]
    client.delete(f"/api/knowledge/documents/{original_id}")
    client.portal.call(db.init_db)
    assert client.get(f"/api/knowledge/documents/{original_id}").status_code == 404


def test_upload_validation_and_role(client):
    login(client)
    fields = {"document_code": "a", "title": "a", "document_type": "contract"}
    assert client.post("/api/knowledge/upload", data=fields, files={"file": ("a.md", b"# x")}).status_code == 403
    login(client, "admin", "admin123")
    assert client.post("/api/knowledge/upload", data=fields, files={"file": ("a.exe", b"x")}).status_code == 400
    assert client.post("/api/knowledge/upload", data=fields, files={"file": ("a.md", b"\xff\xfe")}).status_code == 400
    assert client.post("/api/knowledge/upload", data={**fields, "document_type": "invalid"}, files={"file": ("a.md", b"x")}).status_code == 422


def test_replay_appends_and_history_survives_document_delete(client):
    login(client)
    first = client.post("/api/reconcile", json={"shipment_id": 1}).json()
    second = client.post("/api/reconcile", json={"shipment_id": 1}).json()
    assert second["id"] != first["id"]
    assert second["calculated_amount"] == first["calculated_amount"]
    assert len(client.get("/api/reconcile/runs").json()) == 2
    for system, snapshot in first["snapshot_data"]["sources"].items():
        ref = next(item for item in first["references_json"] if item["id"] == f"snapshot:{system}")
        assert hashlib.sha256(canonical(snapshot).encode("utf-8")).hexdigest() == ref["content_hash"]
    doc_ref = next(item for item in first["references_json"] if item.get("document_id"))
    login(client, "admin", "admin123")
    client.delete(f"/api/knowledge/documents/{doc_ref['document_id']}")
    saved = client.get(f"/api/reconcile/runs/{first['id']}").json()
    assert saved["references_json"] == first["references_json"]
    assert saved["snapshot_data"] == first["snapshot_data"]
    login(client)
    assert client.post("/api/reconcile", json={"shipment_id": 1}).json()["status"] == "pending_manual"


def test_decimal_storage_is_text_and_exact(client):
    async def decimal_roundtrip():
        async with db.SessionLocal() as session:
            shipment = await session.get(db.Shipment, 1)
            shipment.amount = Decimal("123456789.123456789")
            await session.commit()
        async with db.SessionLocal() as session:
            shipment = await session.get(db.Shipment, 1)
            sqlite_type = await session.scalar(text("SELECT typeof(amount) FROM shipments WHERE id=1"))
            return shipment.amount, sqlite_type
    amount, sqlite_type = client.portal.call(decimal_roundtrip)
    assert amount == Decimal("123456789.123456789")
    assert sqlite_type == "text"


def test_invalid_reference_or_pending_fields_rejected():
    refs = [{"id": "r1", "text": "实际重量为120 kg。"}]
    good = {"facts": [{"reference_id": "r1", "quote": "实际重量为120 kg"}], "pending_fields": []}
    assert explanations.validate_explanation(json.dumps(good), refs, {})["facts"]
    with pytest.raises(ValueError):
        explanations.validate_explanation(None, refs, {})
    for bad in [
        {**good, "facts": [{"reference_id": "missing", "quote": "实际重量为120 kg"}]},
        {**good, "facts": [{"reference_id": "r1", "quote": "实际重量为200 kg"}]},
        {**good, "pending_fields": [{"field": "赔付金额", "reason": "100元"}]},
        {**good, "conclusion": "直接扣费"},
    ]:
        with pytest.raises(ValueError):
            explanations.validate_explanation(json.dumps(bad), refs, {})


def test_glm_async_call_and_invalid_output_fallback(client, monkeypatch):
    refs = [{"id": "r1", "text": "实际重量为120 kg。", "source": "测试模拟资料"}]
    monkeypatch.setenv("FREIGHT_LLM_DISABLED", "0")
    monkeypatch.setenv("KB_LLM_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("KB_LLM_MODEL", "glm-4-air")
    original_client = httpx.AsyncClient
    def good_handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "glm-4-air"
        assert str(request.url).endswith("/chat/completions")
        content = json.dumps({"facts": [{"reference_id": "r1", "quote": "实际重量为120 kg"}], "pending_fields": []})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(good_handler), **kwargs))
    assert client.portal.call(explanations.generate_explanation, refs, {})["metadata"]["status"] == "ok"
    def bad_handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"facts":[{"reference_id":"fake","quote":"made-up"}],"pending_fields":[]}'}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(bad_handler), **kwargs))
    result = client.portal.call(explanations.generate_explanation, refs, {})
    assert result["metadata"]["status"] == "invalid_output"
    assert result["facts"][0]["quote"] in refs[0]["text"]


def test_pages_and_existing_demo(client):
    assert client.get("/login").status_code == 200
    login(client)
    for path in ("/", "/reconcile", "/records"):
        response = client.get(path)
        assert response.status_code == 200
        assert "退出登录" in response.text
    assert "知识库与运费关系图谱" in client.get("/").text
    assert client.post("/api/audit/demo").status_code == 200
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422
    assert client.post("/api/reconcile", json={"shipment_id": 99999}).status_code == 404
    login(client, "admin", "admin123")
    assert client.get("/knowledge").status_code == 200


def test_concurrent_runs_append_without_collisions(client):
    login(client)
    token = client.cookies.get("freight_session")
    async def concurrent_requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver",
                                     cookies={"freight_session": token}) as browser:
            return await asyncio.gather(*[browser.post("/api/reconcile", json={"shipment_id": 1}) for _ in range(4)])
    responses = client.portal.call(concurrent_requests)
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 4
    assert {response.json()["calculated_amount"] for response in responses} == {"240.00"}
