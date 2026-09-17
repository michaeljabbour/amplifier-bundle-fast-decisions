/* No dependencies, no remote assets, no control-plane write endpoint. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let events = [], seen = new Set(), pointer = -1, live = false, playing = false;
  let selectedId = null, cursor = 0, epoch = null, timer = null, session = '', source = 'live';
  const tokenParams = new URLSearchParams(location.hash.slice(1));
  const tokenKey = 'afast-token:' + location.host;
  let token = tokenParams.get('token');
  try { if(token) sessionStorage.setItem(tokenKey, token); else token = sessionStorage.getItem(tokenKey); } catch (_) {}
  if(location.hash.startsWith('#token=')) history.replaceState(null, '', location.pathname + location.search);
  const label = event => event.event.replace('fast_decisions:', '');
  const fmt = ms => Number.isFinite(ms) ? (ms >= 1000 ? (ms/1000).toFixed(2)+' s' : ms.toFixed(0)+' ms') : 'Not observed';
  const med = values => { const a=values.filter(Number.isFinite).sort((x,y)=>x-y); return a.length ? (a[Math.floor((a.length-1)/2)] + a[Math.floor(a.length/2)])/2 : NaN; };
  const pretty = text => String(text || '').replaceAll('_', ' ');
  const time = event => { const date=new Date(event.timestamp); return isNaN(date) ? '' : date.toLocaleTimeString([], {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'}) + '.' + String(date.getMilliseconds()).padStart(3,'0'); };
  function put(id, text) { $(id).textContent = text; }
  function filtered() { return session ? events.filter(e=>e.session_id===session) : events; }
  function visible() { return filtered().slice(0, pointer+1); }
  function valid(e) { return e && e.schema_version==='1.0' && typeof e.event_id==='string' && typeof e.event==='string' && e.event.startsWith('fast_decisions:') && typeof e.session_id==='string' && e.data && typeof e.data==='object'; }
  function ingest(batch) {
    for(const e of batch) if(valid(e) && !seen.has(e.event_id)) { events.push(e); seen.add(e.event_id); }
    if(events.length > 20000) { events=events.slice(-20000); seen=new Set(events.map(e=>e.event_id)); }
    updateSessions();
    if(live) pointer=filtered().length-1;
    render();
  }
  function updateSessions() {
    const ids=[...new Set(events.map(e=>e.session_id))];
    if($('session').options.length===ids.length+1) return;
    $('session').replaceChildren(new Option('All sessions',''));
    for(const id of ids) { const event=events.find(e=>e.session_id===id); const parent=event?.parent_session_id; $('session').add(new Option((parent?'Child: ':'')+id.slice(0,24)+(parent?' → '+parent.slice(0,12):''),id)); }
    $('session').value=session;
  }
  function notice() {
    const demo=filtered().some(e=>e.synthetic||e.data.synthetic);
    $('notice').classList.toggle('demo',demo);
    put('notice', demo ? 'SYNTHETIC DEMO. Real routing code with scripted models, tools, and loop fixtures. These timings are not Jev benchmarks.' : 'Read-only telemetry. Metadata only; no prompts, tool contents, or private reasoning. This interface cannot authorize actions.');
  }
  function counts(data) {
    const scored=data.filter(e=>label(e)==='scored');
    const routes=new Map(); for(const e of data) if(label(e)==='routed') routes.set(e.decision_id,e);
    const slow=data.filter(e=>label(e)==='slow_start');
    const completed=data.filter(e=>label(e)==='tool_end');
    put('mDecisions',scored.length);
    put('mFast',[...routes.values()].filter(e=>e.data.route==='fast').length);
    put('mSlow',slow.length);
    put('mTools',completed.filter(e=>e.data.status==='ok').length);
    put('mDecisionLatency','Decision median: '+fmt(med(scored.map(e=>e.data.duration_ms))));
    put('mSlowLatency','Provider median: '+fmt(med(data.filter(e=>label(e)==='slow_end').map(e=>e.data.duration_ms))));
    const errors=completed.filter(e=>e.data.status!=='ok').length;
    put('mToolsFoot', errors ? errors+' failed or cancelled executions' : 'Measured at actual execute()');
    const drops=Math.max(0,...data.map(e=>e.data.dropped_events||0));
    put('health', drops ? 'Warning: '+drops+' recorder events dropped' : 'Local / read-only / metadata only');
  }
  function graph(event) {
    document.querySelectorAll('.edges path').forEach(e=>e.classList.remove('active-fast','active-slow','active-neutral'));
    document.querySelectorAll('.node').forEach(e=>e.classList.remove('active'));
    if(!event) { put('routeTitle','Waiting for events'); put('routeDetail','No event at this replay position.'); put('eventTime',''); return; }
    const type=label(event), d=event.data;
    const activate=(nodes,edges,style)=>{for(const id of nodes) $('node-'+id)?.classList.add('active');for(const id of edges) $('edge-'+id)?.classList.add('active-'+style);};
    if(type==='requested') activate(['state','gate','jev'],['state','fast'],'fast');
    else if(type==='scored') activate(['jev'],['fast'],'fast');
    else if(type==='routed'&&d.route==='fast') activate(['jev','policy','executor'],['policy','execute-fast'],'fast');
    else if(type==='routed'||type==='slow_start'||type==='slow_end'||type==='fallback') activate(['slow'],['slow',...(type==='slow_end'?['execute-slow']:[])],'slow');
    else if(type==='tool_start') activate(['executor'],[],'neutral');
    else if(type==='tool_end') activate(['executor','state'],['feedback'],'neutral');
    else activate(['state'],['state'],'neutral');
    let title=pretty(type), detail=d.reason_code?pretty(d.reason_code):d.status||'';
    if(type==='routed') { title=d.route==='fast'?'Fast action submitted to upstream':'Routed to the reasoning provider'; if(d.shadow) detail='Shadow suggestion only. The actual route remains slow.'; }
    if(type==='scored') title='Candidate distribution returned';
    if(type==='tool_start') title='Tool execution actually started';
    if(type==='tool_end') title='Tool execution '+(d.status==='ok'?'completed':d.status);
    if(type==='slow_start') title='Generative provider call started';
    if(type==='slow_end') title='Generative provider call '+d.status;
    put('routeTitle',title); put('routeDetail',detail||d.destination||d.tool||'Observed event'); put('eventTime',time(event));
    $('routeDot').className='dot '+(d.route==='fast'||['scored','requested'].includes(type)?'fast':type.startsWith('slow')||d.route==='slow'?'slow':'neutral');
  }
  function inspect(event,data) {
    if(!event) { put('modeBadge','NO EVENT'); put('reason','No route selected'); put('destination','Not observed'); put('decisionLatency','Not observed'); put('confidence',''); $('probabilities').replaceChildren(); put('eventJson','{}'); return; }
    const related=event.decision_id ? data.filter(e=>e.decision_id===event.decision_id) : [event];
    const scored=related.findLast(e=>label(e)==='scored');
    const requested=related.find(e=>label(e)==='requested');
    const route=related.findLast(e=>label(e)==='routed');
    const slow=related.findLast(e=>label(e).startsWith('slow_'));
    const d=route?.data||event.data;
    put('modeBadge',(d.mode||event.data.mode||'OBSERVED').toUpperCase());
    $('modeBadge').classList.toggle('warn',d.mode==='shadow');
    put('reason',pretty(d.reason_code||event.data.status||label(event)));
    put('destination',d.route==='slow' ? (slow?.data.provider||'Existing provider') : d.destination||event.data.tool||'Not observed');
    put('decisionLatency',fmt(scored?.data.duration_ms));
    put('confidence',Number.isFinite(scored?.data.selected_probability)?'p = '+scored.data.selected_probability.toFixed(3):'');
    const target=$('probabilities'); target.replaceChildren();
    if(scored) {
      const names=new Map((requested?.data.candidates||[]).map(c=>[c.id,c.label])); names.set('reason','Use reasoning model');
      const rows=Object.entries(scored.data.probabilities||{}).sort((a,b)=>b[1]-a[1]);
      for(const [id,p] of rows) {
        const row=document.createElement('div'), caption=document.createElement('div');caption.className='prob-label';
        const text=document.createElement('span');text.textContent=names.get(id)||id;
        const percent=document.createElement('span');percent.textContent=(p*100).toFixed(1)+'%';caption.append(text,percent);
        const track=document.createElement('div');track.className='prob-track';const fill=document.createElement('div');fill.className='prob-fill'+(id===scored.data.choice?' selected':'')+(id==='reason'?' slow':'');fill.style.width=Math.max(0,Math.min(100,p*100))+'%';track.append(fill);row.append(caption,track);target.append(row);
      }
    } else { const empty=document.createElement('div');empty.className='empty';empty.textContent='No model distribution for this event. Deterministic routing does not need one.';target.append(empty); }
    put('eventJson',JSON.stringify(event,null,2));
  }
  function timeline(data) {
    const filter=$('eventFilter').value;
    const rows=data.filter(e=>filter==='all'||filter==='fallback'?(filter==='all'||label(e)==='fallback'||['decision_timeout','selection_threshold','backend_error','model_abstained','backend_circuit_open'].includes(e.data.reason_code)):filter==='tool'?label(e).startsWith('tool_'):label(e)!=='health');
    put('traceCount',rows.length+' events');
    const tbody=$('timeline');tbody.replaceChildren();
    for(const event of rows.slice(-100).reverse()) {
      const d=event.data,tr=document.createElement('tr');tr.tabIndex=0;tr.dataset.eventId=event.event_id;tr.classList.toggle('selected',event.event_id===selectedId);
      const values=[time(event),pretty(label(event)),d.destination||d.provider||d.tool||d.route||'',pretty(d.reason_code||d.status||''),Number.isFinite(d.duration_ms)?fmt(d.duration_ms):'',(event.decision_id||'').slice(0,8)];
      values.forEach((value,i)=>{const td=document.createElement('td');if(i===1){const pill=document.createElement('span');pill.className='pill'+(d.route==='fast'?' fast':d.route==='slow'||label(event).startsWith('slow')?' slow':'');pill.textContent=value;td.append(pill);}else td.textContent=value;if(i===0||i===4||i===5)td.classList.add('mono');tr.append(td);});
      const choose=()=>{selectedId=event.event_id;render();};tr.addEventListener('click',choose);tr.addEventListener('keydown',e=>{if(e.key==='Enter')choose();});tbody.append(tr);
    }
  }
  function render() {
    const all=filtered();pointer=Math.min(pointer,all.length-1);const data=visible();notice();counts(data);
    $('scrubber').max=Math.max(0,all.length-1);$('scrubber').value=Math.max(0,pointer);put('position',(pointer+1)+' / '+all.length);
    const current=data.at(-1), selected=data.find(e=>e.event_id===selectedId)||current;
    graph(selected);inspect(selected,data);timeline(data);
    const fast=data.findLast(e=>label(e)==='scored'),slow=data.findLast(e=>label(e)==='slow_start');
    put('jevModel',fast?(fast.data.synthetic?'Scripted demo, not Jev':(fast.data.model||'Jev').slice(0,29)):'Typed candidate selection');
    put('slowModel',slow?(slow.data.model||slow.data.provider).slice(0,28):'Existing provider and model');
    document.body.classList.toggle('paused',!live&&!playing);
    $('liveBtn').disabled=source!=='live';
  }
  function pause() { playing=false;clearTimeout(timer);put('playBtn','Replay'); }
  function step() { pause();live=false;selectedId=null;pointer=pointer>=filtered().length-1?0:pointer+1;render(); }
  function tick() {
    if(!playing)return;
    const all=filtered();if(pointer>=all.length-1){pause();return;}
    pointer++;selectedId=null;render();
    const a=Date.parse(all[pointer]?.timestamp),b=Date.parse(all[pointer+1]?.timestamp);
    const delay=Math.min(650,Math.max(60,b-a||120))/Number($('speed').value);
    timer=setTimeout(tick,delay);
  }
  $('playBtn').onclick=()=>{if(playing){pause();render();return;}live=false;playing=true;if(pointer>=filtered().length-1)pointer=-1;put('playBtn','Pause');tick();};
  $('stepBtn').onclick=step;
  $('liveBtn').onclick=()=>{pause();live=true;pointer=filtered().length-1;selectedId=null;render();};
  $('scrubber').oninput=()=>{pause();live=false;pointer=Number($('scrubber').value);selectedId=null;render();};
  $('session').onchange=()=>{session=$('session').value;pointer=filtered().length-1;selectedId=null;render();};
  $('eventFilter').onchange=render;
  $('loadBtn').onclick=()=>$('fileInput').click();
  $('fileInput').onchange=async()=>{
    pause();live=false;source='file';events=[];seen.clear();
    try{for(const file of $('fileInput').files){const text=await file.text();const batch=text.trim().startsWith('[')?JSON.parse(text):text.split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));ingest(batch);}pointer=filtered().length-1;put('connection','LOCAL REPLAY');render();}catch(error){put('notice','Unable to parse the trace: '+error.message);}
  };
  $('exportBtn').onclick=()=>{const blob=new Blob([filtered().map(e=>JSON.stringify(e)).join('\n')+'\n'],{type:'application/x-ndjson'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='amplifier-decision-trace.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
  document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'&&!['INPUT','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();step();}});
  async function poll() {
    if(source!=='live')return;
    try {
      const response=await fetch('/api/events?after='+cursor,{headers:{Authorization:'Bearer '+(token||'')}});
      if(!response.ok)throw new Error(response.status===401?'Open the token-bearing localhost URL printed in your terminal.':'Telemetry connection error: '+response.status);
      const payload=await response.json();
      if(epoch&&epoch!==payload.epoch){events=[];seen.clear();cursor=0;epoch=payload.epoch;return;}
      epoch=payload.epoch;cursor=payload.cursor;
      ingest(payload.events);put('connection',live?'LIVE / READ ONLY':'CONNECTED / PAUSED');$('connection').classList.remove('warn');
      if(payload.invalid_lines)put('health',payload.invalid_lines+' malformed trace records skipped');
    } catch(error) {put('connection','DISCONNECTED');$('connection').classList.add('warn');if(!events.length)put('notice',error.message);}
    finally {setTimeout(poll,250);}
  }
  if(window.AFAST_EMBEDDED){source='embedded';live=false;ingest(window.AFAST_EMBEDDED);pointer=filtered().length-1;put('connection','OFFLINE REPLAY');render();}
  else {live=true;poll();}
})();
