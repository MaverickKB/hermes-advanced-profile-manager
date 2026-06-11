let state={profiles:[],facets:{},workflows:{domains:[],roles:[],tasks:[],topology_modes:[]},library:{domains:[],roles:[],skill_groups:[]},active:null,detail:null,dirty:false,currentText:'',lastChangeSet:null,lastChangeSetSource:'',caches:{}};
let skillState={catalog:[],assigned:new Set(),initialAssigned:new Set(),query:'',category:'',showAssignedOnly:false};
let identityState={file:null};
let groupState={selected:null,view:null};
let teamState={specialists:[]};
const $=sel=>document.querySelector(sel);
const $$=sel=>Array.from(document.querySelectorAll(sel));

async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const t=await r.text();let j={};try{j=JSON.parse(t)}catch{j={raw:t}}if(!r.ok)throw new Error(j.error||r.statusText);return j}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg,kind=''){console.log(msg);const old=$('.toast');if(old)old.remove();const d=document.createElement('div');d.className='toast '+kind;d.textContent=msg;document.body.appendChild(d);setTimeout(()=>d.remove(),4200)}
function kv(rows){return rows.map(([k,v])=>`<div><b>${esc(k)}</b><span>${esc(v??'—')}</span></div>`).join('')}
function okBadge(ok){return ok===true?'<span class="pill good">ok</span>':ok===false?'<span class="pill bad">fail</span>':'<span class="pill">n/a</span>'}

/* ---------------------------------------------------------------- dialogs */
function openModal({title,body,confirmLabel='Confirm',cancelLabel='Cancel',danger=false,hideCancel=false}){
  return new Promise(resolve=>{
    const dlg=$('#app-modal');
    $('#modal-title').textContent=title;
    $('#modal-body').innerHTML=body;
    const confirmBtn=$('#modal-confirm'),cancelBtn=$('#modal-cancel');
    confirmBtn.textContent=confirmLabel;confirmBtn.className=danger?'danger':'primary';
    cancelBtn.textContent=cancelLabel;cancelBtn.style.display=hideCancel?'none':'';
    const close=val=>{dlg.close();confirmBtn.onclick=null;cancelBtn.onclick=null;dlg.oncancel=null;resolve(val)};
    confirmBtn.onclick=()=>close(true);
    cancelBtn.onclick=()=>close(false);
    dlg.oncancel=e=>{e.preventDefault();close(false)};
    dlg.showModal();
    const first=$('#modal-body input,#modal-body select,#modal-body textarea');if(first)first.focus();
  });
}
async function confirmModal(title,message,opts={}){
  return openModal({title,body:`<p class="modal-msg">${message}</p>${opts.detail?`<div class="modal-detail">${opts.detail}</div>`:''}`,confirmLabel:opts.confirmLabel||'Confirm',danger:opts.danger!==false});
}
async function formModal(title,bodyHTML,confirmLabel='Save'){
  const ok=await openModal({title,body:bodyHTML,confirmLabel,danger:false});
  if(!ok)return null;
  const out={};
  $$('#modal-body [data-field]').forEach(el=>{out[el.dataset.field]=el.type==='checkbox'?el.checked:el.value});
  return out;
}
async function infoModal(title,bodyHTML){return openModal({title,body:bodyHTML,confirmLabel:'Close',hideCancel:true,danger:false})}

/* ------------------------------------------------------------ chip fields */
function initChipField(el,values,suggestions){
  el._values=Array.from(values||[]);
  const listId='dl-'+Math.random().toString(36).slice(2,8);
  const render=()=>{
    const head=el.querySelector('b')?.outerHTML||'';const sub=el.querySelector('small')?.outerHTML||'';
    el.innerHTML=`${head}${sub}
      <div class="chip-wrap">${el._values.map(v=>`<span class="chip-item">${esc(v)}<button data-chip-rm="${esc(v)}" title="Remove">×</button></span>`).join('')}
      <input class="chip-input" list="${listId}" placeholder="add…">
      <datalist id="${listId}">${(suggestions||[]).map(s=>`<option value="${esc(s)}">`).join('')}</datalist></div>`;
    el.querySelectorAll('[data-chip-rm]').forEach(b=>b.onclick=()=>{el._values=el._values.filter(v=>v!==b.dataset.chipRm);render()});
    const input=el.querySelector('.chip-input');
    const commit=()=>{const v=input.value.trim();if(v&&!el._values.includes(v)){el._values.push(v);render();el.querySelector('.chip-input').focus()}};
    input.onkeydown=e=>{if(e.key==='Enter'||e.key===','){e.preventDefault();commit()}};
    input.onchange=commit;input.onblur=()=>{if(input.value.trim())commit()};
  };
  render();
  el._get=()=>el._values.slice();
}

/* ----------------------------------------------------------- state/profiles */
async function loadState(){
  const data=await api('/api/state');
  state.profiles=data.profiles||[];state.facets=data.facets||{};state.workflows=data.workflows||{};state.library=data.library||state.library;
  $('#profile-count').textContent=state.profiles.length;
  fillFacetFilters();renderProfiles();fillCreateBase();fillSharedSelectors();renderLibrary();
  if(!state.active&&state.profiles[0])selectProfile(state.profiles.find(p=>p.name==='default')?.name||state.profiles[0].name);
}
function optionList(values,current=''){return (values||[]).map(v=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(v)}</option>`).join('')}
function fillFacetFilters(){
  $('#domain-filter').innerHTML='<option value="">All domains</option>'+optionList(state.facets.domains||[]);
  $('#role-filter').innerHTML='<option value="">All roles</option>'+optionList(state.facets.roles||[]);
  $('#risk-filter').innerHTML='<option value="">All risk levels</option>'+optionList(state.facets.risks||[]);
}
function profileOptions(selected){return state.profiles.map(p=>`<option value="${esc(p.name)}" ${p.name===selected?'selected':''}>${esc(p.name)}</option>`).join('')}
function fillSharedSelectors(){
  $('#purpose-domain').innerHTML=optionList(state.workflows.domains||[],'profile-management');
  $('#purpose-role').innerHTML=optionList(state.workflows.roles||[],'specialist');
  $('#purpose-target').innerHTML=profileOptions(state.active);
  $('#team-primary').innerHTML=profileOptions(state.active);
  $('#identity-copy-source').innerHTML='<option value="default">default (hermes home)</option>'+profileOptions('');
  $('#auth-copy-source').innerHTML='<option value="default">default (hermes home)</option>'+state.profiles.filter(p=>p.name!==state.active).map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  $('#env-copy-source').innerHTML='<option value="global">global (~/.hermes/.env)</option>'+state.profiles.filter(p=>p.name!==state.active).map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  $('#group-preview-target').textContent=state.active||'active profile';
}
function profileMatchesFilters(p){
  const q=($('#profile-filter').value||'').toLowerCase();const m=p.metadata||{};
  if(q&&!(`${p.name} ${m.purpose||''} ${(m.tags||[]).join(' ')}`.toLowerCase().includes(q)))return false;
  if($('#domain-filter').value&&!((m.domains||[]).includes($('#domain-filter').value)))return false;
  if($('#role-filter').value&&m.role!==$('#role-filter').value)return false;
  if($('#risk-filter').value&&m.risk!==$('#risk-filter').value)return false;
  return true;
}
function renderProfiles(){
  const list=$('#profile-list');list.innerHTML='';
  state.profiles.filter(profileMatchesFilters).forEach(p=>{const m=p.metadata||{};const b=document.createElement('button');b.className='profile'+(p.name===state.active?' active':'');b.innerHTML=`<strong>${esc(p.name)}</strong><small>${esc(m.domain||'general')} · ${esc(m.role||'profile')} · ${esc(m.risk||'unknown')}</small><em>${esc(m.purpose||'No purpose inferred')}</em>`;b.onclick=()=>selectProfile(p.name);list.appendChild(b)});
}
function fillCreateBase(){const s=$('#create-base');s.innerHTML='<option value="">Blank profile</option>'+state.profiles.map(p=>`<option value="${esc(p.name)}">Clone ${esc(p.name)}</option>`).join('')}

async function selectProfile(name){
  if(state.dirty&&!await confirmModal('Discard draft?','You have unsaved config draft changes for '+esc(state.active)+'. Discard them and switch to '+esc(name)+'?',{confirmLabel:'Discard and switch'}))return;
  state.active=name;state.caches={};identityState.file=null;delState.view=null;delState.draft=null;chState.view=null;renderProfiles();fillSharedSelectors();
  state.detail=await api('/api/profiles/'+encodeURIComponent(name));
  state.currentText=state.detail.config_text||'';state.dirty=false;
  hydrateSkillState(state.detail.skills||{skills:[]});
  renderDetail();
  const activeTab=$('.tabs button.active')?.dataset.tab||'overview';
  loadTab(activeTab,true);
}
function renderDetail(){
  const d=state.detail;if(!d)return;const v=d.validation||{};const sum=v.summary||{};
  $('#active-title').textContent=d.name;$('#active-subtitle').textContent=(d.metadata?.purpose||d.config_path);
  $('#provider-count').textContent=sum.provider_count||0;$('#skill-count').textContent=skillState.assigned.size;$('#issue-count').textContent=(v.issues||[]).length;
  $('#dirty').textContent=state.dirty?'dirty draft':'clean';$('#config-editor').value=state.currentText;
  renderSummary(sum,d);renderIssues(v.issues||[],'#issues');renderSkills();renderBackups(d.backups||[]);renderAudit(d.audit||[]);
}
function renderSummary(sum,d){
  const m=d.metadata||{};
  $('#summary').innerHTML=kv([['Purpose',m.purpose],['Domain',(m.domains||[]).join(', ')],['Role',m.role],['Risk',m.risk],['Config path',d.config_path],['Model provider',sum.model_provider],['Default model',sum.model_default],['Providers',sum.provider_count],['Installed skills',skillState.catalog.length],['Assigned skills',skillState.assigned.size],['MCP servers',sum.mcp_count],['Enabled toolsets',(sum.toolsets||[]).join(', ')],['Disabled toolsets',(sum.disabled_toolsets||[]).join(', ')]]);
}
function renderIssues(issues,sel){$(sel).innerHTML=issues.length?issues.map(i=>`<div class="issue ${esc(i.severity)}"><strong>${esc(i.severity)} · ${esc(i.scope)}</strong><br>${esc(i.message)}</div>`).join(''):'<div class="issue"><strong>No validation issues found.</strong><br>Draft parses and passes current local checks.</div>'}

/* ------------------------------------------------------------------- tabs */
const TAB_LOADERS={
  overview:()=>renderReadiness(state.caches.readiness),
  purpose:loadIntent,
  identity:loadIdentity,
  domains:()=>refreshLibrary(),
  groups:()=>loadGroups(true),
  toolsets:loadToolsets,
  mcp:loadMcp,
  providers:loadProviders,
  authenv:loadAuthEnv,
  team:(force)=>{renderTeam();return loadDelegation(force)},
  channels:loadChannels,
  changeset:renderChangeSet,
  raw:loadRaw,
};
function showTab(id){$$('.tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===id));$$('.panel').forEach(p=>p.classList.toggle('active',p.id===id));loadTab(id,false)}
function loadTab(id,force){const fn=TAB_LOADERS[id];if(fn){Promise.resolve(fn(force)).catch(err=>toast('Load failed: '+err.message,'error'))}}

/* --------------------------------------------------------------- overview */
async function runReadiness(live){
  if(!state.active)return;
  $('#readiness').innerHTML='<p class="muted">Running '+(live?'live':'quick')+' checks…</p>';$('#readiness').classList.remove('empty');
  const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/readiness?live='+(live?'1':'0'));
  state.caches.readiness=r;renderReadiness(r);
}
function renderReadiness(r,sel='#readiness'){
  const el=$(sel);if(!el)return;
  if(!r){el.classList.add('empty');el.innerHTML='No readiness check run yet. <b>Quick check</b> reads config state; <b>Run live checks</b> also tests routes and MCP servers.';return}
  el.classList.remove('empty');
  const cls=r.verdict==='ready'?'good':r.verdict==='ready-with-warnings'?'warn':'bad';
  el.innerHTML=`
    <div class="verdict ${cls}"><strong>${esc(r.headline)}</strong><small>${esc(r.verdict)} · ${r.live?'live evidence':'offline evidence'}</small></div>
    <div class="evidence">${(r.evidence||[]).map(e=>`<div class="evidence-row">${okBadge(e.ok)}<b>${esc(e.label)}</b><span>${esc(e.detail)}</span></div>`).join('')}</div>
    ${(r.blockers||[]).length?`<div class="issue error"><strong>Blockers</strong><br>${r.blockers.map(esc).join('<br>')}</div>`:''}
  `;
}

/* ---------------------------------------------------------------- purpose */
async function loadIntent(force){
  if(state.caches.intent&&!force)return renderIntent(state.caches.intent);
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/intent');
  state.caches.intent=j;renderIntent(j);
}
function renderIntent(j){
  const i=j.intent||{};
  $('#intent-view').innerHTML=kv([['Profile',i.profile],['Role',i.role],['Domain',i.domain],['Mission',i.mission],['Tasks',(i.tasks||[]).join(', ')],['Success criteria',(i.success_criteria||[]).join('; ')],['Forbidden',(i.forbidden||[]).join('; ')],['Max risk',(i.authority_boundary||{}).max_risk],['Evidence required',(i.evidence_required||[]).join(', ')],['Confidence',i.confidence],['Source',i.source]]);
}
async function generatePurposePlan(){
  const payload={
    domain:$('#purpose-domain').value,role:$('#purpose-role').value,risk:$('#purpose-risk').value,
    tasks:($('#purpose-tasks').value||'').split(',').map(x=>x.trim()).filter(Boolean),
    target_profile:$('#purpose-target').value||state.active,
  };
  const plan=await api('/api/workflows/purpose-plan',{method:'POST',body:JSON.stringify(payload)});
  state.lastChangeSet=plan.change_set;state.lastChangeSetSource='purpose plan for '+payload.target_profile;
  renderPurposePlan(plan);renderChangeSet();toast('Generated profile ChangeSet — review on the ChangeSet tab');
}
function renderPurposePlan(plan){
  const rec=plan.recommended||{};const cs=plan.change_set||{};const findings=cs.findings||[];
  const missing=(rec.missing_skills||[]);const present=(rec.present_skills||[]);
  $('#workflow-plan').classList.remove('empty');
  $('#workflow-plan').innerHTML=`
    <div class="plan-head"><div><strong>${esc(cs.title)}</strong><small>${esc(cs.summary)}</small></div><span class="badge">draft plan · no files written</span></div>
    <div class="plan-grid">
      <div><b>Recommended skills</b><p>${esc((rec.skills||[]).join(', ')||'—')}</p><small>${present.length} present${missing.length?`, ${missing.length} missing`:''}</small></div>
      <div><b>Toolsets</b><p>${esc((rec.toolsets||[]).join(', ')||'—')}</p></div>
      <div><b>Prompt/SOUL sections</b><p>${esc((rec.prompt_sections||[]).join(', ')||'—')}</p></div>
      <div><b>MCP</b><p>${esc((rec.mcp||[]).join(', ')||'No MCP changes required by this template')}</p></div>
    </div>
    ${missing.length?`<div class="issue warning"><strong>Missing skills</strong><br>${esc(missing.join(', '))}<br><small>Create a skill group on tab 5, install the skills, or continue with present skills only.</small></div>`:''}
    <div class="findings">${findings.map(f=>`<div class="issue ${esc(f.severity)}"><strong>${esc(f.severity)} · ${esc(f.scope)}</strong><br>${esc(f.message)}</div>`).join('')}</div>
    <div class="next-step"><b>Next step</b><span>Review the full ChangeSet on <a href="#" data-goto="changeset">the ChangeSet tab</a>, then apply the bounded sections there.</span></div>`;
  wireGotoLinks();
}
function wireGotoLinks(){$$('[data-goto]').forEach(a=>a.onclick=e=>{e.preventDefault();showTab(a.dataset.goto)})}

/* --------------------------------------------------------------- identity */
async function loadIdentity(force){
  if(state.caches.identity&&!force)return renderIdentity(state.caches.identity);
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/identity');
  state.caches.identity=j;renderIdentity(j);
}
function renderIdentity(j){
  $('#identity-list').innerHTML=(j.files||[]).map(f=>`
    <div class="row clickable ${identityState.file===f.name?'selected':''}" data-idfile="${esc(f.name)}">
      <strong>${esc(f.name)} <span class="pill ${f.status==='profile-local'?'good':f.status==='missing'?'bad':''}">${esc(f.status)}</span></strong>
      <small>${esc(f.active_path||f.profile_path)} · ${f.bytes} bytes</small>
    </div>`).join('');
  $$('[data-idfile]').forEach(el=>el.onclick=()=>openIdentityFile(el.dataset.idfile));
  $('#system-prompt-editor').value=j.system_prompt?.text||'';
}
async function openIdentityFile(name){
  identityState.file=name;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/identity/'+encodeURIComponent(name));
  $('#identity-editor-title').textContent=name+' — '+j.status+(j.status==='missing'?' (saving will create it)':'');
  $('#identity-editor').value=j.text||'';
  renderIdentity(state.caches.identity);
}
async function saveIdentityFile(){
  if(!identityState.file){toast('Select an identity file first.','error');return}
  if(!await confirmModal('Save '+identityState.file,'Write this content to <b>'+esc(state.active)+'/'+esc(identityState.file)+'</b>? A backup of the existing file is taken first.',{confirmLabel:'Save with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/identity/'+encodeURIComponent(identityState.file),{method:'POST',body:JSON.stringify({text:$('#identity-editor').value,confirm:true})});
  toast('Saved. Backup: '+(j.backup||'none'));await loadIdentity(true);
}
async function copyIdentityFile(){
  if(!identityState.file){toast('Select an identity file first.','error');return}
  const source=$('#identity-copy-source').value;
  if(!await confirmModal('Copy '+identityState.file,'Copy <b>'+esc(identityState.file)+'</b> from <b>'+esc(source)+'</b> into <b>'+esc(state.active)+'</b>? Existing file is backed up.',{confirmLabel:'Copy'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/identity/'+encodeURIComponent(identityState.file),{method:'POST',body:JSON.stringify({copy_from:source,confirm:true})});
  toast('Copied '+identityState.file+' from '+source);await loadIdentity(true);await openIdentityFile(identityState.file);
}
async function saveSystemPrompt(){
  if(!await confirmModal('Save system prompt','Write the system prompt into <b>'+esc(state.active)+'/config.yaml</b> (agent.system_prompt) with backup?',{confirmLabel:'Save with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/system-prompt',{method:'POST',body:JSON.stringify({text:$('#system-prompt-editor').value,confirm:true})});
  toast('System prompt saved. Backup: '+(j.backup||'none'));
}

/* ----------------------------------------------------- domains & roles */
async function refreshLibrary(){const lib=await api('/api/library');state.library=lib;renderLibrary()}
function renderLibrary(){
  const lib=state.library||{};
  $('#domain-list').innerHTML=(lib.domains||[]).map(d=>`
    <div class="row clickable" data-editdomain="${esc(d.name)}"><strong>${esc(d.name)} <span class="pill">${esc(d.source)}</span></strong><small>${esc(d.description||'')}</small>
    ${d.source!=='built-in'?`<div class="actions"><button class="mini" data-deldomain="${esc(d.name)}">Delete</button></div>`:''}</div>`).join('');
  $('#role-list').innerHTML=(lib.roles||[]).map(r=>`
    <div class="row clickable" data-editrole="${esc(r.name)}"><strong>${esc(r.name)} <span class="pill">${esc(r.source)}</span></strong><small>${esc(r.risk||'')} · ${esc(r.review||'')} · ${esc(r.description||'')}</small>
    ${r.source!=='built-in'?`<div class="actions"><button class="mini" data-delrole="${esc(r.name)}">Delete</button></div>`:''}</div>`).join('');
  $$('[data-editdomain]').forEach(el=>el.onclick=e=>{if(e.target.dataset.deldomain)return;const d=(lib.domains||[]).find(x=>x.name===el.dataset.editdomain);$('#domain-name').value=d.name;$('#domain-desc').value=d.description||''});
  $$('[data-editrole]').forEach(el=>el.onclick=e=>{if(e.target.dataset.delrole)return;const r=(lib.roles||[]).find(x=>x.name===el.dataset.editrole);$('#role-name').value=r.name;$('#role-risk').value=r.risk||'read-only';$('#role-desc').value=r.description||''});
  $$('[data-deldomain]').forEach(b=>b.onclick=async e=>{e.stopPropagation();if(!await confirmModal('Delete domain','Delete domain <b>'+esc(b.dataset.deldomain)+'</b> from the library?'))return;const j=await api('/api/library/domains',{method:'POST',body:JSON.stringify({name:b.dataset.deldomain,delete:true})});state.library.domains=j.domains;renderLibrary();fillSharedSelectors()});
  $$('[data-delrole]').forEach(b=>b.onclick=async e=>{e.stopPropagation();if(!await confirmModal('Delete role','Delete role <b>'+esc(b.dataset.delrole)+'</b> from the library?'))return;const j=await api('/api/library/roles',{method:'POST',body:JSON.stringify({name:b.dataset.delrole,delete:true})});state.library.roles=j.roles;renderLibrary();fillSharedSelectors()});
}
async function saveDomain(){
  const name=$('#domain-name').value.trim();if(!name){toast('Domain name required','error');return}
  const j=await api('/api/library/domains',{method:'POST',body:JSON.stringify({name,description:$('#domain-desc').value})});
  state.library.domains=j.domains;state.workflows.domains=Array.from(new Set([...(state.workflows.domains||[]),name])).sort();
  renderLibrary();fillSharedSelectors();toast('Domain saved: '+name+' — available in the Purpose flow now.');
}
async function saveRole(){
  const name=$('#role-name').value.trim();if(!name){toast('Role name required','error');return}
  const j=await api('/api/library/roles',{method:'POST',body:JSON.stringify({name,risk:$('#role-risk').value,description:$('#role-desc').value})});
  state.library.roles=j.roles;state.workflows.roles=Array.from(new Set([...(state.workflows.roles||[]),name])).sort();
  renderLibrary();fillSharedSelectors();toast('Role saved: '+name);
}

/* ------------------------------------------------------------ skill groups */
async function loadGroups(force){
  if(state.caches.groups&&!force)return renderGroups();
  const view=await api('/api/profiles/'+encodeURIComponent(state.active)+'/skill-groups');
  state.caches.groups=view;groupState.view=view;
  renderGroups();
}
function groupsSuggestions(){
  return {
    skills:skillState.catalog.map(s=>s.name).sort(),
    toolsets:(state.caches.toolsets?.toolsets||[]).map(t=>t.name),
    mcp:(state.caches.mcp?.servers||[]).map(s=>s.name),
    groups:(groupState.view?.groups||[]).map(g=>g.name),
  };
}
function renderGroups(){
  const view=groupState.view||{groups:[],enabled:[],starter_templates:[]};
  const groups=view.groups||[];
  const rtPill=runtimePill(view.runtime);
  $('#group-list').innerHTML=(rtPill?'<div style="margin-bottom:8px">'+rtPill+'</div>':'')+(groups.length?groups.map(g=>{
    const risk=g.risk_level||'medium';
    return `
    <div class="row clickable ${groupState.selected===g.name?'selected':''}" data-group="${esc(g.name)}">
      <strong>${esc(g.title||g.name)} <span class="pill">v${g.version||1}</span>
        <span class="pill ${risk==='low'?'good':risk==='critical'||risk==='high'?'bad':''}">${esc(risk)} risk</span>
        <span class="pill">${esc(g.source)}</span>
        ${g.declared_in_config?'<span class="pill good">enabled in '+esc(state.active)+'</span>':''}
        ${g.missing_required_skills?.length?'<span class="pill warnpill">'+g.missing_required_skills.length+' missing skills</span>':''}
      </strong>
      <small>${esc(g.description||'no description')}</small>
      <small>${(g.required_skills||[]).length} required · ${(g.recommended_skills||[]).length} recommended skills · toolsets: ${esc((g.required_toolsets||[]).join(', ')||'none')} · MCP: ${esc((g.mcp_dependencies||[]).join(', ')||'none')}</small>
      <div class="actions">
        <button class="mini ${g.declared_in_config?'':'accent'}" data-grouptoggle="${esc(g.name)}" data-on="${g.declared_in_config?'1':''}">${g.declared_in_config?'Disable for '+esc(state.active):'Enable for '+esc(state.active)}</button>
      </div>
    </div>`}).join(''):`
    <div class="empty-state">
      <p><b>No skill groups exist yet.</b></p>
      <p class="muted">Groups are YAML manifests in <code>${esc(view.storage?.custom_dir||'~/.hermes/skill_groups')}</code> — shared with Hermes itself. Start from a starter template:</p>
      <div class="actions wrap">${(view.starter_templates||[]).map(t=>`<button data-template="${esc(t)}">+ ${esc(t)}</button>`).join('')}</div>
      <p class="muted">…or click <b>New group</b> to build one from scratch.</p>
    </div>`)
    +((view.unknown_declared||[]).length?`<div class="issue error"><strong>Declared but missing</strong><br>${esc(state.active)} declares ${esc(view.unknown_declared.join(', '))} in config.yaml but no manifest exists. Create it or remove the reference.</div>`:'')
    +(groups.length?`<div class="actions wrap" style="margin-top:8px">${(view.starter_templates||[]).filter(t=>!groups.some(g=>g.name===t)).map(t=>`<button class="mini" data-template="${esc(t)}">+ template: ${esc(t)}</button>`).join('')}</div>`:'');
  $$('[data-group]').forEach(el=>el.onclick=e=>{if(e.target.closest('button'))return;openGroup(el.dataset.group)});
  $$('[data-grouptoggle]').forEach(b=>b.onclick=()=>toggleGroupEnabled(b.dataset.grouptoggle,!b.dataset.on));
  $$('[data-template]').forEach(b=>b.onclick=()=>createFromTemplate(b.dataset.template));
}
function showGroupForm(show){$('#group-form').classList.toggle('hidden',!show);$('#group-editor-hint').textContent=show?'':'Select a group on the left, or click New group to start one.'}
function openGroup(name){
  groupState.selected=name;
  const g=(groupState.view?.groups||[]).find(x=>x.name===name);
  if(!g)return;
  $('#group-editor-title').textContent=(g.title||g.name)+' — '+g.source;
  showGroupForm(true);
  fillGroupForm(g);
  renderGroups();
  $('#group-preview-out').classList.add('empty');$('#group-preview-out').innerHTML='Preview shows exactly what applying this group to '+esc(state.active)+' would change.';
}
function fillGroupForm(g){
  $('#gf-name').value=g.name||'';$('#gf-name').disabled=Boolean(g.name&&groupState.selected);
  $('#gf-desc').value=g.description||'';
  $('#gf-risk').value=['low','medium','high','critical'].includes(g.risk_level)?g.risk_level:'medium';
  $('#gf-load').value=g.prompt_policy?.load_behavior||'lazy-index';
  $('#gf-dryrun').checked=g.dry_run_required!==false;
  $('#gf-export').checked=g.exportable!==false;
  $('#gf-authority').value=g.authority_posture||'';
  $('#gf-prompt').value=typeof g.prompt_policy==='string'?g.prompt_policy:(g.prompt_policy?.note||'');
  const sugg=groupsSuggestions();
  $$('.chip-field').forEach(el=>{
    const field=el.dataset.field;
    initChipField(el,g[field]||[],sugg[el.dataset.suggest]||[]);
  });
  $('#group-editor').value=JSON.stringify(g,null,2);
}
function collectGroupForm(){
  const out={
    name:$('#gf-name').value.trim(),
    description:$('#gf-desc').value.trim(),
    risk_level:$('#gf-risk').value,
    dry_run_required:$('#gf-dryrun').checked,
    exportable:$('#gf-export').checked,
    prompt_policy:{load_behavior:$('#gf-load').value,note:$('#gf-prompt').value.trim()},
  };
  $$('.chip-field').forEach(el=>{if(el._get)out[el.dataset.field]=el._get()});
  return out;
}
function newGroup(){
  groupState.selected=null;
  $('#group-editor-title').textContent='New skill group';
  showGroupForm(true);
  fillGroupForm({name:'',description:'',risk_level:'medium'});
  $('#gf-name').disabled=false;$('#gf-name').focus();
  renderGroups();
}
async function saveGroup(){
  const form=collectGroupForm();
  if(!form.name){toast('Group needs a name (lowercase, dashes).','error');return}
  const j=await api('/api/library/skill-groups',{method:'POST',body:JSON.stringify(form)});
  groupState.selected=form.name;
  await loadGroups(true);openGroup(form.name);
  toast('Saved '+form.name+' (v'+j.group.version+') to '+(groupState.view?.storage?.custom_dir||'~/.hermes/skill_groups'));
}
async function createFromTemplate(template){
  if(!await confirmModal('Create from template','Create skill group <b>'+esc(template)+'</b> from the built-in starter template? It is written to <code>~/.hermes/skill_groups/</code> and fully editable afterwards.',{confirmLabel:'Create group',danger:false}))return;
  await api('/api/library/skill-groups',{method:'POST',body:JSON.stringify({from_template:template})});
  groupState.selected=template;await loadGroups(true);openGroup(template);
  toast('Created '+template+' — adjust required skills/toolsets and save.');
}
async function toggleGroupEnabled(name,enabled){
  if(!await confirmModal((enabled?'Enable':'Disable')+' group','<b>'+esc(name)+'</b> will be '+(enabled?'added to':'removed from')+' <code>skill_groups.enabled</code> in <b>'+esc(state.active)+'/config.yaml</b> with backup.',{confirmLabel:enabled?'Enable':'Disable'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/skill-groups/'+encodeURIComponent(name)+'/enable',{method:'POST',body:JSON.stringify({enabled,confirm:true})});
  await loadGroups(true);
  toast(name+' '+(enabled?'enabled':'disabled')+' for '+state.active);
}
async function duplicateGroup(){
  if(!groupState.selected){toast('Select a group first','error');return}
  const form=await formModal('Duplicate '+groupState.selected,'<label>New group name <input data-field="name" placeholder="adapted-name"></label>','Duplicate');
  if(!form||!form.name)return;
  await api('/api/library/skill-groups',{method:'POST',body:JSON.stringify({name:form.name,duplicate_from:groupState.selected})});
  groupState.selected=form.name;await loadGroups(true);openGroup(form.name);toast('Duplicated as '+form.name);
}
async function deleteGroup(){
  if(!groupState.selected)return;
  if(!await confirmModal('Delete group','Delete the manifest for <b>'+esc(groupState.selected)+'</b> from <code>~/.hermes/skill_groups/</code>? Profiles that declare it will show a missing-manifest blocker.'))return;
  await api('/api/library/skill-groups',{method:'POST',body:JSON.stringify({name:groupState.selected,delete:true})});
  groupState.selected=null;showGroupForm(false);await loadGroups(true);
}
async function exportGroup(){
  if(!groupState.selected){toast('Select a group first','error');return}
  const manifest=await api('/api/library/skill-groups/'+encodeURIComponent(groupState.selected)+'/export');
  const blob=new Blob([manifest.manifest_yaml||JSON.stringify(manifest,null,2)],{type:'text/yaml'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=groupState.selected+'.skill-group.yaml';a.click();
  toast('Exported manifest (secrets excluded by design)');
}
async function importGroup(){
  const form=await formModal('Import skill group manifest','<p class="muted">Paste a manifest (YAML-exported JSON or Hermes YAML converted to JSON).</p><textarea data-field="manifest" class="mono" style="min-height:220px" placeholder=\'{"id": "group-name", ...}\'></textarea>','Import');
  if(!form||!form.manifest)return;
  let manifest;try{manifest=JSON.parse(form.manifest)}catch(e){toast('Invalid JSON: '+e.message,'error');return}
  await api('/api/library/skill-groups',{method:'POST',body:JSON.stringify({import_manifest:manifest})});
  await loadGroups(true);toast('Imported group');
}
async function previewGroup(){
  if(!groupState.selected){toast('Select a group first','error');return}
  const p=await api('/api/library/skill-groups/'+encodeURIComponent(groupState.selected)+'/preview',{method:'POST',body:JSON.stringify({profile:state.active})});
  const usage=await api('/api/library/skill-groups/'+encodeURIComponent(groupState.selected)+'/profiles',{method:'POST',body:JSON.stringify({})});
  $('#group-preview-out').classList.remove('empty');
  $('#group-preview-out').innerHTML=`
    <div class="plan-head"><div><strong>Apply ${esc(p.group)} → ${esc(p.profile)}</strong><small>${p.ready?'Ready to apply':'Not ready — see gaps'}${p.declared_in_config?' · declared in config':''}</small></div><span class="badge">preview only</span></div>
    <div class="plan-grid">
      <div><b>Skills to enable</b><p>${esc(p.skills_to_enable.join(', ')||'none')}</p></div>
      <div><b>Skills to disable (forbidden)</b><p>${esc(p.skills_to_disable.join(', ')||'none')}</p></div>
      <div><b>Missing required skills</b><p>${esc(p.missing_required_skills.join(', ')||'none')}</p></div>
      <div><b>Toolsets to add</b><p>${esc(p.toolsets_to_add.join(', ')||'none')}</p></div>
    </div>
    ${p.forbidden_toolsets_present.length?`<div class="issue warning"><strong>Forbidden toolsets enabled</strong><br>${esc(p.forbidden_toolsets_present.join(', '))}</div>`:''}
    <div class="plan-grid">
      <div><b>MCP dependencies</b><p>${esc((p.mcp_dependencies||[]).join(', ')||'none')}</p></div>
      <div><b>Risk level</b><p>${esc(p.risk_level||'')}</p></div>
      <div><b>Dry-run required</b><p>${p.dry_run_required?'yes':'no'}</p></div>
      <div><b>Profiles using this group</b><p>${(usage.profiles||[]).map(u=>`${esc(u.profile)}${u.declared?' (declared)':''}${u.satisfies?' ✓':''}`).join(', ')||'none'}</p></div>
    </div>
    <div class="actions"><button id="group-apply-skills" class="danger">Apply skill changes with backup</button></div>`;
  $('#group-apply-skills').onclick=async()=>{
    if(!await confirmModal('Apply group skills','Enable <b>'+p.skills_to_enable.length+'</b> and disable <b>'+p.skills_to_disable.length+'</b> skills on <b>'+esc(state.active)+'</b>? Config is backed up first.',{confirmLabel:'Apply with backup'}))return;
    p.skills_to_enable.forEach(s=>skillState.assigned.add(s));
    p.skills_to_disable.forEach(s=>skillState.assigned.delete(s));
    await saveSkillAssignment(true);
    toast('Group skill changes applied');
  };
}

/* ----------------------------------------------------------------- skills */
function hydrateSkillState(skillsPayload){skillState.catalog=skillsPayload.skills||[];skillState.assigned=new Set(skillState.catalog.filter(s=>s.enabled).map(s=>s.name));skillState.initialAssigned=new Set(skillState.assigned);const cats=Array.from(new Set(skillState.catalog.map(s=>s.category||'uncategorized'))).sort();$('#skill-category-filter').innerHTML='<option value="">All categories</option>'+cats.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')}
function skillMatches(s){const q=skillState.query.toLowerCase();const blob=[s.name,s.description,s.category,(s.tags||[]).join(' '),(s.required_toolsets||[]).join(' '),s.path].join(' ').toLowerCase();if(q&&!blob.includes(q))return false;if(skillState.category&&(s.category||'uncategorized')!==skillState.category)return false;if(skillState.showAssignedOnly&&!skillState.assigned.has(s.name))return false;return true}
function filteredSkills(){return skillState.catalog.filter(skillMatches)}
function isSkillsDirty(){if(skillState.assigned.size!==skillState.initialAssigned.size)return true;for(const x of skillState.assigned)if(!skillState.initialAssigned.has(x))return true;return false}
function skillCard(s,pane){
  const on=skillState.assigned.has(s.name);
  const req=(s.required_toolsets||[]).slice(0,4).map(t=>`<span>${esc(t)}</span>`).join('');
  const why=(s.why_selected||[]).map(w=>`<span class="why">${esc(w)}</span>`).join('');
  const arrow=pane==='available'
    ?`<button class="skill-toggle ${on?'remove':'add'}" data-skill="${esc(s.name)}" title="${on?'Already assigned — click to remove':'Assign skill →'}">${on?'✓':'→'}</button>`
    :`<button class="skill-toggle remove" data-skill="${esc(s.name)}" title="← Remove from assigned">←</button>`;
  return `<div class="skill ${on?'enabled':'disabled'}"><div class="skill-main">${arrow}<div><strong>${esc(s.name)}</strong><small>${esc(s.category||'uncategorized')} · ${Math.round((s.bytes||0)/1024)} KB</small><p>${esc(s.description||'')}</p>${req?`<div class="mini-chips">${req}</div>`:''}${why&&on?`<div class="mini-chips">${why}</div>`:''}</div></div></div>`;
}
function renderSkills(){
  const filtered=filteredSkills();
  const assigned=skillState.catalog.filter(s=>skillState.assigned.has(s.name)).sort((a,b)=>a.name.localeCompare(b.name));
  const addable=filtered.filter(s=>!skillState.assigned.has(s.name)).length;
  $('#assigned-count').textContent=skillState.assigned.size;$('#available-count').textContent=skillState.catalog.length;$('#skill-count').textContent=skillState.assigned.size;
  $('#skills-dirty').textContent=isSkillsDirty()?'dirty':'clean';$('#skills-dirty').classList.toggle('dirty',isSkillsDirty());
  $('#add-filtered').textContent=`Add ${addable} filtered…`;$('#add-filtered').disabled=!addable;
  $('#skills-list').innerHTML=filtered.length?filtered.slice(0,300).map(s=>skillCard(s,'available')).join(''):'<p class="muted">No skills match this filter.</p>';
  $('#assigned-list').innerHTML=assigned.length?assigned.map(s=>skillCard(s,'assigned')).join(''):'<p class="muted">No skills assigned. Search left and add a focused set.</p>';
  $$('[data-skill]').forEach(b=>b.onclick=()=>toggleSkill(b.dataset.skill));
}
function toggleSkill(name){if(skillState.assigned.has(name))skillState.assigned.delete(name);else skillState.assigned.add(name);renderSkills()}
async function addFiltered(){
  const toAdd=filteredSkills().filter(s=>!skillState.assigned.has(s.name)).map(s=>s.name);
  if(!toAdd.length)return;
  if(!await confirmModal('Add filtered skills','Add <b>'+toAdd.length+'</b> skill(s) to the draft assignment?',{detail:esc(toAdd.slice(0,30).join(', '))+(toAdd.length>30?'…':''),confirmLabel:'Add to draft',danger:false}))return;
  toAdd.forEach(n=>skillState.assigned.add(n));renderSkills();toast(`Added ${toAdd.length} skills to draft`);
}
async function clearAssigned(){
  if(!await confirmModal('Clear draft assignment','Remove all skills from the draft assignment? Nothing is written until Save.'))return;
  skillState.assigned.clear();renderSkills();
}
async function saveSkillAssignment(skipConfirm){
  const selected=Array.from(skillState.assigned).sort();
  const max=parseInt($('#max-enabled').value||'0',10)||undefined;
  if(max&&selected.length>max){toast(`Selected ${selected.length} skills but max is ${max}. Raise the guardrail or remove skills.`,'error');return}
  if(!skipConfirm&&!await confirmModal('Save skill assignment','Save <b>'+selected.length+'</b> assigned skills for <b>'+esc(state.active)+'</b>? This writes skills.disabled with backup + audit.',{confirmLabel:'Save with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/assign-skills',{method:'POST',body:JSON.stringify({selected,max_enabled:max})});
  hydrateSkillState(j.skills);renderSkills();toast('Saved skill assignment. Backup: '+(j.backup||'none'));
}

/* --------------------------------------------------------------- toolsets */
async function loadToolsets(force){
  if(state.caches.toolsets&&!force)return renderToolsets(state.caches.toolsets);
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/toolsets');
  state.caches.toolsets=j;renderToolsets(j);
}
function renderToolsets(j){
  $('#toolset-source').textContent='Registry source: '+(j.registry_source||'unknown');
  $('#toolset-list').innerHTML=(j.toolsets||[]).map(t=>`
    <details class="row">
      <summary><strong>${esc(t.name)}</strong>
        <span class="pill ${t.state==='enabled'?'good':t.state==='disabled'?'bad':''}">${esc(t.state)}</span>
        <span class="pill">${esc(t.risk)}</span>
        <span class="pill">${t.tool_count} tools</span>
        ${t.enabled_by.length?`<small>${esc(t.enabled_by.join(' · '))}</small>`:''}
      </summary>
      <div class="tool-table" data-tools-for="${esc(t.name)}">${(t.tools||[]).map(tool=>`<div class="tool-row pick"><label class="inline"><input type="checkbox" data-want="${esc(t.name)}::${esc(tool.name)}" checked></label><b>${esc(tool.name)}</b><span class="pill ${tool.risk==='read-only'?'good':''}">${esc(tool.risk)}</span><small>${esc(tool.source)}</small></div>`).join('')||'<p class="muted">Registry has no tool listing for this toolset.</p>'}
      ${t.tools.length?`<div class="actions"><button data-partial="${esc(t.name)}">Check partial selection</button><small class="muted" style="align-self:center">Untick tools you don't want, then check what Hermes can actually enforce.</small></div>`:''}
      <div id="partial-${esc(t.name)}"></div></div>
    </details>`).join('');
  $$('[data-partial]').forEach(b=>b.onclick=()=>planPartial(b.dataset.partial));
}
async function planPartial(toolset){
  const wanted=$$(`[data-want^="${toolset}::"]`).filter(i=>i.checked).map(i=>i.dataset.want.split('::')[1]);
  const plan=await api('/api/profiles/'+encodeURIComponent(state.active)+'/toolsets/partial-plan',{method:'POST',body:JSON.stringify({toolset,wanted_tools:wanted})});
  const el=document.getElementById('partial-'+toolset);
  el.innerHTML=`
    ${plan.applies_cleanly?'<div class="issue"><strong>Applies cleanly</strong><br>Your selection covers the whole toolset, so enabling it exposes exactly what you chose.</div>':plan.findings.map(f=>`<div class="issue ${esc(f.severity)}"><strong>${esc(f.severity)}</strong><br>${esc(f.message)}<br><small>${esc(f.recommendation||'')}</small></div>`).join('')}
    <small class="muted">${esc(state.caches.toolsets.partial_application_note||'')}</small>`;
}

/* -------------------------------------------------------------------- MCP */
async function loadMcp(force){
  if(state.caches.mcp&&!force)return renderMcp(state.caches.mcp);
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/mcp');
  state.caches.mcp=j;renderMcp(j);
}
function renderMcp(j){
  $('#mcp-list').innerHTML=(j.servers||[]).length?(j.servers||[]).map(s=>`
    <div class="row">
      <strong>${esc(s.name)} <span class="pill">${esc(s.transport)}</span> <span class="pill ${s.enabled?'good':'bad'}">${s.enabled?'enabled':'disabled'}</span></strong>
      <small>${esc(s.command?s.command+' '+s.args.join(' '):s.url)}</small>
      <small>Source: ${esc(s.provenance.config_key)} in ${esc(s.provenance.config_path)}</small>
      ${s.required_env_keys.length?`<small>Required env: ${esc(s.required_env_keys.join(', '))} (values never shown)</small>`:''}
      <div class="actions">
        <button data-mcptest="${esc(s.name)}">Test connection</button>
        <button data-mcptoggle="${esc(s.name)}" data-enabled="${s.enabled?'1':''}">${s.enabled?'Disable':'Enable'}</button>
      </div>
      <div id="mcptest-${esc(s.name)}"></div>
    </div>`).join(''):'<p class="muted">No MCP servers configured for this profile. Use <b>Add server…</b> to wire one in.</p>';
  $$('[data-mcptest]').forEach(b=>b.onclick=()=>testMcp(b.dataset.mcptest));
  $$('[data-mcptoggle]').forEach(b=>b.onclick=()=>toggleMcp(b.dataset.mcptoggle,!b.dataset.enabled));
}
async function testMcp(server){
  const el=document.getElementById('mcptest-'+server);el.innerHTML='<p class="muted">Testing…</p>';
  try{
    const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/mcp/'+encodeURIComponent(server)+'/test',{method:'POST',body:JSON.stringify({})});
    if(r.ok&&r.tools){
      el.innerHTML=`<div class="issue"><strong>Connected: ${r.tool_count} tools${r.server_info?.name?' · '+esc(r.server_info.name)+' '+esc(r.server_info.version||''):''}</strong></div>
      <div class="tool-table">${r.tools.map(t=>`<div class="tool-row"><b>${esc(t.name)}</b><span class="pill ${t.risk==='read/low'?'good':'warnpill'}">${esc(t.risk)}</span><small>${esc(t.description)}</small></div>`).join('')}</div>`;
    }else if(r.ok){
      el.innerHTML=`<div class="issue"><strong>Reachable</strong><br>HTTP status ${esc(r.status||'')}</div>`;
    }else{
      el.innerHTML=`<div class="issue error"><strong>Failed at ${esc(r.stage||'?')}</strong><br>${esc(JSON.stringify(r.error))}</div>`;
    }
  }catch(e){el.innerHTML=`<div class="issue error"><strong>Test failed</strong><br>${esc(e.message)}</div>`}
}
async function toggleMcp(server,enabled){
  if(!await confirmModal((enabled?'Enable':'Disable')+' MCP server','<b>'+esc(server)+'</b> will be '+(enabled?'enabled':'disabled')+' in <b>'+esc(state.active)+'/config.yaml</b> with backup.',{confirmLabel:enabled?'Enable':'Disable'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/mcp/'+encodeURIComponent(server)+'/enable',{method:'POST',body:JSON.stringify({enabled,confirm:true})});
  await loadMcp(true);toast('MCP server '+server+' '+(enabled?'enabled':'disabled'));
}
async function addMcp(){
  const form=await formModal('Add MCP server',`
    <label>Server name <input data-field="name" placeholder="my-mcp"></label>
    <label>Transport <select data-field="transport"><option value="stdio">stdio (command)</option><option value="url">http/sse (url)</option></select></label>
    <label>Command (stdio) <input data-field="command" placeholder="/path/to/binary"></label>
    <label>Args, comma-separated <input data-field="args" placeholder="mcp, --flag"></label>
    <label>URL (http/sse) <input data-field="url" placeholder="http://host:port/mcp"></label>
    <p class="muted">Env values belong in the profile .env (tab 10) as \${VAR} references — never inline here.</p>`,'Add with backup');
  if(!form||!form.name)return;
  const spec={command:form.transport==='stdio'?form.command:'',args:(form.args||'').split(',').map(x=>x.trim()).filter(Boolean),url:form.transport==='url'?form.url:'',enabled:true};
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/mcp/'+encodeURIComponent(form.name),{method:'POST',body:JSON.stringify({spec,confirm:true})});
  await loadMcp(true);toast('MCP server added: '+form.name);
}

/* ---------------------------------------------------------------- providers */
async function loadProviders(force){
  if(state.caches.providers&&!force){renderProviders(state.caches.providers);return}
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/providers');
  state.caches.providers=j;renderProviders(j);
  if(!state.detail.model_catalog)state.detail.model_catalog=await api('/api/profiles/'+encodeURIComponent(state.active)+'/models');
  renderRouteControls();
}
function renderProviders(j){
  $('#providers-list').innerHTML=(j.providers||[]).map(p=>`
    <div class="row">
      <strong>${esc(p.name)} ${p.configured?'':'<span class="pill">referenced only</span>'} ${p.auth_required?`<span class="pill ${p.auth_key_present?'good':'bad'}">${p.auth_key_present?'key present':'key missing: '+esc(p.key_env)}</span>`:'<span class="pill">managed auth</span>'}</strong>
      ${p.base_url?`<small>${esc(p.base_url)} · ${esc(p.api_mode||'default mode')}</small>`:''}
      <small>Usage: ${esc((p.usage||[]).join(' · ')||'unused')}</small>
      <small>Source: ${esc(p.provenance.config_key)}</small>
      <div class="actions">
        <button data-ptest="${esc(p.name)}">Test auth/models</button>
        ${p.default_model||p.base_url?`<button data-pcomp="${esc(p.name)}" data-model="${esc(p.default_model)}">Test completion</button>`:''}
      </div>
      <div id="ptest-${esc(p.name)}"></div>
    </div>`).join('')||'<p class="muted">No providers declared.</p>';
  $$('[data-ptest]').forEach(b=>b.onclick=()=>testProviderAuth(b.dataset.ptest));
  $$('[data-pcomp]').forEach(b=>b.onclick=()=>testProviderCompletion(b.dataset.pcomp,b.dataset.model));
}
async function testProviderAuth(name){
  const el=document.getElementById('ptest-'+name);el.innerHTML='<p class="muted">Polling models endpoint…</p>';
  const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/providers/'+encodeURIComponent(name)+'/test-auth',{method:'POST',body:JSON.stringify({})});
  el.innerHTML=r.ok?`<div class="issue"><strong>OK: ${r.model_count} models at ${esc(r.endpoint)}</strong><br><small>${esc((r.models||[]).slice(0,12).join(', '))}${(r.models||[]).length>12?'…':''}</small></div>`:`<div class="issue error"><strong>Failed</strong><br>${esc(r.error||'')}</div>`;
}
async function testProviderCompletion(name,model){
  const form=await formModal('Test completion on '+name,`<label>Model <input data-field="model" value="${esc(model||'')}" placeholder="model id"></label><p class="muted">Sends a 1-token "reply ok" request through this provider route.</p>`,'Run test');
  if(!form||!form.model)return;
  const el=document.getElementById('ptest-'+name);el.innerHTML='<p class="muted">Running 1-token completion…</p>';
  const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/providers/'+encodeURIComponent(name)+'/test-completion',{method:'POST',body:JSON.stringify({model:form.model})});
  el.innerHTML=r.ok?`<div class="issue"><strong>Completion OK</strong><br><small>Reply: ${esc(r.reply_preview)}</small></div>`:`<div class="issue error"><strong>Completion failed</strong><br>${esc(r.error||'')}</div>`;
}
function renderRouteControls(){
  const catalog=state.detail?.model_catalog||{providers:[]};
  const providers=catalog.providers||[];
  $('#route-provider').innerHTML=providers.map(p=>`<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  const update=()=>{
    const entry=providers.find(p=>p.name===$('#route-provider').value)||{models:[]};
    const models=Array.from(new Set([...(entry.models||[]),entry.default_model].filter(Boolean))).sort();
    $('#route-model').innerHTML=models.length?models.map(m=>`<option>${esc(m)}</option>`).join(''):'<option value="">No models discovered</option>';
    $('#route-meta').innerHTML=[entry.base_url?'Backend: '+entry.base_url:'',entry.poll_status?'Discovery: '+entry.poll_status:''].filter(Boolean).map(x=>`<div>${esc(x)}</div>`).join('');
  };
  $('#route-provider').onchange=update;update();
}
async function applyRoute(){
  const route=$('#route-kind').value,provider=$('#route-provider').value,model=$('#route-model').value;
  if(!provider||!model){toast('Provider and model required','error');return}
  if(!await confirmModal('Replace '+route+' route','Set the <b>'+esc(route)+'</b> route on <b>'+esc(state.active)+'</b> to <b>'+esc(provider)+'/'+esc(model)+'</b>? Config is backed up first.',{confirmLabel:'Apply route'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/model-route',{method:'POST',body:JSON.stringify({route,provider,model,confirm:true})});
  toast('Route replaced: '+route+' → '+provider+'/'+model);
  state.caches.providers=null;await loadProviders(true);
}

/* ------------------------------------------------------------- auth & env */
async function loadAuthEnv(force){
  if(state.caches.auth&&state.caches.env&&!force){renderAuth(state.caches.auth);renderEnv(state.caches.env);return}
  const [auth,env]=await Promise.all([
    api('/api/profiles/'+encodeURIComponent(state.active)+'/auth'),
    api('/api/profiles/'+encodeURIComponent(state.active)+'/env'),
  ]);
  state.caches.auth=auth;state.caches.env=env;renderAuth(auth);renderEnv(env);
}
function renderAuth(a){
  $('#auth-view').innerHTML=kv([['Source',a.source+(a.stale?' · STALE':'')],['Active file',a.active_path],['Profile-local file',a.profile_exists?'present':'absent'],['Default file',a.default_exists?'present':'absent'],['Active provider',a.metadata?.active_provider],['Updated at',a.metadata?.updated_at],['Stale threshold',a.stale_threshold_days+' days']]);
  const providers=a.metadata?.providers||[];const pool=a.metadata?.credential_pool||[];
  $('#auth-providers').innerHTML=providers.length||pool.length?`
    ${providers.map(p=>`<div class="row"><strong>${esc(p)} <span class="pill">authenticated provider</span></strong>
      ${a.source==='profile-local'?`<div class="actions"><button class="mini" data-rmauth="${esc(p)}">Remove entry</button></div>`:''}</div>`).join('')}
    ${pool.filter(p=>!providers.includes(p)).map(p=>`<div class="row"><strong>${esc(p)} <span class="pill">credential pool</span></strong></div>`).join('')}`
    :'<p class="muted">No provider entries in active auth file.</p>';
  $$('[data-rmauth]').forEach(b=>b.onclick=async()=>{
    if(!await confirmModal('Remove auth entry','Remove <b>'+esc(b.dataset.rmauth)+'</b> from profile-local auth.json? A backup is taken first.'))return;
    await api('/api/profiles/'+encodeURIComponent(state.active)+'/auth/remove-provider',{method:'POST',body:JSON.stringify({provider:b.dataset.rmauth,confirm:true})});
    await loadAuthEnv(true);toast('Removed auth provider entry');
  });
}
function renderEnv(e){
  $('#env-scope').textContent=e.scope;$('#env-path').textContent=e.path+(e.exists?'':' (not created yet)');
  $('#env-warnings').innerHTML=(e.warnings||[]).map(w=>`<div class="issue warning"><strong>warning</strong><br>${esc(w)}</div>`).join('');
  $('#env-list').innerHTML=(e.keys||[]).length?(e.keys||[]).map(k=>`
    <div class="row env-row"><strong>${esc(k.key)}</strong><small class="env-value" data-envval="${esc(k.key)}">${esc(k.masked)}</small>
      <div class="actions"><button class="mini" data-reveal="${esc(k.key)}">Reveal 10s</button><button class="mini" data-rmenv="${esc(k.key)}">Remove</button></div>
    </div>`).join(''):'<p class="muted">No profile-specific .env yet. Set a key or copy from global/another profile to create one.</p>';
  $$('[data-reveal]').forEach(b=>b.onclick=async()=>{
    if(!await confirmModal('Reveal value','Show the value of <b>'+esc(b.dataset.reveal)+'</b> on screen for 10 seconds? The reveal is recorded in the audit log.',{confirmLabel:'Reveal'}))return;
    const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/env/reveal',{method:'POST',body:JSON.stringify({key:b.dataset.reveal})});
    const cell=$(`[data-envval="${b.dataset.reveal}"]`);const masked=cell.textContent;
    cell.textContent=r.value;cell.classList.add('revealed');
    setTimeout(()=>{cell.textContent=masked;cell.classList.remove('revealed')},10000);
  });
  $$('[data-rmenv]').forEach(b=>b.onclick=async()=>{
    if(!await confirmModal('Remove env key','Remove <b>'+esc(b.dataset.rmenv)+'</b> from the profile .env with backup?'))return;
    await api('/api/profiles/'+encodeURIComponent(state.active)+'/env',{method:'POST',body:JSON.stringify({ops:[{op:'remove',key:b.dataset.rmenv}],confirm:true})});
    await loadAuthEnv(true);toast('Removed key');
  });
}
async function setEnvKey(){
  const key=$('#env-key').value.trim(),value=$('#env-value').value;
  if(!key){toast('Key required','error');return}
  const warn=(state.caches.env?.warnings||[]).length?'<div class="issue warning"><strong>warning</strong><br>'+esc(state.caches.env.warnings[0])+'</div>':'';
  if(!await confirmModal('Set env key','Set <b>'+esc(key)+'</b> in <b>'+esc(state.active)+'/.env</b> with backup? The value stays masked everywhere.',{detail:warn,confirmLabel:'Set key'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/env',{method:'POST',body:JSON.stringify({ops:[{op:'set',key,value}],confirm:true})});
  $('#env-key').value='';$('#env-value').value='';await loadAuthEnv(true);toast('Set '+key);
}
async function copyEnv(){
  const source=$('#env-copy-source').value;
  if(!await confirmModal('Copy .env','Copy the entire .env from <b>'+esc(source)+'</b> into <b>'+esc(state.active)+'</b>? The existing file is backed up.',{confirmLabel:'Copy .env'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/env/copy',{method:'POST',body:JSON.stringify({source,confirm:true})});
  await loadAuthEnv(true);toast('.env copied from '+source);
}
async function copyAuth(){
  const source=$('#auth-copy-source').value;
  if(!await confirmModal('Copy auth state','Copy auth.json from <b>'+esc(source)+'</b> into <b>'+esc(state.active)+'</b>? The existing file is backed up; secret values are never displayed.',{confirmLabel:'Copy auth'}))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/auth/copy',{method:'POST',body:JSON.stringify({source,confirm:true})});
  await loadAuthEnv(true);toast('Auth copied from '+source);
}
async function useDefaultAuth(){
  if(!await confirmModal('Inherit default auth','Remove the profile-local auth.json so <b>'+esc(state.active)+'</b> inherits default auth? A backup is taken first.'))return;
  await api('/api/profiles/'+encodeURIComponent(state.active)+'/auth/use-default',{method:'POST',body:JSON.stringify({confirm:true})});
  await loadAuthEnv(true);toast('Profile now inherits default auth');
}

/* ------------------------------------------------- live delegation authority */
let delState={view:null,draft:null,filter:''};
async function loadDelegation(force){
  if(delState.view&&!force){renderDelegation();return}
  const view=await api('/api/profiles/'+encodeURIComponent(state.active)+'/delegation');
  delState.view=view;
  delState.draft={
    allowed:view.allowed_profiles.map(t=>t.name),
    allow_self:view.allow_self,
    max_depth:view.max_depth,
    timeout:view.default_timeout_seconds,
  };
  renderDelegation();
}
function delTargetInfo(name){
  return (delState.view?.allowed_profiles||[]).find(t=>t.name===name)
    ||{name,status:state.profiles.some(p=>p.name===name)||name==='default'?'ok':'missing'};
}
function delDirty(){
  const v=delState.view,d=delState.draft;
  if(!v||!d)return false;
  const orig=v.allowed_profiles.map(t=>t.name);
  return JSON.stringify(orig)!==JSON.stringify(d.allowed)||v.allow_self!==d.allow_self
    ||String(v.max_depth??'')!==String(d.max_depth??'')||String(v.default_timeout_seconds??'')!==String(d.timeout??'');
}
function runtimePill(rt){
  if(!rt||!rt.runtime_support)return '';
  if(rt.runtime_support==='implemented')return '<span class="pill good" title="The installed hermes-agent implements this surface">runtime: native support</span>';
  if(rt.runtime_support==='not-implemented')return '<span class="pill warnpill" title="'+esc(rt.note||'')+'">runtime: extension (not implemented by the installed hermes-agent — config is forward-compatible but inert)</span>';
  return '<span class="pill" title="'+esc(rt.note||'')+'">runtime support unknown</span>';
}
function renderDelegation(){
  const v=delState.view,d=delState.draft;
  if(!v||!d)return;
  $('#del-config-ref').textContent=v.config_path+' · profile_delegation';
  const gateClass=s=>s==='disabled'?'bad':s.startsWith('enabled')?'good':'';
  $('#del-gates').innerHTML=
    runtimePill(v.runtime)
    +`<span class="pill ${gateClass(v.gates.profile_delegation_toolset)}">profile_delegation toolset: ${esc(v.gates.profile_delegation_toolset)}</span>`
    +`<span class="pill ${gateClass(v.gates.delegation_toolset)}">delegation toolset: ${esc(v.gates.delegation_toolset)}</span>`
    +(v.configured?'':'<span class="pill warnpill">no profile_delegation block yet — saving creates it</span>')
    +(delDirty()?'<span class="pill warnpill">unsaved draft</span>':'');
  $('#del-allowed-count').textContent=d.allowed.length+' allowed';
  $('#del-allowed').innerHTML=d.allowed.length?d.allowed.map(name=>{
    const info=delTargetInfo(name);
    return `<div class="row del-row">
      <strong>${esc(name)}
        ${info.status==='stale-name'?`<span class="pill warnpill">stale name → ${esc(info.resolves_to)}</span>`:''}
        ${info.status==='missing'?'<span class="pill bad">profile missing</span>':''}
      </strong>
      <div class="actions"><button class="mini" data-delrm="${esc(name)}">Revoke</button></div>
    </div>`}).join('')
    :'<p class="muted">No delegation targets. This profile cannot call delegate_profile on anyone.</p>';
  const q=delState.filter.toLowerCase();
  const candidates=(v.available_profiles||[]).filter(p=>p!==state.active&&!d.allowed.includes(p)&&(!q||p.toLowerCase().includes(q)));
  $('#del-available').innerHTML=candidates.length?candidates.map(p=>`
    <div class="row clickable del-row" data-deladd="${esc(p)}"><strong>${esc(p)}</strong><small>click to grant</small></div>`).join('')
    :'<p class="muted">No more profiles match.</p>';
  $('#del-allow-self').checked=!!d.allow_self;
  $('#del-max-depth').value=d.max_depth??'';
  $('#del-timeout').value=d.timeout??'';
  const staleCount=d.allowed.filter(n=>delTargetInfo(n).status==='stale-name').length;
  $('#del-fix-stale').classList.toggle('hidden',!staleCount);
  $('#del-fix-stale').textContent=`Fix ${staleCount} stale name${staleCount===1?'':'s'}…`;
  $('#del-worker').innerHTML=kv([['Provider',v.worker_route.provider],['Model',v.worker_route.model],['Orchestrator enabled',String(v.worker_route.orchestrator_enabled)],['Max spawn depth',v.worker_route.max_spawn_depth],['Inherits MCP/toolsets',String(v.worker_route.inherit_mcp_toolsets)]]);
  $('#del-inbound').innerHTML=(v.inbound||[]).length?v.inbound.map(i=>`
    <div class="row del-row"><strong>${esc(i.profile)} ${i.exact?'':'<span class="pill warnpill">via stale name '+esc(i.declared_as)+'</span>'}</strong></div>`).join('')
    :'<p class="muted">No profile lists this one in its delegation authority.</p>';
  $$('[data-delrm]').forEach(b=>b.onclick=()=>{delState.draft.allowed=delState.draft.allowed.filter(n=>n!==b.dataset.delrm);renderDelegation()});
  $$('[data-deladd]').forEach(el=>el.onclick=()=>{delState.draft.allowed.push(el.dataset.deladd);delState.draft.allowed.sort();renderDelegation()});
}
async function saveDelegation(){
  const d=delState.draft;if(!d)return;
  const removed=(delState.view.allowed_profiles||[]).map(t=>t.name).filter(n=>!d.allowed.includes(n));
  const added=d.allowed.filter(n=>!(delState.view.allowed_profiles||[]).some(t=>t.name===n));
  if(!await confirmModal('Save delegation authority',
    'Write the delegation authority for <b>'+esc(state.active)+'</b> to config.yaml with backup?',
    {detail:(added.length?'<b>Grant:</b> '+esc(added.join(', '))+'<br>':'')+(removed.length?'<b>Revoke:</b> '+esc(removed.join(', ')):'')||'No target changes (settings only).',confirmLabel:'Save with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/delegation',{method:'POST',body:JSON.stringify({
    allowed_profiles:d.allowed,
    allow_self:$('#del-allow-self').checked,
    max_depth:$('#del-max-depth').value?parseInt($('#del-max-depth').value,10):null,
    default_timeout_seconds:$('#del-timeout').value?parseInt($('#del-timeout').value,10):null,
    confirm:true,
  })});
  delState.view=j.view;
  delState.draft={allowed:j.view.allowed_profiles.map(t=>t.name),allow_self:j.view.allow_self,max_depth:j.view.max_depth,timeout:j.view.default_timeout_seconds};
  renderDelegation();
  toast('Delegation authority saved. Backup: '+j.backup);
}
async function fixStaleDelegation(){
  const stale=delState.draft.allowed.map(n=>delTargetInfo(n)).filter(t=>t.status==='stale-name');
  if(!await confirmModal('Fix stale delegation names','Rewrite stale target names in <b>'+esc(state.active)+'</b> config with backup?',
    {detail:stale.map(t=>esc(t.name)+' → '+esc(t.resolves_to)).join('<br>'),confirmLabel:'Fix names'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/delegation/fix-stale',{method:'POST',body:JSON.stringify({confirm:true})});
  delState.view=j.view;
  delState.draft={allowed:j.view.allowed_profiles.map(t=>t.name),allow_self:j.view.allow_self,max_depth:j.view.max_depth,timeout:j.view.default_timeout_seconds};
  renderDelegation();
  toast('Fixed '+(j.fixed||[]).length+' stale name(s). Backup: '+(j.backup||'none'));
}

/* ------------------------------------------------------------------- team */
function specialistRow(s,i){
  return `<div class="specialist-row card" data-spec="${i}">
    <div class="purpose-grid" style="grid-template-columns:1fr 1fr 1fr 1fr auto">
      <label>Profile <input class="spec-name" list="profile-names" value="${esc(s.name||'')}" placeholder="existing or new name"></label>
      <label>Role <select class="spec-role">${['specialist','worker','reviewer','fallback'].map(r=>`<option ${s.role===r?'selected':''}>${r}</option>`).join('')}</select></label>
      <label>Max risk <select class="spec-risk">${['read-only','local-write','remote-write','coordination'].map(r=>`<option ${s.max_risk===r?'selected':''}>${r}</option>`).join('')}</select></label>
      <label>Provisioning <select class="spec-prov">
        <option value="existing" ${s.provisioning==='existing'?'selected':''}>use existing profile</option>
        <option value="create-inline" ${s.provisioning==='create-inline'?'selected':''}>create inline</option>
        <option value="adapt-existing" ${s.provisioning==='adapt-existing'?'selected':''}>duplicate/adapt existing</option>
        <option value="future-dependency" ${s.provisioning==='future-dependency'?'selected':''}>future dependency</option>
      </select></label>
      <label>&nbsp;<button class="spec-remove">Remove</button></label>
    </div>
    <div class="purpose-grid" style="grid-template-columns:1fr 1fr 1fr 1fr">
      <label>Domains <input class="spec-domains" value="${esc((s.domains||[]).join(', '))}" placeholder="rmm-support, analysis"></label>
      <label>Adapt from <input class="spec-adapt" value="${esc(s.adapt_from||'')}" placeholder="(when adapting)"></label>
      <label>Forbidden <input class="spec-forbidden" value="${esc((s.forbidden||[]).join(', '))}" placeholder="ticket-write, rmm-mutation"></label>
      <label class="inline" style="align-self:end"><input type="checkbox" class="spec-mcp" ${s.inherit_mcp?'checked':''}> inherit MCP/tools</label>
    </div>
  </div>`;
}
function renderTeam(){
  const mode=$('#team-mode').value;
  $('#team-evaluator-wrap').classList.toggle('hidden',mode!=='orchestrator');
  $('#team-specialists').innerHTML=teamState.specialists.map((s,i)=>specialistRow(s,i)).join('')
    +`<datalist id="profile-names">${state.profiles.map(p=>`<option value="${esc(p.name)}">`).join('')}</datalist>`;
  $$('.specialist-row').forEach(row=>{
    const i=parseInt(row.dataset.spec,10);
    row.querySelector('.spec-remove').onclick=()=>{teamState.specialists.splice(i,1);renderTeam()};
    const sync=()=>{
      teamState.specialists[i]={
        name:row.querySelector('.spec-name').value.trim(),
        role:row.querySelector('.spec-role').value,
        max_risk:row.querySelector('.spec-risk').value,
        provisioning:row.querySelector('.spec-prov').value,
        domains:row.querySelector('.spec-domains').value.split(',').map(x=>x.trim()).filter(Boolean),
        adapt_from:row.querySelector('.spec-adapt').value.trim(),
        forbidden:row.querySelector('.spec-forbidden').value.split(',').map(x=>x.trim()).filter(Boolean),
        inherit_mcp:row.querySelector('.spec-mcp').checked,
      };
    };
    row.querySelectorAll('input,select').forEach(el=>el.onchange=sync);
  });
  const evalInput=$('#team-evaluator');
  evalInput.oninput=()=>{
    const name=evalInput.value.trim();
    const exists=state.profiles.some(p=>p.name===name);
    $('#team-evaluator-status').textContent=name?(exists?'existing profile':'future dependency'):'—';
  };
}
function addSpecialist(){teamState.specialists.push({role:'specialist',max_risk:'local-write',provisioning:'existing'});renderTeam()}
async function generateTeamPlan(){
  const mode=$('#team-mode').value;
  const payload={primary:$('#team-primary').value||state.active,mode,specialists:teamState.specialists.filter(s=>s.name)};
  const evalName=($('#team-evaluator').value||'').trim();
  if(mode==='orchestrator'&&evalName){
    payload.evaluator={name:evalName,provisioning:state.profiles.some(p=>p.name===evalName)?'existing':'future-dependency'};
  }
  const plan=await api('/api/workflows/team-plan',{method:'POST',body:JSON.stringify(payload)});
  state.lastChangeSet=plan.change_set;state.lastChangeSetSource=mode+' topology for '+payload.primary;
  renderTeamPlan(plan);renderChangeSet();toast('Generated team ChangeSet — review on the ChangeSet tab');
}
function renderTeamPlan(plan){
  const cs=plan.change_set||{};const findings=plan.findings||[];
  $('#team-plan').classList.remove('empty');
  $('#team-plan').innerHTML=`
    <div class="plan-head"><div><strong>${esc(cs.title||'Team plan')}</strong><small>mode: ${esc(plan.mode)} · ${esc(plan.topology.primary)} → ${esc(plan.topology.specialists.join(', ')||'(none)')}</small></div><span class="badge">draft plan</span></div>
    <div class="plan-grid">
      <div><b>Topology</b><p>${esc(plan.topology.primary)} → ${esc(plan.topology.specialists.join(', ')||'no specialists')}</p></div>
      <div><b>Intent contracts</b><p>${(cs.intent_contracts||[]).length}</p></div>
      <div><b>Delegation edges</b><p>${(cs.delegation_edges||[]).length}</p></div>
      <div><b>Fit evaluations</b><p>${(cs.fit_evaluations||[]).map(x=>`${esc(x.profile)}: ${x.fit_score}`).join(', ')||'—'}</p></div>
    </div>
    <div class="findings">${findings.map(f=>`<div class="issue ${esc(f.severity)}"><strong>${esc(f.severity)} · ${esc(f.scope)}</strong><br>${esc(f.message)}${f.recommendation?`<small>${esc(f.recommendation)}</small>`:''}</div>`).join('')}</div>
    <div class="next-step"><b>Next step</b><span>Review the full ChangeSet on <a href="#" data-goto="changeset">the ChangeSet tab</a>, or adjust specialists above — your draft persists.</span></div>`;
  wireGotoLinks();
}

/* ---------------------------------------------------------------- channels */
let chState={view:null};
async function loadChannels(force){
  if(chState.view&&!force)return renderChannels();
  const view=await api('/api/profiles/'+encodeURIComponent(state.active)+'/channels');
  chState.view=view;renderChannels();
}
function renderChannels(){
  const v=chState.view;if(!v)return;
  $('#ch-config-ref').textContent=v.config_path;
  const routingPill=runtimePill(v.routing_runtime);
  $('#ch-platforms').innerHTML=(v.platforms||[]).map(p=>{
    const tokenPills=(p.tokens||[]).map(t=>`<span class="pill ${t.present?'good':'bad'}" title="env var name only — value never shown">${esc(t.env)}: ${t.present?'present':'missing'}</span>`).join('')
      ||'<span class="pill">no token convention checked</span>';
    const accessBits=Object.entries(p.access||{}).map(([k,list])=>`${esc(k)}: ${list.length}`).join(' · ');
    const routingRows=(p.routing||[]).map(r=>`
      <div class="row del-row"><strong>${esc(r.channel)} → ${esc(r.profile)} ${r.valid?'':'<span class="pill bad">profile missing</span>'}</strong>
      <div class="actions"><button class="mini" data-chrm="${esc(p.platform)}::${esc(r.channel)}">Remove route</button></div></div>`).join('');
    return `
    <details class="row ch-platform" ${p.configured?'open':''}>
      <summary><strong style="text-transform:capitalize">${esc(p.platform)}</strong>
        <span class="pill ${p.configured?'good':''}">${p.configured?'configured ('+p.field_count+' fields)':'not configured'}</span>
        ${tokenPills}
        ${p.require_mention!==null?`<span class="pill">${p.require_mention?'mention required':'free response allowed'}</span>`:''}
        ${accessBits?`<small>${esc(accessBits)}${p.channel_prompts?' · '+p.channel_prompts+' channel prompts':''}</small>`:''}
      </summary>
      ${p.routing!==undefined&&PLATFORM_HAS_ROUTING(p)?`
        <h4 style="margin:10px 0 6px">Channel → profile routing ${routingPill}</h4>
        <div class="list">${routingRows||'<p class="muted">No routes. All traffic on this platform uses this profile.</p>'}</div>
        <div class="purpose-grid" style="grid-template-columns:1fr 1fr auto">
          <label>Channel ID <input class="ch-route-channel" data-platform="${esc(p.platform)}" placeholder="e.g. 1511379…"></label>
          <label>Route to profile <select class="ch-route-profile" data-platform="${esc(p.platform)}">${profileOptions('')}</select></label>
          <label>&nbsp;<button class="mini" data-chadd="${esc(p.platform)}">Add route</button></label>
        </div>`:''}
      <details style="margin-top:10px"><summary class="muted">Edit ${esc(p.platform)} block (YAML)</summary>
        <textarea class="mono ch-yaml" data-platform="${esc(p.platform)}" spellcheck="false">${esc(p.block_yaml)}</textarea>
        <div class="actions"><button data-chsave="${esc(p.platform)}" class="danger">Save ${esc(p.platform)} block with backup</button></div>
        <p class="muted">Leave empty (or just <code>${esc(p.platform)}:</code>) to remove the block. Inline tokens are rejected — credentials belong in env.</p>
      </details>
    </details>`;
  }).join('');
  $$('[data-chsave]').forEach(b=>b.onclick=()=>saveChannelBlock(b.dataset.chsave));
  $$('[data-chrm]').forEach(b=>b.onclick=()=>{const [plat,channel]=b.dataset.chrm.split('::');removeRoute(plat,channel)});
  $$('[data-chadd]').forEach(b=>b.onclick=()=>addRoute(b.dataset.chadd));
}
function PLATFORM_HAS_ROUTING(p){return p.platform==='discord'}
async function saveChannelBlock(platform){
  const ta=document.querySelector(`.ch-yaml[data-platform="${platform}"]`);
  if(!await confirmModal('Save '+platform+' block','Replace the <b>'+esc(platform)+'</b> configuration block in <b>'+esc(state.active)+'/config.yaml</b>? A backup is taken first.',{confirmLabel:'Save with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/channels/'+encodeURIComponent(platform),{method:'POST',body:JSON.stringify({block_yaml:ta.value,confirm:true})});
  chState.view=j.view;chState.view.routing_runtime=chState.view.routing_runtime||{};renderChannels();
  toast(platform+' block saved. Backup: '+j.backup);
  await loadChannels(true);
}
async function addRoute(platform){
  const channel=document.querySelector(`.ch-route-channel[data-platform="${platform}"]`).value.trim();
  const target=document.querySelector(`.ch-route-profile[data-platform="${platform}"]`).value;
  if(!channel){toast('Channel ID required','error');return}
  if(!await confirmModal('Add channel route','Route '+esc(platform)+' channel <b>'+esc(channel)+'</b> to profile <b>'+esc(target)+'</b>? Config is backed up first.',{confirmLabel:'Add route'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/channels/'+encodeURIComponent(platform)+'/routing',{method:'POST',body:JSON.stringify({ops:[{op:'set',channel,profile:target}],confirm:true})});
  chState.view=j.view;await loadChannels(true);toast('Route added');
}
async function removeRoute(platform,channel){
  if(!await confirmModal('Remove channel route','Remove the route for '+esc(platform)+' channel <b>'+esc(channel)+'</b>? Config is backed up first.'))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/channels/'+encodeURIComponent(platform)+'/routing',{method:'POST',body:JSON.stringify({ops:[{op:'remove',channel}],confirm:true})});
  chState.view=j.view;await loadChannels(true);toast('Route removed');
}

/* --------------------------------------------------------------- changeset */
function sectionDetails(title,items){items=items||[];return `<details class="cs-detail" ${items.length?'open':''}><summary>${esc(title)} <span>${items.length}</span></summary><pre>${esc(JSON.stringify(items,null,2))}</pre></details>`}
function renderChangeSet(){
  const cs=state.lastChangeSet;
  const el=$('#changeset-view');
  if(!cs){el.classList.add('empty');el.innerHTML='No ChangeSet generated yet. Build one on <a href="#" data-goto="purpose">tab 2 (Purpose)</a> or <a href="#" data-goto="team">tab 11 (Team design)</a>.';wireGotoLinks();return}
  el.classList.remove('empty');
  el.innerHTML=`
    <div class="plan-head"><div><strong>${esc(cs.title)}</strong><small>${esc(cs.summary)} · source: ${esc(state.lastChangeSetSource)}</small></div><span class="badge">${esc(cs.workflow)}</span></div>
    ${sectionDetails('Config patches',cs.config_patches)}
    ${sectionDetails('Skill assignments',cs.skill_assignments)}
    ${sectionDetails('Prompt changes',cs.prompt_changes)}
    ${sectionDetails('MCP changes',cs.mcp_changes)}
    ${sectionDetails('Provider changes',cs.provider_changes)}
    ${sectionDetails('Intent contracts',cs.intent_contracts)}
    ${sectionDetails('Delegation edges',cs.delegation_edges)}
    ${sectionDetails('Team relationships',cs.team_relationship_changes)}
    ${sectionDetails('Generated files',cs.generated_files)}
    ${sectionDetails('Backup plan',cs.backup_plan)}
    ${sectionDetails('Audit preview',cs.audit_preview)}
    <div class="findings">${(cs.findings||[]).map(f=>`<div class="issue ${esc(f.severity)}"><strong>${esc(f.severity)} · ${esc(f.scope)}</strong><br>${esc(f.message)}</div>`).join('')}</div>
    <div id="changeset-result"></div>`;
}
async function applyChangeSetBounded(){
  if(!state.lastChangeSet){toast('No ChangeSet to apply. Generate one on tab 2 or 11.','error');return}
  if(!await confirmModal('Apply bounded ChangeSet','Apply the bounded sections (skill assignments + known config patches) to <b>'+esc(state.active)+'</b>? A backup is taken first; everything else is reported as skipped, never silently dropped.',{confirmLabel:'Apply with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/apply-changeset',{method:'POST',body:JSON.stringify({change_set:state.lastChangeSet,confirm:true})});
  const result=$('#changeset-result');
  if(result)result.innerHTML=`
    <div class="issue"><strong>Applied with backup</strong><br><small>${esc(j.backup)}</small></div>
    ${(j.applied||[]).map(a=>`<div class="issue"><strong>applied · ${esc(a.section)}</strong><br><small>${esc(JSON.stringify(a))}</small></div>`).join('')}
    ${(j.skipped||[]).map(s=>`<div class="issue warning"><strong>skipped · ${esc(s.section)}</strong><br>${esc(s.reason)}</div>`).join('')}`;
  toast('ChangeSet applied — see result panel for applied/skipped sections');
  state.detail=await api('/api/profiles/'+encodeURIComponent(state.active));
  state.currentText=state.detail.config_text||'';state.dirty=false;
  hydrateSkillState(state.detail.skills||{skills:[]});renderDetail();
}

/* ---------------------------------------------------------------- validate */
async function validateDraft(sel='#validate-issues'){
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/validate',{method:'POST',body:JSON.stringify({config_text:state.currentText})});
  state.detail.validation=j;renderIssues(j.issues||[],sel);$('#issue-count').textContent=(j.issues||[]).length;return j;
}
async function showDiff(){const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/diff',{method:'POST',body:JSON.stringify({config_text:state.currentText})});$('#diff-output').textContent=j.diff||'No changes.';return j}
async function applyConfig(){
  await validateDraft('#issues');const d=await showDiff();
  if(!d.changed){toast('No changes to apply.');return}
  if(!await confirmModal('Apply config','Write this draft to <b>'+esc(state.active)+'/config.yaml</b>? The current file is backed up first.',{confirmLabel:'Apply with backup'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/apply',{method:'POST',body:JSON.stringify({config_text:state.currentText,confirm:true})});
  toast('Applied. Backup: '+(j.backup||'none'));await selectProfile(state.active);
}
async function runSmoke(){
  $('#smoke-out').classList.remove('empty');$('#smoke-out').innerHTML='<p class="muted">Running live smoke checks…</p>';
  const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/readiness?live=1');
  renderReadiness(r,'#smoke-out');state.caches.readiness=r;
}

/* ----------------------------------------------------------------- backups */
function renderBackups(backups){
  $('#backup-list').innerHTML=backups.length?backups.map(b=>`
    <div class="row"><strong>${esc(b.name)} <span class="pill">${esc(b.kind)}</span></strong><small>${esc(b.created||'')} · ${b.bytes} bytes</small>
    <div class="actions">
      ${b.kind==='config'?`<button class="mini" data-compare="${esc(b.name)}">Compare</button><button class="mini" data-restore="${esc(b.name)}">Restore</button>`:''}
    </div></div>`).join('')
    :'<p class="muted">No backups yet.<br><button id="first-backup" class="primary" style="margin-top:8px">Create first backup</button></p>';
  const fb=$('#first-backup');if(fb)fb.onclick=backupNow;
  $$('[data-restore]').forEach(b=>b.onclick=()=>rollback(b.dataset.restore));
  $$('[data-compare]').forEach(b=>b.onclick=async()=>{
    const r=await api('/api/profiles/'+encodeURIComponent(state.active)+'/backups/compare',{method:'POST',body:JSON.stringify({backup:b.dataset.compare})});
    $('#backup-compare').textContent=r.changed?r.diff:'Backup matches current config.';
  });
}
async function backupNow(){
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/backup',{method:'POST',body:JSON.stringify({})});
  toast('Backup created: '+j.backup);renderBackups(j.backups||[]);
}
async function rollback(name){
  if(!await confirmModal('Restore from backup','Restore <b>'+esc(state.active)+'</b> config from <b>'+esc(name)+'</b>? The current config is backed up first.',{confirmLabel:'Restore'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/rollback',{method:'POST',body:JSON.stringify({backup:name})});
  state.currentText=j.config_text;state.dirty=false;await selectProfile(state.active);toast('Restored from '+name);
}
async function rollbackLastApply(){
  if(!await confirmModal('Rollback last apply','Undo the last applied change on <b>'+esc(state.active)+'</b> by restoring its pre-apply backup?',{confirmLabel:'Rollback'}))return;
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/rollback-last-apply',{method:'POST',body:JSON.stringify({confirm:true})});
  toast('Rolled back: '+j.undone_event);await selectProfile(state.active);
}
async function exportPackage(){
  const pkg=await api('/api/profiles/'+encodeURIComponent(state.active)+'/export');
  const blob=new Blob([JSON.stringify(pkg,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=state.active+'.profile-package.json';a.click();
  toast('Exported package (secrets excluded by design)');
}
function renderAudit(rows){$('#audit-list').innerHTML=rows.length?rows.slice().reverse().map(r=>`<div class="audit-row"><strong>${esc(r.ts)} · ${esc(r.event)}</strong><small>${esc(JSON.stringify(r.details))}</small></div>`).join(''):'<p class="muted">No audit events for this profile yet.</p>'}

/* --------------------------------------------------------------------- raw */
async function loadRaw(force){
  if(state.caches.raw&&!force)return renderRaw(state.caches.raw);
  const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/raw');
  state.caches.raw=j;renderRaw(j);
}
function renderRaw(j){
  $('#raw-files').innerHTML=(j.identity||[]).map(f=>`
    <details class="row"><summary><strong>${esc(f.name)}</strong> <span class="pill ${f.status==='profile-local'?'good':f.status==='missing'?'bad':''}">${esc(f.status)}</span></summary>
    <pre class="diff">${esc(f.text||'(missing)')}</pre></details>`).join('');
  $('#raw-env').innerHTML=(j.env?.keys||[]).length?(j.env.keys||[]).map(k=>`<div class="row"><strong>${esc(k.key)}</strong><small>${esc(k.masked)}</small></div>`).join(''):'<p class="muted">No profile .env. Edit on tab 10.</p>';
  $('#raw-auth').innerHTML=kv([['Source',j.auth?.source],['Active path',j.auth?.active_path],['Providers',(j.auth?.metadata?.providers||[]).join(', ')],['Credential pool',(j.auth?.metadata?.credential_pool||[]).join(', ')],['Updated',j.auth?.metadata?.updated_at]]);
  $('#raw-provenance').innerHTML=kv([['Profile dir',j.provenance?.profile_dir],['Hermes home',j.provenance?.hermes_home],['Config path',j.provenance?.config_path],['Manager state',j.provenance?.manager_state]]);
}

/* ----------------------------------------------------------------- wiring */
async function createProfile(){const name=$('#create-name').value.trim();const base=$('#create-base').value;const j=await api('/api/profiles',{method:'POST',body:JSON.stringify({name,base})});$('#create-dialog').close();state.profiles=j.profiles;renderProfiles();fillCreateBase();fillSharedSelectors();await selectProfile(name)}
const on=(sel,ev,fn)=>{const el=$(sel);if(el)el[ev]=e=>Promise.resolve(fn(e)).catch(err=>toast(err.message,'error'))};
on('#refresh','onclick',loadState);
on('#profile-filter','oninput',renderProfiles);on('#domain-filter','onchange',renderProfiles);on('#role-filter','onchange',renderProfiles);on('#risk-filter','onchange',renderProfiles);
$$('.tabs button').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
on('#new-profile','onclick',()=>$('#create-dialog').showModal());
on('#create-submit','onclick',e=>{e.preventDefault();return createProfile()});
on('#readiness-offline','onclick',()=>runReadiness(false));
on('#readiness-live','onclick',()=>runReadiness(true));
on('#plan-purpose','onclick',generatePurposePlan);
on('#identity-save','onclick',saveIdentityFile);
on('#identity-copy','onclick',copyIdentityFile);
on('#system-prompt-save','onclick',saveSystemPrompt);
on('#domain-save','onclick',saveDomain);
on('#role-save','onclick',saveRole);
on('#group-new','onclick',newGroup);
on('#group-save','onclick',saveGroup);
on('#group-duplicate','onclick',duplicateGroup);
on('#group-delete','onclick',deleteGroup);
on('#group-export','onclick',exportGroup);
on('#group-import','onclick',importGroup);
on('#group-preview','onclick',previewGroup);
on('#group-json-load','onclick',()=>{try{const g=JSON.parse($('#group-editor').value);fillGroupForm(g);toast('Loaded JSON into form')}catch(e){toast('Invalid JSON: '+e.message,'error')}});
on('#skill-filter','oninput',e=>{skillState.query=e.target.value;renderSkills()});
on('#skill-category-filter','onchange',e=>{skillState.category=e.target.value;renderSkills()});
on('#show-enabled-only','onchange',e=>{skillState.showAssignedOnly=e.target.checked;renderSkills()});
on('#add-filtered','onclick',addFiltered);
on('#clear-assigned','onclick',clearAssigned);
on('#save-skills','onclick',()=>saveSkillAssignment(false));
on('#toolsets-refresh','onclick',async()=>{const j=await api('/api/profiles/'+encodeURIComponent(state.active)+'/toolsets?refresh=1');state.caches.toolsets=j;renderToolsets(j);toast('Registry refreshed: '+j.registry_source)});
on('#mcp-add','onclick',addMcp);
on('#providers-refresh','onclick',()=>loadProviders(true));
on('#route-apply','onclick',applyRoute);
on('#env-set','onclick',setEnvKey);
on('#env-copy','onclick',copyEnv);
on('#auth-copy','onclick',copyAuth);
on('#auth-use-default','onclick',useDefaultAuth);
on('#team-add-specialist','onclick',addSpecialist);
on('#team-mode','onchange',renderTeam);
on('#plan-team','onclick',generateTeamPlan);
on('#del-save','onclick',saveDelegation);
on('#del-fix-stale','onclick',fixStaleDelegation);
on('#del-filter','oninput',e=>{delState.filter=e.target.value;renderDelegation()});
on('#del-allow-self','onchange',e=>{delState.draft.allow_self=e.target.checked;renderDelegation()});
on('#del-max-depth','oninput',e=>{delState.draft.max_depth=e.target.value||null});
on('#del-timeout','oninput',e=>{delState.draft.timeout=e.target.value||null});
on('#changeset-apply','onclick',applyChangeSetBounded);
on('#validate-run','onclick',()=>validateDraft('#validate-issues'));
on('#diff-run','onclick',showDiff);
on('#smoke-run','onclick',runSmoke);
on('#backup-now','onclick',backupNow);
on('#rollback-last','onclick',rollbackLastApply);
on('#export-package','onclick',exportPackage);
on('#shutdown-server','onclick',async()=>{
  if(!await confirmModal('Stop the Profile Manager UI','This stops <b>only this management WebUI process</b> (the local server rendering this page).<br><br><b>It does not touch your Hermes agents, gateways, sessions, or profiles</b> — they keep running exactly as they are. Nothing is written. Restart the UI any time with <code>profile-manager start</code>.',{confirmLabel:'Stop the UI'}))return;
  try{await api('/api/shutdown',{method:'POST',body:JSON.stringify({confirm:true})})}catch(e){}
  document.body.innerHTML='<div class="farewell"><h1>⏻</h1><p>Profile Manager UI stopped. Your Hermes agents were not affected.</p><p class="muted">Restart with <code>profile-manager start</code> (or ask your agent).</p></div>';
});
on('#config-editor','oninput',e=>{state.currentText=e.target.value;state.dirty=true;$('#dirty').textContent='dirty draft'});
on('#validate','onclick',()=>validateDraft('#issues'));
on('#diff','onclick',showDiff);
on('#apply','onclick',applyConfig);
on('#reload','onclick',()=>selectProfile(state.active));

loadState().catch(err=>{document.body.innerHTML='<pre style="color:#ffb4b4;padding:20px">'+esc(err.stack||err.message)+'</pre>'});
