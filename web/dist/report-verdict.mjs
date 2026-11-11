export function criteriaDecisions(report,project){
 const saved=project?.online_criteria_review;
 const reviewed=new Set(saved?.reportId===report?.id?saved?.dimensions:[]);
 return (report?.review?.criteria||[]).map(row=>row.status==='needs_review'&&reviewed.has(row.dimension)?{...row,status:'documented',manuallyReviewed:true}:row);
}
export function reportVerdict(report,project){
 if(report?.terminated_at)return {state:'pending',label:'已终止',scope:'本次审查',reason:'可查看终止前取得的证据与执行记录。'};
 if(!report?.review)return {state:'pending',label:'待验收',scope:'审查尚未结束',reason:'等待材料审阅和执行记录。'};
 const v=report.review,x=report.execution,metrics=x?.metrics||[];
 if(['nonpaper','unknown'].includes(v.paper_type))return {state:'pending',label:v.paper_type==='nonpaper'?'不适用':'需确认',scope:'材料适用性',reason:v.classification_reason||'当前材料尚不支持论文验收，请查看报告范围。'};
 if(report.availability?.answer==='unavailable'||x?.user_answer==='unavailable')return {state:'failed',label:'未通过',scope:'当前条件下的复现验收',reason:'必要材料或资源经确认无法提供，受影响实验未完成。'};
 if(metrics.some(m=>m.status==='outside_tolerance'))return {state:'failed',label:'未通过',scope:'本次实验指标检查',reason:'实际观测与报告目标超出本次验收容差。'};
 if(['failed','expired','cancelled'].includes(x?.status))return {state:'pending',label:'待验收',scope:'实验执行受阻',reason:'已有过程保留；执行失败、超时或停止不等同于论文结论不成立。'};
 if(report.status==='reviewing'||['running','starting','queued','cancelling'].includes(x?.status))return {state:'pending',label:'审查进行中',scope:'等待最终结果',reason:'审阅与实验步骤尚未全部结束。'};
 const criteria=criteriaDecisions(report,project),missing=criteria.filter(c=>c.status==='missing'),issues=v.findings.filter(f=>f.severity==='high');
 if(missing.length||issues.length)return {state:'failed',label:'未通过',scope:'本次材料预审',reason:`${missing.length?missing.length+' 项条件缺少依据':''}${missing.length&&issues.length?'，':''}${issues.length?issues.length+' 项优先处理问题':''}；详见逐项证据与修正建议。`};
 if(criteria.some(c=>c.status==='needs_review')||v.findings.length||v.coverage.gaps.length||metrics.some(m=>m.observed==null)||v.plan.stages.length&&!x?.execution_performed)return {state:'pending',label:'待验收',scope:'部分检查需要复核',reason:'仍有待核对条件、建议、覆盖缺口或未观测指标，不能标记为通过。'};
 return {state:'passed',label:'通过',scope:x?.execution_performed?'本次检查范围内的验收':'本次材料预审',reason:'本次已覆盖检查满足验收条件；完整论文主要结论仍以独立实验依据为准。'};
}
