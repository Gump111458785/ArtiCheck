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
 assert.equal(executionNames.queued,'执行中');
 assert.equal(executionNames.running,'执行中');
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
 assert.doesNotMatch(matHtml,/范围|执行模式|材料缺失时会怎样/);
 assert.doesNotMatch(matHtml,/RTX 4090/);
 assert.match(matHtml,/online-upload has-file/);
 const multiStageReport={...failedReport,
  review:{...failedReport.review,plan:{...failedReport.review.plan,stages:[
   {id:'S1',title:'Stage 1',command:'python s1.py',file:'s1.py'},
   {id:'S2',title:'Stage 2',command:'python s2.py',file:'s2.py'}]}},
  execution:{...failedReport.execution,status:'running',stages:[{id:'S1',status:'running',live_tail:['Epoch 1/10 loss=0.42','Epoch 2/10 loss=0.31','Epoch 3/10 acc=91.4%'],output:'Epoch 1/10 loss=0.42\nEpoch 2/10 loss=0.31\nEpoch 3/10 acc=91.4%'}]}};
 const execHtml=ws.execution(multiStageReport,false);
 assert.match(execHtml,/云端隔离执行/);
 assert.match(execHtml,/意外中断最多重试 3 次/);
 assert.doesNotMatch(execHtml,/展开完整日志|实时动态输出|来源 s1/);
 assert.match(execHtml,/中断运行/);
 assert.doesNotMatch(execHtml,/NVIDIA GeForce RTX 4090/);
 assert.match(execHtml,/terminal-live-tail/);
 assert.match(execHtml,/Epoch 3\/10 acc=91\.4%/);
 assert.match(execHtml,/online-stage stage-running/);
 assert.match(execHtml,/online-status status-running running/);
 assert.match(execHtml,/online-stage stage-planned/);
 assert.match(execHtml,/online-status status-planned needs_review/);
 assert.doesNotMatch(matHtml,/id="online-seconds"/);
 assert.match(activityHtml,/review-timeline-axis/);
 assert.match(activityHtml,/timeline-track-fill/);
 assert.match(activityHtml,/data-role-jump="experiment_runner"/);

 // Paper-only review filters out unused code/planner/experiment roles and hides execution section
 const paperOnlyReport={status:'completed',materials:{paper:'a',code:null},
  activity:[{title:'论文审阅与指标核查',roles:['literature_reader'],status:'completed',time:1700000001},{title:'汇总审查报告',roles:['reporter'],status:'completed',time:1700000002}],
  review:{paper_type:'empirical',task:'self_review',summary:'整体自洽',classification_reason:'纯论文审查',
   paper_title:'Deep Residual Learning for Image Recognition',
   paper_abstract:'Deeper neural networks are more difficult to train. We present a residual learning framework.',
   paper_contributions:['提出残差学习框架解决深层网络退化问题','在 ImageNet 与 CIFAR-10 上取得突破性精度'],
   core_code_snippets:[{title:'trainer.py · train 核心定义',file:'trainer.py',start_line:10,end_line:28,code:'def train(train_loader, model):\n    pass',explanation:'定义训练循环与反向传播逻辑。'}],
   criteria:[],findings:[],metrics:[],
   coverage:{gaps:[],note:'',paper_pages_in_context:12,code_files_in_context:0,total_code_files:0},
   plan:{hardware:'CPU',max_seconds:300,purpose:'',blocked_reason:'未提供代码',stages:[]}},
  execution:null};
 const paperTimeline=activityView(paperOnlyReport,v=>String(v??''));
 assert.match(paperTimeline,/文献审阅/);
 assert.match(paperTimeline,/交叉核查/);
 assert.match(paperTimeline,/报告整理/);
 assert.doesNotMatch(paperTimeline,/代码检查/);
 assert.doesNotMatch(paperTimeline,/计划编排/);
 assert.doesNotMatch(paperTimeline,/实验执行/);

 const finalHtml=ws.finalReport(paperOnlyReport,{title:'我的 ResNet 审查项目',paper:{name:'1512.03385v1.pdf',pages:[{text:'Deep Residual Learning'}]}});
 const idxVerdict=finalHtml.indexOf('review-verdict');
 const idxProject=finalHtml.indexOf('我的 ResNet 审查项目');
 const idxPaper=finalHtml.indexOf('Deep Residual Learning for Image Recognition');
 const idxContrib=finalHtml.indexOf('提出残差学习框架解决深层网络退化问题');
 assert.ok(idxVerdict>=0 && idxVerdict<idxProject && idxProject<idxPaper && idxPaper<idxContrib);
 assert.match(finalHtml,/editorial-verdict/);
 assert.match(finalHtml,/论文审查/);
 assert.match(finalHtml,/代码审查/);
 assert.match(finalHtml,/论文与代码核对/);
 assert.doesNotMatch(finalHtml,/trainer\.py · train 核心定义/);
 const external={...completedMismatch,review:{...completedMismatch.review,purpose:'reproduce_other'}};
 assert.match(ws.finalReport(external,{title:'复现项目'}),/目标 90 % · 实测 70 %/);
 assert.doesNotMatch(ws.finalReport(external,{title:'复现项目'}),/反馈建议|修正建议/);
 external.execution={...external.execution,execution_performed:true,metrics:[{...external.execution.metrics[0],observed:90,status:'within_tolerance'}]};
 assert.equal(reportVerdict(external).state,'passed');
 external.execution.metrics=[];
 assert.equal(reportVerdict(external).label,'未验证');
 assert.doesNotMatch(finalHtml,/查看计划与执行条件/);

 // Fourth-batch UI requirements:
 // 1. Materials UI removes scope restriction checkbox, auto-execute checkbox, and details.online-local; places local button next to submit
 assert.doesNotMatch(matHtml,/data-online-field="online_restrict"/);
 assert.doesNotMatch(matHtml,/data-online-field="online_auto_execute"/);
 assert.doesNotMatch(matHtml,/<details class="online-local">/);
 assert.match(matHtml,/class="btn online-local-btn" data-online="local"/);
 assert.match(activityHtml,/class="live-heading"/);
 assert.match(activityHtml,/class="live-dots"/);

 // 2. Report tab hidden before review completes, terminal button present in toolbar, endedCard shown on cancelled/failed
 const wsRender=new OnlineWorkspace({projects:[{id:'p1',title:'Test Proj',paper:{name:'a.pdf',pages:[1]},online_report:{id:'j1',format:'articheck.online_assessment.v2',source:'model_api_review',scientific_validation:false,status:'cancelled',error:'user_cancelled',review:null,activity:[{title:'审查已手动中止',roles:['reporter'],status:'failed',time:1700000003}]}}],save:async()=>{},h:{render(){},icon:()=>'',account:()=>null},esc:v=>String(v??'')});
 wsRender.selected='p1';
 wsRender.tab='process';
 const cancelledView=wsRender.render();
 assert.doesNotMatch(cancelledView,/data-online="terminal"/);
 assert.doesNotMatch(cancelledView,/data-online-tab="report"/);
 assert.match(cancelledView,/review-ended/);
 assert.match(cancelledView,/审查已中断/);
 assert.match(cancelledView,/data-online="resume-review"/);

 wsRender.i.projects[0].online_report=paperOnlyReport;
 const completedView=wsRender.render();
 assert.match(completedView,/data-online-tab="report"/);

 // Sixth-batch UI requirements:
 // - Sidebar card clickable with data-sidebar-jump
 // - Process tab hides everything below timeline initially (no activeRoleNode), and clicking a role toggles its summary panel
 // - Process-ready-banner is removed
 wsRender.tab='process';
 wsRender.activeRoleNode=null;
 const initialProcessView=wsRender.render();
 assert.doesNotMatch(initialProcessView,/process-ready-banner/);
 assert.doesNotMatch(initialProcessView,/id="online-role-node-panel"/);
 wsRender.jumpFromRole('literature_reader');
 assert.equal(wsRender.activeRoleNode,'literature_reader');
 const openRoleView=wsRender.render();
 assert.match(openRoleView,/id="online-role-node-panel"/);
 assert.match(openRoleView,/01 · 文献审阅节点报告/);
 wsRender.jumpFromRole('literature_reader');
 assert.equal(wsRender.activeRoleNode,null);
 const sidebarHtml=wsRender.sidebar();
 assert.match(sidebarHtml,/data-sidebar-jump="p1"/);

 // Fifth-batch UI requirements:
 const {normalizeGitHubUrl}=await import('../../web/dist/online-workspace.mjs');
 const {AccountWorkspace}=await import('../../web/dist/account.mjs');
 assert.equal(normalizeGitHubUrl('https://github.com/yoonkim/CNN_sentence/tree/master/data'),'https://github.com/yoonkim/CNN_sentence');
 assert.equal(normalizeGitHubUrl('yoonkim/CNN_sentence'),'https://github.com/yoonkim/CNN_sentence');
 assert.equal(normalizeGitHubUrl('https://not-github.example.com/a/b'),null);
 assert.doesNotMatch(matHtml,/class="review-mode-strip"/);
 assert.match(execHtml,/class="online-terminal-box online-stage-list"/);
 assert.match(execHtml,/class="terminal-topbar"/);
 assert.match(execHtml,/class="terminal-stream-body"/);
 const matWithCode=ws.materials({title:'CNN Sentence Proj',paper:null,repository:{name:'CNN_sentence.zip',repo_name:'yoonkim/CNN_sentence',commit:'1234567890abcdef',files:[{path:'a.py'}],sha256:'a'.repeat(64)}});
 assert.match(matWithCode,/源码已读取 · yoonkim\/CNN_sentence/);
 const acct=new AccountWorkspace({esc:v=>String(v??''),icon:()=>'',projects:()=>[]});
 acct.user={id:'u1',username:'tester',name:'测试研究员',role:'member'};
 const centerHtml=acct.center();
 assert.doesNotMatch(centerHtml,/account-change-avatar-btn/);
 assert.match(centerHtml,/data-account="edit-name"/);
});

test('human criterion confirmations are report-specific and keep model evidence intact', async()=>{
 const {criteriaDecisions,reportVerdict}=await import('../../web/dist/report-verdict.mjs');
 const criteria=[{dimension:'code',status:'needs_review',note:'检查提交版本'}];
 const report={id:'first',status:'completed',review:{paper_type:'empirical',criteria,findings:[],coverage:{gaps:[]},plan:{stages:[]}}};
 const project={online_criteria_review:{reportId:'first',dimensions:['code']}};
 assert.equal(reportVerdict(report,project).state,'passed');
 assert.equal(criteriaDecisions(report,project)[0].manuallyReviewed,true);
 assert.equal(reportVerdict({...report,id:'second'},project).state,'pending');
 assert.equal(criteria[0].status,'needs_review');
});

test('a review finishing in the background leaves the selected archived report open',async()=>{
 const {OnlineWorkspace}=await import('../../web/dist/online-workspace.mjs');
 const pending={id:'a',online_report:{id:'job-a',status:'completed',review:{},execution:{status:'failed'}}};
 const history={id:'b',online_report:{id:'job-b',status:'completed',review:{}}};
 const workspace=new OnlineWorkspace({projects:[pending,history],save:async()=>{},h:{page:()=> 'api-review'},esc:String});
 workspace.selected=history.id;
 workspace.tab='report';
 workspace.operationProject=pending.id;
 workspace.liveReport={id:'job-a',status:'reviewing'};
 assert.equal(workspace.viewReport(history),history.online_report);
 assert.equal(workspace.viewReport(pending),workspace.liveReport);
 await workspace.notifyFinished(pending);
 assert.equal(workspace.tab,'report');
 assert.equal(workspace.selected,history.id);
});

test('terminated reports show historical criteria with no action to confirm them',async()=>{
 const {OnlineWorkspace}=await import('../../web/dist/online-workspace.mjs');
 const {reportVerdict}=await import('../../web/dist/report-verdict.mjs');
 const workspace=new OnlineWorkspace({projects:[],h:{},esc:String});
 const report={terminated_at:'now',review:{criteria:[{dimension:'data',status:'needs_review',note:'old'}]}};
 assert.equal(reportVerdict(report).label,'已终止');
 assert.match(workspace.criteriaSection(report,{}),/终止前未复核/);
 assert.doesNotMatch(workspace.criteriaDetails(report,{}),/data-confirm-criterion|data-supply-criterion/);
});

test('detail expansion works without expanding literature and shortens available links',async()=>{
 const {KnowledgeGraphWorkspace}=await import('../../web/dist/knowledge-graph.mjs');
 const graph=new KnowledgeGraphWorkspace({esc:String,render(){}});
 const paper={id:'p',node_type:'Paper',x:0,y:0};
 const parent={id:'c',parent_id:'p',paper_id:'p',node_type:'Contribution',x:100,y:0};
 const detail={id:'d',parent_id:'c',paper_id:'p',node_type:'Detail',x:230,y:0};
 graph.selected='p';
 graph.data={nodes:[paper,parent,detail]};
 graph.api=()=>assert.fail('existing details must not trigger retrieval');
 assert.match(graph.canvasControls(),/展开子贡献/);
 await graph.togglePaperDetails();
 assert.ok(graph.expanded.has('c'));
 graph.placeDetailNodes(graph.data.nodes,[{source:'c',target:'d'}]);
 assert.ok(Math.hypot(parent.x-detail.x,parent.y-detail.y)<130);
 const fixed={x:detail.x,y:detail.y};
 graph.pinned.add('d');
 parent.x+=140;
 graph.placeDetailNodes(graph.data.nodes,[{source:'c',target:'d'}]);
 assert.deepEqual({x:detail.x,y:detail.y},fixed);
});

test('verified relationships collapse to paper edges and expansion never searches public sources',async()=>{
 const {KnowledgeGraphWorkspace}=await import('../../web/dist/knowledge-graph.mjs');
 const messages=[];
 const graph=new KnowledgeGraphWorkspace({esc:String,render(){},toast:message=>messages.push(message)});
 const nodes=[
  {id:'a',node_type:'Paper'}, {id:'b',node_type:'Paper'}, {id:'c',node_type:'Paper'},
  {id:'a1',paper_id:'a',parent_id:'a',node_type:'Contribution'},
  {id:'a2',paper_id:'a',parent_id:'a1',node_type:'Detail'},
  {id:'b1',paper_id:'b',parent_id:'b',node_type:'Contribution'},
 ];
 const edge={source:'a1',target:'b1',edge_type:'SIMILAR_CONTRIBUTION'};
 graph.data={nodes,edges:[edge],timeline:[
  {paper_id:'a',direction:'Computer Vision'},{paper_id:'b',direction:'Semantic Segmentation'},
  {paper_id:'c',direction:'Natural language processing'},
 ]};
 graph.selected='c';
 graph.api=()=>assert.fail('expansion must not call any endpoint');
 await graph.togglePaperDetails();
 assert.deepEqual(messages,['这篇论文暂无可展示的子贡献。']);
 assert.deepEqual(graph.displayedEdges(new Set(['a','b','c'])),[{...edge,source:'a',target:'b'}]);
 assert.deepEqual(graph.displayedEdges(new Set(['a','b','a1','b1'])),[edge]);
 graph.filters.direction='CV';
 assert.deepEqual(graph.matchingPapers().map(paper=>paper.paper_id),['a','b']);
});

test('paired contributions use the paper axis and preserve fixed papers and spacing',async()=>{
 const {KnowledgeGraphWorkspace}=await import('../../web/dist/knowledge-graph.mjs');
 const graph=new KnowledgeGraphWorkspace({esc:String,render(){}});
 const a={id:'a',node_type:'Paper',x:100,y:200};
 const b={id:'b',node_type:'Paper',x:780,y:200};
 const c={id:'c',node_type:'Paper',x:440,y:340};
 const left={id:'la',node_type:'Contribution',paper_id:'a',parent_id:'a',x:100,y:540};
 const right={id:'rb',node_type:'Contribution',paper_id:'b',parent_id:'b',x:780,y:540};
 const third={id:'rc',node_type:'Contribution',paper_id:'c',parent_id:'c',x:430,y:590};
 const nodes=[a,b,c,left,right,third];
 const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
 const length=()=>distance(a,left)+distance(left,right)+distance(right,b)+distance(left,third)+distance(third,c);
 const original=length();
 const papers=[a,b,c].map(({x,y})=>[x,y]);
 const relation=(source,target)=>({source,target,edge_type:'SIMILAR_CONTRIBUTION'});
 const edges=[relation('la','rb'),relation('la','rc')];
 graph.placeDetailNodes(nodes,edges);
 assert.ok(left.x>a.x && right.x<b.x);
 assert.ok(length()<original*.65);
 for(let i=0;i<nodes.length;i++)for(const other of nodes.slice(i+1))assert.ok(distance(nodes[i],other)>=68-1e-8);
 const placed=nodes.map(({x,y})=>[x,y]);
 graph.placeDetailNodes([a,b,c],[]);
 graph.placeDetailNodes(nodes,edges);
 assert.deepEqual(nodes.map(({x,y})=>[x,y]),placed);
 assert.deepEqual([a,b,c].map(({x,y})=>[x,y]),papers);
});
