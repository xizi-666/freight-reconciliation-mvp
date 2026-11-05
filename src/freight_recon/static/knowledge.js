"use strict";
const typeLabels={contract:"合同条款",price_list:"价目表",rule:"计费规则",interview:"访谈记录"};
async function loadDocuments() {
  const documents=await api("/api/knowledge/documents");
  document.getElementById("documentCount").textContent=`${documents.length} 个版本`;
  document.getElementById("documents").innerHTML=documents.length ? documents.map(doc=>`<tr><td><b>${escapeHTML(doc.title)}</b><small>${escapeHTML(doc.document_code)}</small></td><td>${escapeHTML(typeLabels[doc.document_type])}</td><td><span class="pill">${escapeHTML(doc.version)}</span></td><td><button class="btn link" data-view="${doc.id}">原文</button><button class="btn danger" data-delete="${doc.id}">删除</button></td></tr>`).join("") : '<tr><td colspan="4" class="muted">暂无文档，请上传 Markdown。</td></tr>';
}
document.getElementById("documents").addEventListener("click",async event=>{
  const view=event.target.closest("[data-view]"), remove=event.target.closest("[data-delete]");
  try {
    if(view){const doc=await api(`/api/knowledge/documents/${view.dataset.view}`);const preview=document.getElementById("documentPreview");preview.hidden=false;preview.innerHTML=`<h3>${escapeHTML(doc.title)} / ${escapeHTML(doc.version)}</h3><pre>${escapeHTML(doc.content)}</pre>`;}
    if(remove && confirm("删除此文档版本及当前检索片段？历史对账引用原文会保留。")){await api(`/api/knowledge/documents/${remove.dataset.delete}`,{method:"DELETE"});document.getElementById("documentPreview").hidden=true;await loadDocuments();toast("文档已删除，索引已同步");}
  }catch(error){toast(error.message);}
});
document.getElementById("uploadForm").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget, button=form.querySelector("button"), message=document.getElementById("uploadMessage");
  button.disabled=true;message.textContent="正在保存并构建索引…";
  try {await api("/api/knowledge/upload",{method:"POST",body:new FormData(form)});message.textContent="上传成功，索引已更新";form.reset();await loadDocuments();}catch(error){message.textContent=error.message;}finally{button.disabled=false;}
});
loadDocuments().catch(error=>toast(error.message));
