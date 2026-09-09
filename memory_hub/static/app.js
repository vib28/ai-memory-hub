'use strict';
const $=id=>document.getElementById(id), token="__LAUNCH_TOKEN__";
const reviewStatuses=['pending','rejected','approved'];
const state={rows:[],selected:null,view:'library',detail:null,request:0};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const human=s=>String(s||'').replaceAll('-',' ');
const button=(text,fn,cls='')=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.className=cls;b.onclick=()=>safe(fn);return b;};
function notice(message,error=false){$('notice').textContent=message;$('notice').hidden=!message;$('notice').className=error?'error':'';}
async function safe(fn){try{await fn();}catch(e){notice(e.message,true);}}
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Launch-Token':token},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok||data.error)throw Error(data.error||'Request failed');return data;}
function inline(text){return esc(text).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');}
function markdown(text){let out='',list=false;for(const line of String(text).split('\n')){if(/^<!--.*-->$/.test(line.trim()))continue;if(line.startsWith('- ')){if(!list){out+='<ul>';list=true;}out+='<li>'+inline(line.slice(2))+'</li>';continue;}if(list){out+='</ul>';list=false;}if(/^#{1,6} /.test(line))out+='<h3>'+inline(line.replace(/^#{1,6} /,''))+'</h3>';else if(line.trim())out+='<p>'+inline(line)+'</p>';}return out+(list?'</ul>':'');}
function options(id,values,label){const before=$(id).value;$(id).replaceChildren(new Option(label,''),...values.map(v=>new Option(human(v),v)));$(id).value=values.includes(before)?before:'';}
function validDateValue(value){return /^\d{4}-\d{2}-\d{2}$/.test(String(value||''));}
function rowDateValue(row){const match=/^(\d{4}-\d{2}-\d{2})/.exec(String(row.date||''));return match?match[1]:'';}
function dateFilter(){
  const on=$('date-on').value.trim(),from=$('date-from').value.trim(),to=$('date-to').value.trim();
  if([on,from,to].some(value=>value&&!validDateValue(value)))return {invalid:true,hasConstraint:true,message:'Enter dates in YYYY-MM-DD format.'};
  if(on&&(from||to))return {invalid:true,hasConstraint:true,message:'Choose one day or a range, not both.'};
  if(from&&to&&from>to)return {invalid:true,hasConstraint:true,message:'The start date must not be after the end date.'};
  return {invalid:false,hasConstraint:Boolean(on||from||to),on,from,to,message:''};
}
function matchesDate(row,filter){if(filter.invalid)return false;if(!filter.hasConstraint)return true;const date=rowDateValue(row);return Boolean(date&&((!filter.on||date===filter.on)&&(!filter.from||date>=filter.from)&&(!filter.to||date<=filter.to)));}
async function refresh(){state.rows=await api('/api/memories');$('total').textContent=state.rows.length;options('kind',[...new Set(state.rows.map(r=>r.kind))].sort(),'All types');options('tag-filter',[...new Set(state.rows.flatMap(r=>r.tags||[]))].sort(),'All tags');renderList();if(state.selected&&state.view==='library')await select(state.selected);const pending=await api('/api/pending');$('pending-count').textContent=pending.length||'';const worker=await api('/api/worker-health');$('worker-status').textContent='Worker: '+human(worker.status||'unknown')+(worker.backlog?' · '+worker.backlog+' queued':'');}
function renderList(){const query=$('search').value.toLowerCase(),kind=$('kind').value,tag=$('tag-filter').value,date=dateFilter();$('date-filter-status').textContent=date.message||'';const rows=state.rows.filter(r=>(!kind||r.kind===kind)&&(!tag||(r.tags||[]).includes(tag))&&matchesDate(r,date)&&[r.text,r.subject,r.writer,r.path,...(r.tags||[])].join(' ').toLowerCase().includes(query));$('result-count').textContent=rows.length+' memories · '+new Set(rows.map(r=>r.group_key)).size+' groups';$('memory-list').replaceChildren();for(const r of rows){const b=button('',()=>select(r.memory_id),'memory-card'+(r.memory_id===state.selected?' selected':''));b.setAttribute('aria-pressed',r.memory_id===state.selected?'true':'false');b.innerHTML='<div class="card-meta"><span class="kind">'+esc(r.kind)+'</span><span>'+esc(r.date.slice(0,10))+'</span></div><span class="card-title">'+esc(human(r.subject||r.group_label))+'</span><span class="card-preview">'+esc(r.text)+'</span><div class="card-meta"><span>'+esc(r.writer)+'</span><span>'+esc(r.tag)+(r.is_most_recent?' · Latest in group':'')+'</span></div>';$('memory-list').append(b);}if(!rows.length)$('memory-list').innerHTML='<div class="empty"><h3>No memories found</h3><p>Try another search or clear the filters.</p></div>';}
function linkButton(id){const row=state.rows.find(r=>r.memory_id===id);return button(row?'↗ '+human(row.subject)+' · '+row.kind:'Unavailable memory · '+id,()=>row?select(id):notice('This link points to a removed or unindexed memory.'),'link-row');}
async function select(id){const request=++state.request;const r=await api('/api/memory/'+encodeURIComponent(id));if(request!==state.request)return;state.selected=id;state.detail=r;renderList();const reader=$('reader');reader.innerHTML='<header class="reader-header"><span class="kind">'+esc(r.kind)+'</span><h2>'+esc(r.title)+'</h2><div class="meta">'+esc(r.writer)+' · '+esc(r.date)+' · '+esc(r.tag)+'</div><div class="meta">'+esc(r.path)+' · '+esc(r.memory_id)+'</div><div id="reader-tools" class="reader-tools"></div></header><div class="body-copy">'+markdown(r.display.replace(/^## .*\n/,''))+'</div><section class="relations"><h3>Tags</h3><div id="tags" class="chips"></div><h3>Linked memories</h3><div id="links"></div><h3>Linked from</h3><div id="backlinks"></div><h3>Links in source</h3><div id="source-links"></div></section><details><summary>View original Markdown</summary><pre>'+esc(r.source)+'</pre></details>';
$('reader-tools').append(button('Edit tags & links',()=>editRelations(r)));
if(r.kind!=='session')$('reader-tools').append(button('Edit text',()=>editText(r)));
$('reader-tools').append(button('Forget…',()=>forget(r),'danger'));
for(const t of r.tags)$('tags').insertAdjacentHTML('beforeend','<span class="chip">#'+esc(t)+'</span>');
for(const t of r.source_tags)$('tags').insertAdjacentHTML('beforeend','<span class="chip source-chip" title="Stored in source; not changed by organization editing">#'+esc(t)+' · source</span>');
if(!r.tags.length&&!r.source_tags.length)$('tags').innerHTML='<span class="muted">No tags yet</span>';
for(const [slot,ids] of [['links',r.links],['backlinks',r.backlinks]]){for(const target of ids)$(slot).append(linkButton(target));if(!ids.length)$(slot).innerHTML='<span class="muted">No connections yet</span>';}
for(const link of r.source_links)$('source-links').append(button('↗ '+link,()=>{const target=link.split('|')[0].split('#')[0].replace(/^\//,'').replace(/\.md$/,'');const found=state.rows.filter(x=>x.path.replace(/^\//,'').replace(/\.md$/,'')===target||x.path.split('/').pop().replace(/\.md$/,'')===target);if(found.length===1)return select(found[0].memory_id);$('search').value=found.length?found[0].path:target;$('kind').value='';$('tag-filter').value='';renderList();notice(found.length?'Matching memories shown in the list.':'No indexed target found for this source link.');},'link-row'));
if(!r.source_links.length)$('source-links').innerHTML='<span class="muted">No wiki-links in source</span>';
}
function dialog(title,html,save){$('editor-title').textContent=title;$('editor-body').innerHTML=html;$('editor-error').textContent='';$('save').onclick=async()=>{const b=$('save');b.disabled=true;try{await save();$('editor').close();await refresh();notice('Changes saved.');}catch(e){$('editor-error').textContent=e.message;}finally{b.disabled=false;}};$('editor').showModal();}
function editText(r){dialog('Edit memory text','<label for="memory-text">Memory text</label><textarea id="memory-text"></textarea>',async()=>{const result=await api('/api/memory/'+r.memory_id+'/edit',{text:$('memory-text').value});if(result.status!=='updated')throw Error(result.reason||result.status);});$('memory-text').value=r.text;}
function editRelations(r){
  let tags=[...r.tags],links=[...r.links];
  const knownTags=[...new Set([...state.rows.flatMap(x=>x.tags||[]),...r.source_tags])].sort();
  dialog('Organize this memory',
    '<p class="muted">Select a tag or linked memory below. Source text stays unchanged.</p>'+
    '<label for="tag-lookup">Find or create a tag</label>'+
    '<input id="tag-lookup" type="search" autocomplete="off" aria-controls="tag-results" placeholder="Filter tags or type a new name">'+
    '<div id="tag-results" class="lookup-results" role="group" aria-label="Tag choices"></div>'+
    '<p class="meta">Selected tags</p><div id="chosen-tags" class="chips"></div>'+
    '<label for="link-lookup">Find a memory to link</label>'+
    '<input id="link-lookup" type="search" autocomplete="off" aria-controls="link-results" placeholder="Filter by subject, text or ID">'+
    '<div id="link-results" class="lookup-results" role="group" aria-label="Memory choices"></div>'+
    '<p class="meta">Selected links</p><div id="chosen-links" class="chips"></div>',
    async()=>{await api('/api/memory/'+r.memory_id+'/metadata',{tags,links,revision:r.metadata_revision});});
  function redraw(){
    $('chosen-tags').replaceChildren(...tags.map(t=>button('#'+t+' ×',()=>{tags=tags.filter(x=>x!==t);redraw();},'chip')));
    $('chosen-links').replaceChildren(...links.map(id=>button(human(state.rows.find(x=>x.memory_id===id)?.subject||id)+' ×',()=>{links=links.filter(x=>x!==id);redraw();},'chip')));
    if(!tags.length)$('chosen-tags').textContent='None selected';
    if(!links.length)$('chosen-links').textContent='None selected';
    tagLookup();memoryLookup();
  }
  function addTag(t){tags.push(t);$('tag-lookup').value='';redraw();$('tag-lookup').focus();}
  function tagLookup(){
    const query=$('tag-lookup').value.trim().replace(/^#/,'');
    const matches=knownTags.filter(t=>!tags.includes(t)&&t.toLowerCase().includes(query.toLowerCase()));
    const host=$('tag-results');host.replaceChildren();
    for(const tag of matches)host.append(button('#'+tag+' · Select existing tag',()=>addTag(tag),'lookup-option'));
    if(query&&!knownTags.includes(query)&&!tags.includes(query)){
      if(/^[\p{L}\p{N}_-]{1,64}$/u.test(query))host.append(button('+ Create tag #'+query,()=>addTag(query),'lookup-option create-tag'));
      else host.append(document.createTextNode('Use letters, numbers, underscores or hyphens; up to 64 characters.'));
    }else if(!matches.length)host.append(document.createTextNode(query?'No unselected matching tags.':'No more existing tags. Type a name to create one.'));
  }
  function memoryLookup(){
    const query=$('link-lookup').value.toLowerCase();
    const found=state.rows.filter(x=>x.memory_id!==r.memory_id&&!links.includes(x.memory_id)&&[x.subject,x.text,x.memory_id,x.kind,x.path].join(' ').toLowerCase().includes(query));
    const host=$('link-results');host.replaceChildren();
    for(const record of found.slice(0,30)){
      const choice=button('',()=>{links.push(record.memory_id);redraw();$('link-lookup').focus();},'lookup-option');
      choice.innerHTML='<strong>'+esc(human(record.subject))+'</strong><span class="meta">'+esc(record.kind)+' · '+esc(record.writer)+' · '+esc(record.memory_id)+'</span><span class="lookup-preview">'+esc(record.text.slice(0,160))+'</span>';
      host.append(choice);
    }
    if(!found.length)host.textContent=query?'No matching memories. Try a different word.':'No other memories are available to link.';
    if(found.length>30){const hint=document.createElement('p');hint.className='meta';hint.textContent='Showing 30 of '+found.length+' matches. Type more to narrow the list.';host.append(hint);}
  }
  $('tag-lookup').oninput=tagLookup;$('tag-lookup').onfocus=tagLookup;
  $('link-lookup').oninput=memoryLookup;$('link-lookup').onfocus=memoryLookup;
  redraw();
}
function forget(r){dialog('Forget this memory?','<p>This deletes the stored record. Other memories are not merged or removed. Existing links may become unavailable. Cancel if you have not backed up something important.</p>',async()=>{const result=await api('/api/memory/'+r.memory_id+'/forget',{});if(result.status!=='forgotten')throw Error(result.status);state.selected=null;$('reader').innerHTML='<div class="empty"><h2>Memory removed</h2><p>Select another memory to continue.</p></div>';});}
function pendingBody(r){const p=r.payload;if(p?.type==='session'&&p.data)return ['investigated','learned','completed','next_steps'].map(k=>'<h3>'+esc(human(k.replace('_',' ')))+'</h3><ul>'+[].concat(p.data[k]||[]).map(x=>'<li>'+inline(x)+'</li>').join('')+'</ul>').join('');if(p?.type==='pattern')return '<h3>Project fact</h3><p>'+inline(p.project_fact_text)+'</p><h3>Preference rule</h3><p>'+inline(p.preference_rule_text)+'</p>';return markdown(r.text);}
function settingControl(s){const id='set-'+s.key;
  if(s.type==='bool')return '<div class="setting-checkbox"><input id="'+id+'" type="checkbox"'+(s.value?' checked':'')+'><label for="'+id+'" style="margin:0;text-transform:none;font-weight:500;color:var(--ink)">Enabled</label></div>';
  if(s.type==='select')return '<select id="'+id+'">'+s.options.map(o=>'<option value="'+esc(o)+'"'+(o===s.value?' selected':'')+'>'+esc(o)+'</option>').join('')+'</select>';
  if(s.type==='int')return '<input id="'+id+'" type="number" min="'+s.min+'" max="'+s.max+'" value="'+esc(s.value)+'">';
  if(s.type==='password')return '<input id="'+id+'" type="password" value="'+esc(s.value)+'" placeholder="Leave blank to keep unset" autocomplete="off">';
  return '<input id="'+id+'" type="text" value="'+esc(s.value)+'">';
}
function settingValue(s){const el=$('set-'+s.key);if(s.type==='bool')return el.checked;if(s.type==='int')return Number(el.value);return el.value;}
async function renderSettings(){
  const data=await api('/api/config');
  if(state.view!=='settings')return;
  const host=$('secondary');
  host.innerHTML='<div class="settings"><p class="muted">Changes apply to processes started after saving — restart the worker, dashboard or exporter to pick them up.</p><div class="settings-toolbar"><p class="meta" id="settings-status">Loaded current configuration.</p><button class="primary" id="settings-save">Save changed settings</button></div></div>';
  const container=host.querySelector('.settings');
  for(const g of data.groups){
    const rows=data.settings.filter(s=>s.group===g.key);
    if(!rows.length)continue;
    const group=document.createElement('section');group.className='settings-group';
    group.innerHTML='<h3>'+esc(g.label)+'</h3>'+rows.map(s=>
      '<div class="setting-row" data-key="'+esc(s.key)+'">'+
        '<div class="setting-info"><span class="setting-label">'+esc(s.label)+'</span>'+
        (s.description?'<p class="meta">'+esc(s.description)+'</p>':'')+
        '<span class="setting-source'+(s.source==='file'?' from-file':'')+'">'+esc(s.source)+'</span></div>'+
        '<div class="setting-field">'+settingControl(s)+'</div>'+
      '</div>').join('');
    container.append(group);
  }
  // Only fields the user actually touches get submitted -- a value merely
  // *displayed* because it currently comes from an env var (a deliberate
  // one-off override, per the config-file docs) must not get silently baked
  // into the persistent file just because some other field was saved.
  const dirty=new Set();
  for(const s of data.settings){
    const el=$('set-'+s.key);
    el.addEventListener('input',()=>dirty.add(s.key));
    el.addEventListener('change',()=>dirty.add(s.key));
  }
  $('settings-save').onclick=()=>safe(async()=>{
    if(!dirty.size){notice('No changes to save.');return;}
    const payload={};for(const key of dirty){const s=data.settings.find(x=>x.key===key);payload[key]=settingValue(s);}
    await api('/api/config',payload);
    notice('Settings saved. Restart the affected process to pick them up.');
    await renderSettings();
  });
}
async function showView(view){state.view=view;state.request++;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('library').hidden=view!=='library';$('secondary').hidden=view==='library';$('heading').textContent=({library:'Memory library',review:'Review & history',conflicts:'Potential conflicts',audit:'Vault health',settings:'Settings'})[view];notice('');if(view==='library'){await refresh();return;}const host=$('secondary');host.innerHTML='<p class="muted">Loading…</p>';
if(view==='settings'){await renderSettings();return;}
if(view==='review'){const rows=await api('/api/pending?history=1');if(state.view!==view)return;host.innerHTML='<p class="muted">Review proposed memories before they become part of your vault.</p>';for(const status of [...new Set([...reviewStatuses,...rows.map(r=>r.status)])]){const group=rows.filter(r=>r.status===status);const heading=document.createElement('h2');heading.textContent=human(status)+' · '+group.length;host.append(heading);for(const r of group){const card=document.createElement('article');card.className='review-card';card.innerHTML='<span class="kind">'+esc(r.kind)+'</span><h3>'+esc(human(r.subject))+'</h3><div class="meta">'+esc(r.writer)+' · '+esc(r.proposal_id)+'</div><div class="body-copy">'+pendingBody(r)+'</div>';if(r.note)card.insertAdjacentHTML('beforeend','<p>'+esc(r.note)+'</p>');if(status==='pending'){const footer=document.createElement('footer');for(const action of ['approve','reject'])footer.append(button(human(action),async()=>{const result=await api('/api/pending/'+r.proposal_id+'/'+action,{});if(!['approved','rejected','stored','stored_without_project_link','duplicate'].includes(result.status))throw Error(result.reason||result.status);await refresh();await showView('review');},action==='approve'?'primary':''));card.append(footer);}host.append(card);}}}
if(view==='conflicts'){const groups=await api('/api/conflicts');if(state.view!==view)return;host.innerHTML='<p class="muted">These records share an identity. Review the facts before choosing which to keep current.</p>';if(!groups.length)host.insertAdjacentHTML('beforeend','<h2>No potential conflicts found.</h2>');for(const g of groups){const card=document.createElement('article');card.className='review-card';card.innerHTML='<h2>'+esc(human(g.subject))+'</h2>';for(const r of g.memories||g.records||[]){const div=document.createElement('div');div.innerHTML='<div class="body-copy">'+markdown(r.text)+'</div><p class="meta">'+esc(r.writer)+' · '+esc(r.date)+'</p>';div.append(button('Keep this one…',()=>dialog('Keep this memory current?','<p>Other conflicting records for this identity will be marked superseded, not deleted.</p>',async()=>{await api('/api/conflict/resolve',{keep_id:r.memory_id});await showView('conflicts');})));card.append(div);}host.append(card);}}
if(view==='audit'){const result=await api('/api/audit');if(state.view!==view)return;host.innerHTML='<h2>'+ (result.healthy?'Your vault checks passed.':'Your vault needs attention.')+'</h2><p class="muted">Checks stored files against the search index. This does not change your memories.</p>';const dl=document.createElement('dl');for(const [k,v]of Object.entries(result)){const row=document.createElement('div');row.className='audit-row';const dt=document.createElement('dt');dt.textContent=k.replaceAll('_',' ');const dd=document.createElement('dd');dd.textContent=typeof v==='object'?JSON.stringify(v,null,2):String(v);dd.style.whiteSpace='pre-wrap';row.append(dt,dd);dl.append(row);}host.append(dl);}}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>safe(()=>showView(b.dataset.view));
for(const id of ['search','kind','tag-filter','date-on','date-from','date-to'])$(id).addEventListener('input',renderList);
$('clear-date').onclick=()=>{$('date-on').value='';$('date-from').value='';$('date-to').value='';renderList();};
$('refresh').onclick=()=>safe(()=>showView(state.view));
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();if(state.view==='library')$('search').focus();}});
function applyTheme(){
const dark=$('dark-mode').checked,accessible=$('colorblind-mode').checked;
document.documentElement.dataset.theme=(accessible?'colorblind-':'')+(dark?'dark':'light');
try{localStorage.setItem('memory-hub-appearance',JSON.stringify({dark,accessible}));}catch{}
}
let appearance={dark:window.matchMedia('(prefers-color-scheme: dark)').matches,accessible:false};
try{const saved=JSON.parse(localStorage.getItem('memory-hub-appearance'));if(saved&&typeof saved.dark==='boolean'&&typeof saved.accessible==='boolean')appearance=saved;}catch{}
$('dark-mode').checked=appearance.dark;$('colorblind-mode').checked=appearance.accessible;
$('dark-mode').onchange=applyTheme;$('colorblind-mode').onchange=applyTheme;applyTheme();
safe(refresh);
