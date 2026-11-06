import test from 'node:test';
import assert from 'node:assert/strict';
import {validateInput,inputKey,coverageCounts,sessionCapability,metricUnit} from '../../web/dist/online-core.mjs';
import {IntakeWorkspace} from '../../web/dist/intake.mjs';

test('decimal ratios never acquire an unsupported percent label, including archived reports',()=>{
 assert.equal(metricUnit({value:0.8338,unit:'%',quote:'Ours 0.8338'}),'（单位待核对）');
 assert.equal(metricUnit({value:0.8338,unit:'%',quote:'Ours 0.8338%'}),'%');
 assert.equal(metricUnit({value:0.8338,unit:'',unit_uncertain:true}),'（单位待核对）');
 assert.equal(metricUnit({value:83.38,unit:'%',quote:'83.38%'}),'%');
});

test('partial materials are usable without manually confirmed claims or local execution bindings',()=>{
 for(const key of ['paper','repository']){
  const p={[key]:{blob:new Blob(['material']),sha256:'one'}};
  assert.deepEqual(validateInput(p,{token:'website-code',consent:true}),{});
 }
 assert.ok(validateInput({}, {token:'x',consent:true}).material);
});
test('automatic scope is optional; restricting a scope requires a value; invalid time is actionable',()=>{
 const p={paper:{blob:new Blob(['pdf'])}};
 assert.equal(validateInput(p,{token:'x',consent:true}).scope,undefined);
 assert.ok(validateInput({...p,online_restrict:true},{token:'x',consent:true}).scope);
 assert.ok(validateInput({...p,online_max_seconds:601},{token:'x',consent:true}).seconds);
 assert.equal(validateInput({...p,online_max_seconds:''},{token:'x',consent:true}).seconds,undefined);
});
test('editing code, task or scope invalidates the association with an old report',()=>{
 const p={paper:{sha256:'a'},repository:{sha256:'b'}};
 for(const mutation of [{repository:{sha256:'c'}},{online_task:'self_review'},{online_scope:'Table 2'}])assert.notEqual(inputKey(p),inputKey({...p,...mutation}));
});
test('coverage counts are calculated from identified metrics and actual observations',()=>{
 const r={review:{metrics:[{id:'M1'},{id:'M2'}],coverage:{gaps:['unreadable figure']}},execution:{metrics:[{id:'M1',observed:0},{id:'M2',observed:null}]}};
 assert.deepEqual(coverageCounts(r),{identified:2,observed:1,missing:1,gaps:1});
});
test('owner identity persists independently of the provider key and access code',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const a=sessionCapability(storage);assert.match(a,/^[a-f0-9]{64}$/);assert.equal(sessionCapability(storage),a);assert.equal(values.size,1);
});
test('a manual claim starts without a fabricated page and can be collapsed, deleted and restored',async()=>{
 const i=new IntakeWorkspace({mode:()=> 'demo',page:()=> 'project',render(){},toast(){}});
 const p={id:'editing-project',claims:[],resources:{}};i.projects=[p];i.activeId=p.id;
 i.page=9;
 await i.action('add-claim',{});
 const id=p.claims[0].id;
 assert.equal(p.claims[0].page,null);
 await i.action('collapse-claim',{});assert.equal(i.activeClaimId,null);
 await i.action('delete-claim',{dataset:{id}});assert.equal(p.claims.length,0);
 await i.action('undo-claim',{});assert.equal(p.claims.length,1);assert.equal(p.claims[0].id,id);
});

test('a large GitHub reference is a usable material without downloading a browser Blob',async()=>{
 const {hasCode}=await import('../../web/dist/online-core.mjs');
 const p={repository:{sha256:'a'.repeat(64),remote:{name:'code.zip',repository:'author/project',commit:'b'.repeat(40)}}};
 assert.equal(hasCode(p),true);assert.deepEqual(validateInput(p,{token:'access-code',consent:true}),{});
});

test('large local materials bypass JSON and reuse the completed direct upload',async()=>{
 const {OnlineWorkspace}=await import('../../web/dist/online-workspace.mjs');
 const p={repository:{blob:new Blob([new Uint8Array(3_100_000)]),sha256:'a'.repeat(64),name:'source.zip'}};
 const workspace=new OnlineWorkspace({projects:[p],save:async()=>{},h:{render(){}},esc:v=>v});
 let requests=0,transfers=0;workspace.request=async(path,body)=>{requests++;assert.equal(path,'/uploads');assert.equal(body.files[0].bytes,3_100_000);return {id:'1'.repeat(32),expires_at:Date.now()/1000+800,files:{code:{upload_url:'https://fixture.e2b.app/files?signature=test',material:{name:'source.zip',upload_id:'1'.repeat(32),kind:'code'}}}};};
 const original=globalThis.fetch;globalThis.fetch=async(url,options)=>{transfers++;assert.equal(options.headers,undefined);assert.ok(options.body instanceof FormData);return {ok:true};};
 try{
  const first=await workspace.payload(p);const second=await workspace.payload(p);
  assert.equal(first.code.upload_id,'1'.repeat(32));assert.equal(first.code.content_base64,undefined);
  assert.ok(JSON.stringify(first).length<1000);assert.deepEqual(first,second);assert.equal(requests,1);assert.equal(transfers,1);
  assert.doesNotMatch(JSON.stringify(p.online_upload),/signature|upload_url/);
 }finally{globalThis.fetch=original;}
});

test('verdict, default-open activity hierarchy, and GPU execution labels render accurately',async()=>{
 const {reportVerdict}=await import('../../web/dist/report-verdict.mjs');
 const {activityView}=await import('../../web/dist/review-activity.mjs');
 const {OnlineWorkspace}=await import('../../web/dist/online-workspace.mjs');
 const {executionNames}=await import('../../web/dist/online-core.mjs');
 assert.equal(executionNames.queued,'等待 GPU 执行器');
 const failedReport={status:'completed',materials:{paper:'a',code:'b'},
  review:{paper_type:'empirical',task:'reproduction',summary:'summary',classification_reason:'reason',
   criteria:[],findings:[{severity:'high',title:'issue',detail:'d',suggestion:'s'}],
   metrics:[{id:'M1',metric:'acc',value:90,unit:'%',page:1,quote:'90%',author_method:true}],
   coverage:{gaps:[],note:'',paper_pages_in_context:1,code_files_in_context:1,total_code_files:1},
   plan:{hardware:'GPU',max_seconds:180,purpose:'CUDA check',blocked_reason:'',stages:[{id:'S1',title:'CUDA probe',command:'python test.py',file:'test.py'}]}},
  execution:{status:'queued',provider:'owned_gpu',environment:{cpu_count:8,memory_mb:16384,gpu:true,gpu_name:'NVIDIA GeForce RTX 4090'},
   stages:[],metrics:[],events:[{role:'planner',kind:'plan_scheduled',time:1700000000}]}};
 assert.equal(reportVerdict(failedReport).state,'pending');
 const completedMismatch={...failedReport,execution:{...failedReport.execution,status:'completed',metrics:[{id:'M1',metric:'acc',expected:90,observed:70,unit:'%',status:'outside_tolerance'}]}};
 assert.equal(reportVerdict(completedMismatch).state,'failed');
 const activityHtml=activityView(failedReport,v=>String(v??''));
 assert.match(activityHtml,/<details class="review-activity-log" open>/);
 const ws=new OnlineWorkspace({projects:[],save:async()=>{},h:{render(){}},esc:v=>String(v??'')});
 ws.capabilities={compute:{capacity:{gpu:true}}};
 const matHtml=ws.materials({paper:{name:'resnet.pdf',pages:[1,2,3]},repository:null,online_auto_execute:true});
 assert.match(matHtml,/rail-badge ready">已导入 · 3 页/);
 assert.match(matHtml,/rail-badge empty">未提供/);
 assert.match(matHtml,/rail-badge gpu">云端 CPU \/ 自有 GPU/);
 assert.match(matHtml,/online-upload has-file/);
 const multiStageReport={...failedReport,
  review:{...failedReport.review,plan:{...failedReport.review.plan,stages:[
   {id:'S1',title:'Stage 1',command:'python s1.py',file:'s1.py'},
   {id:'S2',title:'Stage 2',command:'python s2.py',file:'s2.py'}]}},
  execution:{...failedReport.execution,status:'running',stages:[{id:'S1',status:'running'}]}};
 const execHtml=ws.execution(multiStageReport,false);
 assert.match(execHtml,/自有 GPU 隔离执行/);
 assert.match(execHtml,/NVIDIA GeForce RTX 4090/);
 assert.match(execHtml,/online-stage stage-running/);
 assert.match(execHtml,/online-status status-running running/);
 assert.match(execHtml,/online-stage stage-planned/);
 assert.match(execHtml,/online-status status-planned needs_review/);
});
