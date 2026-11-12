import test from 'node:test';
import assert from 'node:assert/strict';
import {reportOutcome,reportNodes,suggestionType,metricGap} from '../../web/dist/report-verdict.mjs';

const dims=['scope','code','data','environment','settings','workflow','resources','results'];
const quote='We replace each convolution in the residual branch with a separable pair.';
function report({purpose,paper=true,code=true}){
 return {id:'r1',status:'completed',materials:{paper:paper?'p':null,code:code?'c':null},
  activity:[{title:'材料解析完成',time:100},{title:paper&&code?'联合审阅与计划编排':'论文审阅与指标核查',time:103},{title:'交叉核查依据',time:190},{title:'汇总审查报告',time:200}],
  audit:{status:'completed',withdrawn:1,additional_metrics:0,raw_findings:[{title:'kept'},{title:'上标丢失误读'}],
   reviews:[{index:0,decision:'retain',reason:'有原文依据'},{index:1,decision:'remove',reason:'排版丢失上标'}]},
  review:{purpose,paper_type:paper?'empirical':'code_only',criteria:dims.map(dimension=>({dimension,status:'documented',note:''})),
   findings:[],metrics:[],method_graph:[],contribution_details:[],contribution_metrics:{},paper_contributions:['模型给出的概括'],
   coverage:{gaps:[],total_paper_pages:12,paper_pages_in_context:12,total_code_files:42,code_files_in_context:18},
   plan:{hardware:'GPU',max_seconds:600,needs:[],blocked_reason:code?'':'未提供代码',
    stages:code?[{id:'S1',title:'安装依赖',file:'requirements.txt'},{id:'S2',title:'评估',file:'eval.py'}]:[],metric_patterns:[]}},
  execution:null};
}
const fixFinding={title:'正文与表 3 不一致',detail:'正文 4.2，表 3 计算为 3.7',suggestion:'统一为 3.7',severity:'high',area:'paper',confirmed_error:true,suggestion_type:'fix',page:6,file:null};
const optFinding={title:'未固定随机种子',detail:'trainer.py 未设置种子',suggestion:'增加 --seed',severity:'medium',area:'code',confirmed_error:false,suggestion_type:'optimize',page:null,file:'trainer.py'};
const stages=(failAt)=>[{id:'S1',title:'安装依赖',status:'completed',exit_code:0,started_at:300,finished_at:338,file:'requirements.txt'},
 failAt?{id:'S2',title:'评估',status:'failed',exit_code:1,started_at:338,finished_at:350,file:'eval.py',reason:''}:{id:'S2',title:'评估',status:'completed',exit_code:0,started_at:338,finished_at:400,file:'eval.py'}];
const metric=(id,expected,observed,status)=>({id,metric:id+' Top-1',expected,observed,unit:'%',tolerance:0.3,status});

test('self review, paper only: a fix list, a related-work node and no execution nodes',()=>{
 const r=report({purpose:'self_review',code:false});r.review.findings=[fixFinding,optFinding];
 const o=reportOutcome(r,{},{conflicts:[{id:'x'}]});
 assert.equal(o.headline,'需要修改 1 处');
 assert.match(o.sub,/可优化 1 处/);assert.match(o.sub,/待你确认 1 项/);
 assert.equal(o.groups.fix[0].suggestion,'统一为 3.7');
 assert.equal(o.groups.confirm[0].node,'related');
 const {nodes,notApplicable}=reportNodes(r,{},{conflicts:[]});
 assert.deepEqual(nodes.map(n=>n.id),['material','review','audit','related','report']);
 assert.equal(nodes.find(n=>n.id==='related').badge,'未发现候选重叠');
 assert.ok(notApplicable.includes('环境与运行'));
 assert.doesNotMatch(o.headline,/不通过/);
});

test('self review, code only: a failing stage becomes a required fix',()=>{
 const r=report({purpose:'self_review',paper:false});
 r.execution={status:'failed',execution_performed:true,stages:stages(true),metrics:[]};
 const o=reportOutcome(r);
 assert.equal(o.headline,'需要修改 1 处');
 assert.match(o.groups.fix[0].fact,/退出码 1/);
 const {nodes}=reportNodes(r);
 assert.equal(nodes.find(n=>n.id==='run').state,'fail');
 assert.ok(!nodes.some(n=>['metrics','related'].includes(n.id)));
});

test('self review, paper and code: a metric outside tolerance is quantified',()=>{
 const r=report({purpose:'self_review'});r.review.findings=[optFinding];
 r.execution={status:'completed',execution_performed:true,stages:stages(false),elapsed_seconds:100,
  metrics:[metric('M1',93.4,92.71,'outside_tolerance'),metric('M2',92.1,92.04,'within_tolerance')]};
 const o=reportOutcome(r);
 assert.equal(o.headline,'需要修改 1 处');
 assert.match(o.groups.fix[0].fact,/论文 93.4% · 实测 92.71% · 差 −0.69 pp · 容差 ±0.3/);
 assert.equal(o.groups.optimize[0].suggestion,'增加 --seed');
 const m=reportNodes(r).nodes.find(n=>n.id==='metrics');
 assert.equal(m.state,'fail');assert.equal(m.badge,'1 项超出容差');assert.equal(m.summary,'容差内 1/2');
});

test('other review, paper only: reasonableness verdict, no suggestions, stated innovations only from quotes',()=>{
 const r=report({purpose:'reproduce_other',code:false});r.review.findings=[fixFinding];
 const o=reportOutcome(r);
 assert.equal(o.headline,'论文合理性：存在影响结论的问题');
 assert.equal(o.groups.weakens[0].suggestion,'');
 assert.deepEqual(o.innovations,[]);
 r.review.method_graph=[{local_id:'c1',title:'深度可分离残差块',summary:'替换标准卷积',quote,page:3,section:'3.1'}];
 assert.equal(reportOutcome(r).innovations[0].status,'stated');
 assert.ok(!reportNodes(r).nodes.some(n=>n.id==='related'));
});

test('other review, code only: runnability without paper comparison or innovations',()=>{
 const r=report({purpose:'reproduce_other',paper:false});
 r.execution={status:'completed',execution_performed:true,stages:stages(false),metrics:[],elapsed_seconds:62};
 const o=reportOutcome(r);
 assert.equal(o.headline,'可运行性：跑通');
 assert.equal(o.facts[0].value,'2 / 2');
 assert.deepEqual(o.innovations,[]);
 assert.ok(reportNodes(r).notApplicable.includes('创新点凝练'));
 r.execution={...r.execution,status:'failed',stages:stages(true)};
 assert.equal(reportOutcome(r).headline,'可运行性：部分跑通 1/2');
});

test('other review, paper and code: partial reproduction with per-innovation support',()=>{
 const r=report({purpose:'reproduce_other'});
 r.review.method_graph=[{local_id:'c1',title:'可分离残差块',quote,page:3},{local_id:'c2',title:'通道重排捷径',quote,page:4},{local_id:'c3',title:'宽度搜索',quote,page:5}];
 r.review.contribution_metrics={c1:['M1'],c2:['M3']};
 r.execution={status:'completed',execution_performed:true,stages:stages(false),elapsed_seconds:255,
  metrics:[metric('M1',92.1,92.04,'within_tolerance'),metric('M2',41,41.2,'within_tolerance'),metric('M3',93.4,92.71,'outside_tolerance')]};
 const o=reportOutcome(r);
 assert.equal(o.headline,'复现程度：部分复现');
 assert.deepEqual(o.innovations.map(i=>i.status),['supported','unsupported','uncovered']);
 assert.match(o.innovations[1].evidence,/−0.69 pp/);
 assert.equal(o.facts[1].value,'2 / 3');
 assert.ok(o.groups.weakens.every(item=>item.suggestion===''));
});

test('unexecuted, running, stale and archived reports never claim a result they do not have',()=>{
 const r=report({purpose:'reproduce_other'});
 assert.equal(reportOutcome(r).headline,'复现程度：无法判定');
 assert.equal(reportNodes(r).nodes.find(n=>n.id==='metrics').state,'unreached');
 r.execution={status:'running',stages:[],metrics:[]};
 assert.equal(reportOutcome(r).tone,'wait');
 r.execution={status:'completed',execution_performed:true,stages:stages(false),metrics:[metric('M1',1,1,'within_tolerance')]};
 assert.equal(reportOutcome(r).headline,'复现程度：已复现');
 const stale=reportOutcome(r,{},{stale:true});
 assert.equal(stale.state,'stale');assert.equal(stale.tone,'wait');assert.match(stale.note,/旧版本/);
 assert.equal(suggestionType({confirmed_error:true,page:2}),'fix');
 assert.equal(suggestionType({confirmed_error:true}),'optimize');
 assert.equal(metricGap({expected:41,observed:41.2,unit:'M'}),'+0.2 M');
});

test('reproduction distinguishes missing observations from mismatches',()=>{
 const r=report({purpose:'reproduce_other'});
 r.review.metrics=[{id:'M1',author_method:true},{id:'M2',author_method:true}];
 r.review.method_graph=[{local_id:'c1',title:'可分离残差块',quote,page:3}];
 r.review.contribution_metrics={c1:['M1','M2']};
 r.execution={status:'completed',execution_performed:true,stages:stages(false),
  metrics:[metric('M1',1,null,'unobserved')]};
 assert.equal(reportOutcome(r).headline,'复现程度：无法判定');
 r.execution.metrics=[metric('M1',1,1,'within_tolerance')];
 assert.equal(reportOutcome(r).headline,'复现程度：部分复现');
 assert.equal(reportOutcome(r).innovations[0].status,'uncovered');
 assert.equal(reportOutcome(r).facts[1].value,'1 / 2');
 assert.equal(reportOutcome({...r,materials:{}}).headline,'审查结果：无法判定');
});

test('rendered reports follow the purpose: fix list for self review, innovations without advice for others',async()=>{
 const {OnlineWorkspace}=await import('../../web/dist/online-workspace.mjs');
 const ws=new OnlineWorkspace({projects:[],save:async()=>{},h:{render(){}},esc:v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')});
 const self=report({purpose:'self_review'});self.review.findings=[fixFinding,optFinding];
 self.execution={status:'completed',execution_performed:true,stages:stages(false),elapsed_seconds:100,metrics:[metric('M1',93.4,92.71,'outside_tolerance')]};
 const selfHtml=ws.finalReport(self,{title:'自查项目'});
 assert.match(selfHtml,/需要修改 2 处/);
 assert.match(selfHtml,/data-report-group="fix"/);assert.match(selfHtml,/<strong>建议<\/strong>统一为 3.7/);
 assert.match(selfHtml,/<details data-report-node="r1:metrics" open>/);
 assert.match(selfHtml,/<details data-report-node="r1:material" >/);
 assert.match(selfHtml,/data-report-anchor="rpt-node-metrics"/);
 assert.doesNotMatch(selfHtml,/创新点凝练|不通过/);
 const other=structuredClone(self);other.review.purpose='reproduce_other';
 other.review.findings=other.review.findings.map(f=>({...f,suggestion:''}));
 other.review.method_graph=[{local_id:'c1',title:'可分离残差块',quote,page:3}];other.review.contribution_metrics={c1:['M1']};
 const otherHtml=ws.finalReport(other,{title:'评估项目'});
 assert.match(otherHtml,/复现程度：<span class="rpt-verdict tone-fail">未复现/);
 assert.match(otherHtml,/创新点凝练/);assert.match(otherHtml,/实测未支持/);
 assert.doesNotMatch(otherHtml,/<strong>建议<\/strong>|导出修改清单/);
 const stale=ws.finalReport(self,{title:'自查项目',online_report:{id:'r1'},online_input_key:'old'});
 assert.match(stale,/材料已更新，本报告对应旧版本/);
});
