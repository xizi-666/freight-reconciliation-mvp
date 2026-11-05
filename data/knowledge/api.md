# API 说明草案

本文件描述 MVP 的建议接口，不表示生产接口已存在。所有接口默认只读业务源数据；建议与审批动作只写入本工具的审计/任务记录，不调用付款、扣费或结算批准接口。

## POST /api/v1/reconciliations

提交单笔或批次对账任务。

```json
{
  "business_id": "WB-2026-000123",
  "carrier_id": "CARRIER-01",
  "invoice_id": "INV-0008",
  "source_refs": ["tms:shipment/123", "billing:invoice/8"],
  "requested_at": "2026-10-29T10:00:00+08:00"
}
```

响应返回 `reconciliation_id`、状态和当前数据新鲜度。

## GET /api/v1/reconciliations/{id}

返回账单、合同与凭证的引用版本，规则核算结果、差异原因、AI 摘要、待确认项、人工任务状态和审计事件。AI 解释必须包含引用来源，不能只返回无依据的结论。

```json
{
  "reconciliation_id": "REC-0001",
  "business_id": "WB-2026-000123",
  "status": "needs_human_review",
  "freshness": {"updated_at": "2026-10-29T09:45:00+08:00", "stale": false},
  "versions": {"contract": "v12", "rate_card": "v7", "rule_set": "r3"},
  "checks": [{"code": "RATE_VERSION_CONFLICT", "result": "review", "evidence_refs": ["contract:p12", "rate-card:row88"]}],
  "calculation": {"formula": "approved_rule_expression", "inputs": {}, "expected_amount": null},
  "explanation": "发现价目版本冲突，需审计人员确认适用版本。",
  "human_task": {"reason": "版本冲突", "assignee_role": "billing_reviewer", "acknowledged_at": null}
}
```

## POST /api/v1/reconciliations/{id}/review

由授权人员提交确认、修改或转交。记录操作者身份、理由、时间和原建议，不覆盖源系统原始记录。

## 安全与失败处理

- 按角色授权访问合同价目、称重单、签收回执和附加费依据。
- 不记录账号口令或不必要个人信息。
- 数据超过已约定更新周期时标记待刷新；不可称为实时状态。
- 接口中断时返回上一份带时间戳的只读快照并显示“暂未更新”，避免重复创建待办。
- 版本冲突、缺资料、关键系统不可用时强制人工处理。
- MVP 不提供自动审批、付款、扣费 API。
