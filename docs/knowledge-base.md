# 运费对账知识库

## 架构

使用 LangGraph `StateGraph` 构建两节点 RAG 工作流：`retrieve` 从本地索引检索相关材料，`answer` 输出可追溯摘要。LangGraph 负责节点和状态流转；检索当前用轻量 TF-IDF，不依赖外部向量服务。可选配置 OpenAI 时才调用模型进行归纳；缺省只返回检索片段。

```text
Markdown 来源 → 分块与来源元数据 → chunks.jsonl → TF-IDF 检索 → LangGraph answer 节点 → 回答 + citations
```

## 构建

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m freight_recon.kb_cli --rebuild
python -m freight_recon.kb_cli "首期范围和资金动作的边界是什么？"
```

可选模型：复制 `.env.example` 为 `.env` 并在安全环境中设置 `KB_LLM_PROVIDER=openai` 与 `OPENAI_API_KEY`。不要提交 `.env`。

## 资料范围

收录访谈报告、项目设计、接口草案、报价建议和流程图说明。知识库只回答资料支持的内容；证据不足时应回答“尚未确认”。原始业务文件应符合授权与脱敏要求。

## 安全边界

当前只读，不连接结算审批、付款或扣费系统。检索结果和生成回答是辅助材料，不构成合同解释或最终计费审批。

## 当前限制

TF-IDF 对中文召回能力有限，当前分词按单字与英文/数字词处理；后续可替换为中文 tokenizer、向量数据库和 reranker，并以人工标注问题集评估召回率与引用准确率。
