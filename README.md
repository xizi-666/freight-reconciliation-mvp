# 运费对账与计费争议智能助手 MVP

在原有 FastAPI + LangGraph 知识库 demo 上增量增加 SQLite、Cookie 登录、知识库管理、单笔运单对账和历史记录。规则负责确定性核算，GLM 负责引用整理，人工负责业务认定与结算审批。

**完整运行目录：**`C:/Users/希杍/Desktop/运费对账交付物/mvp/src/`。应用、页面资源、样本、测试和启动脚本均在此目录中，运行不依赖开发时的暂存目录。本目录下还有一个 `src/`，Python 包位于 `src/freight_recon/`。

## 启动与依赖

要求 Python 3.11+。本机使用 `D:\conda\envs\ds-study\python.exe` 创建项目 `.venv`；运行依赖见 `requirements.txt`，测试依赖见 `requirements-dev.txt`，不需要安装 PostgreSQL。

从任意 PowerShell 目录启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\希杍\Desktop\运费对账交付物\mvp\src\start_mvp.ps1"
```

打开 [登录页](http://127.0.0.1:8000/login)。保持命令窗口运行，按 `Ctrl+C` 停止。脚本首次创建 `.venv` 时自动安装依赖，配置的运行库路径只影响当前进程，不修改系统 PATH 或 `.env`。

更新依赖或更换端口：

```powershell
Set-Location -LiteralPath 'C:\Users\希杍\Desktop\运费对账交付物\mvp\src'
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_mvp.ps1 -Install
# 端口被占用时：
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_mvp.ps1 -Port 8001
```

`start_demo.bat`、`start_demo_system.bat` 是兼容入口，均转发到它们所在目录的 `start_mvp.ps1`。双击可启动当前项目，不再指向旧项目目录。

## 默认账号与页面

| 角色 | 用户名 | 密码 | 权限 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 知识问答、上传/删除知识文档、查看全部对账记录 |
| 对账专员 | `recon` | `recon123` | 知识问答、查看运单与快照、发起对账、查看本人记录 |

| 地址 | 页面 | 访问范围 |
|---|---|---|
| `/login` | 登录 | 未登录用户 |
| `/` | 原知识库图谱与问答 | 登录用户 |
| `/knowledge` | 文档列表、预览、上传和删除 | 管理员 |
| `/reconcile` | 运单、三系统快照、复算、解释及状态 | 对账专员 |
| `/records` | 历史列表和详情，支持 `?run=编号` | 管理员查看全部；专员查看本人 |

会话由 HttpOnly Cookie 携带标识，保存在服务器内存，有效期 8 小时；退出后立即失效，服务重启后需重新登录。因此启动固定使用 **1 个 Uvicorn worker**。密码按本次需求使用 SHA-256，预置账号用于本机演示。

## 目录与功能

```text
当前项目目录/
├── README.md / README_MVP.md      # 主说明与增量说明
├── requirements.txt              # 运行依赖
├── requirements-dev.txt          # 测试依赖（包含运行依赖）
├── .env                          # 已有 GLM 配置
├── start_mvp.ps1                 # 推荐启动入口
├── start_demo*.bat               # 兼容启动入口
├── src/freight_recon/
│   ├── web.py                    # 原图谱页面与路由集成
│   ├── db.py / auth.py           # 数据库与登录鉴权
│   ├── ui.py / static/           # 新页面、CSS、JavaScript
│   ├── sample_data.py            # 合成样本生成
│   ├── routes/                   # 知识库、运单、对账、历史接口
│   ├── core/audit.py             # 保留的确定性审计规则
│   ├── core/reconciliation.py    # 快照校验、复算与异常分流
│   ├── core/explanations.py      # 异步 GLM 调用与引用验证
│   └── knowledge/                # 原分块、TF-IDF 检索和 LangGraph
├── data/
│   ├── freight.db                # 自动初始化的 SQLite 数据库
│   ├── knowledge/                # 原有六份 Markdown 文档
│   ├── index/chunks.jsonl        # 数据库同步管理的检索索引
│   └── samples/                  # 10 笔运单、30 份快照、4 份模拟合同/价目文档
├── tests/                        # 隔离数据的自动化测试
├── scripts/qa/                   # 可选浏览器、模型和启动验证工具
├── docs/                         # 原设计资料与增量验证报告
└── incremental-change-manifest.json
```

原 `graph.py`、`retrieval.py`、`audit.py` 和六份原知识文档保持不变。`examples/demo.py`、`scripts/run_demo.ps1` 是早期占位示例，启动完整 Web MVP 使用上述启动入口。

## 数据与知识库管理

首次启动自动建立 `data/freight.db`，包含 `users`、`documents`、`knowledge_chunks`、`shipments`、`reconciliation_runs` 五张表，并导入两个账号、六份原知识文档、四份模拟合同/价目文档和十笔运单。

管理员可上传 UTF-8 `.md` 文档（最大 2 MiB），填写编号、标题、类型与版本。类型为 `contract`、`price_list`、`rule`、`interview`。同一编号使用新版本号新增记录，重复编号与版本会被拒绝。

上传后保存到数据库，复用原 `split_md` 分块，原子更新 `chunks.jsonl`。删除会同步移除当前索引片段；重启不会恢复已删除文档。原 `data/knowledge/*.md` 不被上传/删除操作改写，历史对账记录仍保留当时的引用原文。日常知识库维护应使用管理页面，无需直接执行旧 `ingest` 命令。

## 对账、异常和引用

流程：选择运单 → 固定三系统快照 → 校验编号、时点、版本与依据 → 样例规则复算 → 检索合同依据 → GLM 整理解释 → 验证引用 → 新增运行记录。

- 金额和重量使用 `Decimal`，在 SQLite 中以十进制文本保存，API 金额以字符串返回。差额定义为“复算金额 − 原账单金额”。
- `matched` 为样例一致；`needs_review` 为金额或重量差异；`pending_manual` 为前置条件未确认、待人工处理。
- 月中换价、缺依据、版本冲突、系统不可用自动转人工；时点冲突也由人工澄清，不由模型选择。前置条件未确认时不输出唯一复算金额。
- 每次重跑新增记录，保存输入快照、规则指纹、模型状态、解释和引用原文及哈希，不覆盖原记录。
- **保留的 `audit.py` 使用“三种重量取最大值 × 单价”的样例公式。**配套模拟合同与之对应，仅验证流程。真实合同的“实际重量优先”等不同口径需要另行确认，不能直接套用样例公式。

10 笔运单包括：2 笔正常一致、2 笔金额差异、2 笔重量差异，时点冲突、月中换价、缺依据、版本冲突各 1 笔。系统不可用由测试修改临时快照验证。全部标注“模拟数据”，当前采用历史回放，未接入真实三系统同步。

## GLM 配置

继续使用根目录已有 `.env` 中的 `KB_LLM_PROVIDER`、`KB_LLM_API_KEY`、`KB_LLM_BASE_URL`、`KB_LLM_MODEL`。当前供应商为智谱，默认地址 `https://open.bigmodel.cn/api/paas/v4`，模型 `glm-4-air`；不要将真实密钥写入文档或版本控制。

原问答继续调用既有 LangGraph，在接口层移出事件循环执行。新增对账解释使用异步 HTTP 调用 GLM。模型选择原文候选并整理待确认字段，后端校验引用 ID 和逐字原文，禁止模型新增或遗漏待确认字段。超时、服务错误或无效输出会降级显示固定原文。

GLM 不选择计价时点、不生成执行公式、不裁定合同变更、责任或赔付，也不触发结算审批、付款或扣费。访谈资料用于背景说明，不能替代合同依据。此版本保存待人工状态，尚未提供独立人工签核流转。

## 主要 API

| 接口 | 用途 |
|---|---|
| `POST /api/login`、`POST /api/logout`、`GET /api/me` | 登录、退出和当前用户 |
| `POST /api/ask`、`POST /api/audit/demo` | 保留的问答与合成审计，需登录 |
| `GET /api/knowledge/documents`、`GET /api/knowledge/documents/{id}` | 文档列表与原文，需登录 |
| `POST /api/knowledge/upload` | 管理员上传；multipart 字段：`file`、`document_code`、`title`、`document_type`、`version` |
| `DELETE /api/knowledge/documents/{id}` | 管理员删除文档 |
| `GET /api/shipments`、`GET /api/shipments/{id}` | 运单与三系统快照，需登录 |
| `POST /api/reconcile` | 专员发起对账，请求体如 `{"shipment_id": 1}` |
| `GET /api/reconcile/runs`、`GET /api/reconcile/runs/{id}` | 按角色限制可见范围的历史记录 |
| `GET /health` | 健康检查 |

## 测试与可选验证工具

在项目目录执行以下命令；运行库路径仅影响当前命令进程：

```powershell
Set-Location -LiteralPath 'C:\Users\希杍\Desktop\运费对账交付物\mvp\src'
$dsPrefix = 'D:\conda\envs\ds-study'
$dsRuntimePaths = @($dsPrefix, "$dsPrefix\Library\mingw-w64\bin", "$dsPrefix\Library\usr\bin", "$dsPrefix\Library\bin", "$dsPrefix\Scripts", "$dsPrefix\bin")
$env:PATH = ($dsRuntimePaths -join ';') + ';' + $env:PATH
$env:CONDA_PREFIX = $dsPrefix
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = (Resolve-Path .\src).Path
& .\.venv\Scripts\python.exe -X utf8 -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -X utf8 -m pytest tests -q
```

自动化测试使用临时 SQLite 与样本目录，禁用真实模型调用，不修改项目业务数据库或 `.env`。覆盖账号权限、十笔样本、四类转人工、索引同步、引用验证、Decimal 精度、历史保留和并发追加。

可选工具也随项目保存，均按文件位置定位项目根目录，不依赖暂存路径。沿用上面的当前进程环境运行：

```powershell
# 启动脚本与账号检查，结束后停止自己启动的本机服务
& .\.venv\Scripts\python.exe -X utf8 scripts/qa/startup_smoke.py
# 本机 Edge 无头浏览器，使用隔离模拟数据，不调用真实模型
& .\.venv\Scripts\python.exe -X utf8 scripts/qa/browser_smoke.py
# 真实 GLM 联调：使用已有配置，仅发送合成资料，会产生 API 调用
& .\.venv\Scripts\python.exe -X utf8 scripts/qa/live_glm_smoke.py
```

工具输出保存在项目的 `outputs/qa/`。此前已通过 23 项自动测试、浏览器检查及合成运单的真实 GLM 验证，详情见 [验证报告](docs/MVP增量验证报告.md)；实际业务改善仍需试点验证。

更多资料：[增量说明](README_MVP.md)、[原文档导航](docs/README.md)、[文件变更清单](incremental-change-manifest.json)。
