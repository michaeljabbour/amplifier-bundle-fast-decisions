/* Read-only event projection. No generated events, animation clock or inferred savings. */
(() => {
  'use strict';
  const kind = e => e.event.replace('fast_decisions:', '');
  const native = e => e.data.native_event || '';
  const decisionKey = e => e.session_id + ':' + e.decision_id;
  const isScore = e => ['scored', 'shadow_proposed'].includes(kind(e));
  const stamp = e => Date.parse(e.timestamp) || 0;
  const fmt = n => Number.isFinite(n) ? (n >= 1000 ? (n / 1000).toFixed(2) + ' s' : Math.round(n) + ' ms') : '—';
  const pretty = s => String(s || '').replaceAll('_', ' ');
  const valid = e => e && e.schema_version === '1.0' && typeof e.event_id === 'string' && typeof e.session_id === 'string' && typeof e.event === 'string' && e.event.startsWith('fast_decisions:') && e.data && typeof e.data === 'object' && !Array.isArray(e.data);
  function scriptedKeys(events) {
    return new Set(events.filter(e => e.decision_id && (e.synthetic || e.data.synthetic || (isScore(e) && e.data.backend === 'scripted-demo'))).map(decisionKey));
  }
  const synthetic = (e, keys) => !!(e.synthetic || e.data.synthetic || (e.decision_id && !['health','observatory'].includes(kind(e)) && keys.has(decisionKey(e))));
  const issue = e => ['provider:error','provider:retry'].includes(native(e)) || ['error','cancelled'].includes(e.data.status) || kind(e) === 'fallback';
  const useful = e => kind(e) !== 'health' || native(e) || e.data.reason_code || ['configuration','session_closed'].includes(e.data.phase);
  const backendName = b => ({'scripted-demo':'Scripted scorer',deterministic:'Scripted scorer','ollama-token':'Local model',ollama:'Local model',jev:'Jev',unavailable:'No scorer'}[b] || b || 'Backend not recorded');
  function configFor(events, id) {
    return events.filter(e => e.session_id === id && (e.data.phase === 'configuration' || kind(e) === 'turn_start')).reduce((config,e)=>({...config,...e.data}),{});
  }
  function sessionsFor(events, now) {
    const map = new Map();
    for (const e of events) {
      let s = map.get(e.session_id);
      if (!s) { s = {id:e.session_id, parent:null, events:[], latest:e, config:{}}; map.set(s.id,s); }
      s.events.push(e);
      if (e.parent_session_id) s.parent = e.parent_session_id;
      if (stamp(e) >= stamp(s.latest)) s.latest = e;
      if (e.data.phase === 'configuration' || kind(e) === 'turn_start') s.config = {...s.config,...e.data};
    }
    for (const s of map.values()) {
      const life = s.events.findLast(e => ['execution:start','execution:end','session:end','provider:error','provider:retry'].includes(native(e)) || ['turn_start','turn_end'].includes(kind(e)) || e.data.phase === 'session_closed');
      const beat = s.events.findLast(e => ['session_heartbeat','configuration'].includes(e.data.phase));
      const closed = life && (life.data.phase === 'session_closed' || native(life) === 'session:end');
      s.reporting = !closed && !!beat && now - stamp(beat) < 45000;
      s.state = closed ? 'Session closed' : !s.reporting ? 'No recent heartbeat' : !life ? 'Connected, idle' : issue(life) ? 'Provider issue reported' : ['execution:end'].includes(native(life)) || kind(life)==='turn_end' ? 'Connected, idle' : 'Working';
    }
    return [...map.values()].sort((a,b) => stamp(b.latest)-stamp(a.latest));
  }
  function metrics(events) {
    const scores=events.filter(isScore), fast=new Set(events.filter(e=>kind(e)==='routed'&&e.data.route==='fast').map(decisionKey));
    const executions=events.filter(e=>kind(e)==='tool_end'&&(e.data.success===true||e.data.status==='ok'));
    const nativePosts=events.filter(e=>native(e)==='tool:post');
    const postSessions=new Set(nativePosts.map(e=>e.session_id));
    const durations=scores.map(e=>e.data.duration_ms).filter(Number.isFinite).sort((a,b)=>a-b);
    return {scores:scores.length,fast:fast.size,fastExecuted:executions.filter(e=>fast.has(decisionKey(e))).length,
      tools:nativePosts.length+executions.filter(e=>!postSessions.has(e.session_id)).length,
      issues:events.filter(issue).length,p95:durations.length?durations[Math.ceil(durations.length*.95)-1]:NaN};
  }
  function decisionPath(events, session, selected) {
    const focus = events.find(e => e.event_id === selected && e.decision_id && e.session_id === session)
      || events.findLast(e => e.session_id === session && e.decision_id && kind(e) === 'scored')
      || events.findLast(e => e.session_id === session && e.decision_id && kind(e) === 'requested')
      || events.findLast(e => e.session_id === session && e.decision_id && isScore(e));
    if (!focus) return [];
    const stages = new Set(['requested','scored','shadow_proposed','shadow_observed','routed','fallback','tool_start','tool_end','slow_start','slow_end','shadow_agreement']);
    return events.filter(e => decisionKey(e) === decisionKey(focus) && stages.has(kind(e)))
      .sort((a,b) => stamp(a)-stamp(b) || (a.seq||0)-(b.seq||0));
  }
  function describe(e, simulated=false) {
    const k=kind(e), d=e.data, n=native(e);
    let title=pretty(k), detail=d.reason_code?pretty(d.reason_code):d.status||'Recorded metadata', source='Runtime record', tone='runtime';
    if(n){title=({'execution:start':'Turn started','execution:end':'Turn finished','session:end':'Session ended','provider:request':'Provider request','provider:retry':'Provider retry','provider:error':'Provider error','tool:pre':'Tool proposed','tool:post':'Tool result observed','context:compaction':'Context compaction observed','llm:response':'Provider response observed'}[n]||n);detail=[d.tool||d.provider,d.exception_type,d.retry_attempt?'Attempt '+d.retry_attempt:'',d.status_code?'HTTP '+d.status_code:''].filter(Boolean).join(' · ')||'Reported by an Amplifier hook';source='Native hook observation';}
    if(d.phase==='configuration'){title='Bundle mounted';detail=backendName(d.backend)+' · '+(d.mode||'Mode not recorded');source='Runtime configuration';}
    if(d.phase==='session_closed'){title='Telemetry session closed';detail='The bundle observer was unmounted.';}
    if(k==='requested'){title='Decision requested';detail=(d.candidate_count??'?')+' prepared candidates';source='Decision service';tone='decision';}
    if(isScore(e)){title=k==='shadow_proposed'?'Shadow proposal scored':'Decision scored';detail=d.model||backendName(d.backend);source=simulated?'Scripted score': 'Model score';tone='decision';}
    if(k==='routed'){title=d.route==='fast'?'Fast action submitted':'Reasoning provider selected';detail=pretty(d.reason_code);source='Routing decision';tone='decision';}
    if(k==='tool_start'){title='Tool execution started';detail=d.tool||'Tool not recorded';source='Measured execution';}
    if(k==='tool_end'){title=d.success===false||d.status==='error'?'Tool execution failed':'Tool execution '+(d.status==='ok'?'completed':(d.status||'ended'));detail=d.tool||'Tool not recorded';source='Measured execution';}
    if(k==='slow_start'||k==='slow_end'){title=k==='slow_start'?'Model invocation started':'Model invocation ended';detail=d.provider||d.model||'Provider not recorded';source='Measured invocation';}
    if(k==='shadow_observed'){title='Tool choice observed';detail=d.tool||'Tool not recorded';source='Shadow observation';}
    if(k==='shadow_agreement'){title='Shadow comparison: '+pretty(d.agreement);detail='Compared with the observed tool choice; no execution changed.';source='Shadow comparison';}
    if(k==='role_proposed'||k==='role_agreement'){title='Model-role '+(k==='role_proposed'?'suggestion':'comparison');detail='Shadow only; provider selection is unchanged.';source='Shadow comparison';}
    if(d.reason_code==='no_eligible_candidates'){title='No prepared action available';detail='The request did not produce an eligible candidate.';}
    if(k==='turn_start'){title='Hybrid turn started';detail=backendName(d.backend)+' · '+d.mode;}
    if(k==='turn_end'){title='Hybrid turn finished';detail=(d.fast_total??0)+' fast submissions · '+(d.slow_total??0)+' measured provider calls';}
    if(k==='observatory'){title='Viewer '+(d.action||'event');detail=pretty(d.reason)||'Viewer lifecycle metadata';}
    if(issue(e))tone='error';
    if(simulated){source='Synthetic / scripted';tone='synthetic';}
    return {title,detail,source,tone};
  }
  // Pure projections are exported for regression tests; browser code remains dependency-free.
  if(typeof module!=='undefined')module.exports={kind,valid,scriptedKeys,synthetic,sessionsFor,metrics,describe,decisionPath};
  if(typeof document==='undefined')return;
  const $=id=>document.getElementById(id), put=(id,text)=>{$(id).textContent=text;};
  const make=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
  let events=[],seen=new Set(),cursor=0,epoch=null,session='',selected=null,category='activity',following=true,source='live',lastPoll=0,connectionError='',retained=0,invalidLines=0,windowGap=false,hasMore=false;
  let frozenIds=null,expanded=new Set(),token='',pollTimer=null,pollGeneration=0;
  const tokenKey='afast-token:'+location.host;
  try {token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem(tokenKey)||'';if(token)sessionStorage.setItem(tokenKey,token);}catch(_){}
  if(location.hash.startsWith('#token='))history.replaceState(null,'',location.pathname+location.search);
  const age=t=>{const n=Math.max(0,Math.floor((Date.now()-t)/1000));return n<5?'just now':n<60?n+'s ago':n<3600?Math.floor(n/60)+'m ago':n<86400?Math.floor(n/3600)+'h ago':Math.floor(n/86400)+'d ago';};
  const clock=e=>new Date(e.timestamp).toLocaleTimeString([],{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  function ingest(batch){for(const e of batch)if(valid(e)&&!seen.has(e.event_id)){seen.add(e.event_id);events.push(e);}events.sort((a,b)=>stamp(a)-stamp(b)||(a.session_id===b.session_id?(a.seq||0)-(b.seq||0):0));if(events.length>20000){events=events.slice(-20000);seen=new Set(events.map(e=>e.event_id));}render();}
  function currentWindow(){const limit=$('timeWindow').value;return events.filter(e=>(limit==='all'||Date.now()-stamp(e)<=Number(limit))&&(!frozenIds||frozenIds.has(e.event_id)));}
  function scopeData(base){const children=$('includeChildren').checked;const parents=new Map(events.filter(e=>e.parent_session_id).map(e=>[e.session_id,e.parent_session_id]));const descendant=id=>{const visited=new Set();while(parents.has(id)&&!visited.has(id)){visited.add(id);id=parents.get(id);if(id===session)return true;}return false;};return base.filter(e=>session?(e.session_id===session||(children&&descendant(e.session_id))):(children||!parents.has(e.session_id)));}
  function selectSession(id){session=id;selected=null;render();}
  function renderSessions(base,keys){
    const sessions=sessionsFor(base,Date.now()), map=new Map(sessions.map(s=>[s.id,s]));
    const roots=sessions.filter(s=>!s.parent), orphans=sessions.filter(s=>s.parent&&!map.has(s.parent));
    for(const child of orphans)if(!roots.some(s=>s.id===child.parent))roots.push({id:child.parent,parent:null,events:[],latest:child.latest,config:{},state:'Parent not observed',reporting:false});
    const search=$('sessionSearch').value.toLowerCase();
    put('sessionCount',roots.length);put('allSessionCount',roots.length);
    $('allSessions').classList.toggle('selected',!session);$('allSessions').setAttribute('aria-pressed',String(!session));
    const target=$('sessions');target.replaceChildren();
    function row(s,child=false){const button=make('button','session-row'+(s.id===session?' selected':'')+(child?' child':''));button.setAttribute('aria-pressed',String(s.id===session));button.title=s.id;button.dataset.sessionId=s.id;const top=make('span','session-top');top.append(make('span','session-name',s.config.session_label||s.id.slice(0,8)),make('span','session-age',age(stamp(s.latest))));button.append(top,make('span','session-config',s.config.mode?backendName(s.config.backend)+' / '+s.config.mode:'Configuration not recorded'),make('span','session-state'+(s.state==='Provider issue reported'?' issue':''),s.state));button.onclick=()=>selectSession(s.id);return button;}
    function group(s,level=0,visited=new Set()){if(visited.has(s.id))return null;visited=new Set([...visited,s.id]);const kids=sessions.filter(x=>x.parent===s.id);const matches=[s,...kids].some(x=>(x.id+' '+(x.config.session_label||'')).toLowerCase().includes(search));if(!matches)return null;const wrap=make('div','session-group');wrap.append(row(s,level>0));if(kids.length){const toggle=make('button','children-toggle',(expanded.has(s.id)?'Hide ':'Show ')+kids.length+' child session'+(kids.length===1?'':'s'));toggle.dataset.childrenId=s.id;toggle.setAttribute('aria-expanded',String(expanded.has(s.id)));toggle.onclick=()=>{expanded.has(s.id)?expanded.delete(s.id):expanded.add(s.id);render();};wrap.append(toggle);if(expanded.has(s.id))for(const child of kids){const g=group(child,level+1,visited);if(g)wrap.append(g);}}return wrap;}
    for(const s of roots){const g=group(s);if(g)target.append(g);}
    if(!roots.length)target.append(make('p','session-config','No parent sessions in this window.'));
    return sessions;
  }
  function renderDetails(e,keys){
    $('detailEmpty').hidden=!!e;$('detailContent').hidden=!e;
    if(!e){put('evidenceKind','No selection');return;}
    const simulated=synthetic(e,keys), info=describe(e,simulated), d=e.data;
    put('evidenceKind',info.source);$('evidenceKind').className='tag '+info.tone;
    put('detailTitle',info.title);put('detailDescription',info.detail);
    const cfg=configFor(events,e.session_id), related=e.decision_id?events.filter(x=>decisionKey(x)===decisionKey(e)):[e];
    const score=related.findLast(isScore), request=related.find(x=>kind(x)==='requested');
    const facts=[['Session',e.session_id],...(e.parent_session_id?[['Parent session',e.parent_session_id]]:[]),['Recorded',new Date(e.timestamp).toLocaleString()],['Event',e.event],['Source',info.source],...(d.tool_call_id?[['Tool call',d.tool_call_id]]:[]),...(e.decision_id?[['Decision',e.decision_id]]:[]),...(Number.isFinite(d.duration_ms)?[['Measured duration',fmt(d.duration_ms)]]:[]),...(d.reason_code?[['Reason code',pretty(d.reason_code)]]:[])];
    $('eventFacts').replaceChildren();for(const [label,value] of facts){const row=make('div');row.append(make('dt','',label),make('dd','',value));$('eventFacts').append(row);}
    put('sessionConfig',cfg.mode?backendName(cfg.backend)+' in '+cfg.mode+' mode. '+(cfg.backend==='scripted-demo'?'Scores are scripted; no model is connected to this scorer.':cfg.mode==='shadow'?'Proposals do not change execution.':'Fast selections still pass native approval.'):'No configuration event is available for this session.');
    $('distribution').hidden=!score;$('probabilities').replaceChildren();
    if(score){put('scoreMeaning',synthetic(score,keys)?'Scripted values. These did not come from a model.':score.data.probability_kind==='token_mass_with_abstention_residual'?'Uncalibrated token scores. They do not measure correctness.':'Backend-reported scores; not independent evidence of correctness.');const names=new Map((request?.data.candidates||[]).map(c=>[c.id,c.label]));names.set('reason','Use reasoning model');for(const [id,p] of Object.entries(score.data.probabilities||{}).filter(([,p])=>Number.isFinite(p)).sort((a,b)=>b[1]-a[1])){const row=make('div','prob-row'), caption=make('div','prob-label'), track=make('div','prob-track'), fill=make('div','prob-fill');caption.append(make('span','',names.get(id)||id),make('span','',(p*100).toFixed(1)+'%'));fill.style.width=Math.max(0,Math.min(100,p*100))+'%';track.append(fill);row.append(caption,track);$('probabilities').append(row);}}
    put('eventJson',JSON.stringify(e,null,2));
  }
  function renderMechanics(scoped, keys) {
    $('mechanics').hidden=!session;
    const path=decisionPath(scoped,session,selected);
    $('decisionPath').replaceChildren();
    put('pathNote',path.length?'Decision '+path[0].decision_id+' · recorded sequence in this session. Select a stage to inspect its evidence.':'No scored decision path recorded in this window. Native activity is listed below.');
    for(const e of path){
      const info=describe(e,synthetic(e,keys)), node=make('button','path-stage '+info.tone+(e.event_id===selected?' selected':''));
      node.dataset.stageId=e.event_id;node.setAttribute('aria-pressed',String(e.event_id===selected));
      node.append(make('span','path-time',clock(e)),make('strong','',info.title),make('span','',info.detail));
      if(Number.isFinite(e.data.duration_ms))node.append(make('span','path-duration',fmt(e.data.duration_ms)));
      node.onclick=()=>{selected=e.event_id;render();};$('decisionPath').append(node);
    }
  }
  function render(){
    const focused=document.activeElement;
    const focusKey=['eventId','sessionId','childrenId','stageId'].find(key=>focused?.dataset?.[key]);
    const focusValue=focusKey?focused.dataset[focusKey]:null;
    const keys=scriptedKeys(events), base=currentWindow(), realBase=base.filter(e=>!synthetic(e,keys));
    const sessions=renderSessions($('includeSynthetic').checked?base:realBase,keys);
    const scoped=scopeData(base), hidden=scoped.filter(e=>synthetic(e,keys)).length;
    const real=scoped.filter(e=>!synthetic(e,keys)), m=metrics(real);
    put('modelCount',m.scores);put('fastCount',m.fast);put('toolCount',m.tools);put('errorCount',m.issues);put('fastExecuted',m.fastExecuted);put('scorerP95',fmt(m.p95));
    put('impactDetail',m.fastExecuted?'Confirmed tool executions after a fast submission. Whole-task time saved has not been measured.':m.fast?'Fast actions were submitted. No successful fast-path tool execution is recorded in this window.':'No executed fast path recorded in this window. Shadow suggestions do not change execution.');
    put('scopeNotice','Counts exclude scripted/demo events. Tool results may be hook observations; only instrumented execution proves a completed fast path.');
    const cfg=session?configFor(events,session):null;
    put('viewTitle',session?(cfg.session_label||'Session '+session.slice(0,8)):'Across parent sessions');
    put('viewSubtitle',session?(cfg.mode?backendName(cfg.backend)+' / '+cfg.mode:'Configuration not recorded'):'Runtime activity from '+sessions.filter(s=>!s.parent&&s.reporting).length+' parent session(s) currently reporting.');
    put('syntheticCount',hidden?'('+hidden+($('includeSynthetic').checked?' shown)':' hidden)'):'');
    const display=scoped.filter(e=>($('includeSynthetic').checked||!synthetic(e,keys))&&useful(e)&&(category==='decisions'?['requested','scored','routed','shadow_proposed','shadow_agreement','role_proposed','role_agreement','fallback'].includes(kind(e)):category==='errors'?issue(e):true));
    const rows=display.slice(-250).reverse();$('feed').replaceChildren();
    if(selected&&!scoped.some(e=>e.event_id===selected&&($('includeSynthetic').checked||!synthetic(e,keys))))selected=null;
    for(const e of rows){const info=describe(e,synthetic(e,keys)), button=make('button','event-row'+(selected===e.event_id?' selected':''));button.setAttribute('aria-pressed',String(selected===e.event_id));button.dataset.eventId=e.event_id;const icon=make('span','event-icon '+info.tone,info.tone==='error'?'!':info.tone==='decision'?'◆':info.tone==='synthetic'?'~':'·'),body=make('span');body.append(make('span','event-title',info.title),make('span','event-description',info.detail),make('span','event-source',info.source));const when=make('span','event-time',clock(e));if(Number.isFinite(e.data.duration_ms))when.append(make('span','event-duration',fmt(e.data.duration_ms)));button.append(icon,body,make('span','event-session',e.session_id.slice(0,8)),when);button.onclick=()=>{selected=e.event_id;render();};$('feed').append(button);}
    $('emptyState').hidden=rows.length>0;
    put('emptyTitle',connectionError?'Connection needs attention':hidden?'Scripted events are hidden':category==='errors'?'No issues recorded':'No activity in this window');
    put('emptyDetail',connectionError?'Restore the viewer connection above. Existing records remain available.':hidden?'Enable scripted & demo events to inspect them. They never count as model decisions or measured improvements.':source!=='live'?'This is a saved trace. Try another category or session.':'The viewer is listening. Start a turn in a session with the bundle loaded, or widen the time window.');
    put('feedCount',display.length>250?'Latest 250 of '+display.length+' events':display.length+' events');
    put('dataHealth',invalidLines?invalidLines+' invalid records skipped':windowGap?'Older events expired from the retained window':'No prompts or tool contents.');
    put('freshness',source!=='live'?'Saved trace · no live updates':lastPoll?'Checked '+age(lastPoll)+' · last event '+(events.length?age(stamp(events.at(-1))):'not received'):'Waiting for first response');
    put('followBtn',source!=='live'?'Return to live':following?'Following live':'Resume live');$('followBtn').setAttribute('aria-pressed',String(source==='live'&&following));
    renderMechanics(scoped.filter(e=>$('includeSynthetic').checked||!synthetic(e,keys)),keys);
    renderDetails(events.find(e=>e.event_id===selected),keys);
    if(source!=='live'){put('connection','Saved trace');$('connection').className='connection replay';}
    else if(connectionError){put('connection','Disconnected');$('connection').className='connection problem';}
    else {put('connection',lastPoll?(hasMore?'Syncing history':following?'Connected':'Connected · paused'):'Connecting');$('connection').className='connection'+(lastPoll?' connected':'');}
    $('connectionNotice').hidden=!connectionError;put('connectionNotice',connectionError);
    if(focusKey){const replacement=[...document.querySelectorAll('button')].find(node=>node.dataset[focusKey]===focusValue);replacement?.focus({preventScroll:true});}
  }
  $('allSessions').onclick=()=>selectSession('');$('sessionSearch').oninput=render;
  for(const id of ['timeWindow','includeSynthetic','includeChildren'])$(id).onchange=()=>{selected=null;render();};
  document.querySelectorAll('[data-filter]').forEach(b=>{b.onclick=()=>{category=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b));});render();};});
  $('followBtn').onclick=()=>{if(source!=='live'){pollGeneration++;source='live';events=[];seen.clear();cursor=0;epoch=null;selected=null;session='';following=true;frozenIds=null;$('timeWindow').value='3600000';schedule(0);}else{following=!following;frozenIds=following?null:new Set(events.map(e=>e.event_id));}render();};
  $('loadBtn').onclick=()=>$('fileInput').click();
  $('fileInput').onchange=async()=>{try{const batch=[];for(const file of $('fileInput').files){const text=await file.text();batch.push(...(text.trim().startsWith('[')?JSON.parse(text):text.split(/\r?\n/).filter(Boolean).map(JSON.parse)));}pollGeneration++;clearTimeout(pollTimer);source='file';events=[];seen.clear();selected=null;session='';frozenIds=null;following=false;connectionError='';$('reconnectPanel').hidden=true;$('timeWindow').value='all';ingest(batch);}catch(_){connectionError='Could not read this trace. Choose a JSON array or a JSONL event file.';render();}};
  $('exportBtn').onclick=()=>{const keys=scriptedKeys(events),data=scopeData(currentWindow()).filter(e=>$('includeSynthetic').checked||!synthetic(e,keys)), blob=new Blob([data.map(e=>JSON.stringify(e)).join('\n')+'\n'],{type:'application/x-ndjson'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='amplifier-events.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  $('connectForm').onsubmit=e=>{e.preventDefault();try{const url=new URL($('viewerLink').value);if(url.origin!==location.origin)throw Error();const value=new URLSearchParams(url.hash.slice(1)).get('token');if(!value)throw Error();pollGeneration++;token=value;try{sessionStorage.setItem(tokenKey,token);}catch(_){}$('viewerLink').value='';connectionError='';$('reconnectPanel').hidden=true;schedule(0);}catch(_){connectionError='Use the full viewer link for this same local address and port.';render();}};
  function schedule(delay){clearTimeout(pollTimer);pollTimer=setTimeout(poll,delay);}
  async function poll(){
    if(source!=='live')return;
    if(!token){connectionError='This tab has no viewer access token. Reopen the full launching link or reconnect below.';$('reconnectPanel').hidden=false;render();return;}
    const generation=++pollGeneration;
    try{const response=await fetch('/api/events?after='+cursor,{headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(5000)});
      if(source!=='live'||generation!==pollGeneration)return;
      if(!response.ok){if(response.status===401){$('reconnectPanel').hidden=false;throw Error('The viewer link has expired or is missing its access token. Reopen the launching link.');}throw Error('The local viewer returned HTTP '+response.status+'. Retrying…');}
      const payload=await response.json();
      if(source!=='live'||generation!==pollGeneration)return;
      if(epoch&&epoch!==payload.epoch){events=[];seen.clear();cursor=0;epoch=payload.epoch;selected=null;windowGap=false;schedule(0);return;}
      if(cursor&&payload.first_cursor>cursor+1)windowGap=true;
      epoch=payload.epoch;cursor=payload.cursor;retained=payload.retained;invalidLines=payload.invalid_lines||0;hasMore=!!payload.has_more;lastPoll=Date.now();connectionError='';$('reconnectPanel').hidden=true;ingest(payload.events||[]);
    }catch(error){if(source!=='live'||generation!==pollGeneration)return;connectionError=error.name==='TimeoutError'?'The viewer did not respond within 5 seconds. Retrying…':error instanceof TypeError?'Cannot reach the local viewer. Retrying…':error.message;render();}
    if(source==='live'&&generation===pollGeneration)schedule(connectionError?2000:hasMore?0:500);
  }
  if(window.AFAST_EMBEDDED){source='embedded';following=false;$('timeWindow').value='all';ingest(window.AFAST_EMBEDDED);}
  else {render();schedule(0);}
})();
