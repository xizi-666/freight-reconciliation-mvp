"use strict";
let selectedShipment=null, selectionVersion=0;
const reconcileButton=document.getElementById("reconcileButton");
async function selectShipment(id) {
  const version=++selectionVersion; selectedShipment=null;reconcileButton.disabled=true;document.getElementById("result").innerHTML="";
  document.querySelectorAll(".shipment-item").forEach(el=>el.classList.toggle("selected",Number(el.dataset.id)===id));
  try {
    const data=await api(`/api/shipments/${id}`);if(version!==selectionVersion)return;
    selectedShipment=data.shipment; const item=data.shipment;
    document.getElementById("shipmentDetail").className="panel";
    const values=[["运单编号",item.shipment_no],["承运商",item.carrier],["线路",item.lane],["实际重量 / kg",item.weight_actual],["体积重量 / kg",item.weight_volume],["保底重量 / kg",item.weight_min],["原账单 / 元",item.amount],["计费时间",item.billing_time],["数据性质","模拟数据 · 历史回放"]];
    document.getElementById("shipmentDetail").innerHTML=`<div class="panel-head">运单与三系统原记录</div><div class="detail-body"><div class="kv-grid">${values.map(([label,value])=>`<div><small>${escapeHTML(label)}</small><b>${escapeHTML(value)}</b></div>`).join("")}</div>${snapshotHTML(data.snapshots)}</div>`;
    reconcileButton.disabled=false;document.getElementById("actionHint").textContent="每次运行固定当前快照，重跑新增记录。";
  }catch(error){toast(error.message);}
}
reconcileButton.addEventListener("click",async()=>{
  if(!selectedShipment)return;
  const shipmentId=selectedShipment.id, version=selectionVersion;
  reconcileButton.disabled=true;reconcileButton.textContent="正在复算并整理引用…";
  document.querySelectorAll(".shipment-item").forEach(el=>el.disabled=true);
  try {
    const run=await api("/api/reconcile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({shipment_id:shipmentId})});
    if(version===selectionVersion)document.getElementById("result").innerHTML=runHTML(run);
    toast(`运行 #${run.id} 已保存`);
  }catch(error){toast(error.message);}finally{reconcileButton.disabled=false;reconcileButton.textContent="再次对账（新增记录） →";document.querySelectorAll(".shipment-item").forEach(el=>el.disabled=false);}
});
document.getElementById("shipments").addEventListener("click",event=>{const button=event.target.closest(".shipment-item");if(button && !button.disabled)selectShipment(Number(button.dataset.id));});
(async()=>{
  const rows=await api("/api/shipments");
  document.getElementById("shipments").innerHTML=rows.map(item=>`<button class="shipment-item" data-id="${item.id}"><b>${escapeHTML(item.shipment_no)}</b><small>${escapeHTML(item.carrier)} · ${escapeHTML(item.lane)}</small><span class="shipment-bottom"><span>¥ ${escapeHTML(item.amount)}</span><small>模拟数据</small></span></button>`).join("");
  if(rows.length)await selectShipment(rows[0].id);
})().catch(error=>toast(error.message));
