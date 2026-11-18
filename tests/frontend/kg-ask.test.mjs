import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {KnowledgeGraphWorkspace} from '../../web/dist/knowledge-graph.mjs';

const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const nodes=()=>[
 {id:'P1',node_type:'Paper',layer:1,label:'Paper 1',full_title:'Paper 1',pdf_available:true,read:true,x:100,y:120,metadata:{}},
 {id:'P2',node_type:'Paper',layer:1,label:'Paper 2',full_title:'Paper 2',pdf_available:false,read:false,x:400,y:300,metadata:{}},
 {id:'C1',node_type:'Contribution',layer:2,paper_id:'P1',parent_id:'P1',label:'Routing',full_title:'Routing',x:160,y:160},
];
function workspace(extra={}){
 const kg=new KnowledgeGraphWorkspace({esc,icon:()=>'',render(){},projects:()=>[],...extra});
 kg.data={nodes:nodes(),edges:[],timeline:[{paper_id:'P1',title:'Paper 1'},{paper_id:'P2',title:'Paper 2'}]};
 return kg;
}
function scripted(kg,responses){
 const calls=[];
 kg.api=async(path,payload)=>{
  calls.push([path,payload]);
  const next=responses.shift();
  return typeof next==='function'?next(path,payload):next;
 };
 return calls;
}
const answered={ask_id:'a'.repeat(32),status:'answered',phase:'answering',turns:3,answer:'两篇论文报告了结果。',citations:[
 {paper_id:'P1',title:'Paper 1',page:3,quote:'94.2% Top-1',has_pdf:true},
 {paper_id:'P2',title:'Paper 2',page:5,has_pdf:false},
 {paper_id:'P1',title:'Paper 1',page:2,quote:'learned routes',has_pdf:true},
]};

test('图谱问答 is the fourth inspector tab and works with no selected node',()=>{
 const kg=workspace();
 kg.selected=null;
 const tabs=[...kg.inspector().matchAll(/data-kg-tab="([a-z]+)">([^<]+)</g)].map(match=>[match[1],match[2]]);
 assert.deepEqual(tabs,[['detail','节点详情'],['relations','主要贡献'],['lineage','研究脉络'],['ask','图谱问答']]);
 assert.match(kg.inspector(),/选择论文或贡献/);
 kg.inspectorTab='ask';
 const html=kg.inspector();
 assert.doesNotMatch(html,/选择论文或贡献/);
 assert.match(html,/<p class="kg-meta kg-ask-scope"><span>范围：我的图谱 · 2 篇论文 · 其中 1 篇已保存原文<\/span><\/p>/);
 assert.match(html,/<label class="kg-ask-label" for="kg-ask-question">问题<\/label><textarea id="kg-ask-question"[^>]*rows="3"[^>]*placeholder="例如：哪些论文在 CIFAR-10 上报告了 Top-1 准确率？"/);
 assert.match(html,/<div class="kg-insp-actions" data-kg-ask-actions><button type="submit" class="btn small primary" >提问<\/button><\/div>/);
 assert.match(html,/aria-live="polite"/);
 assert.doesNotMatch(html,/<footer/);
 kg.selected='C1';
 assert.match(kg.inspector(),/围绕：《Paper 1》<button type="button" data-kg-ask-unfocus/);
 kg.askFocusDismissed='P1';
 assert.doesNotMatch(kg.inspector(),/围绕/);
 kg.selected='P2';
 assert.match(kg.inspector(),/围绕：《Paper 2》/);
});

test('running disables 提问, shows 停止 and keeps calling step until a terminal state',async()=>{
 const kg=workspace();
 kg.selected='P1';
 let during;
 const calls=scripted(kg,[
  {ask_id:'a'.repeat(32)},
  ()=>{during=[kg.askActions(),kg.askProgress()];return {ask_id:'a'.repeat(32),status:'running',phase:'reading',phase_detail:{title:'Paper 1',page:3},turns:2};},
  ()=>{during.push(kg.askProgress(),kg.askActions());return {ask_id:'a'.repeat(32),status:'running',phase:'answering',turns:3,busy:false};},
  answered,
 ]);
 await kg.submitAsk('  哪些论文报告了准确率？ ');
 assert.deepEqual(calls.map(([path])=>path),['/ask',...Array(3).fill('/ask/'+'a'.repeat(32)+'/step')]);
 assert.deepEqual(calls[0][1],{question:'哪些论文报告了准确率？',focus_paper_id:'P1'});
 assert.deepEqual(calls[1][1],{});
 assert.match(during[0],/class="btn small primary" disabled>提问<\/button><button type="button" class="btn small" data-kg-ask-stop >停止<\/button>/);
 assert.equal(during[1],'正在检索图谱 · 已进行 0 轮');
 assert.equal(during[2],'正在阅读《Paper 1》 第 3 页 · 已进行 2 轮');
 assert.match(during[3],/data-kg-ask-stop/);
 assert.equal(kg.ask.status,'answered');
 assert.doesNotMatch(kg.askActions(),/disabled|停止/);
 assert.equal(kg.askProgress(),'已进行 3 轮');
});

test('busy steps wait before retrying and stop requests the server cancel',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const kg=workspace();
 const id='b'.repeat(32);
 let release;
 const inFlight=new Promise(done=>{release=done;});
 const calls=scripted(kg,[{ask_id:id},{ask_id:id,status:'running',phase:'searching',turns:1,busy:true},
  ()=>inFlight,{ask_id:id,status:'running',phase:'searching',turns:1}]);
 const run=kg.submitAsk('问题');
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(calls.length,2);
 t.mock.timers.tick(1499);
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(calls.length,2);
 t.mock.timers.tick(1);
 for(let i=0;i<5;i++)await Promise.resolve();
 assert.equal(calls.length,3);
 const stop=kg.stopAsk();
 assert.match(kg.askActions(),/data-kg-ask-stop disabled>正在停止…/);
 await stop;
 assert.equal(kg.ask.status,'running');
 release({ask_id:id,status:'stopped',phase:'searching',turns:2,citations:[]});
 await run;
 assert.deepEqual(calls.map(([path])=>path.split('/').pop()),['ask','step','step','cancel']);
 assert.equal(kg.ask.status,'stopped');
});

test('model output, titles, quotes and questions are escaped',()=>{
 const kg=workspace();
 kg.data.nodes[0].full_title='<b>Paper</b>';
 kg.selected='P1';
 kg.inspectorTab='ask';
 kg.askDraft='</textarea><script>x()</script>';
 kg.ask={id:'c'.repeat(32),status:'answered',turns:1,answer:'<img src=x onerror=alert(1)>\n第二行',citations:[
  {paper_id:'P1',title:'<script>alert(2)</script>',page:'<i>3</i>',quote:'"<svg onload=1>"',has_pdf:true}]};
 const html=kg.inspector();
 assert.doesNotMatch(html,/<img|<script|<svg|<\/textarea><script|<b>Paper|<i>3/);
 assert.match(html,/&lt;img src=x onerror=alert\(1\)&gt;<br>第二行/);
 assert.match(html,/&lt;script&gt;alert\(2\)&lt;\/script&gt;/);
 assert.match(html,/围绕：《&lt;b&gt;Paper&lt;\/b&gt;》/);
 kg.ask={id:'c'.repeat(32),status:'running',phase:'reading',phase_detail:{title:'<u>T</u>',page:1},turns:1};
 assert.match(kg.inspector(),/正在阅读《&lt;u&gt;T&lt;\/u&gt;》 第 1 页/);
});

test('clicking a source focuses its node and opens the cited page of the saved paper',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});
 const listeners={};
 const saved={document:globalThis.document,window:globalThis.window};
 globalThis.document={addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),querySelector:()=>null,getElementById:()=>null};
 let opened='';
 const tab={closed:false,opener:1,location:{replace:href=>{opened=href;}},document:{title:'',documentElement:{},
  body:{style:{},replaceChildren(){}},createElement:()=>({setAttribute(){},textContent:''})}};
 globalThis.window={addEventListener(){},open:()=>tab};
 t.after(()=>Object.assign(globalThis,saved));
 const renders=[];
 const kg=workspace({render:()=>renders.push(kg.inspectorTab)});
 kg.savedPDF=async id=>{assert.equal(id,'P1');return new Blob(['%PDF-1.4'],{type:'application/pdf'});};
 kg.bind();
 kg.inspectorTab='ask';
 kg.ask={id:'d'.repeat(32),...answered};
 const html=kg.askResult();
 assert.match(html,/<h3 class="kg-ask-heading">出处<\/h3><ol class="kg-ask-sources"><li><button type="button" class="link" data-kg-ask-node="P1">Paper 1<\/button><span class="kg-ask-source-meta"><button type="button" class="link" data-kg-ask-page="P1" data-page="3">第 3 页<\/button><span class="kg-ask-quote">“94.2% Top-1”<\/span>/);
 assert.match(html,/data-kg-ask-node="P2">Paper 2<\/button><span class="kg-ask-source-meta"><span>第 5 页<\/span><\/span>/);
 assert.equal((html.match(/<li>/g)||[]).length,3);
 const element=(attribute,dataset)=>({dataset,matches:()=>false,closest:selector=>selector.includes('['+attribute+']')?{dataset}:null});
 const click=target=>Promise.all(listeners.click.map(listener=>listener({target,preventDefault(){},stopPropagation(){}})));
 kg.filters.year='1999';
 await click(element('data-kg-ask-node',{kgAskNode:'P2'}));
 assert.equal(kg.selected,'P2');
 assert.equal(kg.inspectorTab,'ask');
 assert.equal(kg.filters.year,'');
 assert.deepEqual(kg.pan,{x:520-400,y:340-300});
 assert.equal(renders.at(-1),'ask');
 await click(element('data-kg-ask-page',{kgAskPage:'P1',page:'3'}));
 for(let i=0;i<10&&!opened;i++)await new Promise(done=>setImmediate(done));
 assert.match(opened,/^blob:.*#page=3$/);
});

test('no_information, failed and stopped states render their notices and 继续 resumes the run',async()=>{
 const kg=workspace();
 const id='e'.repeat(32);
 const verified=[{paper_id:'P1',title:'Paper 1',page:2,quote:'learned routes',has_pdf:true}];
 kg.ask={id,status:'no_information',answer:'图谱中没有足够信息',turns:2,citations:[]};
 assert.equal(kg.askResult(),'<p class="kg-notice">图谱中没有足够信息回答这个问题。</p>');
 kg.ask={id,status:'failed',turns:4,error:{message:'模型请求失败，可点击继续从断点重试。'},citations:verified};
 const failed=kg.askResult();
 assert.match(failed,/^<p class="kg-notice">模型请求失败，可点击继续从断点重试。<\/p><div class="kg-insp-actions"><button type="button" class="btn small" data-kg-ask-continue>继续<\/button><\/div><h3 class="kg-ask-heading">出处/);
 assert.doesNotMatch(kg.askActions(),/disabled|停止/);
 kg.ask={id,status:'stopped',turns:1,citations:[]};
 assert.match(kg.askResult(),/^<p class="kg-meta">已停止。可从断点继续。<\/p><div class="kg-insp-actions"><button type="button" class="btn small" data-kg-ask-continue>继续<\/button>/);
 const calls=scripted(kg,[{ask_id:id,status:'running',phase:'searching',turns:2},{...answered,ask_id:id}]);
 await kg.continueAsk();
 assert.deepEqual(calls.map(([path,payload])=>[path.split('/').pop(),payload]),[['step',{resume:true}],['step',{}]]);
 assert.equal(kg.ask.status,'answered');
 kg.ask={id:null,question:'重新提交',status:'failed',error:{message:'网络错误'}};
 const retry=scripted(kg,[{ask_id:id},{...answered,ask_id:id}]);
 await kg.continueAsk();
 assert.deepEqual(retry.map(([path])=>path.split('/').pop()),['ask','step']);
 assert.equal(retry[0][1].question,'重新提交');
});

test('a running question is restored from its saved id after reopening the page',async(t)=>{
 const store=new Map([['articheck:kg-ask','f'.repeat(32)]]);
 const saved=globalThis.localStorage;
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)}});
 t.after(()=>Object.defineProperty(globalThis,'localStorage',{configurable:true,value:saved}));
 const kg=workspace();
 const calls=scripted(kg,[{ask_id:'f'.repeat(32),question:'旧问题',status:'running',phase:'searching',turns:5},{...answered,ask_id:'f'.repeat(32)}]);
 await kg.restoreAsk();
 assert.deepEqual(calls.map(([path])=>path.split('/').pop()),['f'.repeat(32),'step']);
 assert.equal(kg.ask.status,'answered');
 assert.equal(kg.askDraft,'旧问题');
 const other=workspace();
 scripted(other,[()=>{throw Error('未找到这次问答。');}]);
 await other.restoreAsk();
 assert.equal(store.has('articheck:kg-ask'),false);
});

test('ask styles reuse existing variables and the inspector keeps four equal tabs',()=>{
 const css=fs.readFileSync(new URL('../../web/dist/feedback-redesign.css',import.meta.url),'utf8');
 assert.doesNotMatch(css,/\.kg-insp-tabs\{grid-template-columns:repeat\(3,1fr\)\}/);
 const rules=css.split('\n').filter(line=>line.includes('.kg-ask'));
 assert.ok(rules.length>=10);
 for(const rule of rules){
  assert.doesNotMatch(rule,/#[0-9a-f]{3,8}\b|rgba?\(|shadow|gradient/i,rule);
  for(const selector of rule.split('{')[0].split(',').filter(part=>part.includes('kg-')))
   assert.match(selector,/\.kg-(ask|insp-body)/,selector);
 }
});
