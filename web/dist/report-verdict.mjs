import {criterionNames,typeNames} from './online-core.mjs';

export function criteriaDecisions(report,project){
 const saved=project?.online_criteria_review;
 const reviewed=new Set(saved?.reportId===report?.id?saved?.dimensions:[]);
 return (report?.review?.criteria||[]).map(row=>row.status==='needs_review'&&reviewed.has(row.dimension)?{...row,status:'documented',manuallyReviewed:true}:row);
}
const statusLabels={passed:'通过',failed:'不通过',pending:'待核查'};
function result(state,scope,reason,extra={}){return {state,label:statusLabels[state],scope,reason,...extra};}

export function reportVerdict(report,project){
 const v=report?.review,x=report?.execution,metrics=x?.metrics||[];
 if(!v)return result('pending','本次审查','审查尚未生成可验收的报告。');
 if(report.terminated_at)return result('pending','本次审查','审查已终止，部分证据尚未核验。');
 const mismatches=metrics.filter(m=>m.status==='outside_tolerance');
 const errors=(v.findings||[]).filter(f=>f.confirmed_error&&(f.page||f.file));
 if(mismatches.length)return result('failed','实验指标','实测值超出验收容差。',{mismatches,errors});
 if(errors.length)return result('failed','证据一致性',errors[0].title,{errors});
 if(['failed','expired'].includes(x?.status)||report.availability?.answer==='unavailable'||x?.user_answer==='unavailable'){
  const stage=x?.stages?.find(row=>row.status==='failed');
  return result('failed','复现执行',stage?.reason||x?.availability_verdict||report.availability?.verdict||
   (x?.status==='expired'?'运行超时，复现未完成。':'复现未完成，详见实验执行记录。'),{stage});
 }
 if(['cancelled','cancelling'].includes(x?.status))return result('pending','本次审查','审查已中断，部分证据尚未核验。');
 if(['nonpaper','unknown'].includes(v.paper_type))return result('pending','材料适用性',v.classification_reason||'材料类型或检查范围仍需确认。');
 if(report.status==='reviewing'||['running','starting','queued'].includes(x?.status))return result('pending','本次审查','审阅或实验仍在进行。');
 const planned=(v.plan?.stages||[]).length>0;
 const declared=(v.metrics||[]).filter(m=>m.author_method&&m.id);
 const required=new Set([...declared.map(m=>m.id),...(v.plan?.metric_patterns||[]).map(m=>m.metric_id)]);
 const observed=metrics.filter(m=>m.status==='within_tolerance'&&m.observed!=null);
 const checked=new Set(observed.map(m=>m.id).filter(Boolean));
 const missingMetrics=[...required].filter(id=>!checked.has(id));
 if(missingMetrics.length||metrics.some(m=>m.status!=='within_tolerance'||m.observed==null)
  ||planned&&!x?.execution_performed||v.purpose==='reproduce_other'&&v.paper_type==='empirical'&&!observed.length){
  return result('pending','实验指标',missingMetrics.length?`还有 ${missingMetrics.length} 项指标缺少可比较的实测结果。`:'当前缺少足够的实验观测。');
 }
 const conditions=criteriaDecisions(report,project);
 if(conditions.some(c=>['missing','needs_review'].includes(c.status))||(v.findings||[]).length||(v.coverage?.gaps||[]).length){
  return result('pending','证据核查','仍有疑点、待核查条件或覆盖缺口。');
 }
 return result('passed','本次核验范围',observed.length?`${observed.length} 项实测指标均符合验收要求。`:'本次适用的检查均有证据支持。');
}

// ---- Final report: one skeleton; the outcome depends on purpose × submitted materials ----

export function reportScope(report,project){
 const v=report?.review||{},x=report?.execution||null;
 const purpose=['self_review','reproduce_other'].includes(v.purpose)?v.purpose:v.task==='reproduction'?'reproduce_other':'self_review';
 const paper=Boolean(report?.materials?report.materials.paper:project?.paper);
 const code=Boolean(report?.materials?report.materials.code:project?.repository);
 return {v,x,purpose,paper,code,materials:paper&&code?'both':paper?'paper':code?'code':'none'};
}

const num=n=>typeof n==='number'&&Number.isFinite(n)?String(Number(n.toFixed(6))):'未记录';
export const withUnit=(value,unit)=>value==null?'未记录':num(value)+(unit?(unit==='%'?'%':' '+unit):'');
export function metricGap(m){
 if(typeof m?.observed!=='number'||typeof m?.expected!=='number')return '';
 const d=m.observed-m.expected;
 if(d===0)return '0';
 return (d>0?'+':'−')+Number(Math.abs(d).toFixed(4))+(m.unit==='%'?' pp':m.unit?' '+m.unit:'');
}
export function duration(seconds){
 if(typeof seconds!=='number'||!Number.isFinite(seconds))return '';
 const s=Math.max(0,Math.round(seconds));
 return s<60?`${s} 秒`:`${Math.floor(s/60)} 分 ${String(s%60).padStart(2,'0')} 秒`;
}
export function location(row){return [row?.page?`PDF 第 ${row.page} 页`:'',row?.reference||'',row?.file||''].filter(Boolean).join(' · ');}
export function suggestionType(f){
 if(f?.suggestion_type==='fix'||f?.suggestion_type==='optimize')return f.suggestion_type;
 return f?.confirmed_error&&(f.page||f.file)?'fix':'optimize';
}
function areaOf(f,{paper,code}){return !paper?'code':!code?'paper':f.area||(f.page&&f.file?'alignment':f.file?'code':'paper');}
const failedStages=x=>(x?.stages||[]).filter(s=>s.status==='failed');

function findingItem(f,index,scope){
 return {key:'finding-'+index,title:f.title,fact:f.detail||'',location:location(f),suggestion:f.suggestion||'',node:'review',area:areaOf(f,scope)};
}
function metricItem(m,v){
 const src=(v.metrics||[]).find(t=>t.id===m.id)||{};
 return {key:'metric-'+m.id,title:`${m.metric||m.id} 超出容差`,
  fact:`论文 ${withUnit(m.expected,m.unit)} · 实测 ${withUnit(m.observed,m.unit)} · 差 ${metricGap(m)} · 容差 ±${num(m.tolerance)}`,
  location:location({page:src.page,reference:src.reference}),suggestion:'',node:'metrics'};
}
function stageItem(s){
 return {key:'stage-'+s.id,title:`阶段 ${s.title||s.id} 执行失败`,
  fact:[s.exit_code!=null?`退出码 ${s.exit_code}`:'',s.timed_out?'超时':'',s.reason||''].filter(Boolean).join(' · ')||'阶段未正常结束',
  location:s.file||'',suggestion:'',node:'run'};
}
function confirmItems(report,project,scope,conflicts){
 const items=criteriaDecisions(report,project).filter(row=>['missing','needs_review'].includes(row.status)).map(row=>({
  key:'criterion-'+row.dimension,title:`${criterionNames[row.dimension]||row.dimension}：${row.status==='missing'?'缺少依据':'需要复核'}`,
  fact:row.note||'',location:location(row),suggestion:'',node:'review',dimension:row.dimension,status:row.status}));
 const {v,x}=scope;
 if(x?.needs_user&&x.question)items.push({key:'needs-user',title:'执行受阻，需要补充材料',fact:x.question,location:'',suggestion:'',node:'run'});
 if(scope.code&&!(v.plan?.stages||[]).length)items.push({key:'no-plan',title:'未生成可执行计划',fact:v.plan?.blocked_reason||'没有找到可以直接运行的入口。',location:'',suggestion:'',node:'plan'});
 if(scope.purpose==='self_review'&&conflicts?.length)items.push({key:'related',title:`与已有工作可能重叠 ${conflicts.length} 处`,fact:'候选来自你已加入知识图谱的论文，是否构成重复需要你判断。',location:'',suggestion:'',node:'related'});
 return items;
}
function progress(report,stale){
 const x=report?.execution;
 if(report?.terminated_at)return {state:'terminated',note:'审查已终止，以下为终止前取得的结果。'};
 if(report?.status==='reviewing')return {state:'running',note:'审阅仍在进行。'};
 if(['queued','starting','running','cancelling'].includes(x?.status))return {state:'running',note:'实验仍在执行，结束后结果会更新。'};
 if(stale)return {state:'stale',note:'材料已更新，本报告对应旧版本，请重新审查。'};
 return null;
}
function failureReason(x){
 const s=failedStages(x)[0];
 if(x?.failure_category==='transient_service')return '外部服务暂时不可用（限流或网络超时）';
 if(s?.timed_out)return `阶段 ${s.title||s.id} 超时`;
 if(x?.needs_user)return '缺少数据、权重或运行条件';
 if(s)return `阶段 ${s.title||s.id} 退出码 ${s.exit_code}`;
 return x?.status==='expired'?'运行超时':x?.notice||'执行未完成';
}
export function runState({v,x}){
 const planned=(v.plan?.stages||[]).length,stages=x?.stages||[];
 const done=stages.filter(s=>s.status==='completed').length,total=planned||stages.length;
 if(!planned)return {key:'blocked',label:'无法执行',tone:'wait',done,total,reason:v.plan?.blocked_reason||'未生成可执行计划'};
 if(!x)return {key:'not_run',label:'未执行',tone:'wait',done,total,reason:'计划尚未执行'};
 if(['queued','starting','running','cancelling'].includes(x.status))return {key:'running',label:'执行中',tone:'wait',done,total,reason:''};
 if(x.status==='cancelled')return {key:'interrupted',label:'已中断',tone:'wait',done,total,reason:'执行被停止'};
 if(x.status==='completed'&&total>0&&done===total)return {key:'passed',label:'跑通',tone:'pass',done,total,reason:''};
 return {key:done?'partial':'failed',label:done?`部分跑通 ${done}/${total}`:'未跑通',tone:done?'warn':'fail',done,total,reason:failureReason(x)};
}

export function innovations(scope){
 const {v,x}=scope;
 const rows=(v.method_graph||[]).length
  ?v.method_graph.map(g=>({id:g.local_id,title:g.title,summary:g.summary&&g.summary!==g.title?g.summary:'',quote:g.quote,page:g.page,section:g.section||''}))
  :(v.contribution_details||[]).map((d,i)=>({id:'detail-'+i,title:d.summary,summary:'',quote:d.quote,page:d.page,section:''}));
 const executed=scope.code&&Boolean(x?.execution_performed);
 return rows.filter(row=>row.title&&row.quote).slice(0,5).map(row=>{
  if(!executed)return {...row,status:'stated',statusLabel:'论文自述，未经执行验证',evidence:''};
  const ids=(v.contribution_metrics||{})[row.id]||[],ms=(x.metrics||[]).filter(m=>ids.includes(m.id));
  if(!ms.length)return {...row,status:'uncovered',statusLabel:'未覆盖',evidence:'本次执行没有直接支撑这一点的指标。'};
  const bad=ms.filter(m=>m.status==='outside_tolerance');
  if(bad.length)return {...row,status:'unsupported',statusLabel:'实测未支持',evidence:bad.map(m=>`${m.metric} 实测 ${withUnit(m.observed,m.unit)}，与论文差 ${metricGap(m)}，超出容差`).join('；')};
  if(ids.every(id=>ms.some(m=>m.id===id&&m.status==='within_tolerance'&&Number.isFinite(m.observed))))return {...row,status:'supported',statusLabel:'实测支持',evidence:ms.map(m=>`${m.metric} 实测 ${withUnit(m.observed,m.unit)}，与论文差 ${metricGap(m)}`).join('；')};
  return {...row,status:'uncovered',statusLabel:'未覆盖',evidence:'相关指标未取得观测值。'};
 });
}

export function reportOutcome(report,project,{stale=false,conflicts=null}={}){
 const scope=reportScope(report,project),{v,x}=scope;
 const findings=(v.findings||[]).map((f,i)=>({f,i}));
 const outside=(x?.metrics||[]).filter(m=>m.status==='outside_tolerance');
 const failed=scope.code?failedStages(x):[];
 const confirm=confirmItems(report,project,scope,conflicts);
 const flag=progress(report,stale);
 const run=scope.code?runState(scope):null;
 const fixes=findings.filter(({f})=>suggestionType(f)==='fix').map(({f,i})=>findingItem(f,i,scope));
 const others=findings.filter(({f})=>suggestionType(f)!=='fix').map(({f,i})=>findingItem(f,i,scope));
 if(scope.purpose==='self_review'){
  const fix=[...outside.map(m=>metricItem(m,v)),...failed.map(stageItem),...fixes];
  const headline=fix.length?`需要修改 ${fix.length} 处`:others.length?`可优化 ${others.length} 处`:'核验范围内未发现需要修改的问题';
  const sub=[fix.length&&others.length?`可优化 ${others.length} 处`:'',confirm.length?`待你确认 ${confirm.length} 项`:''].filter(Boolean).join(' · ');
  return {...scope,state:flag?.state||(fix.length?'fix':others.length?'optimize':'clean'),
   tone:flag?'wait':fix.length?'fail':others.length?'warn':'pass',headline,sub,note:flag?.note||'',run,
   groups:{fix,optimize:others,confirm},total:fix.length+others.length+confirm.length};
 }
 const strip=item=>({...item,suggestion:''});
 const weakens=[...outside.map(m=>metricItem(m,v)),...failed.map(stageItem),...fixes].map(strip);
 const gaps=others.map(strip);
 const ms=x?.metrics||[];
 const compared=ms.filter(m=>Number.isFinite(m.observed)&&['within_tolerance','outside_tolerance'].includes(m.status));
 const within=compared.filter(m=>m.status==='within_tolerance').length;
 const expected=new Set([...(v.metrics||[]).filter(m=>m.author_method).map(m=>m.id),
  ...(v.plan?.metric_patterns||[]).map(m=>m.metric_id),...ms.map(m=>m.id)].filter(Boolean));
 const missing=[...expected].filter(id=>!compared.some(m=>m.id===id)).length;
 const cov=v.coverage||{};
 let verdict,facts;
 if(scope.materials==='none'){
  verdict={title:'审查结果',label:'无法判定',tone:'wait',reason:'此记录缺少可核对的材料信息。'};
  facts=[];
 }else if(scope.materials==='paper'){
  verdict={title:'论文合理性',label:weakens.length?'存在影响结论的问题':gaps.length?'存在疑点':'未发现问题',tone:weakens.length?'fail':gaps.length?'warn':'pass',
   reason:weakens.length||gaps.length?`有直接证据的问题 ${weakens.length} 处，存疑 ${gaps.length} 处。`:'核验范围内的数据与论证均找到依据。'};
  facts=[{label:'核对页数',value:`${cov.paper_pages_in_context??'—'} / ${cov.total_paper_pages??'—'}`,unit:'页'},
   {label:'图表指标',value:String((v.metrics||[]).length),unit:'项有出处'},{label:'存疑与问题',value:String(weakens.length+gaps.length),unit:'处'}];
 }else if(scope.materials==='code'){
  verdict={title:'可运行性',label:run.label,tone:run.tone,reason:run.reason||(run.key==='passed'?`${run.total} 个阶段全部以退出码 0 结束。`:'')};
  facts=[{label:'阶段',value:`${run.done} / ${run.total}`,unit:'完成'},
   {label:'运行资源',value:v.plan?.hardware||'CPU',unit:x?.elapsed_seconds!=null?'用时 '+duration(x.elapsed_seconds):''}];
 }else{
  let label,tone,reason;
  if(['blocked','not_run','interrupted'].includes(run.key)){label='无法判定';tone='wait';reason=run.reason;}
  else if(run.key==='running'){label='执行中';tone='wait';reason='';}
  else if(run.key!=='passed'){label='未复现';tone='fail';reason=`代码${run.label}：${run.reason}`;}
  else if(!compared.length){label='无法判定';tone='wait';reason='运行完成，但没有可与论文比较的观测值。';}
  else if(within===compared.length&&!missing&&!weakens.length){label='已复现';tone='pass';reason=`${within} 项实测指标均在容差内。`;}
  else if(within>0){label='部分复现';tone='warn';reason=[`${compared.length} 项实测指标中 ${within} 项在容差内`,
   missing?`${missing} 项缺少可比较的观测值`:'',fixes.length?`${fixes.length} 处已确认的问题`:''].filter(Boolean).join(' · ');}
  else{label='未复现';tone='fail';reason=`${compared.length} 项实测指标超出容差。`;}
  verdict={title:'复现程度',label,tone,reason};
  const needs=(v.plan?.needs||[]).filter(n=>n.required).length;
  facts=[{label:'能否跑通',value:`${run.done} / ${run.total}`,unit:'阶段完成'},
   {label:'与论文指标契合',value:`${within} / ${expected.size||compared.length}`,unit:'在容差内'},
   {label:'实现与论文描述',value:String(findings.filter(({f})=>areaOf(f,scope)==='alignment').length),unit:'处不一致'},
   {label:'复现成本',value:[v.plan?.hardware||'CPU',x?.elapsed_seconds!=null?duration(x.elapsed_seconds):''].filter(Boolean).join(' · '),unit:needs?`需要 ${needs} 项数据或资源`:'无额外数据或资源要求'}];
 }
 return {...scope,state:flag?.state||verdict.tone,tone:flag?'wait':verdict.tone,headline:`${verdict.title}：${verdict.label}`,
  verdict,facts,note:flag?.note||'',run,innovations:scope.paper?innovations(scope):[],
  groups:{weakens,gaps,confirm},total:weakens.length+gaps.length+confirm.length};
}

const timeOf=t=>typeof t==='number'&&Number.isFinite(t)?t:null;
function activityTime(report,pattern){return timeOf((report?.activity||[]).find(a=>pattern.test(a.title||''))?.time);}

export function reportNodes(report,project,{stale=false,conflicts=null,conflictError=false}={}){
 const outcome=reportOutcome(report,project,{stale,conflicts});
 const {v,x,paper,code,purpose,run}=outcome,cov=v.coverage||{},findings=v.findings||[],nodes=[];
 nodes.push({id:'material',title:'材料接收',time:activityTime(report,/材料解析/),state:'pass',badge:'通过',
  summary:[paper?`论文 ${cov.total_paper_pages??'—'} 页`:'',code?`代码 ${cov.total_code_files??'—'} 个文件`:'',typeNames[v.paper_type]?`识别为${typeNames[v.paper_type]}`:''].filter(Boolean).join(' · ')});
 const parts=[];
 const pick=area=>findings.map((f,i)=>({...f,index:i})).filter(f=>areaOf(f,outcome)===area);
 if(paper)parts.push({name:'论文',findings:pick('paper'),facts:`读取 ${cov.paper_pages_in_context??'—'}/${cov.total_paper_pages??'—'} 页 · 图表指标 ${(v.metrics||[]).length} 项`});
 if(code)parts.push({name:'代码',findings:pick('code'),facts:`审阅 ${cov.code_files_in_context??'—'}/${cov.total_code_files??'—'} 个文件`});
 if(paper&&code)parts.push({name:'论文与代码对齐',findings:pick('alignment'),facts:''});
 nodes.push({id:'review',title:paper&&code?'联合审阅':paper?'论文审阅':'代码审阅',time:activityTime(report,/联合审阅|论文审阅/),
  state:findings.length?'issue':'pass',badge:findings.length?`${findings.length} 处问题`:'通过',summary:parts.map(p=>p.facts).filter(Boolean).join(' · '),parts});
 const audit=report?.audit;
 if(audit?.status==='completed'){
  const reviews=audit.reviews||[],withdrawn=reviews.filter(r=>r.decision==='remove');
  nodes.push({id:'audit',title:'交叉复核',time:activityTime(report,/交叉核查依据/),state:'pass',badge:'通过',
   summary:`复核 ${reviews.length} 条：保留 ${reviews.length-withdrawn.length} 条，撤回 ${withdrawn.length} 条依据不足的条目`+(audit.additional_metrics?` · 补充指标 ${audit.additional_metrics} 项`:''),
   withdrawn:withdrawn.map(r=>({title:audit.raw_findings?.[r.index]?.title||'',reason:r.reason}))});
 }else if(audit){
  nodes.push({id:'audit',title:'交叉复核',time:activityTime(report,/交叉复核未执行|交叉核查依据/),state:'skipped',badge:'未完成',
   summary:{request_deadline:'审阅用时接近上限，本次未复核',cross_audit_failed:'复核请求未成功'}[audit.reason]||'复核未完成；问题按原审阅结果列出'});
 }
 if(purpose==='self_review'&&paper){
  nodes.push({id:'related',title:'相关工作对比',time:null,
   state:conflictError?'skipped':conflicts==null?'running':conflicts.length?'confirm':'pass',
   badge:conflictError?'未完成':conflicts==null?'读取中':conflicts.length?`${conflicts.length} 项待确认`:'未发现候选重叠',
   summary:'比较范围：你已加入知识图谱的论文；共享数据集与指标或贡献描述相似的列为候选'});
 }
 if(code){
  const planned=v.plan?.stages||[],patterns=v.plan?.metric_patterns||[];
  nodes.push({id:'plan',title:'执行计划',time:activityTime(report,/主审结果已返回/),state:planned.length?'pass':'fail',badge:planned.length?'通过':'无法执行',
   summary:planned.length?[`${planned.length} 个阶段`,v.plan.hardware||'CPU',v.plan.max_seconds?`时间上限 ${duration(v.plan.max_seconds)}`:'',paper?(patterns.length?`绑定 ${patterns.length} 项指标`:'未绑定论文指标'):''].filter(Boolean).join(' · '):(v.plan?.blocked_reason||'未生成可执行计划'),
   stages:planned});
  const state={passed:'pass',partial:'fail',failed:'fail',running:'running',interrupted:'interrupted',blocked:'unreached',not_run:'unreached'}[run.key];
  nodes.push({id:'run',title:'环境与运行',time:timeOf(x?.started_at),state,
   badge:{pass:'通过',fail:run.label,running:'执行中',interrupted:'已中断',unreached:'未执行'}[state],
   summary:run.key==='passed'?`${run.done}/${run.total} 阶段完成 · 退出码均为 0`+(x?.elapsed_seconds!=null?` · 用时 ${duration(x.elapsed_seconds)}`:'')
    :['partial','failed'].includes(run.key)?`${run.done}/${run.total} 阶段完成 · ${run.reason}`
    :run.key==='running'?`${run.done}/${run.total} 阶段完成`:run.reason,
   stages:(x?.stages||[]).map(s=>({id:s.id,title:s.title||s.id,file:s.file||'',status:s.status,exit:s.exit_code,reason:s.reason||'',
    duration:timeOf(s.started_at)!=null&&timeOf(s.finished_at)!=null?duration(s.finished_at-s.started_at):'',tail:(s.live_tail||[]).slice(-2)})),
   runtime:x?.runtime||null});
  if(paper){
   const ms=x?.metrics||[],bad=ms.filter(m=>m.status==='outside_tolerance'),none=ms.filter(m=>typeof m.observed!=='number'),
    good=ms.filter(m=>m.status==='within_tolerance'&&typeof m.observed==='number');
   const rows=ms.map(m=>{const src=(v.metrics||[]).find(t=>t.id===m.id)||{},rule=(v.plan?.metric_patterns||[]).find(p=>p.metric_id===m.id)||{};
    return {...m,gap:metricGap(m),source:location({page:src.page,reference:src.reference}),basis:rule.tolerance_basis||''};});
   let state,badge,summary;
   if(['blocked','not_run','interrupted'].includes(run.key)){state='unreached';badge='未执行';summary=`上游未完成：${run.reason||run.label}`;}
   else if(run.key==='running'){state='running';badge='等待执行';summary='执行结束后比对';}
   else if(!ms.length){state='skipped';badge='无可比指标';summary='计划没有绑定可与论文比较的指标';}
   else if(bad.length){state='fail';badge=`${bad.length} 项超出容差`;summary=`容差内 ${good.length}/${ms.length}`+(none.length?` · 未取得观测 ${none.length} 项`:'');}
   else if(none.length){state='issue';badge=`${none.length} 项无观测`;summary=`容差内 ${good.length}/${ms.length}`;}
   else{state='pass';badge='通过';summary=`容差内 ${good.length}/${ms.length}`;}
   nodes.push({id:'metrics',title:'指标比对',time:timeOf(x?.finished_at),state,badge,summary,rows});
  }
 }
 nodes.push({id:'report',title:'报告汇总',time:Math.max(activityTime(report,/汇总审查报告/)||0,timeOf(x?.finished_at)||0)||null,state:'pass',badge:'',
  summary:purpose==='self_review'?`修改清单 ${outcome.total} 条`:`${outcome.headline}`+(outcome.innovations.length?` · 创新点 ${outcome.innovations.length} 条`:'')});
 const notApplicable=paper&&!code?['代码审阅','执行计划','环境与运行','指标比对']:code&&!paper?['论文审阅','指标比对',...(purpose==='reproduce_other'?['创新点']:[])]:[];
 return {outcome,nodes,notApplicable};
}
