"""Deterministic demo freight audit rules; never triggers financial actions."""
from decimal import Decimal

CONTRACTS = {
    "CARRIER-A": {"LANE-001": {"version": "v2", "effective_from": "2026-01-01", "effective_to": "2026-12-31", "rate_per_kg": Decimal("2.00"), "min_weight_kg": Decimal("100")}},
    "CARRIER-B": {"LANE-002": {"version": "v1", "effective_from": "2026-01-01", "effective_to": "2026-12-31", "rate_per_kg": Decimal("1.80"), "min_weight_kg": Decimal("80")}},
}

def audit_invoice(invoice: dict) -> dict:
    carrier=invoice.get("carrier_id",""); lane=invoice.get("lane_id","")
    contract=CONTRACTS.get(carrier,{}).get(lane)
    findings=[]; evidence=[]
    if not contract:
        findings.append({"code":"CONTRACT_NOT_FOUND","severity":"high","message":"没有匹配到承运商线路合同，需人工核对。"})
        return {"status":"needs_review","findings":findings,"expected_amount":None,"evidence":evidence}
    date=invoice.get("charge_date","")
    if not (contract["effective_from"] <= date <= contract["effective_to"]):
        findings.append({"code":"RATE_DATE_OUT_OF_RANGE","severity":"high","message":"计费日期不在样例合同有效期内。"})
    if invoice.get("rate_version") != contract["version"]:
        findings.append({"code":"RATE_VERSION_CONFLICT","severity":"high","message":f"账单价目版本 {invoice.get('rate_version')} 与合同版本 {contract['version']} 不一致。"})
    actual=Decimal(str(invoice.get("actual_weight_kg",0))); volume=Decimal(str(invoice.get("volume_weight_kg",0))); floor=contract["min_weight_kg"]
    billable=max(actual,volume,floor)
    expected=billable*contract["rate_per_kg"]
    billed=Decimal(str(invoice.get("billed_amount",0)))
    evidence=[{"source":"sample_contracts.py","field":"rate_per_kg","value":str(contract['rate_per_kg'])},{"source":"sample_contracts.py","field":"min_weight_kg","value":str(floor)},{"source":"invoice","field":"weights_kg","value":{"actual":str(actual),"volume":str(volume),"minimum":str(floor)}}]
    if billed != expected:
        findings.append({"code":"AMOUNT_MISMATCH","severity":"medium","message":f"账单金额 {billed} 元；按样例规则预计 {expected} 元。计费重量=max(实际,体积,保底)={billable} kg。"})
    return {"status":"needs_review" if findings else "matched","findings":findings,"billable_weight_kg":str(billable),"expected_amount":str(expected),"evidence":evidence,"rule":"金额= max(实际重量,体积重量,合同保底重量) × 合同单价"}
