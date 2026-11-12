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
