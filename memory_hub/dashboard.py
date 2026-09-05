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
:root { color-scheme: dark; --bg:#0d1117; --bg2:#010409; --card:#161b22; --card2:#1c2129; --line:#30363d; --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff; --accent-dim:#1f6feb33; --bad:#f85149; --bad-dim:#f8514922; --good:#3fb950; --good-dim:#3fb95022; --warn:#d29922; --warn-dim:#d2992222; --radius:10px; }
*{box-sizing:border-box} html,body{height:100%}
body{margin:0;font:14px/1.5 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
.app{display:flex;min-height:100vh}
.sidebar{width:230px;flex:0 0 230px;background:var(--bg2);border-right:1px solid var(--line);display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.brand{display:flex;align-items:center;gap:9px;padding:18px 16px;font-weight:700;font-size:15px;border-bottom:1px solid var(--line)}
.brand .dot{width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 0 3px var(--good-dim)}
nav{padding:10px;display:flex;flex-direction:column;gap:3px;flex:1}
.nav-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:transparent;color:var(--muted);border:1px solid transparent;border-radius:8px;padding:9px 10px;cursor:pointer;font-size:13.5px;transition:background .12s,color .12s}
.nav-item:hover{background:#1c212966;color:var(--text)}
.nav-item.active{background:var(--accent-dim);color:var(--accent);font-weight:600}
.nav-item .ico{width:18px;text-align:center}
.nav-item .lbl{flex:1}
.badge{font-size:11px;background:#30363d;color:var(--muted);padding:1px 7px;border-radius:99px;min-width:20px;text-align:center}
.nav-item.active .badge{background:var(--accent);color:#04162e}
.badge.bad{background:var(--bad-dim);color:var(--bad)}
.sidebar-foot{padding:12px 16px;color:var(--muted);font-size:11.5px;border-top:1px solid var(--line);display:flex;align-items:center;gap:6px}
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{padding:16px 26px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#0d1117ee;backdrop-filter:blur(8px);z-index:5;display:flex;justify-content:space-between;align-items:center;gap:12px}
.topbar h1{margin:0;font-size:19px}
.topbar .sub{color:var(--muted);font-size:12.5px;margin-top:3px}
.content{max-width:1080px;width:100%;margin:0 auto;padding:22px 26px 60px;flex:1}
.panel.hidden{display:none}
button,.btn{background:#21262d;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 13px;cursor:pointer;font:inherit;transition:border-color .12s,background .12s}
button:hover{border-color:var(--accent)}
button:disabled{opacity:.5;cursor:default}
button.primary{background:#1f6feb;border-color:#1f6feb}
button.primary:hover{background:#3182ff}
button.ghost{background:transparent}
button.danger-outline{color:var(--bad);border-color:var(--bad-dim)}
button.danger-outline:hover{background:var(--bad-dim);border-color:var(--bad)}
button.good-outline{color:var(--good);border-color:var(--good-dim)}
button.good-outline:hover{background:var(--good-dim);border-color:var(--good)}
button.icon{padding:7px 9px}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.search-wrap{position:relative;flex:1;min-width:200px}
.search-wrap input{padding-left:32px}
.search-wrap .sico{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chip{font-size:12px;padding:5px 11px;border-radius:99px;border:1px solid var(--line);color:var(--muted);cursor:pointer;background:transparent}
.chip:hover{border-color:var(--accent)}
.chip.active{background:var(--accent-dim);border-color:var(--accent);color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px}
.meta{color:var(--muted);font-size:11.5px;margin-top:10px;display:flex;flex-wrap:wrap;gap:5px 8px}
.meta code{background:#0d1117;border:1px solid var(--line);border-radius:5px;padding:0 5px;font-size:11px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.space{justify-content:space-between}
input,textarea{width:100%;background:#0d1117;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px;font:inherit}
input:focus,textarea:focus{outline:none;border-color:var(--accent)}
textarea{min-height:110px;resize:vertical;line-height:1.5}
.hidden{display:none !important}
.tag-chip{font-size:11px;border:1px solid var(--line);padding:2px 8px;border-radius:99px;color:var(--muted);white-space:nowrap}
.tag-chip.superseded{color:var(--muted);text-decoration:line-through;opacity:.7}
.tag-chip.kind{border-color:transparent}
.empty{color:var(--muted);padding:40px 20px;text-align:center;border:1px dashed var(--line);border-radius:var(--radius)}
.empty .big{font-size:26px;display:block;margin-bottom:8px}
.section-title{display:flex;justify-content:space-between;align-items:center;margin:0 0 14px}
.section-title h2{margin:0;font-size:16px}
.memory-text{white-space:pre-wrap;margin:0 0 4px;line-height:1.5}
.card-actions{margin-top:12px;display:flex;gap:8px;justify-content:flex-end}
.skeleton{color:var(--muted);padding:30px;text-align:center}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px}
.stat .n{font-size:22px;font-weight:700}
.stat .l{color:var(--muted);font-size:12px;margin-top:2px}
.stat.bad{border-color:var(--bad-dim)}.stat.bad .n{color:var(--bad)}
.stat.good .n{color:var(--good)}
.banner{display:flex;align-items:center;gap:10px;padding:12px 15px;border-radius:var(--radius);margin-bottom:18px;font-weight:600}
.banner.good{background:var(--good-dim);color:var(--good)}
.banner.bad{background:var(--bad-dim);color:var(--bad)}
details.issue{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:10px;overflow:hidden}
details.issue summary{padding:12px 15px;cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center}
details.issue summary::-webkit-details-marker{display:none}
details.issue summary .n{color:var(--warn);font-weight:700}
details.issue .body{padding:0 15px 14px;color:var(--muted);font-size:12.5px}
details.issue .body div{padding:6px 0;border-top:1px solid var(--line)}
.conflict-group{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:14px;margin-bottom:14px}
.conflict-group h3{margin:0 0 10px;font-size:14px;font-weight:600;color:var(--warn)}
.conflict-item{background:var(--card2);border:1px solid var(--line);border-radius:8px;padding:11px;margin-top:8px;position:relative}
.conflict-item.stale{opacity:.6}
.recent-badge{position:absolute;top:-9px;right:10px;background:var(--good);color:#04170b;font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:99px;letter-spacing:.02em}
.project-group{margin-bottom:22px}
.project-head{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.project-head h3{margin:0;font-size:13.5px;font-weight:600;color:var(--text);text-transform:capitalize}
.project-head .badge{background:transparent;border:1px solid var(--line)}
.toast-host{position:fixed;bottom:18px;right:18px;display:flex;flex-direction:column;gap:8px;z-index:100}
.toast{background:#1c2129;border:1px solid var(--line);border-left:3px solid var(--accent);color:var(--text);padding:10px 14px;border-radius:8px;box-shadow:0 6px 20px #0008;font-size:13px;min-width:220px;animation:slidein .15s ease-out}
.toast.ok{border-left-color:var(--good)}.toast.err{border-left-color:var(--bad)}
@keyframes slidein{from{transform:translateY(6px);opacity:0}to{transform:translateY(0);opacity:1}}
.modal-host{position:fixed;inset:0;background:#010409cc;display:flex;align-items:center;justify-content:center;z-index:200;padding:20px}
.modal{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;width:100%;max-width:480px;box-shadow:0 20px 60px #000a}
.modal h3{margin:0 0 4px}
.modal p.desc{color:var(--muted);margin:0 0 14px;font-size:13px}
.modal .actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
@media (max-width:760px){
 .app{flex-direction:column}
 .sidebar{width:100%;flex:none;height:auto;position:static;flex-direction:row;overflow-x:auto}
 .brand{border-bottom:none;border-right:1px solid var(--line)}
 nav{flex-direction:row;flex:none}
 .sidebar-foot{display:none}
 .content{padding:16px}
}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
 <div class="brand">🧠 <span>AI Memory Hub</span></div>
 <nav>
  <button class="nav-item active" data-tab="memories" onclick="showTab('memories')"><span class="ico">📚</span><span class="lbl">Memories</span><span class="badge" id="c-memories">–</span></button>
  <button class="nav-item" data-tab="pending" onclick="showTab('pending')"><span class="ico">📥</span><span class="lbl">Review queue</span><span class="badge" id="c-pending">–</span></button>
  <button class="nav-item" data-tab="conflicts" onclick="showTab('conflicts')"><span class="ico">⚡</span><span class="lbl">Conflicts</span><span class="badge" id="c-conflicts">–</span></button>
  <button class="nav-item" data-tab="audit" onclick="showTab('audit')"><span class="ico">🩺</span><span class="lbl">Vault health</span><span class="badge hidden" id="c-audit">!</span></button>
 </nav>
 <div class="sidebar-foot"><span class="dot" style="width:6px;height:6px;border-radius:50%;background:var(--good)"></span> Bound to localhost only</div>
</aside>
<div class="main">
 <div class="topbar">
  <div><h1 id="pageTitle">Memories</h1><div class="sub" id="pageSub">Everything currently stored in your vault</div></div>
  <button class="icon" title="Refresh" onclick="refreshCurrent()">⟳</button>
 </div>
 <div class="content">

<section id="memories" class="panel">
 <div class="toolbar">
  <div class="search-wrap"><span class="sico">🔍</span><input id="search" placeholder="Search memories…" oninput="debouncedSearch()" onkeydown="if(event.key==='Enter')loadMemories()"></div>
  <button onclick="loadMemories()">Search</button>
 </div>
 <div class="chips" id="kindChips"></div>
 <div id="memoryList"><div class="skeleton">Loading…</div></div>
</section>

<section id="pending" class="panel hidden">
 <div class="section-title"><h2>Pending review</h2><span class="sub" style="color:var(--muted);font-size:12.5px">Proposals waiting for your approval before they're written to the vault</span></div>
 <div id="pendingList" class="grid"><div class="skeleton">Loading…</div></div>
</section>

<section id="conflicts" class="panel hidden">
 <div class="section-title"><h2>Potential conflicts</h2><span class="sub" style="color:var(--muted);font-size:12.5px">Same kind + subject, but disagreeing text</span></div>
 <div id="conflictList"><div class="skeleton">Loading…</div></div>
</section>

<section id="audit" class="panel hidden">
 <div class="section-title"><h2>Vault health</h2><button onclick="loadAudit()">Run audit</button></div>
 <div id="auditOut"><div class="skeleton">Loading…</div></div>
</section>

 </div>
</div>
</div>
<div id="toastHost" class="toast-host"></div>
<div id="modalHost" class="modal-host hidden"></div>
<script>
const $=id=>document.getElementById(id);
const TITLES={memories:['Memories','Everything currently stored in your vault'],pending:['Review queue','Proposals waiting for approval'],conflicts:['Conflicts','Memories that disagree with each other'],audit:['Vault health','Consistency check across files and index']};
let currentTab='memories', memoryRows=[], activeKind=null, searchTimer=null;

async function api(path,method='GET',body=null){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});
  let j={}; try{j=await r.json()}catch(e){}
  if(!r.ok) throw new Error(j.error||r.statusText);
  return j;
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function toast(msg,type='ok'){
  const host=$('toastHost'); const el=document.createElement('div');
  el.className='toast '+type; el.textContent=msg; host.appendChild(el);
  setTimeout(()=>{el.style.opacity='0';el.style.transition='opacity .2s';setTimeout(()=>el.remove(),200)},2800);
}
async function guarded(fn,okMsg){
  try{ const r=await fn(); if(okMsg) toast(okMsg,'ok'); return r; }
  catch(e){ toast(e.message||'Something went wrong','err'); throw e; }
}
function closeModal(){$('modalHost').classList.add('hidden');$('modalHost').innerHTML=''}
function confirmModal(title,desc,confirmLabel,danger){
  return new Promise(resolve=>{
    const host=$('modalHost');
    host.innerHTML=`<div class="modal"><h3>${esc(title)}</h3><p class="desc">${esc(desc)}</p><div class="actions"><button onclick="__cancel()">Cancel</button><button class="${danger?'primary':'primary'}" style="${danger?'background:var(--bad);border-color:var(--bad)':''}" onclick="__ok()">${esc(confirmLabel)}</button></div></div>`;
    host.classList.remove('hidden');
    window.__ok=()=>{closeModal();resolve(true)};
    window.__cancel=()=>{closeModal();resolve(false)};
  });
}
function editModal(currentText){
  return new Promise(resolve=>{
    const host=$('modalHost');
    host.innerHTML=`<div class="modal"><h3>Edit memory</h3><p class="desc">Update the wording. This rewrites the entry in place and keeps its history tag.</p><textarea id="editArea">${esc(currentText)}</textarea><div class="actions"><button onclick="__cancel()">Cancel</button><button class="primary" onclick="__ok()">Save changes</button></div></div>`;
    host.classList.remove('hidden');
    const ta=$('editArea'); ta.focus(); ta.setSelectionRange(ta.value.length,ta.value.length);
    window.__ok=()=>{const v=ta.value.trim();closeModal();resolve(v||null)};
    window.__cancel=()=>{closeModal();resolve(null)};
  });
}
function showTab(name){
  currentTab=name;
  for(const s of ['memories','pending','conflicts','audit']){
    $(s).classList.toggle('hidden',s!==name);
    document.querySelector(`.nav-item[data-tab="${s}"]`).classList.toggle('active',s===name);
  }
  const [title,sub]=TITLES[name]; $('pageTitle').textContent=title; $('pageSub').textContent=sub;
  refreshCurrent();
}
function refreshCurrent(){
  if(currentTab==='memories')loadMemories();
  if(currentTab==='pending')loadPending();
  if(currentTab==='conflicts')loadConflicts();
  if(currentTab==='audit')loadAudit();
}
function debouncedSearch(){clearTimeout(searchTimer);searchTimer=setTimeout(loadMemories,300)}

function formatWhen(s){
  if(!s) return '';
  const hasTime = s.includes('T');
  const d = new Date(hasTime ? s : s+'T00:00:00');
  if(isNaN(d)) return esc(s);
  const dateFmt = d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
  if(!hasTime) return esc(dateFmt);
  const timeFmt = d.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
  return esc(dateFmt+' · '+timeFmt);
}
function kindColor(kind){
  const palette=['#58a6ff','#3fb950','#d29922','#f778ba','#a371f7','#39c5cf','#f85149','#8b949e'];
  let h=0; for(const c of String(kind)) h=(h*31+c.charCodeAt(0))>>>0;
  return palette[h%palette.length];
}
function renderKindChips(){
  const kinds=[...new Set(memoryRows.map(r=>r.kind))].sort();
  $('kindChips').innerHTML = kinds.length<=1 ? '' : ['<button class="chip'+(activeKind===null?' active':'')+'" onclick="setKindFilter(null)">All</button>']
    .concat(kinds.map(k=>`<button class="chip${activeKind===k?' active':''}" onclick="setKindFilter('${esc(k)}')">${esc(k)}</button>`)).join('');
}
function setKindFilter(k){activeKind=k;renderKindChips();renderMemories()}
function memoryCard(r,isMostRecent=false){
  return `
    <div class="card" style="position:relative">
      ${isMostRecent?'<span class="recent-badge">🕐 Most recent</span>':''}
      <div class="row space">
        <span class="row" style="gap:6px">
          <span class="tag-chip kind" style="background:${kindColor(r.kind)}22;color:${kindColor(r.kind)}">${esc(r.kind)}</span>
          <span class="tag-chip${r.tag==='superseded'?' superseded':''}">${esc(r.tag)}</span>
        </span>
        <span class="meta" style="margin:0">${formatWhen(r.date)}</span>
      </div>
      <p class="memory-text" id="t-${r.memory_id}">${esc(r.text)}</p>
      <div class="meta">
        <span>📄 ${esc(r.path)}</span><span>·</span><span>${esc(r.writer)}</span><span>·</span><code>${esc(r.memory_id)}</code>
      </div>
      <div class="card-actions">
        <button class="ghost" onclick="editMemory('${r.memory_id}')">✎ Edit</button>
        <button class="danger-outline" onclick="forgetMemory('${r.memory_id}')">🗑 Forget</button>
      </div>
    </div>`;
}
function renderMemories(){
  const rows = activeKind ? memoryRows.filter(r=>r.kind===activeKind) : memoryRows;
  $('c-memories').textContent=memoryRows.length;
  if(!rows.length){
    $('memoryList').innerHTML = `<div class="empty"><span class="big">🔎</span>No memories found${activeKind?' for "'+esc(activeKind)+'"':''}.</div>`;
    return;
  }
  // Group projects by their canonical file, since routing may place several
  // related subjects in one file. Other kinds are grouped by kind + subject.
  // Newest first within a group — the latest entry at the top.
  const groups = new Map();
  for(const r of rows){
    const isProject = r.kind === 'project';
    const key = isProject ? `project:${r.path}` : `${r.kind}:${r.subject || 'general'}`;
    const label = isProject ? r.path.replace(/^\/projects\//,'').replace(/\.md$/,'') : (r.subject || 'general');
    if(!groups.has(key)) groups.set(key, {label,items:[]});
    groups.get(key).items.push(r);
  }
  // Newest first: descending date within each group.
  const compareRows=(a,b)=>a.date>b.date?-1:a.date<b.date?1:a.memory_id>b.memory_id?-1:a.memory_id<b.memory_id?1:0;
  for(const g of groups.values()) g.items.sort(compareRows);
  // Most recently active project first (the newest item of a group is now its first).
  const ordered = [...groups.values()].sort((a,b)=>{
    const la=a.items[0], lb=b.items[0];
    return compareRows(la,lb);
  });
  $('memoryList').innerHTML = ordered.map(({label,items})=>`
    <div class="project-group">
      <div class="project-head"><h3>${esc(label)}</h3><span class="badge">${items.length}</span></div>
      <div class="grid">${items.map(item=>memoryCard(item,item.is_most_recent)).join('')}</div>
    </div>`).join('');
}
async function loadMemories(){
  const q=$('search').value.trim();
  memoryRows = await guarded(()=>api('/api/memories'+(q?'?q='+encodeURIComponent(q):'')));
  renderKindChips(); renderMemories();
}
async function editMemory(id){
  const el=$('t-'+id); const v=await editModal(el.innerText);
  if(v===null) return;
  await guarded(()=>api('/api/memory/'+id+'/edit','POST',{text:v}),'Memory updated');
  await loadMemories(); await loadConflicts();
}
async function forgetMemory(id){
  const ok=await confirmModal('Forget this memory?','This permanently removes the entry from the vault file. This cannot be undone.','Forget it',true);
  if(!ok) return;
  await guarded(()=>api('/api/memory/'+id+'/forget','POST',{}),'Memory forgotten');
  await loadMemories(); await loadConflicts();
}
async function loadPending(){
  const rows=await guarded(()=>api('/api/pending'));
  $('c-pending').textContent=rows.length;
  $('pendingList').innerHTML = rows.length ? rows.map(r=>`
    <div class="card">
      <div class="row space">
        <span class="row" style="gap:6px">
          <span class="tag-chip kind" style="background:${kindColor(r.kind)}22;color:${kindColor(r.kind)}">${esc(r.kind)}</span>
          <span class="tag-chip">${esc(r.tag)}</span>
        </span>
      </div>
      <p class="memory-text">${esc(r.text)}</p>
      <div class="meta"><span>${esc(r.subject)}</span><span>·</span><span>${esc(r.writer)}</span><span>·</span><span>🕐 ${formatWhen(r.created_at)}</span></div>
      <div class="card-actions">
        <button class="good-outline" onclick="approve('${r.proposal_id}')">✓ Approve</button>
        <button class="danger-outline" onclick="rejectP('${r.proposal_id}')">✕ Reject</button>
      </div>
    </div>`).join('') : `<div class="empty"><span class="big">✅</span>Queue is empty. The memory goblins are behaving.</div>`;
}
async function approve(id){await guarded(()=>api('/api/pending/'+id+'/approve','POST',{}),'Approved and stored');await loadPending();await loadConflicts()}
async function rejectP(id){await guarded(()=>api('/api/pending/'+id+'/reject','POST',{}),'Rejected');await loadPending()}
async function loadConflicts(){
  const groups=await guarded(()=>api('/api/conflicts'));
  $('c-conflicts').textContent=groups.length;
  $('conflictList').innerHTML = groups.length ? groups.map(g=>{
    // Backend already returns each group's memories oldest-first (creation order),
    // so the last one is the most recent — flag it to make "which do I keep" fast.
    const lastIdx = g.memories.length-1;
    return `
    <div class="conflict-group">
      <h3>⚡ ${esc(g.kind)} · ${esc(g.subject)}</h3>
      ${g.memories.map((m,i)=>`
        <div class="conflict-item${i===lastIdx?'':' stale'}">
          ${i===lastIdx?'<span class="recent-badge">🕐 Most recent</span>':''}
          <p class="memory-text">${esc(m.text)}</p>
          <div class="meta"><span>${esc(m.writer)}</span><span>·</span><span>${formatWhen(m.date)}</span><span>·</span><code>${esc(m.memory_id)}</code></div>
          <div class="card-actions" style="justify-content:flex-start;margin-top:9px">
            <button class="good-outline" onclick="resolveConflict('${m.memory_id}')">Keep this as current</button>
          </div>
        </div>`).join('')}
    </div>`;
  }).join('') : `<div class="empty"><span class="big">🎉</span>No potential conflicts detected.</div>`;
}
async function resolveConflict(id){
  const ok=await confirmModal('Resolve conflict','Keep this memory as current and mark the other entries for the same kind/subject as superseded.','Keep this one',false);
  if(!ok) return;
  await guarded(()=>api('/api/conflict/resolve','POST',{keep_id:id}),'Conflict resolved');
  await loadConflicts(); await loadMemories();
}
function issueSection(title,items,render){
  if(!items||!items.length) return `<details class="issue"><summary><span>${esc(title)}</span><span style="color:var(--good)">0</span></summary></details>`;
  return `<details class="issue"><summary><span>${esc(title)}</span><span class="n">${items.length}</span></summary><div class="body">${items.map(render).join('')}</div></details>`;
}
async function loadAudit(){
  $('auditOut').innerHTML='<div class="skeleton">Running audit…</div>';
  const j=await guarded(()=>api('/api/audit'));
  $('c-audit').classList.toggle('hidden', j.healthy);
  $('auditOut').innerHTML = `
    <div class="banner ${j.healthy?'good':'bad'}">${j.healthy?'✅ Vault is healthy — no inconsistencies found':'⚠️ Issues found — see details below'}</div>
    <div class="stats">
      <div class="stat"><div class="n">${j.records_in_files}</div><div class="l">Records in files</div></div>
      <div class="stat"><div class="n">${j.records_in_index}</div><div class="l">Records in index</div></div>
      <div class="stat${j.pending_review?' warn':''}"><div class="n">${j.pending_review}</div><div class="l">Pending review</div></div>
      <div class="stat${j.potential_conflicts?' bad':''}"><div class="n">${j.potential_conflicts}</div><div class="l">Potential conflicts</div></div>
    </div>
    ${issueSection('Duplicate memory IDs', j.duplicate_ids, id=>`<div><code>${esc(id)}</code></div>`)}
    ${issueSection('In files but missing from index', j.missing_from_index, id=>`<div><code>${esc(id)}</code></div>`)}
    ${issueSection('In index but stale (not in files)', j.stale_in_index, id=>`<div><code>${esc(id)}</code></div>`)}
    ${issueSection('Malformed memory lines', j.malformed_memory_lines, m=>`<div>📄 ${esc(m.path)}:${m.line} — <code>${esc(m.text)}</code></div>`)}
  `;
}
loadMemories(); loadPending(); loadConflicts();
</script>
</body></html>
"""

def memory_rows_for_dashboard(manager: MemoryManager, query: str = "") -> list[dict]:
    """Return visible dashboard rows with recency calculated from the full index."""
    newest = {}
    for row in manager.index.all_rows():
        is_project = row["kind"] == "project"
        key = f"project:{row['path']}" if is_project else f"{row['kind']}:{row['subject'] or 'general'}"
        if key not in newest or (row["date"], row["memory_id"]) > (newest[key]["date"], newest[key]["memory_id"]):
            newest[key] = row
    rows = manager.search(query, 200) if query else manager.index.all_rows()[::-1][:200]
    for row in rows:
        is_project = row["kind"] == "project"
        key = f"project:{row['path']}" if is_project else f"{row['kind']}:{row['subject'] or 'general'}"
        row["is_most_recent"] = newest.get(key, {}).get("memory_id") == row["memory_id"]
    return rows

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
                return self._json(memory_rows_for_dashboard(self.manager, q))
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
