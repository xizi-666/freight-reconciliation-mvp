"use strict";
// Keep the existing graph, presets, search and HTML; upgrade request handling only.
window.askWiki=async function(){
  const question=document.getElementById("question").value.trim();if(!question)return;
  const button=document.getElementById("askbtn"), answer=document.getElementById("answer"), sources=document.getElementById("sources");
  button.disabled=true;button.textContent="正在检索…";answer.style.display="block";answer.textContent="正在检索知识库并整理引用…";sources.textContent="";
  try {const data=await api("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});answer.textContent=data.answer;sources.textContent=(data.citations || []).map(item=>`${item.source} · ${item.heading} (${item.id})`).join("\n");}
  catch(error){answer.textContent=error.message;}finally{button.disabled=false;button.textContent="查找依据并回答 ↗";}
};
