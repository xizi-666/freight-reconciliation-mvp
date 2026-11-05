"""Snapshot validation around the unchanged audit and retrieval modules."""
import asyncio
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db
from ..knowledge.retrieval import search
from .audit import CONTRACTS, audit_invoice
from .explanations import format_explanation, generate_explanation

RULE_VERSION = "demo-audit-v1:" + hashlib.sha256((db.ROOT / "src" / "freight_recon" / "core" / "audit.py").read_bytes()).hexdigest()[:12]
SOURCES = ("tms", "billing", "erp")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def shipment_dict(shipment: db.Shipment) -> dict:
    result = {key: getattr(shipment, key) for key in ("id", "shipment_no", "carrier", "lane", "billing_time", "system_status")}
    result.update({key: format(getattr(shipment, key), "f") for key in ("weight_actual", "weight_volume", "weight_min", "amount")})
    result["data_label"] = "模拟数据"
    return result


def read_snapshots(shipment_no: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", shipment_no):
        raise ValueError("运单编号无效")
    result = {}
    for system in SOURCES:
        path = db.DATA_DIR / "samples" / "snapshots" / f"{shipment_no}_{system}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
            if not isinstance(payload, dict) or payload.get("shipment_no") != shipment_no or payload.get("source_system") != system:
                raise ValueError("快照标识不一致")
            result[system] = payload
        except (OSError, ValueError):
            result[system] = {"data_label": "模拟数据", "source_system": system, "shipment_no": shipment_no,
                              "system_status": "unavailable", "error": "快照缺失、无法解析或标识不一致"}
    return result


def snapshot_reference(system: str, snapshot: dict) -> dict:
    text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    return {"id": f"snapshot:{system}", "source": f"{snapshot['shipment_no']}_{system}.json",
            "heading": f"{system.upper()} 只读快照（模拟数据）", "version": snapshot.get("snapshot_at", "unavailable"),
            "text": text, "content_hash": hashlib.sha256(canonical(snapshot).encode("utf-8")).hexdigest(),
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(), "kind": "snapshot"}


def decimal_value(value) -> Decimal:
    if value is None or isinstance(value, (bool, float)):
        raise ValueError("缺少十进制字段或字段类型不正确")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number.adjusted() > 12 or number.as_tuple().exponent < -6:
        raise ValueError("字段必须为非负、有限且范围合理的十进制数")
    return number


async def contract_references(session: AsyncSession, shipment: dict, billing: dict, contract: dict | None) -> tuple[list[dict], list[dict]]:
    records = (await session.execute(select(db.Document, db.KnowledgeChunk).join(db.KnowledgeChunk))).all()
    required_codes = {billing.get("contract_ref"), billing.get("rate_card_ref")}
    candidates = []
    for document, chunk in records:
        if document.document_type not in ("contract", "price_list") or document.document_code not in required_codes:
            continue
        if f"承运商：{shipment['carrier']}" not in document.content or f"线路：{shipment['lane']}" not in document.content:
            continue
        candidates.append((document, chunk))
    # TF-IDF ranks candidates, but never decides contract applicability or versions.
    query = f"{shipment['carrier']} {shipment['lane']} {billing.get('rate_version', '')} 计费重量 单价 合同 计价时点"
    ranked = await asyncio.to_thread(search, query, max(len(records), 5))
    ranks = {row["id"]: index for index, row in enumerate(ranked)}
    refs = [db.chunk_reference(document, chunk) for document, chunk in candidates]
    refs.sort(key=lambda item: ranks.get(item["id"], len(ranks)))
    # Keep at least one complete chunk for each selected document.
    selected = []
    seen = set()
    for reference in refs:
        if reference["document_id"] not in seen:
            selected.append({**reference, "kind": "document"})
            seen.add(reference["document_id"])
    issues = []
    for document_type in ("contract", "price_list"):
        docs = {document.id: document for document, _chunk in candidates if document.document_type == document_type}
        if not docs:
            issues.append({"code": "MISSING_EVIDENCE", "reason": f"缺少适用的{document_type}原文依据", "field": "合同与价目依据"})
        elif len(docs) > 1:
            issues.append({"code": "VERSION_CONFLICT", "reason": f"{document_type}存在多个候选版本，需人工核实", "field": "价目版本"})
        elif contract:
            document = next(iter(docs.values()))
            if document.version != contract["version"] or f"价目版本：{contract['version']}" not in document.content:
                issues.append({"code": "VERSION_CONFLICT", "reason": "文档版本与样例审计配置不一致", "field": "价目版本"})
            expected_rule = f"保底重量为 {contract['min_weight_kg']} kg；单价为 {contract['rate_per_kg']} 元/kg"
            if "计费重量=max(实际重量,体积重量,保底重量)" not in document.content or expected_rule not in document.content:
                issues.append({"code": "MISSING_EVIDENCE", "reason": "合同规则与保留的样例审计公式不一致，不能套用样例公式", "field": "重量口径"})
            if "计价时点：signed_time（签收时间）" not in document.content:
                issues.append({"code": "TIME_BASIS_CONFLICT", "reason": "合同未明确支持当前样例的签收计价时点", "field": "计价时点"})
    return selected, issues


async def reconcile_shipment(session: AsyncSession, shipment: db.Shipment, user_id: int) -> db.ReconciliationRun:
    record = shipment_dict(shipment)
    snapshots = await asyncio.to_thread(read_snapshots, shipment.shipment_no)
    tms, billing, erp = (snapshots[key] for key in SOURCES)
    contract = CONTRACTS.get(shipment.carrier, {}).get(shipment.lane)
    references, issues = await contract_references(session, record, billing, contract)
    references += [snapshot_reference(system, snapshots[system]) for system in SOURCES]
    for system, snapshot in snapshots.items():
        if snapshot.get("system_status") != "ok" or shipment.system_status != "ok":
            issues.append({"code": "SYSTEM_UNAVAILABLE", "reason": f"{system.upper()}系统或快照不可用", "field": "系统状态"})
        if snapshot.get("carrier") != shipment.carrier or snapshot.get("lane") != shipment.lane:
            issues.append({"code": "MISSING_EVIDENCE", "reason": f"{system.upper()}快照的承运商或线路无法关联", "field": "业务编号"})
    if billing.get("mid_month_change"):
        issues.append({"code": "MID_MONTH_RATE_CHANGE", "reason": "价目表月中变更，适用版本需人工确认", "field": "价目版本"})
    if not tms.get("weight_ticket"):
        issues.append({"code": "MISSING_EVIDENCE", "reason": "缺少原始称重凭证", "field": "称重凭证"})
    if not contract:
        issues.append({"code": "MISSING_EVIDENCE", "reason": "未找到已确认的样例合同规则", "field": "合同与价目依据"})
    elif billing.get("rate_version") != contract["version"]:
        issues.append({"code": "VERSION_CONFLICT", "reason": "账单价目版本与合同样例版本不一致", "field": "价目版本"})
    if billing.get("pricing_event") != "signed_time" or billing.get("carrier_pricing_event") != "signed_time":
        issues.append({"code": "TIME_BASIS_CONFLICT", "reason": "发车与签收计价口径尚未澄清；需人工查合同", "field": "计价时点"})
    numbers = {}
    try:
        for field in ("weight_actual", "weight_volume"):
            numbers[field] = decimal_value(tms.get(field))
            if numbers[field] != decimal_value(record[field]):
                raise ValueError("运单列表与TMS重量不一致")
        numbers["weight_min"] = decimal_value(billing.get("weight_min"))
        numbers["amount"] = decimal_value(billing.get("amount"))
        numbers["billed_weight"] = decimal_value(billing.get("billed_weight"))
        if numbers["amount"] != shipment.amount or decimal_value(erp.get("amount")) != shipment.amount:
            raise ValueError("三系统金额不一致")
        if numbers["weight_min"] != shipment.weight_min or (contract and numbers["weight_min"] != contract["min_weight_kg"]):
            raise ValueError("保底重量与合同样例不一致")
        signed_time = datetime.fromisoformat(tms["signed_time"])
        billed_time = datetime.fromisoformat(billing["billing_time"])
        if signed_time.utcoffset() is None or billed_time.utcoffset() is None or signed_time != billed_time or billing["billing_time"] != shipment.billing_time:
            raise ValueError("计费时间与已确认样例事件不一致")
        if contract and not contract["effective_from"] <= signed_time.date().isoformat() <= contract["effective_to"]:
            raise ValueError("计价日期不在样例合同生效区间内")
    except (ValueError, TypeError, KeyError, InvalidOperation):
        issues.append({"code": "MISSING_EVIDENCE", "reason": "字段缺失、格式不合法或三系统数据不一致，需核实原记录", "field": "原始字段"})
    # Preserve all reasons, while removing duplicates caused by multiple documents.
    issues = list({(item["code"], item["reason"]): item for item in issues}.values())
    pending = {item["field"]: item["reason"] for item in issues}
    calculated = difference = None
    audit = None
    status = "pending_manual" if issues else "matched"
    if not issues:
        audit = audit_invoice({
            "carrier_id": shipment.carrier, "lane_id": shipment.lane,
            "charge_date": datetime.fromisoformat(billing["billing_time"]).date().isoformat(),
            "rate_version": billing["rate_version"], "actual_weight_kg": str(numbers["weight_actual"]),
            "volume_weight_kg": str(numbers["weight_volume"]), "billed_amount": str(numbers["amount"]),
        })
        calculated = Decimal(audit["expected_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        difference = (calculated - shipment.amount).quantize(Decimal("0.01"))
        if difference or audit["status"] != "matched":
            status = "needs_review"
            pending["账单金额"] = "原账单与样例规则复算金额不一致，请核实计费依据"
        if numbers["billed_weight"] != Decimal(audit["billable_weight_kg"]):
            status = "needs_review"
            pending["计费重量"] = "账单计费重量与TMS凭证及样例合同规则不一致，请人工核查"
    explanation = await generate_explanation(references, pending)
    snapshot_data = {
        "data_label": "模拟数据", "mode": "historical_replay", "shipment": record,
        "sources": snapshots, "manual_reasons": issues, "audit_result": audit,
        "ai": explanation, "rule_version": RULE_VERSION,
        "difference_definition": "复算金额 - 原账单金额",
        "rounding": "金额保留两位小数，ROUND_HALF_UP；仅适用于合成样例",
    }
    run = db.ReconciliationRun(
        shipment_id=shipment.id, snapshot_data=canonical(snapshot_data), rule_version=RULE_VERSION,
        calculated_amount=calculated, original_amount=shipment.amount, difference=difference, status=status,
        explanation=format_explanation(explanation), references_json=canonical(references), created_by=user_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def run_dict(run: db.ReconciliationRun, shipment_no: str | None = None, detail: bool = True) -> dict:
    result = {key: getattr(run, key) for key in ("id", "shipment_id", "rule_version", "status", "created_by", "explanation")}
    result.update({key: None if getattr(run, key) is None else format(getattr(run, key), ".2f")
                   for key in ("calculated_amount", "original_amount", "difference")})
    result["shipment_no"] = shipment_no
    result["created_at"] = db.iso_timestamp(run.created_at)
    if detail:
        result["snapshot_data"] = json.loads(run.snapshot_data)
        result["references_json"] = json.loads(run.references_json)
    return result
