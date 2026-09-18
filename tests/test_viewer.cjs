const {test} = require('node:test');
const assert = require('node:assert/strict');
const {scriptedKeys,synthetic,sessionsFor,metrics,describe,valid,decisionPath} = require('../src/amplifier_fast_decisions/static/app.js');
let seq=0;
const now=Date.parse('2026-09-18T03:00:00Z');
const event=(kind,data={},decision=null,session='parent',extra={})=>({schema_version:'1.0',event_id:String(++seq),event:'fast_decisions:'+kind,session_id:session,decision_id:decision,timestamp:new Date(now).toISOString(),data,...extra});
function real(events){const keys=scriptedKeys(events);return events.filter(e=>!synthetic(e,keys));}
test('scripted decision chains never count as model decisions or fast-path gains',()=>{
 const events=[event('health',{phase:'configuration',backend:'scripted-demo',mode:'shadow'}),event('requested',{},'d1'),event('shadow_proposed',{synthetic:true,backend:'scripted-demo'},'d1'),event('shadow_agreement',{agreement:'match',would_have_avoided_llm_turn:true},'d1'),event('health',{native_event:'tool:post'},'d1')];
 assert.equal(real(events).length,2);assert.equal(metrics(real(events)).scores,0);assert.equal(metrics(real(events)).tools,1);assert.equal(metrics(real(events)).fastExecuted,0);
});
test('native and measured tool events do not double count within a session',()=>{
 const events=[event('health',{native_event:'tool:post'}),event('tool_end',{status:'ok'}),event('tool_end',{status:'ok'},null,'other')];
 assert.equal(metrics(events).tools,2);
});
test('fast submission alone never proves an executed action',()=>{
 const events=[event('routed',{route:'fast'},'d1')];assert.equal(metrics(events).fast,1);assert.equal(metrics(events).fastExecuted,0);
 events.push(event('tool_end',{status:'ok'},'d1'));assert.equal(metrics(events).fastExecuted,1);
});
test('decision ids cannot link execution across sessions',()=>{
 const events=[event('routed',{route:'fast'},'same','one'),event('tool_end',{status:'ok'},'same','two')];
 assert.equal(metrics(events).fastExecuted,0);
});
test('synthetic flag on an entire fixture session excludes native-looking data',()=>{
 const e=event('health',{native_event:'tool:post'},null,'demo',{synthetic:true});assert.equal(real([e]).length,0);
});
test('children retain their parent identity; parents remain independently selectable',()=>{
 const events=[event('health',{phase:'configuration',backend:'ollama-token',mode:'active'}),event('health',{phase:'configuration'},null,'child',{parent_session_id:'parent'})];
 const sessions=sessionsFor(events,now);assert.equal(sessions.filter(s=>!s.parent).length,1);assert.equal(sessions.find(s=>s.id==='child').parent,'parent');
});
test('connected viewer does not make old sessions appear alive',()=>{
 const e=event('health',{phase:'configuration'});assert.equal(sessionsFor([e],now+60000)[0].reporting,false);
 const recentNative=event('health',{native_event:'provider:request'});assert.equal(sessionsFor([recentNative],now)[0].reporting,false);
});
test('heartbeats distinguish mounted idle sessions from working sessions and closed sessions',()=>{
 const events=[event('health',{phase:'session_heartbeat'})];assert.equal(sessionsFor(events,now)[0].state,'Connected, idle');
 events.push(event('health',{native_event:'execution:start'}));assert.equal(sessionsFor(events,now)[0].state,'Working');
 events.push(event('health',{native_event:'execution:end'}));assert.equal(sessionsFor(events,now)[0].state,'Connected, idle');
 events.push(event('health',{phase:'session_closed'}));assert.equal(sessionsFor(events,now)[0].reporting,false);
});
test('retry events explain real provider issues without error bodies',()=>{
 const e=event('health',{native_event:'provider:retry',provider:'anthropic',retry_attempt:2,exception_type:'ConnectTimeout'});
 assert.match(describe(e).detail,/anthropic.*ConnectTimeout.*Attempt 2/);assert.equal(metrics([e]).issues,1);
});
test('local model scores are model evidence; scripted scores remain explicit',()=>{
 const e=event('scored',{model:'qwen3:0.6b',duration_ms:24,probability_kind:'token_mass_with_abstention_residual'});
 assert.equal(describe(e).source,'Model score');assert.equal(describe(e,true).source,'Synthetic / scripted');assert.equal(metrics([e]).p95,24);
});
test('malformed imported data is rejected',()=>{
 assert.equal(valid({...event('health'),data:[]}),false);assert.equal(valid(event('health')),true);
});

test('mechanics joins only the selected session and decision, without inventing missing stages',()=>{
 const scored=event('scored',{model:'qwen3:0.6b'},'same','one');
 const other=event('tool_end',{status:'ok'},'same','two');
 const next=event('scored',{},'later','one');
 const events=[scored,other,next];
 assert.deepEqual(decisionPath(events,'one',scored.event_id),[scored]);
 assert.deepEqual(decisionPath(events,'one',null),[next]);
 assert.deepEqual(decisionPath(events,'two',null),[]);
});
