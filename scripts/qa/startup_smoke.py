"""Check this project's launcher, authentication, bootstrap and protected files.

No model requests or reconciliation runs are created. Only the process tree
started by this command is stopped when validation finishes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

PROJECT = Path(__file__).resolve().parents[2]
QA = PROJECT / "outputs" / "qa"


def protected_hashes() -> dict[str, str | None]:
    paths = [
        PROJECT / "src" / "freight_recon" / "knowledge" / "graph.py",
        PROJECT / "src" / "freight_recon" / "knowledge" / "retrieval.py",
        PROJECT / "src" / "freight_recon" / "core" / "audit.py",
        PROJECT / ".env",
    ]
    paths.extend(sorted((PROJECT / "data" / "knowledge").glob("*.md")))
    # Only digests are compared in memory; no secret bytes or digests are printed.
    return {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in paths}


def stop_spawned_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        # The direct Python entry has no child server workers.
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="验证当前项目启动、默认账号与角色权限；不调用模型、不写对账运行记录。")
    parser.add_argument("--direct", action="store_true", help="直接使用本项目 .venv 启动 Uvicorn；默认验证 start_mvp.ps1。")
    args = parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT / "src")
    environment["FREIGHT_LLM_DISABLED"] = "1"
    environment.pop("FREIGHT_DATA_DIR", None)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    if args.direct:
        python = PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            raise SystemExit("未找到项目 .venv，请先运行 start_mvp.ps1 安装运行环境。")
        command = [str(python), "-X", "utf8", "-m", "uvicorn", "freight_recon.web:app",
                   "--host", "127.0.0.1", "--port", str(port), "--workers", "1"]
    else:
        if os.name != "nt":
            raise SystemExit("默认启动脚本需要 Windows PowerShell；其他环境可使用 --direct。")
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(PROJECT / "start_mvp.ps1"), "-Port", str(port)]
    process = None
    try:
        with (QA / "startup-server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=PROJECT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                # Keep requests in one client so repeated health probes do not
                # repeatedly initialize transports while the launcher boots.
                deadline = time.monotonic() + 120
                with httpx.Client(base_url=base, timeout=2) as client:
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError("项目服务提前退出，请检查 outputs/qa/startup-server.log")
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                    else:
                        raise RuntimeError("项目服务未在 120 秒内就绪，请检查 outputs/qa/startup-server.log")
                    assert client.post("/api/ask", json={"question": "重量"}).status_code == 401
                    assert client.post("/api/login", json={"username": "admin", "password": "admin123"}).status_code == 200
                    documents_response = client.get("/api/knowledge/documents")
                    shipments_response = client.get("/api/shipments")
                    runs_response = client.get("/api/reconcile/runs")
                    assert documents_response.status_code == shipments_response.status_code == runs_response.status_code == 200
                    documents = documents_response.json()
                    shipments = shipments_response.json()
                    runs = runs_response.json()
                    # Users may maintain documents or create legitimate records.
                    # Validate endpoint shape rather than a fixed document count.
                    assert isinstance(documents, list) and isinstance(shipments, list) and isinstance(runs, list)
                    assert shipments, "运单列表为空，无法验证预置样本快照"
                    assert client.get("/knowledge").status_code == 200
                    assert client.get("/reconcile").status_code == 403
                    assert client.post("/api/logout").status_code == 200
                    assert client.post("/api/login", json={"username": "recon", "password": "recon123"}).status_code == 200
                    assert client.get("/reconcile").status_code == 200
                    assert client.get("/knowledge").status_code == 403
                    detail = client.get(f"/api/shipments/{shipments[0]['id']}")
                    assert detail.status_code == 200
                    assert set(detail.json()["snapshots"]) == {"tms", "billing", "erp"}
                    assert client.post("/api/logout").status_code == 200
            finally:
                stop_spawned_process_tree(process)
        after = protected_hashes()
        assert before == after, "启动验证期间受保护文件发生变化"
        summary = {
            "startup": "passed", "windows_powershell_launcher": not args.direct,
            "database": str(PROJECT / "data" / "freight.db"),
            "documents": len(documents), "shipments": len(shipments), "existing_run_count": len(runs),
            "protected_files_unchanged": True, "test_runs_added_to_delivery_database": 0,
        }
        (QA / "startup-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        # Also compare when endpoint assertions fail; do not persist the hashes.
        if before != protected_hashes():
            raise RuntimeError("启动验证期间受保护文件发生变化")


if __name__ == "__main__":
    main()
