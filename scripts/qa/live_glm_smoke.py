"""Verify one synthetic reconciliation with the project's configured GLM API.

This command makes a real model request when run. It sends only newly generated
sample contracts and snapshots, writes into outputs/qa, and never prints keys.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[2]
QA = PROJECT / "outputs" / "qa"


def main() -> None:
    parser = argparse.ArgumentParser(description="使用项目 .env 对一笔新生成的模拟运单调用真实 GLM，并校验原文引用。")
    parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    # A fresh database and fresh fixtures ensure maintained business documents
    # and the project's delivery database do not enter this smoke test.
    os.environ["FREIGHT_DATA_DIR"] = str(QA / f"live-data-{time.time_ns()}")
    os.environ["FREIGHT_LLM_DISABLED"] = "0"
    load_dotenv(PROJECT / ".env", override=False)
    if not os.getenv("KB_LLM_API_KEY"):
        raise SystemExit("未找到 KB_LLM_API_KEY；请先在项目 .env 配置智谱 API。未发送模型请求。")
    sys.path.insert(0, str(PROJECT / "src"))

    from freight_recon.web import app
    from freight_recon.core import explanations

    original_async_client = explanations.httpx.AsyncClient

    class CapturingClient(original_async_client):
        async def send(self, *args, **kwargs):
            response = await super().send(*args, **kwargs)
            if response.status_code == 200:
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                    if isinstance(content, str):
                        # Save only the response to synthetic evidence. Headers,
                        # API keys and request objects are never persisted.
                        (QA / "synthetic-glm-answer.txt").write_text(content, encoding="utf-8")
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
            return response

    with patch.object(explanations.httpx, "AsyncClient", CapturingClient), TestClient(app) as client:
        login = client.post("/api/login", json={"username": "recon", "password": "recon123"})
        assert login.status_code == 200, "模拟数据库中的默认对账专员登录失败"
        response = client.post("/api/reconcile", json={"shipment_id": 1})
        assert response.status_code == 201, f"模拟对账请求失败，HTTP {response.status_code}"
        run = response.json()
        data = run["snapshot_data"]
        assert data["data_label"] == "模拟数据"
        assert all(source["data_label"] == "模拟数据" for source in data["sources"].values())
        reference_map = {reference["id"]: reference for reference in run["references_json"]}
        for fact in data["ai"]["facts"]:
            assert fact["reference_id"] in reference_map, "模型引用不属于本次固定资料"
            assert fact["quote"] in reference_map[fact["reference_id"]]["text"], "模型引用无法逐字匹配原文"
        metadata = data["ai"]["metadata"]
        summary = {
            "run_status": run["status"], "calculated_amount": run["calculated_amount"],
            "llm_status": metadata["status"], "model": metadata["model"],
            "fact_count": len(data["ai"]["facts"]), "reference_count": len(reference_map),
            "data_label": "模拟数据", "delivery_database_modified": False,
        }
        (QA / "live-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        assert run["status"] == "matched" and run["calculated_amount"] == "240.00", "样例复算结果与预期不一致"
        if metadata["status"] != "ok":
            raise SystemExit("GLM 未返回通过校验的解释，当前为原文降级结果。详情见 outputs/qa/live-result.json。")


if __name__ == "__main__":
    main()
