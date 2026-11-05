"""Small local web UI for the LangGraph knowledge-base demo."""
import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from freight_recon.knowledge.graph import ask
from freight_recon.core.audit import audit_invoice
from freight_recon import db, auth, ui
from freight_recon.knowledge import retrieval
from freight_recon.routes import knowledge, reconciliation


@asynccontextmanager
async def lifespan(_app):
    retrieval.INDEX = db.INDEX_PATH
    await db.init_db()
    yield
    await db.engine.dispose()


app=FastAPI(title="运费对账知识库",version="0.2.0",lifespan=lifespan)
app.include_router(auth.router)
app.include_router(knowledge.router)
app.include_router(reconciliation.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def authentication_boundary(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
        origin_url = urlsplit(origin)
        if origin_url.netloc != request.url.netloc or origin_url.scheme != request.url.scheme:
            return JSONResponse({"detail": "不接受跨站点修改请求"}, status_code=403)
    public = request.url.path in {"/login", "/api/login", "/api/logout", "/health"} or request.url.path.startswith("/static/")
    if not public:
        user = await auth.resolve_user(request)
        if user is None:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "请先登录"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        request.state.user = user
    response = await call_next(request)
    if request.url.path.startswith("/api/") or not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

class Question(BaseModel):
    question: str = Field(min_length=1,max_length=4000)

    @field_validator("question")
    @classmethod
    def nonblank(cls,value):
        if not value.strip():
            raise ValueError("请输入问题")
        return value.strip()

PAGE=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>运费结算工作台</title>
<style>
:root{--ink:#20283a;--muted:#778096;--line:#e8eaf0;--blue:#4353d6;--blue2:#eef0ff;--bg:#f7f7fa;--teal:#42a78b;--amber:#c78a48;--purple:#7662a8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,"Microsoft YaHei",Arial,sans-serif;font-size:14px}.app{min-height:100vh;display:grid;grid-template-columns:220px minmax(610px,1fr) 290px}.sidebar{background:#fff;border-right:1px solid var(--line);padding:24px 16px;position:sticky;top:0;height:100vh;overflow:auto}.brand{display:flex;gap:11px;align-items:center;padding:0 8px 25px}.mark{width:38px;height:38px;border-radius:12px;background:#20283a;color:#fff;display:grid;place-items:center;font-weight:800}.brand strong{font-size:17px;display:block}.brand small{font-size:9px;letter-spacing:2px;color:#9299a8}.project{background:#faf9f6;border:1px solid #eeece6;border-radius:12px;padding:14px;margin:0 4px 20px}.project b{font-size:13px}.project small{display:block;color:var(--muted);margin-top:6px}.navtitle{font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#a0a5b1;padding:12px 10px 7px}.nav{display:flex;align-items:center;gap:10px;padding:12px 11px;margin:3px 0;border-radius:10px;color:#51596b}.nav.active{background:var(--blue2);color:var(--blue);font-weight:700}.ni{width:22px;text-align:center;font-size:12px;color:#7d8494}.main{min-width:0}.topbar{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;z-index:2}.crumb{color:#8b91a0}.crumb b{color:#293044}.persona{border:1px solid var(--line);border-radius:20px;background:#fff;padding:9px 13px;color:#525a6b}.content{padding:25px 26px 38px;max-width:1120px;margin:auto}.title-row{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px}.title-row h1{font-size:22px;margin:0 0 7px}.title-row p{margin:0;color:var(--muted);font-size:13px}.btn{border:1px solid var(--line);border-radius:22px;background:#fff;padding:10px 16px;color:#384052;cursor:pointer}.btn.primary{background:var(--blue);color:#fff;border-color:var(--blue)}.searchbar{display:flex;gap:10px;margin:18px 0}.searchbar input,.searchbar select{background:#fff;border:1px solid #e2e4eb;border-radius:11px;padding:12px 14px;font:inherit;color:#434a5b}.searchbar input{flex:1}.layout{display:grid;grid-template-columns:205px minmax(330px,1fr);gap:14px}.panel{background:#fff;border:1px solid var(--line);border-radius:15px;overflow:hidden}.panel-head{padding:16px 17px;border-bottom:1px solid var(--line);font-weight:700}.panel-head small{font-weight:400;color:var(--muted);margin-left:6px}.cases{max-height:690px;overflow:auto}.case{padding:14px 15px;border-bottom:1px solid #f0f1f5;cursor:pointer}.case:hover,.case.selected{background:#f1f2ff;border-left:3px solid var(--blue)}.case .tag{font-size:10px;color:var(--blue);margin-bottom:7px}.case b{display:block;font-size:13px;line-height:1.45}.case p{font-size:11px;color:var(--muted);line-height:1.5;margin:6px 0 0}.workspace{min-width:0}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:13px}.metric{background:#fff;border:1px solid var(--line);border-radius:13px;padding:14px}.metric small{display:block;color:var(--muted);font-size:11px}.metric b{font-size:20px;display:block;margin-top:7px}.metric em{font-style:normal;color:#bb7842;font-size:11px;margin-left:5px}.graph-panel{min-height:490px}.graph-tools{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line)}.graph-tools button{border:1px solid var(--line);border-radius:20px;background:#fff;padding:7px 12px;color:#60687a}.legend{display:flex;gap:14px;padding:13px 17px;color:#71798a;font-size:11px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}.graph{height:365px;position:relative;overflow:hidden;background:radial-gradient(ellipse at center,#fbfbfe 0,#fff 68%)}.links{position:absolute;inset:0;width:100%;height:100%}.links line{stroke:#d7dbea;stroke-width:1.5}.node{position:absolute;border-radius:50%;display:grid;place-items:center;color:#fff;font-size:9px;text-align:center;box-shadow:0 2px 6px #25305020}.node.big{width:51px;height:51px;background:var(--blue)}.node.mid{width:38px;height:38px;background:#8873ae}.node.small{width:22px;height:22px;background:#47a58c}.node.tiny{width:13px;height:13px;background:#c3935d}.node span{position:absolute;top:100%;white-space:nowrap;color:#576074;margin-top:3px}.graph-caption{padding:11px 16px;color:var(--muted);font-size:11px;border-top:1px solid var(--line)}.right{background:#fff;border-left:1px solid var(--line);padding:24px 17px;min-height:100vh}.ask-title{font-size:10px;letter-spacing:2px;color:#b1895b;margin:5px 0 13px}.right h2{font-size:19px;margin:0 0 9px}.right .sub{font-size:12px;line-height:1.6;color:var(--muted);margin:0 0 17px}.quick{width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:5px 0;color:#424a5c;cursor:pointer;font-size:12px}.formlabel{display:block;margin:19px 0 8px;font-size:12px;font-weight:700}.right textarea{width:100%;height:88px;resize:vertical;border:1px solid #e1e3ea;border-radius:11px;padding:11px;font:inherit;font-size:12px}.right .primary{width:100%;margin-top:8px}.answer{display:none;white-space:pre-wrap;background:#f7f8fd;border-radius:11px;padding:12px;margin-top:12px;font-size:12px;line-height:1.6;max-height:250px;overflow:auto}.sources{color:var(--blue);font-size:11px;margin-top:8px;line-height:1.5}.rulebox{margin-top:18px;padding:12px;border-radius:11px;background:#fbf8f1;color:#746548;font-size:11px;line-height:1.55}.status{display:inline-block;padding:4px 8px;border-radius:20px;background:#fff3e8;color:#a86832;font-size:10px;margin-top:9px}@media(max-width:1100px){.app{grid-template-columns:190px 1fr}.right{grid-column:2;border-left:0;border-top:1px solid var(--line);min-height:auto}.layout{grid-template-columns:185px 1fr}}@media(max-width:760px){.app{display:block}.sidebar{height:auto;position:relative;padding:12px}.sidebar .navtitle,.sidebar .nav,.project{display:none}.brand{padding:0}.topbar{height:56px}.content{padding:18px 12px}.layout{grid-template-columns:1fr}.cases{display:flex;max-height:none;overflow:auto}.case{min-width:190px}.right{min-height:auto}.title-row h1{font-size:18px}}
</style></head><body><div class="app"><aside class="sidebar"><div class="brand"><div class="mark">FR</div><div><strong>运费结算</strong><small>FREIGHT CONTROL</small></div></div><div class="project"><b>运费对账与计费争议</b><small>东航陆运 · 试点工作台</small></div><div class="navtitle">工作空间</div><div class="nav"><span class="ni">✦</span>业务助手</div><div class="nav"><span class="ni">▦</span>工作总览</div><div class="nav active"><span class="ni">KB</span>知识库与图谱</div><div class="nav"><span class="ni">01</span>运费对账</div><div class="nav"><span class="ni">02</span>差异复核</div><div class="nav"><span class="ni">03</span>审计留痕</div><div class="navtitle">项目资料</div><div class="nav"><span class="ni">◇</span>合同与价目版本</div><div class="nav"><span class="ni">◇</span>运单与称重凭证</div><div class="nav"><span class="ni">◇</span>流程说明</div><div class="rulebox">演示环境<br>仅使用合成账单数据；不连接生产系统。</div></aside>
<main class="main"><header class="topbar"><div class="crumb">运费结算工作台　/　<b>知识库与图谱</b></div><button class="persona">演示身份　客户 A · 结算专员　⌄</button></header><div class="content"><div class="title-row"><div><h1>知识库与运费关系图谱</h1><p>围绕运单、合同版本、计费规则与差异依据进行关联检索</p></div><button class="btn" onclick="document.querySelector('#question').focus()">＋ 添加知识</button></div><div class="searchbar"><input id="search" placeholder="搜索合同条款、运单编号、重量口径或差异原因…"><select id="topic"><option>全部主题</option><option>合同与价目</option><option>重量口径</option><option>异常处理</option></select><button class="btn primary" onclick="searchKnowledge()">检索</button></div><div class="layout"><section class="panel cases"><div class="panel-head">知识条目 <small>6 条</small></div><div class="case selected" onclick="selectCase(this,'重量口径与差异核验')"><div class="tag">计费规则 / 重量</div><b>实际重量、体积重量与保底重量</b><p>核对合同优先级、来源凭证与计费重量。</p></div><div class="case" onclick="selectCase(this,'价目版本与生效时间')"><div class="tag">合同 / 版本</div><b>线路月中换价后的版本核对</b><p>旧运单重算时需匹配业务时点对应价目。</p></div><div class="case" onclick="selectCase(this,'资料缺失的人工处理')"><div class="tag">异常 / 交接</div><b>缺少称重或签收依据</b><p>创建人工任务，记录原因、接手人和时间。</p></div><div class="case" onclick="selectCase(this,'计价时点冲突')"><div class="tag">合同 / 争议</div><b>发车时间与签收时间口径</b><p>模型只提示冲突，由合同审计人员确认。</p></div><div class="case" onclick="selectCase(this,'审计留痕字段')"><div class="tag">审计 / 留痕</div><b>建议结果的可重建记录</b><p>保存业务编号、资料版本、引用、修改和签核。</p></div><div class="case" onclick="selectCase(this,'结算权限边界')"><div class="tag">权限 / 结算</div><b>付款、扣费与审批权限</b><p>模型不执行资金动作，沿用原审批流程。</p></div></section>
<section class="workspace"><div class="summary"><div class="metric"><small>待复核差异</small><b>12 <em>演示</em></b></div><div class="metric"><small>版本冲突</small><b>3 <em>需人工</em></b></div><div class="metric"><small>依据完整率</small><b>86% <em>样例</em></b></div></div><div class="panel graph-panel"><div class="panel-head">业务关系图谱 <small>18 个节点 · 27 条关联</small></div><div class="graph-tools"><button onclick="zoom(0.9)">− 缩小</button><button id="zoomlabel">100%</button><button onclick="zoom(1.1)">＋ 放大</button><button onclick="zoom(1)">适应画布</button></div><div class="legend"><span><i class="dot" style="background:#4353d6"></i>业务单据</span><span><i class="dot" style="background:#c3935d"></i>主题</span><span><i class="dot" style="background:#47a58c"></i>来源</span><span><i class="dot" style="background:#8873ae"></i>业务规则</span></div><div class="graph" id="graph"><svg class="links" viewBox="0 0 600 360" preserveAspectRatio="none"><line x1="300" y1="170" x2="160" y2="90"/><line x1="300" y1="170" x2="430" y2="80"/><line x1="300" y1="170" x2="170" y2="260"/><line x1="300" y1="170" x2="440" y2="260"/><line x1="300" y1="170" x2="300" y2="55"/><line x1="160" y1="90" x2="90" y2="160"/><line x1="430" y1="80" x2="510" y2="150"/><line x1="170" y1="260" x2="270" y2="310"/><line x1="440" y1="260" x2="350" y2="315"/><line x1="160" y1="90" x2="300" y2="55"/><line x1="430" y1="80" x2="300" y2="55"/><line x1="170" y1="260" x2="90" y2="160"/><line x1="440" y1="260" x2="510" y2="150"/><line x1="300" y1="170" x2="300" y2="310"/><line x1="90" y1="160" x2="300" y2="170"/><line x1="510" y1="150" x2="300" y2="170"/></svg><div class="node big" style="left:46%;top:41%">运单<span>业务编号 WB-001</span></div><div class="node mid" style="left:23%;top:20%">合同<span>价目版本 v2</span></div><div class="node mid" style="left:69%;top:18%">称重<span>称重单据</span></div><div class="node mid" style="left:25%;top:68%">计费<span>计费规则</span></div><div class="node mid" style="left:70%;top:67%">签收<span>签收回执</span></div><div class="node small" style="left:48%;top:8%">版本<span>有效期</span></div><div class="node small" style="left:13%;top:42%">实际重<span>字段来源</span></div><div class="node small" style="left:82%;top:40%">体积重<span>换算依据</span></div><div class="node small" style="left:45%;top:83%">保底重<span>合同条款</span></div><div class="node tiny" style="left:34%;top:38%"></div><div class="node tiny" style="left:61%;top:40%"></div><div class="node tiny" style="left:36%;top:58%"></div><div class="node tiny" style="left:63%;top:58%"></div><div class="node tiny" style="left:18%;top:30%"></div><div class="node tiny" style="left:78%;top:27%"></div><div class="node tiny" style="left:29%;top:82%"></div><div class="node tiny" style="left:76%;top:82%"></div></div><div class="graph-caption">图谱为演示示意；节点关系来自项目规则样例，不代表已连接企业生产数据。</div></div><div class="panel" style="margin-top:13px"><div class="panel-head">选中条目：<span id="selectedTitle">重量口径与差异核验</span></div><div style="padding:14px 17px;color:#697287;font-size:12px;line-height:1.65">系统先引用原始单据与适用规则，再给出差异说明。资料缺失、版本冲突或计价时点不明时，停止建议并转人工复核。</div></div></section></div></div></main>
<aside class="right"><div class="ask-title">ASK YOUR FREIGHT WIKI</div><h2>带着依据问答</h2><p class="sub">检索条目 → 关联业务规则 → 返回依据与来源</p><button class="quick" onclick="fillQ('旧运单重算时如何确认适用的价目版本？')">旧运单重算时如何确认价目版本？　↗</button><button class="quick" onclick="fillQ('实际重量、体积重量和保底重量如何核验？')">三种重量口径如何核验？　↗</button><button class="quick" onclick="fillQ('哪些情形必须转人工，模型不能决定什么？')">哪些情形必须转人工？　↗</button><label class="formlabel" for="question">向知识库提问</label><textarea id="question" placeholder="输入运费对账问题…"></textarea><button class="btn primary" id="askbtn" onclick="askWiki()">查找依据并回答　↗</button><div class="answer" id="answer"></div><div class="sources" id="sources"></div><div class="rulebox">安全边界：模型不认定合同变更或赔付，不批准结算，不付款、不扣费。命中版本冲突、缺依据或系统不可用时必须转人工。</div></aside></div>
<script>
function fillQ(s){document.querySelector('#question').value=s;askWiki()}function selectCase(el,title){document.querySelectorAll('.case').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');document.querySelector('#selectedTitle').textContent=title;document.querySelector('#question').value=title}
let z=1;function zoom(f){z=f===1?1:Math.max(.7,Math.min(1.4,z*f));document.querySelector('#zoomlabel').textContent=Math.round(z*100)+'%';document.querySelector('#graph').style.transform='scale('+z+')';document.querySelector('#graph').style.transformOrigin='center'}
function searchKnowledge(){const s=document.querySelector('#search').value;if(s){document.querySelector('#question').value=s;askWiki()}}
async function askWiki(){const q=document.querySelector('#question').value.trim();if(!q)return;const b=document.querySelector('#askbtn'),a=document.querySelector('#answer');b.disabled=true;b.textContent='正在检索…';a.style.display='block';a.textContent='正在检索知识库并整理引用…';try{const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});const d=await r.json();a.textContent=d.answer;document.querySelector('#sources').textContent=(d.citations||[]).map(c=>c.source+' · '+c.heading+' ('+c.id+')').join('\n')}catch(e){a.textContent='请求失败：'+e}finally{b.disabled=false;b.textContent='查找依据并回答　↗'}}
</script></body></html>'''

@app.get("/",response_class=HTMLResponse)
async def home(user=Depends(auth.get_current_user)):
    return ui.decorate_legacy(PAGE,user)


@app.get("/login",response_class=HTMLResponse)
async def login_page(request:Request):
    if await auth.resolve_user(request):
        return RedirectResponse("/",status_code=303)
    return ui.LOGIN_PAGE


@app.get("/knowledge",response_class=HTMLResponse)
async def knowledge_page(user=Depends(auth.require_role("admin"))):
    return ui.shell("知识库管理",ui.KNOWLEDGE_BODY,user,"/knowledge","knowledge.js")


@app.get("/reconcile",response_class=HTMLResponse)
async def reconciliation_page(user=Depends(auth.require_role("reconciler"))):
    return ui.shell("对账工作台",ui.RECONCILE_BODY,user,"/reconcile","reconcile.js")


@app.get("/records",response_class=HTMLResponse)
async def records_page(user=Depends(auth.get_current_user)):
    return ui.shell("历史记录",ui.RECORDS_BODY,user,"/records","records.js")

@app.post("/api/ask")
async def ask_api(body:Question,_user=Depends(auth.get_current_user)):
    # Keep the original synchronous graph unchanged, off the ASGI event loop.
    try:
        result=await asyncio.wait_for(asyncio.to_thread(ask,body.question),timeout=45)
        answer=result.get("answer","")
        citations=result.get("citations",[])
        rows=await asyncio.to_thread(retrieval.load_chunks)
        known={row["id"]:row for row in rows}
        valid=all(c.get("id") in known and all(c.get(key)==known[c["id"]].get(key) for key in ("source","heading")) for c in citations)
        allowed={f"{c['source']} / {c['heading']}" for c in citations}
        cited=set(re.findall(r"\[([^\[\]\n]+ / [^\[\]\n]+)\]",answer))
        if valid and cited.issubset(allowed) and not answer.startswith("模型服务暂不可用"):
            return {"answer":answer,"citations":citations}
    except (TimeoutError,ValueError,TypeError,KeyError):
        pass
    contexts=await asyncio.to_thread(retrieval.search,body.question,3)
    return {"answer":"当前展示可核验的原文资料，请人工确认：\n\n"+"\n\n".join(f"[{row['source']} / {row['heading']}]\n{row['text']}" for row in contexts),
            "citations":[{key:row[key] for key in ("id","source","heading")} for row in contexts]}

@app.post("/api/audit/demo")
async def audit_demo(_user=Depends(auth.get_current_user)):
    sample={"invoice_id":"DEMO-001","carrier_id":"CARRIER-A","lane_id":"LANE-001","charge_date":"2026-06-15","rate_version":"v1","actual_weight_kg":"120","volume_weight_kg":"135","billed_amount":"250"}
    return {"invoice":sample,"audit":audit_invoice(sample),"mode":"synthetic_demo_read_only"}

@app.get("/health")
async def health(): return {"status":"ok","knowledge_base":"read_only"}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("freight_recon.web:app",host="127.0.0.1",port=8000,reload=False)
