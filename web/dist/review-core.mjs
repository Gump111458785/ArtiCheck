// Execution identity is independent of navigation and of the selected quick probe.
export const identityOf = p => ({project_id:p.id,paper_sha256:p.paper?.sha256||null,archive_sha256:p.repository?.sha256||null,plan_sha256:p.assessment?.reproduction?.audit?.plan_sha256||null});
export function sameIdentity(a,b){return !!a&&!!b&&['project_id','paper_sha256','archive_sha256','plan_sha256'].every(k=>a[k]===b[k]);}
export function archiveExecution(s,reason){
 s.history??=[];
 if(s.job||s.report){const id=s.job?.id||s.report?.run_id||s.report?.plan_sha256;const entry={id,job:s.job,report:s.report,source:s.source,binding:s.binding,reason,archived_at:new Date().toISOString()};const index=s.history.findIndex(x=>x.id===id);if(index<0)s.history.unshift(entry);else s.history[index]=entry;}
 s.job=null;s.report=null;s.binding=null;s.source=null;s.confirmed_plan=null;
}
export function currentExecution(p){const s=p.assessment?.reproduction;if(!s||s.stale||s.source==='uploaded')return null;
 // Legacy records without an explicit binding stay in history; never infer ownership from a filename.
 if(!sameIdentity(s.binding,identityOf(p)))return null;
 if(s.job?.plan_sha256&&s.job.plan_sha256!==s.binding.plan_sha256)return null;
 if(s.report&&s.report.plan_sha256!==s.binding.plan_sha256)return null;
 return s;
}
export const dimensionNames={scope:'复现目标',code:'代码与版本',data:'数据与划分',environment:'环境重建',settings:'实验设置',commands:'执行流程',resources:'计算与预算',acceptance:'结果验收'};
export function checkTitle(code){const labels={inventory_review:'整篇实验清单完整性',method_correspondence:'核心方法与代码对应',clean_build:'干净环境重建',runtime_measurement:'实际资源与费用测量'};if(labels[code])return labels[code];const [prefix,...rest]=code.split(':');const names={conclusion_source:'主要结论的原文依据',coverage:'论文实验覆盖',splits:'数据划分来源与交集',file:'文件内容指纹',unclassified:'未归类图表'};return names[prefix]?names[prefix]+' · '+rest.join(':'):code;}
export function reviewTargets(r){return [
 ...(r.audit?.checks||[]).map((c,i)=>({id:'check:'+i,kind:'材料预审',title:checkTitle(c.code),code:c.code,status:c.status,dimension:c.dimension,detail:c.detail,evidence:c.evidence})),
 ...(r.experiments||[]).flatMap((exp,ei)=>(exp.comparisons||[]).map((c,ci)=>({id:`comparison:${ei}:${ci}`,kind:'统计',title:exp.experiment_id+' · '+c.method+' / '+c.other,status:c.status,detail:c.reason,evidence:c}))),
 ...(r.runs||[]).flatMap((run,ri)=>(run.stages||[]).map((stage,si)=>({id:`stage:${ri}:${si}`,kind:'阶段',title:`${run.experiment} / ${run.variant} / seed ${run.seed} · ${stage.id}`,status:stage.status,detail:stage.stderr||stage.stdout||'没有文本输出',evidence:stage})))
 ];}
export const needsReview=t=>['fail','unknown','review_required','not_supported','inconclusive','failed','cancelled'].includes(t.status);
export function planSummary(plan){return {runs:(plan?.experiments||[]).reduce((n,x)=>n+x.seeds.length*x.variants.length,0),stages:(plan?.experiments||[]).reduce((n,x)=>n+x.seeds.length*x.variants.length*x.stages.length,0)};}
