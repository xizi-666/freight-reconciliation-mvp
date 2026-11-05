"""在隔离的模拟数据目录中，用本机 Edge 无头浏览器验收主要流程。"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[2]
QA = PROJECT / "outputs" / "qa"

# 应用的两个模块都会加载 .env。启动前禁用该函数，兼容旧版 python-dotenv，
# 确保验收不读取本地密钥；环境变量另外禁止真实 LLM 调用。
SERVER_BOOTSTRAP = """
import sys
import dotenv
import dotenv.main

def skip_dotenv(*args, **kwargs):
    return False

dotenv.load_dotenv = skip_dotenv
dotenv.main.load_dotenv = skip_dotenv

import uvicorn
uvicorn.run("freight_recon.web:app", host="127.0.0.1", port=int(sys.argv[1]))
"""


def stop_server(process: subprocess.Popen) -> None:
    """仅清理本次创建的服务进程及其子进程。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_server(process: subprocess.Popen, base: str, log_path: Path) -> None:
    import httpx

    deadline = time.monotonic() + 30
    with httpx.Client(timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"隔离测试服务已退出（退出码 {process.returncode}），"
                    f"请检查 {log_path.relative_to(PROJECT)}"
                )
            try:
                if client.get(base + "/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError(f"隔离测试服务未启动，请检查 {log_path.relative_to(PROJECT)}")


def exercise_browser(base: str) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1480, "height": 1080})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(base + "/login")
            page.locator('[name="username"]').fill("recon")
            page.locator('[name="password"]').fill("recon123")
            page.locator('button[type="submit"]').click()
            page.wait_for_url(base + "/")
            assert page.locator("#graph").count() == 1
            page.locator("#question").fill("哪些情形必须转人工")
            page.locator("#askbtn").click()
            page.wait_for_function(
                "document.querySelector('#answer').textContent.includes('本地检索')"
            )
            page.screenshot(path=str(QA / "knowledge-question.png"), full_page=True)

            page.locator('a[href="/reconcile"]').click()
            page.locator("#reconcileButton").wait_for()
            page.wait_for_function("!document.querySelector('#reconcileButton').disabled")
            page.locator("#reconcileButton").click()
            page.locator("#result .run-card").wait_for()
            assert page.locator("#result .status-badge").inner_text() == "样例一致"
            page.screenshot(path=str(QA / "reconcile.png"), full_page=True)

            page.locator('.shipment-item[data-id="7"]').click()
            page.wait_for_function("!document.querySelector('#reconcileButton').disabled")
            page.locator("#reconcileButton").click()
            page.locator("#result .run-card").wait_for()
            assert page.locator("#result .status-badge").inner_text() == "待人工处理"
            assert "待确认" in page.locator("#result .amounts").inner_text()

            page.locator('a[href="/records"]').click()
            page.locator("[data-run]").first.wait_for()
            page.locator("[data-run]").first.click()
            page.locator("#runDetail .run-card").wait_for()
            page.screenshot(path=str(QA / "records.png"), full_page=True)

            page.set_viewport_size({"width": 440, "height": 900})
            page.goto(base + "/reconcile")
            page.wait_for_function("!document.querySelector('#reconcileButton').disabled")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.screenshot(path=str(QA / "reconcile-mobile.png"), full_page=True)
            page.locator(".logout").click()
            page.wait_for_url(base + "/login")
            page.locator('[name="username"]').fill("admin")
            page.locator('[name="password"]').fill("admin123")
            page.locator('button[type="submit"]').click()
            page.wait_for_url(base + "/")
            page.set_viewport_size({"width": 1480, "height": 1080})

            page.goto(base + "/knowledge")
            page.locator('#uploadForm [name="document_code"]').fill("browser-contract")
            page.locator('#uploadForm [name="title"]').fill("浏览器上传测试")
            page.locator('#uploadForm [name="file"]').set_input_files(
                {
                    "name": "test.md",
                    "mimeType": "text/markdown",
                    "buffer": "# 模拟数据\n\nBROWSERTEST 条款：保留原始凭证。".encode("utf-8"),
                }
            )
            page.locator('#uploadForm button[type="submit"]').click()
            page.wait_for_function(
                "document.querySelector('#uploadMessage').textContent.includes('上传成功')"
            )
            uploaded_row = page.locator("#documents tr").filter(has_text="浏览器上传测试")
            uploaded_row.wait_for()
            assert uploaded_row.count() == 1
            uploaded_row.locator("[data-view]").click()
            page.locator("#documentPreview pre").wait_for()
            assert "BROWSERTEST" in page.locator("#documentPreview").inner_text()
            page.screenshot(path=str(QA / "knowledge-admin.png"), full_page=True)
            uploaded_row.locator("[data-delete]").click()
            page.wait_for_function(
                "!document.querySelector('#documents').textContent.includes('浏览器上传测试')"
            )
            page.set_viewport_size({"width": 440, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            assert not errors, errors
            return {
                "browser": "Microsoft Edge / headless",
                "workflows": [
                    "登录退出", "原图谱问答", "发起对账", "时点冲突转人工",
                    "历史详情", "上传检索文档与删除", "移动端布局",
                ],
                "page_errors": errors,
            }
        finally:
            browser.close()


def main() -> None:
    QA.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="browser-data-", dir=QA))
    environment = os.environ.copy()
    environment.update(
        PYTHONPATH=str(PROJECT / "src"),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        PYTHON_DOTENV_DISABLED="1",
        FREIGHT_DATA_DIR=str(data_dir),
        FREIGHT_LLM_DISABLED="1",
        KB_LLM_PROVIDER="",
        KB_LLM_API_KEY="",
    )
    project_python = PROJECT / ".venv" / "Scripts" / "python.exe"
    server_python = project_python if project_python.is_file() else Path(sys.executable)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log_path = QA / "browser-server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(server_python), "-X", "utf8", "-c", SERVER_BOOTSTRAP, str(port)],
            cwd=PROJECT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            wait_for_server(process, base, log_path)
            summary = exercise_browser(base)
            (QA / "browser-result.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary, ensure_ascii=False))
        finally:
            stop_server(process)


if __name__ == "__main__":
    main()
