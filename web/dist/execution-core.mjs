import {reproductionSummary} from './reproduction-core.mjs';
import {reviewTargets,needsReview} from './review-core.mjs';

export const ROLES = [
 {id:'literature',name:'文献主张',english:'Literature Reader',icon:'book',job:'读取经人工审核的论文主张，保留页码、类型与检查规范。',input:'task.manifest.claims',output:'validated claims',events:['preflight'],full:{job:'计划审计 scope 维度：论文身份、原文出处、引用与实验覆盖。',input:'plan.paper / audit(scope)',output:'scope checks · audit.json'}},
 {id:'code',name:'代码检查',english:'Code Inspector',icon:'code',job:'盘点代码文件与受控 probe 命令，确认核查入口。',input:'artifact snapshot',output:'file inventory / probe argv',events:['preflight'],full:{job:'代码、数据、环境与设置维度审计；冻结源码快照并在结束时核对完整性。',input:'plan.repository / data / environment / settings',output:'material checks · source-files.json'}},
 {id:'planner',name:'规划调度',english:'Planner',icon:'route',job:'在预算内选择未检查主张，或决定停止。',input:'claims / findings / budget',output:'check(claim_id) | stop',events:['decision','model'],full:{job:'按冻结计划排程每次运行，核对资源声明，记录停止原因；不做模型决策。',input:'frozen plan / executor limits',output:'schedule_run · stop(reason)'}},
 {id:'experiment',name:'实验执行',english:'Experiment Runner',icon:'terminal',job:'执行受控 probe 或复用匹配源码与环境的缓存证据。',input:'probe argv / sandbox / limits',output:'Evidence + stdout / stderr',events:['tool'],full:{job:'禁网构建镜像、镜像内环境验证，按阶段执行并记录输入输出指纹。',input:'Dockerfile / stage argv / limits',output:'stage-execution.json · fingerprints'}},
 {id:'audit',name:'交叉核查',english:'Cross Auditor',icon:'shield',job:'对照主张规范与实际输出，记录判定及证据引用。',input:'Claim + Evidence',output:'Finding + evidence_ids',events:['audit'],full:{job:'镜像兼容、未声明改动、配置冻结、划分与训练证据、独立指标重算及公平性。',input:'stage outputs / metric files / plan acceptance',output:'stage_checks · run_verdict · acceptance'}},
 {id:'report',name:'报告归档',english:'Reporter',icon:'file',job:'归档逐主张结论、使用量、停止原因与原始轨迹。',input:'findings / trace / usage',output:'report.md / report.json',events:['complete'],full:{job:'汇总运行、环境、训练协议与主要结论四层验收。',input:'runs / experiments / audit',output:'levels · report.json'}}
];
export const statusLabels={queued:'排队中',running:'执行中',completed:'已完成',failed:'执行失败',cancelled:'已停止',pending:'未开始'};
export const sourceLabels={runtime:'本机执行',teaching:'教学归档',public_case:'公开 CI 归档'};
export const kindLabels={full:'完整实验',probe:'短时核查'};
export const ROLE_IDS={LiteratureReader:'literature',CodeInspector:'code',Planner:'planner',ExperimentRunner:'experiment',CrossAuditor:'audit',Reporter:'report'};
export const roleEvents=(run,id)=>(run?.events||[]).filter(x=>x.kind==='role'?x.roleId===id:ROLES.find(r=>r.id===id)?.events.includes(x.kind));
// Adapts executor-written roles.jsonl (GET /api/reproduction/runs/{id}/roles) to the role page; never synthesizes events.
export function fullRoleRun(data,status){
 const events=(Array.isArray(data?.events)?data.events:[]).filter(x=>x&&ROLE_IDS[x.role]).map(x=>({...x,kind:'role',roleId:ROLE_IDS[x.role],sequence:x.seq}));
 const active=['running','queued'].includes(status);
 const stages=Object.fromEntries(ROLES.map(r=>{const mine=events.filter(x=>x.roleId===r.id);return [r.id,!mine.length?'pending':mine.some(x=>x.status==='fail')?'failed':active?'running':status==='cancelled'?'cancelled':'completed'];}));
 return {mode:'full',available:Boolean(data?.available)&&events.length>0,events,stages,policy:data?.policy||{Planner:'frozen_plan'},skipped:data?.skipped||0,error:data?.error||null};
}
export function rolePayload(event,id){return event.kind==='preflight'?event.data?.[id]:event;}
export function roleState(run,id){if(!run)return 'pending';const explicit=run.stages?.[id];if(Object.hasOwn(statusLabels,explicit))return explicit;return roleEvents(run,id).length?'completed':'pending';}
export function fullRecord(job,report,projects=[],source='runtime'){
 const sum=report?reproductionSummary(report):null,project=projects.find(x=>x.id===job?.project_id);
 return {key:source==='public_case'?'case:liblinear':'full:'+job.id,id:job?.id,kind:'full',source,project_id:job?.project_id||null,title:source==='public_case'?'LIBLINEAR / news20':project?.title||job?.project_id||'独立完整实验',status:job?.status||report?.status||'queued',
  created_at:job?.created_at||report?.created_at||null,completed:job?.progress?.completed_runs??sum?.completed??0,total:sum?.expected??null,unit:'次运行',phases:job?.progress&&report&&job.progress.recorded_runs!==report.runs.length?null:sum?.stages??null,
  attention:report?reviewTargets(report).filter(needsReview).length:null,plan_sha256:job?.plan_sha256||report?.plan_sha256||null,report,job};
}
export function probeRecord(run,tasks=[],projects=[],mode='demo'){
 const task=tasks.find(t=>t.id===run.task_id),project=projects.find(p=>p.run_id===run.id),source=mode==='runtime'?'runtime':'teaching',findings=run.findings||run.report?.findings||[];
 return {key:'probe:'+run.id,id:run.id,kind:'probe',source,project_id:project?.id||null,title:project?.title||task?.title||run.title||'短时主张核查',status:run.status,created_at:source==='teaching'?null:run.created_at||null,
  completed:findings.length,total:task?.claim_count??task?.manifest?.claims?.length??null,unit:'条主张',phases:null,attention:findings.filter(f=>f.verdict!=='supported').length,plan_sha256:null,run,task};
}
export function executionRecords({jobs=[],publicCase=null,runs=[],tasks=[],projects=[],mode='demo',selected=null}={}){
 const rows=jobs.map(job=>fullRecord(job,selected?.job?.id===job.id?selected.report:null,projects));
 if(publicCase)rows.push(fullRecord(null,publicCase,projects,'public_case'));
 rows.push(...runs.map(run=>probeRecord(run,tasks,projects,mode)));
 return rows.sort((a,b)=>Number(['running','queued'].includes(b.status))-Number(['running','queued'].includes(a.status))||Number(b.source==='runtime')-Number(a.source==='runtime')||String(b.created_at||'').localeCompare(String(a.created_at||'')));
}
export function filterRecords(rows,{query='',kind='all',source='all',status='all',project='all'}={}){
 const q=query.trim().toLocaleLowerCase();return rows.filter(r=>(kind==='all'||r.kind===kind)&&(source==='all'||r.source===source)&&(project==='all'||r.project_id===project)&&(status==='all'||status==='active'&&['running','queued'].includes(r.status)||status==='attention'&&((r.attention??0)>0||r.status==='failed')||status==='completed'&&r.status==='completed')&&(!q||[r.title,r.id,r.plan_sha256,kindLabels[r.kind],sourceLabels[r.source]].filter(Boolean).join(' ').toLocaleLowerCase().includes(q)));
}
export function recordCounts(rows){return {all:rows.length,active:rows.filter(r=>['running','queued'].includes(r.status)).length,attention:rows.filter(r=>(r.attention??0)>0||r.status==='failed').length,completed:rows.filter(r=>r.status==='completed').length};}
export function progressText(row){return `${row.completed} / ${row.total??'—'} ${row.unit}`;}
