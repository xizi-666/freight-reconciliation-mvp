"""Additive pages and navigation; preserve the original knowledge graph markup."""
import html
import re


def navigation(user: dict, active: str) -> str:
    links = []
    for path, label, role in [("/", "知识库问答", None), ("/knowledge", "知识库管理", "admin"),
                              ("/reconcile", "对账工作台", "reconciler"), ("/records", "历史记录", None)]:
        enabled = role is None or role == user["role"]
        attributes = f'href="{path}"' if enabled else 'aria-disabled="true" tabindex="-1"'
        hint = "" if enabled else f'<small>{"管理员" if role == "admin" else "对账专员"}</small>'
        links.append(f'<a class="nav {"active" if path == active else ""}" {attributes}>{label}{hint}</a>')
    role_label = "管理员" if user["role"] == "admin" else "对账专员"
    return (
        '<aside class="sidebar"><a class="brand" href="/"><span class="mark">FR</span><span><strong>运费结算</strong><small>FREIGHT CONTROL</small></span></a>'
        '<div class="project"><b>运费对账与计费争议</b><small>历史回放 · 两家承运商</small></div><div class="navtitle">工作空间</div>'
        + "".join(links)
        + '<button class="nav logout" onclick="logout()">退出登录</button>'
        + f'<div class="sidebar-footer"><b>{html.escape(user["username"])}</b><small>{role_label}</small><p>模拟数据 · 只读业务源<br>解释附依据，处理由人工确认</p></div></aside>'
    )


def shell(title: str, body: str, user: dict, active: str, script: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(title)} · 运费结算工作台</title><link rel="stylesheet" href="/static/mvp.css"></head>'
        '<body><div class="app new-app">' + navigation(user, active)
        + f'<main class="main"><header class="topbar"><span class="crumb">运费结算工作台 / <b>{title}</b></span><span class="pill">模拟数据 · 只读</span></header>'
        + '<div class="content">' + body + '</div></main></div><div id="toast" role="status"></div>'
        + f'<script src="/static/common.js"></script><script src="/static/{script}"></script></body></html>'
    )


LOGIN_PAGE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>登录 · 运费结算工作台</title><link rel="stylesheet" href="/static/mvp.css"></head>
<body class="login-body"><main class="login-card"><div class="mark">FR</div><p class="eyebrow">FREIGHT CONTROL / MVP</p><h1>运费对账与计费争议<br>智能助手</h1><p class="muted">带着依据查差异，保留每一次处理记录。</p><form id="loginForm"><label>用户名<input name="username" autocomplete="username" required maxlength="80" placeholder="请输入用户名"></label><label>密码<input name="password" type="password" autocomplete="current-password" required maxlength="200" placeholder="请输入密码"></label><p id="loginError" class="error" role="alert"></p><button class="btn primary" type="submit">登录工作台 →</button></form><div class="note">演示账号：管理员 admin / admin123<br>对账专员 recon / recon123<br>本工作台使用模拟数据，不执行付款或扣费。</div></main><script src="/static/login.js"></script></body></html>'''

KNOWLEDGE_BODY = '''<div class="title-row"><div><p class="eyebrow">KNOWLEDGE / ADMIN</p><h1>知识库管理</h1><p class="muted">维护原文与版本，让每一条解释有据可查。</p></div><span class="pill">仅管理员可维护</span></div>
<div class="knowledge-layout"><section class="panel"><div class="panel-head">文档列表 <small id="documentCount"></small></div><div class="table-scroll"><table><thead><tr><th>标题 / 编号</th><th>类型</th><th>版本</th><th>操作</th></tr></thead><tbody id="documents"><tr><td colspan="4">正在读取…</td></tr></tbody></table></div><div id="documentPreview" class="document-preview" hidden></div></section>
<section class="panel upload-panel"><div class="panel-head">上传 Markdown</div><form id="uploadForm" class="form-body"><label>文档编号<input name="document_code" required maxlength="120" placeholder="如 carrier-a-contract"></label><label>文档标题<input name="title" required maxlength="240" placeholder="如 承运商 A 运费合同"></label><div class="form-row"><label>类型<select name="document_type"><option value="contract">合同条款</option><option value="price_list">价目表</option><option value="rule">计费规则</option><option value="interview">访谈记录</option></select></label><label>版本<input name="version" value="1" required maxlength="40"></label></div><label>UTF-8 文档（最大 2 MiB）<input name="file" type="file" accept=".md" required></label><p class="muted small">同编号使用新版本号。上传后自动分块并更新现有检索索引。访谈仅用于背景说明。</p><button class="btn primary" type="submit">上传并更新索引</button><p id="uploadMessage" role="status"></p></form></section></div>'''

RECONCILE_BODY = '''<div class="title-row"><div><p class="eyebrow">RECONCILIATION / HISTORICAL REPLAY</p><h1>对账工作台</h1><p class="muted">固定快照 → 样例规则复算 → 引用解释 → 人工核对</p></div><span class="pill">10 笔模拟运单</span></div>
<div class="workbench"><section class="panel shipment-panel"><div class="panel-head">运单样本 <small>两家承运商</small></div><div class="list-note">2 正常 · 2 金额差异 · 2 重量差异<br>时点冲突、月中换价、缺依据、版本冲突各 1 笔</div><div id="shipments" class="shipment-list">正在读取…</div></section>
<section class="workspace"><div id="shipmentDetail" class="panel empty">从左侧选择一笔运单，查看原始资料。</div><div id="result" aria-live="polite"></div><div class="action-bar"><span id="actionHint" class="muted">重跑会新增记录，不会覆盖历史结果。</span><button id="reconcileButton" class="btn primary" disabled>发起对账 →</button></div></section></div>'''

RECORDS_BODY = '''<div class="title-row"><div><p class="eyebrow">RUN HISTORY / TRACEABILITY</p><h1>历史记录</h1><p class="muted">按每次运行保留快照、规则版本、引用与解释。</p></div><button class="btn" id="refreshRecords">刷新列表</button></div><section class="panel"><div class="panel-head">对账运行 <small id="runCount"></small></div><div class="table-scroll"><table><thead><tr><th>运行 / 运单</th><th>状态</th><th>原账单</th><th>复算金额</th><th>差额</th><th>发起时间</th><th></th></tr></thead><tbody id="records"></tbody></table></div><div class="pagination"><button class="btn" id="previousRecords">上一页</button><span id="recordsPage" class="muted"></span><button class="btn" id="nextRecords">下一页</button></div></section><div id="runDetail" aria-live="polite"></div>'''


def decorate_legacy(page: str, user: dict) -> str:
    page = page.replace('<body>', '<body class="legacy-page">')
    page = re.sub(r'<aside class="sidebar">.*?</aside>', lambda _match: navigation(user, "/"), page, count=1, flags=re.S)
    page = page.replace('</head>', '<link rel="stylesheet" href="/static/mvp.css"></head>')
    page = page.replace('</body>', '<div id="toast" role="status"></div><script src="/static/common.js"></script><script src="/static/legacy.js"></script></body>')
    page = re.sub(r'<button class="persona">.*?</button>', lambda _match: f'<span class="persona">{html.escape(user["username"])} · {"管理员" if user["role"] == "admin" else "对账专员"}</span>', page, count=1)
    if user["role"] == "admin":
        page = page.replace('onclick="document.querySelector(\'#question\').focus()"', 'onclick="location.href=\'/knowledge\'"')
    else:
        page = page.replace('＋ 添加知识', '查看知识资料')
    return page
