from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .manager import MemoryManager

HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Memory Hub</title>
<style>
:root { color-scheme: dark; --bg:#0d1117; --card:#161b22; --line:#30363d; --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --bad:#f85149; --good:#3fb950; --warn:#d29922; }
*{box-sizing:border-box} body{margin:0;font:14px/1.45 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
header{padding:18px 22px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#0d1117ee;backdrop-filter:blur(8px);z-index:5}
h1{margin:0;font-size:20px} .sub{color:var(--muted);margin-top:4px}
main{max-width:1180px;margin:0 auto;padding:20px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
button,.btn{background:#21262d;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 11px;cursor:pointer}
button:hover{border-color:var(--accent)} button.primary{background:#1f6feb}.danger{color:#ff7b72}.good{color:#56d364}.warn{color:#e3b341}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px}
.meta{color:var(--muted);font-size:12px;margin-top:8px}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.space{justify-content:space-between}
input,textarea{width:100%;background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px}
textarea{min-height:85px;resize:vertical}.hidden{display:none}.pill{font-size:11px;border:1px solid var(--line);padding:2px 7px;border-radius:99px;color:var(--muted)}
.empty{color:var(--muted);padding:24px;text-align:center;border:1px dashed var(--line);border-radius:10px}
.count{font-weight:700}.section-title{display:flex;justify-content:space-between;align-items:center;margin:16px 0 10px}.memory-text{white-space:pre-wrap}
</style>
</head>
<body>
<header><h1>🧠 AI Memory Hub</h1><div class="sub">Local dashboard for your shared Obsidian memory</div></header>
<main>
<div class="tabs">
<button onclick="showTab('memories')">Memories <span id="memoryCount"></span></button>
<button onclick="showTab('pending')">Review queue <span id="pendingCount"></span></button>
<button onclick="showTab('conflicts')">Conflicts <span id="conflictCount"></span></button>
<button onclick="showTab('audit')">Audit</button>
</div>

<section id="memories">
<div class="row"><input id="search" placeholder="Search memories…" onkeydown="if(event.key==='Enter')loadMemories()"><button onclick="loadMemories()">Search</button></div>
<div class="section-title"><h2>Stored memories</h2><button onclick="loadMemories()">Refresh</button></div>
<div id="memoryList" class="grid"></div>
</section>

<section id="pending" class="hidden">
<div class="section-title"><h2>Pending review</h2><button onclick="loadPending()">Refresh</button></div>
<div id="pendingList" class="grid"></div>
</section>

<section id="conflicts" class="hidden">
<div class="section-title"><h2>Potential conflicts</h2><button onclick="loadConflicts()">Refresh</button></div>
<div id="conflictList"></div>
</section>

<section id="audit" class="hidden">
<div class="section-title"><h2>Vault audit</h2><button onclick="loadAudit()">Run audit</button></div>
<pre id="auditOut" class="card"></pre>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
async function api(path,method='GET',body=null){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
  const j=await r.json(); if(!r.ok) throw new Error(j.error||r.statusText); return j;
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function showTab(name){for(const s of ['memories','pending','conflicts','audit'])$(s).classList.toggle('hidden',s!==name); if(name==='pending')loadPending(); if(name==='conflicts')loadConflicts(); if(name==='audit')loadAudit();}
async function loadMemories(){
 const q=$('search').value.trim(); const rows=await api('/api/memories'+(q?'?q='+encodeURIComponent(q):''));
 $('memoryCount').textContent='('+rows.length+')';
 $('memoryList').innerHTML=rows.length?rows.map(r=>`<div class="card"><div class="row space"><span class="pill">${esc(r.tag)}</span><span class="pill">${esc(r.kind)}</span></div><p class="memory-text" id="t-${r.memory_id}">${esc(r.text)}</p><div class="meta">${esc(r.path)} · ${esc(r.subject)} · ${esc(r.writer)} · ${esc(r.date)} · ${esc(r.memory_id)}</div><div class="row" style="margin-top:10px"><button onclick="editMemory('${r.memory_id}')">Edit</button><button class="danger" onclick="forgetMemory('${r.memory_id}')">Forget</button></div></div>`).join(''):'<div class="empty">No memories found.</div>';
}
async function editMemory(id){
 const el=$('t-'+id); const v=prompt('Edit memory:',el.innerText); if(v===null||!v.trim())return;
 await api('/api/memory/'+id+'/edit','POST',{text:v}); await loadMemories(); await loadConflicts();
}
async function forgetMemory(id){
 if(!confirm('Permanently forget this memory?'))return;
 await api('/api/memory/'+id+'/forget','POST',{}); await loadMemories(); await loadConflicts();
}
async function loadPending(){
 const rows=await api('/api/pending'); $('pendingCount').textContent='('+rows.length+')';
 $('pendingList').innerHTML=rows.length?rows.map(r=>`<div class="card"><div class="row space"><span class="pill">${esc(r.tag)}</span><span class="pill">${esc(r.kind)}</span></div><p>${esc(r.text)}</p><div class="meta">${esc(r.subject)} · ${esc(r.writer)} · ${esc(r.created_at)}</div><div class="row" style="margin-top:10px"><button class="primary" onclick="approve('${r.proposal_id}')">Approve</button><button class="danger" onclick="rejectP('${r.proposal_id}')">Reject</button></div></div>`).join(''):'<div class="empty">Queue is empty. The memory goblins are behaving.</div>';
}
async function approve(id){await api('/api/pending/'+id+'/approve','POST',{});await loadPending();await loadMemories();await loadConflicts()}
async function rejectP(id){await api('/api/pending/'+id+'/reject','POST',{});await loadPending()}
async function loadConflicts(){
 const groups=await api('/api/conflicts'); $('conflictCount').textContent='('+groups.length+')';
 $('conflictList').innerHTML=groups.length?groups.map(g=>`<div class="card" style="margin-bottom:12px"><h3>${esc(g.kind)} / ${esc(g.subject)}</h3>${g.memories.map(m=>`<div class="card" style="margin:8px 0"><p>${esc(m.text)}</p><div class="meta">${esc(m.writer)} · ${esc(m.date)} · ${esc(m.memory_id)}</div><button class="good" onclick="resolveConflict('${m.memory_id}')">Keep this as current</button></div>`).join('')}</div>`).join(''):'<div class="empty">No potential conflicts detected.</div>';
}
async function resolveConflict(id){if(!confirm('Keep this memory current and supersede the other active memories for the same subject?'))return;await api('/api/conflict/resolve','POST',{keep_id:id});await loadConflicts();await loadMemories()}
async function loadAudit(){const j=await api('/api/audit');$('auditOut').textContent=JSON.stringify(j,null,2)}
loadMemories(); loadPending(); loadConflicts();
</script>
</body></html>
"""

class DashboardHandler(BaseHTTPRequestHandler):
    manager: MemoryManager = None  # type: ignore

    def log_message(self, format, *args):
        return

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            data = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        try:
            if u.path == "/api/memories":
                q = parse_qs(u.query).get("q", [""])[0]
                rows = self.manager.search(q, 200) if q else self.manager.index.all_rows()[::-1][:200]
                return self._json(rows)
            if u.path == "/api/pending":
                return self._json(self.manager.list_pending())
            if u.path == "/api/conflicts":
                return self._json(self.manager.conflicts())
            if u.path == "/api/audit":
                return self._json(self.manager.audit())
            self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._body()
            parts = [p for p in u.path.split("/") if p]
            if len(parts) == 4 and parts[:2] == ["api", "pending"] and parts[3] == "approve":
                return self._json(self.manager.approve(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "pending"] and parts[3] == "reject":
                return self._json(self.manager.reject(parts[2], str(body.get("note", ""))))
            if len(parts) == 4 and parts[:2] == ["api", "memory"] and parts[3] == "forget":
                return self._json(self.manager.forget(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "memory"] and parts[3] == "edit":
                return self._json(self.manager.edit(parts[2], str(body.get("text", "")), writer="user"))
            if u.path == "/api/conflict/resolve":
                return self._json(self.manager.resolve_conflict(str(body["keep_id"])))
            self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

def serve(vault: str, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    manager = MemoryManager(vault)
    manager.reindex()
    DashboardHandler.manager = manager
    httpd = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"AI Memory Hub dashboard: {url}")
    print("Bound to localhost only. Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    finally:
        manager.close()
        httpd.server_close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=os.environ.get("AI_MEMORY_VAULT"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    if not args.vault:
        p.error("Set --vault or AI_MEMORY_VAULT")
    serve(args.vault, args.host, args.port, not args.no_browser)

if __name__ == "__main__":
    main()
