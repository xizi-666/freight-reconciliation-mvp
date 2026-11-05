"use strict";
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
async function api(path, options = {}) {
  const response = await fetch(path, {...options, credentials:"same-origin"});
  if (response.status === 401) { location.href = "/login"; throw new Error("登录已失效，请重新登录"); }
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求参数不正确，请检查后重试";
    throw new Error(detail);
  }
  return data;
}
function toast(message) { const el=document.getElementById("toast"); el.textContent=message;el.style.display="block";clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>el.style.display="none",4500); }
async function logout() { try {await api("/api/logout",{method:"POST"});location.href="/login";} catch(error) {toast(error.message);} }
const statuses = {matched:"样例一致",needs_review:"差异待复核",pending_manual:"待人工处理"};
function badge(status) { return `<span class="status-badge status-${escapeHTML(status)}">${escapeHTML(statuses[status] || status)}</span>`; }
function snapshotHTML(sources) {
  return `<div class="snapshot-grid">${Object.entries(sources).map(([system, snapshot]) => `<details><summary>${escapeHTML(system.toUpperCase())} · ${escapeHTML(snapshot.system_status)}<br><span class="muted">${escapeHTML(snapshot.snapshot_at || "快照不可用")}</span></summary><pre>${escapeHTML(JSON.stringify(snapshot,null,2))}</pre></details>`).join("")}</div>`;
}
function runHTML(run) {
  const snapshot=run.snapshot_data, ai=snapshot.ai, audit=snapshot.audit_result;
  const reasonHTML = snapshot.manual_reasons.length ? `<ul class="reason-list">${snapshot.manual_reasons.map(item=>`<li>${escapeHTML(item.reason)}</li>`).join("")}</ul>` : "";
  return `<section class="panel run-card"><div class="run-header"><div><h2>运行 #${run.id} · ${escapeHTML(run.shipment_no)}</h2><small class="muted">${escapeHTML(run.created_at)} · 发起人 #${run.created_by}</small></div>${badge(run.status)}</div>
    <div class="amounts"><div class="amount"><small>原账单 / 元</small><b>${escapeHTML(run.original_amount)}</b></div><div class="amount"><small>样例复算 / 元</small><b>${escapeHTML(run.calculated_amount ?? "待确认")}</b></div><div class="amount"><small>复算 − 原账单 / 元</small><b>${escapeHTML(run.difference ?? "—")}</b></div></div>
    <div class="run-section">${reasonHTML}<h3>确定性规则复算</h3><p class="muted small">规则版本 ${escapeHTML(run.rule_version)}</p>${audit ? `<pre>${escapeHTML(audit.rule)}\n计费重量：${escapeHTML(audit.billable_weight_kg)} kg\n${escapeHTML(snapshot.rounding)}</pre>` : '<div class="note">前置条件未确认，本次未套用样例规则计算唯一金额。需人工核实资料。</div>'}
    <h3>事实引用 ＋ 待确认字段 <span class="pill">${ai.metadata.status === "ok" ? "GLM 输出已校验" : "原文降级展示"}</span></h3><pre>${escapeHTML(run.explanation)}</pre>
    <h3>依据原文 <span class="muted small">历史引用独立留存</span></h3>${run.references_json.map(ref=>`<details><summary>[${escapeHTML(ref.id)}] ${escapeHTML(ref.source)} · ${escapeHTML(ref.version)}<br>${escapeHTML(ref.heading)}</summary><div class="evidence-meta"><span>SHA-256 ${escapeHTML((ref.text_hash || ref.content_hash).slice(0,16))}…</span>${ref.document_id ? `<a href="/api/knowledge/documents/${ref.document_id}" target="_blank" rel="noopener">查看当前原文</a>` : ""}</div><pre>${escapeHTML(ref.text)}</pre></details>`).join("")}
    <h3>本次固定的三系统快照</h3>${snapshotHTML(snapshot.sources)}<div class="note">所有金额均为样例核验值，不代表结算审批。合同变更、赔付、付款和扣费仍由原业务流程处理。</div></div></section>`;
}
