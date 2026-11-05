"use strict";
document.getElementById("loginForm").addEventListener("submit", async event => {
  event.preventDefault(); const form=event.currentTarget, button=form.querySelector("button"), error=document.getElementById("loginError");
  error.textContent="";button.disabled=true;
  try {
    const response=await fetch("/api/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.fromEntries(new FormData(form)))});
    const data=await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请检查用户名与密码");
    location.href="/";
  } catch(problem) {error.textContent=problem.message;} finally {button.disabled=false;}
});
