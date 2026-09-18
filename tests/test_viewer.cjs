// Run with: node --test tests/test_viewer.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../src/amplifier_fast_decisions/static/app.js'),'utf8');
function viewer(events) {
  const nodes = new Map();
  function element() {
    return {textContent:'',children:[],style:{},dataset:{},options:[],value:'decisions',
      classList:{add(){},remove(){},toggle(){}},append(...xs){this.children.push(...xs)},
      replaceChildren(...xs){this.children=xs},add(x){this.options.push(x)},
      setAttribute(){},addEventListener(){}};
  }
  const document = {getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},
    createElement:element,createElementNS:element,querySelectorAll(){return []},
    addEventListener(){},body:element()};
  vm.runInNewContext(source,{document,window:{AFAST_EMBEDDED:events},
    location:{hash:'',host:'test'},sessionStorage:{getItem(){return ''}},
    URLSearchParams,Option:function(text,value){return {text,value}},setTimeout,clearTimeout});
  return nodes;
}
let seq=0;
const event=(kind,data={},decision='d1',session='s1')=>({schema_version:'1.0',event_id:String(++seq),event:'fast_decisions:'+kind,session_id:session,decision_id:decision,timestamp:'2026-09-17T00:00:00Z',data});
test('local model scores are explicitly uncalibrated',()=>{
  const nodes=viewer([event('scored',{backend:'ollama-token',model:'test-local',selected_probability:.92,probability_kind:'token_mass_with_abstention_residual'})]);
  assert.equal(nodes.get('fastTitle').textContent,'Local model');
  assert.match(nodes.get('confidence').textContent,/Uncalibrated token score/);
});
test('shadow score appears in metrics, inspector and decision list without a fast submission',()=>{
  const nodes=viewer([
    event('health',{phase:'configuration',mode:'shadow',backend:'scripted-demo',allow_external_state:false}),
    event('shadow_proposed',{choice:'read',probabilities:{read:.97,reason:.03},selected_probability:.97,duration_ms:12,mode:'shadow',backend:'scripted-demo',synthetic:true}),
    event('shadow_agreement',{agreement:'match',proposed_candidate:'read',actual_tool:'fast_workspace'}),
    event('health',{queue_depth:0},null),
  ]);
  assert.equal(nodes.get('mDecisions').textContent,1);
  assert.equal(nodes.get('mFast').textContent,0);
  assert.equal(nodes.get('decisionLatency').textContent,'12 ms');
  assert.equal(nodes.get('probabilities').children.length,2);
  assert.equal(nodes.get('decisionList').children[0].children[6].textContent,'12 ms');
  assert.match(nodes.get('notice').textContent,/SHADOW ONLY.*Jev is not connected/);
  assert.equal(nodes.get('fastTitle').textContent,'Offline scorer');
  assert.equal(nodes.get('routeTitle').textContent,'Shadow comparison: match');
});
test('legacy native health events stay visible without claiming measured execution',()=>{
  const nodes=viewer([
    event('health',{native_event:'provider:request',provider:'test'}),
    event('health',{native_event:'tool:pre',tool:'read_file'}),
    event('health',{native_event:'tool:post',tool:'read_file'}),
  ]);
  assert.equal(nodes.get('mSlow').textContent,1);
  assert.equal(nodes.get('mTools').textContent,1);
  assert.match(nodes.get('mSlowLatency').textContent,/invocation not measured/);
  assert.match(nodes.get('mToolsFoot').textContent,/success\/duration not inferred/);
  assert.equal(nodes.get('timeline').children.length,3);
  assert.equal(nodes.get('routeTitle').textContent,'Native tool:post observed');
});
test('active facade measurements and native hooks are not double counted',()=>{
  const nodes=viewer([
    event('health',{native_event:'provider:request'}),event('slow_start'),
    event('health',{native_event:'tool:post'}),event('tool_end',{status:'ok'}),
    event('routed',{route:'fast'}),event('scored',{duration_ms:2}),
  ]);
  assert.equal(nodes.get('mSlow').textContent,1);
  assert.equal(nodes.get('mTools').textContent,1);
  assert.equal(nodes.get('mFast').textContent,1);
});
test('candidate absence has an explanation and is visible in the default trace',()=>{
  const nodes=viewer([event('health',{phase:'shadow',reason_code:'no_eligible_candidates',candidate_count:0})]);
  assert.equal(nodes.get('routeTitle').textContent,'No eligible prepared action');
  assert.equal(nodes.get('timeline').children.length,1);
  assert.equal(nodes.get('mFast').textContent,0);
});
