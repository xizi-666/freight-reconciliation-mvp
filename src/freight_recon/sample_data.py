"""Deterministic synthetic fixtures. Existing fixtures are never overwritten."""
import json
from pathlib import Path

LABEL = "模拟数据"


def ensure_samples(data_dir: Path) -> None:
    samples = data_dir / "samples"
    snapshots = samples / "snapshots"
    contracts = samples / "contracts"
    snapshots.mkdir(parents=True, exist_ok=True)
    contracts.mkdir(parents=True, exist_ok=True)
    # Amounts and weights are strings so no binary floating point enters billing.
    cases = [
        ("001", "A", "120", "100", "240.00", "正常一致", "120"),
        ("002", "B", "90", "70", "162.00", "正常一致", "90"),
        ("003", "A", "150", "100", "310.00", "金额差异", "150"),
        ("004", "B", "100", "90", "175.00", "金额差异", "100"),
        ("005", "A", "120", "150", "240.00", "重量差异", "120"),
        ("006", "B", "90", "70", "144.00", "重量差异", "80"),
        ("007", "A", "120", "100", "240.00", "时点冲突", "120"),
        ("008", "A", "120", "100", "240.00", "月中换价", "120"),
        ("009", "B", "90", "70", "162.00", "缺依据", "90"),
        ("010", "A", "120", "100", "240.00", "版本冲突", "120"),
    ]
    shipments = []
    for number, carrier, actual, volume, amount, scenario, billed_weight in cases:
        version = "v2" if carrier == "A" else "v1"
        floor = "100" if carrier == "A" else "80"
        row = {
            "data_label": LABEL, "shipment_no": f"WB-SIM-{number}",
            "carrier": f"CARRIER-{carrier}",
            "lane": "LANE-001" if carrier == "A" else "LANE-002",
            "weight_actual": actual, "weight_volume": volume, "weight_min": floor,
            "amount": amount, "billing_time": "2026-06-16T10:00:00+08:00",
            "rate_version": "v1" if scenario == "版本冲突" else version,
            "system_status": "ok", "scenario": scenario,
        }
        shipments.append(row)
        common = {
            "data_label": LABEL, "shipment_no": row["shipment_no"],
            "carrier": row["carrier"], "lane": row["lane"],
            "snapshot_at": "2026-06-17T09:00:00+08:00", "system_status": "ok",
        }
        payloads = {
            "tms": {
                **common, "weight_actual": actual, "weight_volume": volume,
                "departure_time": "2026-06-14T08:00:00+08:00",
                "signed_time": "2026-06-16T10:00:00+08:00",
                "weight_ticket": None if scenario == "缺依据" else f"SIM-WEIGHT-{number}",
            },
            "billing": {
                **common, "amount": amount, "weight_min": floor,
                "billed_weight": billed_weight, "billing_time": row["billing_time"],
                "rate_version": row["rate_version"],
                "pricing_event": "unconfirmed" if scenario == "时点冲突" else "signed_time",
                "carrier_pricing_event": "departure_time" if scenario == "时点冲突" else "signed_time",
                "mid_month_change": scenario == "月中换价",
                "contract_ref": f"sample-contract-{carrier.lower()}",
                "rate_card_ref": f"sample-price-{carrier.lower()}",
            },
            "erp": {**common, "amount": amount, "settlement_status": "待人工审批（模拟）"},
        }
        for system, payload in payloads.items():
            path = snapshots / f"{row['shipment_no']}_{system}.json"
            if not path.exists():
                path.write_text(json.dumps({"source_system": system, **payload}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = samples / "shipments.json"
    if not path.exists():
        path.write_text(json.dumps(shipments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for carrier, lane, version, rate, floor in [("A", "LANE-001", "v2", "2.00", "100"), ("B", "LANE-002", "v1", "1.80", "80")]:
        for kind, title in [("contract", "模拟运费合同"), ("price", "模拟价目表")]:
            path = contracts / f"sample-{kind}-{carrier.lower()}.md"
            content = (
                f"# {title} CARRIER-{carrier}\n\n数据性质：模拟数据，仅验证现有 demo，不适用于真实合同。\n\n"
                f"承运商：CARRIER-{carrier}\n线路：{lane}\n价目版本：{version}\n"
                "生效日期：2026-01-01\n失效日期：2026-12-31\n计价时点：signed_time（签收时间）\n\n"
                "## 已确认的样例规则\n\n"
                f"计费重量=max(实际重量,体积重量,保底重量)；保底重量为 {floor} kg；单价为 {rate} 元/kg。"
                "该公式仅与保留的 audit.py 样例规则对应，不代表实际重量优先等真实合同约定。\n\n"
                "## 解释与人工边界\n\n"
                "引用原记录并列出待确认字段，不认定合同变更或赔付。月中换价、缺依据、版本冲突、系统不可用必须转人工。"
                "发车与签收口径冲突时由人工澄清，不由模型选择。\n"
            )
            if not path.exists():
                path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    ensure_samples(Path(__file__).resolve().parents[2] / "data")
