// Dispatcher is a presentation over canonical chat/runtime state. It does not own a transcript,
// execute turns, or persist runtime data.
const DISPATCHER_SESSION_KEY='ares-dispatcher-session-id';
const DISPATCHER_CONTEXT_KEY='ares-dispatcher-context';
let _dispatcherPreviousSession='';
let _dispatcherRefreshTimer=null;
let _dispatcherTimelineObserver=null;

function _dispatcherSessionId(){try{return localStorage.getItem(DISPATCHER_SESSION_KEY)||'';}catch(_){return '';}}
function _dispatcherSetSessionId(sid){if(!sid)return;try{localStorage.setItem(DISPATCHER_SESSION_KEY,sid);}catch(_){}}
function _dispatcherContext(){try{const value=JSON.parse(localStorage.getItem(DISPATCHER_CONTEXT_KEY)||'[]');return Array.isArray(value)?value.filter(item=>typeof item==='string'&&item.trim()).slice(0,12):[];}catch(_){return [];}}
function _dispatcherSetContext(items){try{localStorage.setItem(DISPATCHER_CONTEXT_KEY,JSON.stringify(items.slice(0,12)));}catch(_){}}
function _dispatcherIsMission(session){return !!(session&&session.session_id&&(_dispatcherSessionId()===session.session_id||String(session.title||'')==='Dispatcher'));}

async function _dispatcherEnsureSession(){
  if(typeof S==='undefined')return '';
  if(S.session&&_dispatcherIsMission(S.session)){_dispatcherSetSessionId(S.session.session_id);return S.session.session_id;}
  if(S.session&&S.session.session_id)_dispatcherPreviousSession=S.session.session_id;
  const stored=_dispatcherSessionId();
  const cached=(typeof _allSessions!=='undefined'&&Array.isArray(_allSessions)?_allSessions:[]).find(item=>item&&(item.session_id===stored||String(item.title||'')==='Dispatcher'));
  const target=(cached&&cached.session_id)||stored;
  if(target&&typeof loadSession==='function'){
    try{await loadSession(target);if(S.session&&S.session.session_id===target){_dispatcherSetSessionId(target);return target;}}catch(_){}
  }
  if(typeof newSession!=='function')return '';
  await newSession(false,{worktree:false});
  const sid=S.session&&S.session.session_id;
  if(!sid)return '';
  _dispatcherSetSessionId(sid);
  try{await api('/api/session/rename',{method:'POST',body:JSON.stringify({session_id:sid,title:'Dispatcher'})});S.session.title='Dispatcher';}catch(_){}
  try{await api('/api/session/pin',{method:'POST',body:JSON.stringify({session_id:sid,pinned:true})});S.session.pinned=true;}catch(_){}
  return sid;
}

function _dispatcherCloneTimeline(){
  const target=$('dispatcherTimeline');
  const source=$('messages');
  if(!target)return;
  if(!source||!source.children.length){target.innerHTML='<div class="dispatcher-empty">No mission activity yet. Dispatch an instruction below to begin.</div>';return;}
  const clone=source.cloneNode(true);
  clone.removeAttribute('id');
  clone.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
  clone.querySelectorAll('script,form,#approvalCard,#clarifyCard').forEach(node=>node.remove());
  target.replaceChildren(clone);
  target.scrollTop=target.scrollHeight;
}

function _dispatcherRenderContext(){
  const items=_dispatcherContext();
  const render=items.map((path,index)=>`<span class="dispatcher-pin"><span>${esc(path)}</span><button type="button" aria-label="Remove pinned context" onclick="dispatcherUnpinContext(${index})">×</button></span>`).join('');
  const row=$('dispatcherContextRow');if(row)row.innerHTML=render;
  const side=$('dispatcherPinnedContext');if(side)side.innerHTML=render||'<span style="color:var(--muted)">Nothing pinned</span>';
}

function dispatcherPinWorkspace(){
  const workspace=typeof S!=='undefined'&&S.session&&String(S.session.workspace||'').trim();
  if(!workspace){if(typeof showToast==='function')showToast('Bind a workspace to this mission first','warning');return;}
  const items=_dispatcherContext();if(!items.includes(workspace))items.push(workspace);_dispatcherSetContext(items);_dispatcherRenderContext();
}
function dispatcherUnpinContext(index){const items=_dispatcherContext();items.splice(index,1);_dispatcherSetContext(items);_dispatcherRenderContext();}

function _dispatcherRenderRuntime(){
  const status=$('dispatcherRuntimeStatus');
  const side=$('dispatcherRuntimeSummary');
  const payload=typeof _aresCapabilityPayload==='object'&&_aresCapabilityPayload?_aresCapabilityPayload:{};
  const runtime=String(payload.current||((S&&S.session&&(S.session.provider||S.session.model))||'Selected runtime'));
  const negotiated=payload.capability_negotiated===true;
  const busy=!!(S&&S.busy);
  const healthy=negotiated&&!(payload.status&&payload.status[runtime]===false);
  const label=busy?'Executing mission':healthy?`${runtime} ready`:payload.capability_error||`${runtime} unavailable`;
  if(status){status.className='dispatcher-status '+(busy?'is-busy':healthy?'is-ready':'is-down');status.innerHTML=`<span></span>${esc(label)}`;}
  if(side)side.textContent=label;
}

function _dispatcherMessageText(message){
  const content=message&&message.content;
  if(typeof content==='string')return content;
  if(Array.isArray(content))return content.map(item=>typeof item==='string'?item:String(item&&item.text||'')).join('\n');
  return '';
}

function _dispatcherHaltReason(){
  const messages=S&&Array.isArray(S.messages)?S.messages:[];
  for(let index=messages.length-1;index>=0;index--){
    const message=messages[index];
    if(!message||message.role!=='assistant')continue;
    const match=_dispatcherMessageText(message).trim().match(/\[halted:\s*([^\]]+)\]/i);
    return match?match[1].trim():'';
  }
  return '';
}

function _dispatcherRenderRecovery(){
  const card=$('dispatcherRecoveryCard');const state=$('dispatcherHaltState');const summary=$('dispatcherRecoverySummary');
  const retry=$('dispatcherRetry');const undo=$('dispatcherUndo');const resume=$('dispatcherContinue');
  if(!card||!state||!summary)return;
  const busy=!!(S&&S.busy);const hasMessages=!!(S&&Array.isArray(S.messages)&&S.messages.some(message=>message&&message.role==='user'));
  const reason=_dispatcherHaltReason();
  card.classList.toggle('is-halted',!!reason);card.classList.toggle('is-busy',busy);
  state.textContent=busy?'Running':reason?'Halted':'Ready';
  summary.textContent=reason?`The runtime stopped safely: ${reason}. Continue starts a new turn with the existing session context.`:'Retry reruns the latest user turn. Undo removes the latest exchange. Continue is available after a structured halt.';
  if(retry)retry.disabled=busy||!hasMessages;if(undo)undo.disabled=busy||!hasMessages;if(resume)resume.disabled=busy||!reason;
}

async function _dispatcherRenderApproval(){
  const sid=S&&S.session&&S.session.session_id;
  const body=$('dispatcherApprovalState');const count=$('dispatcherApprovalCount');
  if(!body||!sid)return;
  try{
    const data=await api('/api/approval/pending?session_id='+encodeURIComponent(sid),{timeoutToast:false});
    const pending=data&&data.pending;const total=Number(data&&data.pending_count||0);
    if(count)count.textContent=String(total);
    if(pending){const description=pending.description||pending.command||'The runtime needs a decision.';body.innerHTML=`<div class="dispatcher-attention">${esc(description)}<br><button class="btn secondary" type="button" onclick="dispatcherOpenInChat()">Review approval</button></div>`;}
    else body.textContent='No approval is waiting.';
  }catch(_){if(count)count.textContent='—';body.textContent='Approval status is unavailable.';}
}

function _dispatcherRenderOutputs(){
  const items=typeof collectSessionArtifacts==='function'?collectSessionArtifacts():[];
  const list=$('dispatcherOutputs');const count=$('dispatcherOutputCount');if(count)count.textContent=String(items.length);if(!list)return;
  list.innerHTML=items.length?items.slice(0,20).map(item=>`<button type="button" title="${esc(item.path)}" data-dispatcher-output="${esc(item.path)}" onclick="openArtifactPath(this.dataset.dispatcherOutput)">${esc(item.path)}</button>`).join(''):'<div class="dispatcher-empty">No outputs yet.</div>';
}

async function refreshDispatcherGit(){
  const root=$('dispatcherGitState');const sid=S&&S.session&&S.session.session_id;if(!root||!sid)return;
  if(!(S.session&&S.session.workspace)){root.textContent='No workspace is bound to this mission.';return;}
  try{
    const data=await api('/api/git/status?session_id='+encodeURIComponent(sid),{timeoutToast:false});const git=data&&data.git||{};const totals=git.totals||{};
    const branch=git.branch||git.head||'Detached';const changed=Number(totals.changed||0);const staged=Number(totals.staged||0);const unstaged=Number(totals.unstaged||0);
    root.innerHTML=`<div class="dispatcher-git-row"><strong>${esc(branch)}</strong><span class="${changed?'dispatcher-git-dirty':''}">${changed} changed</span></div><div>${staged} staged · ${unstaged} unstaged</div>`;
  }catch(error){root.textContent=(error&&error.message)||'Git status is unavailable for this workspace.';}
}

async function refreshDispatcherEvidence(){
  const root=$('dispatcherEvidence');if(!root)return;
  try{
    const data=await api('/api/ares/verification-evidence',{timeoutToast:false});
    if(!data||data.available!==true){root.textContent=data&&data.reason||'No runtime evidence has been recorded.';return;}
    const promises=Array.isArray(data.promises)?data.promises:[];const passed=promises.filter(item=>item&&item.result==='pass').length;
    const recorded=data.commits&&data.commits.recorded||{};const current=data.commits&&data.commits.current||{};
    const rows=promises.map(item=>`<div class="dispatcher-evidence-row" title="${esc(item.boundary||'')}"><span>${esc(String(item.id||'').replaceAll('_',' '))}</span><span class="dispatcher-evidence-result ${esc(item.result||'')}">${esc(item.result||'unknown')}</span></div>`).join('');
    const stale=data.stale===true?`<span class="dispatcher-evidence-stale">Stale for ${esc((data.stale_components||[]).join(', '))}</span>`:`<span class="dispatcher-evidence-result pass">Commit matched</span>`;
    root.innerHTML=`<div class="dispatcher-evidence-summary"><strong>${passed}/${promises.length} passed</strong>${stale}</div><div class="dispatcher-evidence-list">${rows}</div><div class="dispatcher-evidence-meta">Recorded ${esc(data.finished_at||'unknown time')} · ARES ${esc(String(recorded.ares||'unknown').slice(0,9))} → ${esc(String(current.ares||'unknown').slice(0,9))}</div>`;
  }catch(error){root.textContent=(error&&error.message)||'Verification evidence is unavailable.';}
}

async function refreshDispatcherLineage(){
  const root=$('dispatcherLineage');const count=$('dispatcherLineageCount');const sid=S&&S.session&&S.session.session_id;if(!root||!sid)return;
  try{
    const results=await Promise.allSettled([
      api('/api/session/lineage/report?session_id='+encodeURIComponent(sid),{timeoutToast:false}),
      api('/api/delegation/tasks',{timeoutToast:false}),
    ]);
    const report=results[0].status==='fulfilled'?results[0].value:{};const delegated=results[1].status==='fulfilled'&&Array.isArray(results[1].value.tasks)?results[1].value.tasks:[];
    const sessions=[...(report.segments||[]),...(report.children||[])];const tasks=delegated.filter(task=>task&&task.parent_session_id===sid);
    const rows=[
      ...sessions.map(item=>({label:item.title||item.session_id,meta:`${item.role||'session'} · ${item.active?'active':item.end_reason||'closed'}`,kind:'session'})),
      ...tasks.map(item=>({label:item.prompt||item.id,meta:`${item.relation||'delegated'} · ${item.status||'unknown'}`,kind:'task'})),
    ];
    if(count)count.textContent=String(rows.length);
    root.innerHTML=rows.length?rows.map(item=>`<div class="hub-list-item"><div class="hub-list-main"><div class="hub-list-title">${esc(item.label)}</div><div class="hub-list-sub">${esc(item.meta)}</div></div><span class="hub-badge">${esc(item.kind)}</span></div>`).join(''):'<div class="dispatcher-empty">This mission has no child or continuation runs yet.</div>';
  }catch(error){if(count)count.textContent='—';root.innerHTML=`<div class="dispatcher-empty">${esc(error&&error.message||'Mission lineage is unavailable.')}</div>`;}
}

function _dispatcherRenderOperations(){
  const jobs=Array.isArray(_cronList)?_cronList.length:'—';
  const tasks=_kanbanBoard&&Array.isArray(_kanbanBoard.columns)?_kanbanBoard.columns.reduce((sum,column)=>sum+(Array.isArray(column.tasks)?column.tasks.length:0),0):'—';
  if($('dispatcherTaskCount'))$('dispatcherTaskCount').textContent=String(jobs);if($('dispatcherKanbanCount'))$('dispatcherKanbanCount').textContent=String(tasks);
}

async function refreshDispatcher(force=false){
  if(typeof _currentPanel!=='undefined'&&_currentPanel!=='dispatcher'&&!force)return;
  const title=$('dispatcherSessionTitle');if(title)title.textContent=(S&&S.session&&S.session.title)||'Dispatcher';
  _dispatcherRenderRuntime();_dispatcherRenderRecovery();_dispatcherRenderContext();_dispatcherCloneTimeline();_dispatcherRenderOutputs();_dispatcherRenderOperations();
  await Promise.allSettled([_dispatcherRenderApproval(),refreshDispatcherGit(),refreshDispatcherEvidence(),refreshDispatcherLineage()]);
}

async function loadDispatcher(){
  await _dispatcherEnsureSession();
  if(typeof renderMessages==='function')renderMessages();
  const source=$('messages');
  if(source&&typeof MutationObserver==='function'){
    if(_dispatcherTimelineObserver)_dispatcherTimelineObserver.disconnect();
    _dispatcherTimelineObserver=new MutationObserver(()=>{if(_currentPanel==='dispatcher'){_dispatcherCloneTimeline();_dispatcherRenderOutputs();_dispatcherRenderRuntime();}});
    _dispatcherTimelineObserver.observe(source,{childList:true,subtree:true,characterData:true});
  }
  clearInterval(_dispatcherRefreshTimer);_dispatcherRefreshTimer=setInterval(()=>refreshDispatcher(),3000);
  await refreshDispatcher(true);
  const input=$('dispatcherInput');if(input)setTimeout(()=>input.focus(),30);
}

function leaveDispatcher(){clearInterval(_dispatcherRefreshTimer);_dispatcherRefreshTimer=null;if(_dispatcherTimelineObserver)_dispatcherTimelineObserver.disconnect();}
async function sendDispatcherMission(){
  const input=$('dispatcherInput');const text=String(input&&input.value||'').trim();if(!text||!S||S.busy)return;
  const context=_dispatcherContext();const prompt=context.length?`Pinned workspace context:\n${context.map(path=>'- '+path).join('\n')}\n\n${text}`:text;
  input.value='';if(typeof send==='function')await send(prompt,{fromDispatcher:true});
}
async function dispatcherRetryLastTurn(){if(!S||S.busy||typeof cmdRetry!=='function')return;await cmdRetry();await refreshDispatcher(true);}
async function dispatcherUndoLastTurn(){if(!S||S.busy||typeof cmdUndo!=='function')return;await cmdUndo();await refreshDispatcher(true);}
async function dispatcherContinueHaltedTurn(){
  const reason=_dispatcherHaltReason();if(!reason||!S||S.busy||typeof send!=='function')return;
  await send(`Continue the halted mission from the current session state. The prior runtime stop was: ${reason}. Review completed work first, avoid repeating successful tool calls, and finish the remaining work.`,{fromDispatcher:true});
  await refreshDispatcher(true);
}
function dispatcherOpenInChat(){if(typeof switchPanel==='function')switchPanel('chat');}
function dispatcherOpenPanel(name){if(typeof switchPanel==='function')switchPanel(name);}

window.loadDispatcher=loadDispatcher;window.leaveDispatcher=leaveDispatcher;window.refreshDispatcher=refreshDispatcher;window.refreshDispatcherGit=refreshDispatcherGit;window.refreshDispatcherEvidence=refreshDispatcherEvidence;window.refreshDispatcherLineage=refreshDispatcherLineage;window.sendDispatcherMission=sendDispatcherMission;window.dispatcherRetryLastTurn=dispatcherRetryLastTurn;window.dispatcherUndoLastTurn=dispatcherUndoLastTurn;window.dispatcherContinueHaltedTurn=dispatcherContinueHaltedTurn;window.dispatcherPinWorkspace=dispatcherPinWorkspace;window.dispatcherUnpinContext=dispatcherUnpinContext;window.dispatcherOpenInChat=dispatcherOpenInChat;window.dispatcherOpenPanel=dispatcherOpenPanel;
