import test from 'node:test';
import assert from 'node:assert/strict';
import {apiBase,ReviewAPIClient,validateAPIJob,validateAPIReport,materialPayload} from '../../web/dist/review-api-client.mjs';
const job={id:'job1',status:'completed',source:'model_api_static_review',execution_performed:false,scientific_validation:false,report_ready:true};
const report=()=>({format:'articheck-api-static-review-v1',job_id:'job1',source:'model_api_static_review',execution_performed:false,scientific_validation:false,review:{summary:'静态建议',criteria:['scope','code','data','environment','settings','workflow','resources','results'].map(d=>({dimension:d,status:'needs_review',note:'待核对'})),findings:[]}});
test('API addresses allow secure services and explicit loopback without embedded keys',()=>{assert.equal(apiBase('https://review.example/'),'https://review.example');assert.equal(apiBase('http://127.0.0.1:8790'),'http://127.0.0.1:8790');for(const u of ['http://remote.example','file:///secret','https://key@remote.example','https://x.example?api_key=x'])assert.throws(()=>apiBase(u));});
test('API failures do not fall back to demo or silently mark jobs complete',async()=>{const c=new ReviewAPIClient('https://review.example',async()=>({ok:false,status:503,json:async()=>({error:{code:'provider_not_configured',message:'模型未配置'}})}));await assert.rejects(c.health(),/provider_not_configured/);assert.throws(()=>validateAPIJob({...job,source:'frontend_demo'}));});
test('reports require matching job identity, static provenance and all eight unique dimensions',()=>{assert.equal(validateAPIReport(report(),job).review.criteria.length,8);for(const patch of [{job_id:'other'},{scientific_validation:true},{source:'frontend_demo'},{execution_performed:true}])assert.throws(()=>validateAPIReport({...report(),...patch},job));const r=report();r.review.criteria[0].dimension='code';assert.throws(()=>validateAPIReport(r,job));});
test('API upload refuses directory-only project references before sending material',async()=>{await assert.rejects(materialPayload({paper:{pages:[{}]},repository:{kind:'github',files:[{}]}}),/原始 PDF 与代码 ZIP/);});
test('network request uses explicit client header, timeout signal and no browser credentials',async()=>{let call;const c=new ReviewAPIClient('https://review.example',async(url,options)=>{call={url,options};return {ok:true,json:async()=>({service:'articheck-review-api',version:1,configured:false})};});assert.equal((await c.health()).configured,false);assert.equal(call.url,'https://review.example/v1/health');assert.equal(call.options.credentials,'omit');assert.equal(call.options.redirect,'error');assert.equal(call.options.headers['X-ArtiCheck-Client'],'review-api');assert.ok(call.options.signal);});

test('native fetch transport is not called with the client as its receiver',async()=>{let receiver;const c=new ReviewAPIClient('https://review.example',async function(){receiver=this;return {ok:true,json:async()=>({service:'articheck-review-api',version:1,configured:false})};});await c.health();assert.equal(receiver,globalThis);});

test('cloud authentication and limits reject before reading or transmitting materials',async()=>{
 let calls=0;
 const fetcher=async()=>{calls++;return {ok:true,json:async()=>({service:'articheck-review-api',version:1,configured:true,mode:'synchronous',auth_required:true,limits:{max_body_bytes:5000000}})};};
 const c=new ReviewAPIClient('https://review.example',fetcher);
 await assert.rejects(c.submit({}),/网站审阅访问码/);
 assert.equal(calls,1);
 const authorized=new ReviewAPIClient('https://review.example',fetcher,{token:'access-code'});
 await assert.rejects(authorized.submit({paper:{blob:{size:4000000}},repository:{blob:{size:1}}}),/上传上限/);
 assert.equal(calls,2);
});

test('cloud synchronous response keeps the validated report without polling nonexistent jobs',async()=>{
 const prior=globalThis.FileReader;
 globalThis.FileReader=class{readAsDataURL(){this.result='data:application/octet-stream;base64,AA==';this.onload();}};
 try{
  const calls=[];
  const c=new ReviewAPIClient('https://review.example',async(url,options)=>{
   calls.push({url,options});
   return {ok:true,json:async()=>url.endsWith('/health')?{service:'articheck-review-api',version:1,configured:true,mode:'synchronous',auth_required:true}:{job,report:report()}};
  },{token:'site-access-code'});
  const result=await c.submit({paper:{name:'x.pdf',blob:{size:1}},repository:{name:'x.zip',blob:{size:1}}});
  assert.equal(result.id,job.id);
  assert.equal(c.lastReport.job_id,job.id);
  assert.equal(calls.length,2);
  assert.equal(calls[1].options.headers.Authorization,'Bearer site-access-code');
  assert.ok(!calls[1].options.body.includes('site-access-code'));
 }finally{globalThis.FileReader=prior;}
});
