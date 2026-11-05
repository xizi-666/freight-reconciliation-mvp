"use strict";
let page=0;const pageSize=30;
async function loadRuns() {
  const rows=await api(`/api/reconcile/runs?offset=${page*pageSize}&limit=${pageSize}`);
  document.getElementById("runCount").textContent=`本页 ${rows.length} 次运行`;
  document.getElementById("recordsPage").textContent=`第 ${page+1} 页`;
  document.getElementById("previousRecords").disabled=page===0;
  document.getElementById("nextRecords").disabled=rows.length<pageSize;
  document.getElementById("records").innerHTML=rows.length ? rows.map(run=>`<tr><td><b>#${run.id}</b><small>${escapeHTML(run.shipment_no)}</small></td><td>${badge(run.status)}</td><td>${escapeHTML(run.original_amount)}</td><td>${escapeHTML(run.calculated_amount ?? "待确认")}</td><td>${escapeHTML(run.difference ?? "—")}</td><td>${escapeHTML(run.created_at)}</td><td><button class="btn link" data-run="${run.id}">查看详情</button></td></tr>`).join("") : '<tr><td colspan="7" class="muted">暂无对账记录。对账专员可前往工作台发起。</td></tr>';
}
async function loadDetail(id){const run=await api(`/api/reconcile/runs/${id}`);document.getElementById("runDetail").innerHTML=runHTML(run);document.getElementById("runDetail").scrollIntoView({behavior:"smooth",block:"start"});}
document.getElementById("records").addEventListener("click",event=>{const button=event.target.closest("[data-run]");if(button){history.replaceState(null,"",`/records?run=${button.dataset.run}`);loadDetail(button.dataset.run).catch(error=>toast(error.message));}});
document.getElementById("refreshRecords").addEventListener("click",()=>loadRuns().catch(error=>toast(error.message)));
document.getElementById("previousRecords").addEventListener("click",()=>{if(page>0){page--;loadRuns().catch(error=>toast(error.message));}});
document.getElementById("nextRecords").addEventListener("click",()=>{page++;loadRuns().catch(error=>toast(error.message));});
(async()=>{await loadRuns();const id=new URLSearchParams(location.search).get("run");if(id && /^\d+$/.test(id))await loadDetail(id);})().catch(error=>toast(error.message));
