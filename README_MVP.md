# 增量 MVP 使用说明

本次在现有 demo 上增加 SQLite、Cookie 登录、知识库管理、单笔对账和历史记录。保留 `knowledge/graph.py`、`knowledge/retrieval.py`、`core/audit.py`、原有六份知识文档及 `.env` 配置；`web.py` 只增加集成与页面包装，原图谱 HTML 保留。

## 启动

在此项目目录打开 PowerShell，运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_mvp.ps1
```

首次启动创建项目 `.venv` 并安装依赖，使用本机 `D:\conda\envs\ds-study\python.exe` 创建环境，运行库路径只影响当前进程。需要更新依赖时加 `-Install`，端口冲突时加 `-Port 8001`。脚本不会更改系统 PATH 或 `.env`。

已有可用 Python 环境也可安装 `requirements.txt`，将项目的 `src` 加入 `PYTHONPATH`，再运行 `python -m uvicorn freight_recon.web:app --host 127.0.0.1 --port 8000 --workers 1`。

## 账号与页面

| 角色 | 用户名 | 密码 | 权限 |
|---|---|---|---|
| 管理员 | admin | admin123 | 知识问答、知识库上传/删除、查看所有运行记录 |
| 对账专员 | recon | recon123 | 知识问答、发起对账、查看本人记录 |

| 地址 | 页面 |
|---|---|
| `/login` | 登录 |
| `/` | 原知识库图谱与问答 |
| `/knowledge` | 管理员知识库管理 |
| `/reconcile` | 对账专员工作台 |
| `/records` | 历史记录，`?run=编号` 可直达详情 |

Cookie 会话在服务器内存保存，有效期 8 小时，退出登录立即失效，服务重启后需重新登录。因此此 MVP 使用单个 Uvicorn worker。密码依照需求使用 SHA-256。默认账号仅用于本机演示。

## 数据、样本与规则

- 首次启动自动建立 `data/freight.db` 的五张表，导入默认账号、原有六份知识文档、四份新增模拟合同/价目文档、十笔运单。
- `data/samples/shipments.json` 包含要求的十类样本分布；`data/samples/snapshots/` 包含每笔三份只读快照，共 30 份，全部标注“模拟数据”。
- 原知识文档不修改。上传文档存入数据库，复用原 `split_md`，再原子更新 `data/index/chunks.jsonl`。重启时根据数据库修复索引，不恢复管理员已删除的文档。
- 金额和重量在 Python 中使用 `Decimal`，在 SQLite 中使用十进制文本保存，避免经过 SQLite 浮点转换。API 金额以字符串返回。差额定义为“复算金额 − 原账单金额”。
- **保留的 `audit.py` 使用三种重量取最大值。四份模拟合同明确采用该样例公式，仅用于验证流程，不代表真实合同口径。**实际重量优先或其他不兼容规则不能直接套用样例审计公式；不匹配时转人工。
- 月中换价、缺依据、版本冲突、系统不可用进入 `pending_manual`，不输出唯一复算金额。时点冲突也转人工。正常一致为 `matched`，金额/重量差异为 `needs_review`；这些状态均不构成结算审批。
- 十笔样本按要求不另加系统不可用运单；该分支由自动测试修改临时 ERP 快照验证。
- 快照按历史回放展示其原始时间，未连接真实 TMS、计费系统或 ERP，也未声称已完成每 15 分钟同步。

## GLM 与引用

继续使用已有 `.env` 中的 `KB_LLM_PROVIDER`、`KB_LLM_API_KEY`、`KB_LLM_BASE_URL`、`KB_LLM_MODEL`，默认地址为 `https://open.bigmodel.cn/api/paas/v4`，模型 `glm-4-air`。

原问答仍调用既有 LangGraph；新对账解释使用异步 HTTP 调用 GLM。GLM 只能选择引用片段与整理待确认字段，不负责公式、时点、结果或资金动作。后端验证引用 ID 和逐字原文，待确认字段不允许模型增加或遗漏。超时、服务错误和无效输出时降级展示固定原文，明确标注模型未返回可验证解释。

运行记录保存实际使用的三系统快照、审计规则文件指纹、模型状态与参数、解释、引用原文及哈希。每次重跑新增记录；删除当前知识文档不影响已保存的历史引用。本版本仅保存待人工状态和解释，不包含额外的签核流转或付款扣费功能。

## 测试

安装 `pytest` 后，在项目根目录配置 `PYTHONPATH=src`，运行 `python -m pytest tests -q`。测试使用临时 SQLite 和样本目录，并禁用真实模型调用，不读取或输出真实密钥。
