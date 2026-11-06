export const taskNames={auto:'自动识别',self_review:'论文自查',reproduction:'复现评估',code_review:'代码审查'};
export const typeNames={empirical:'实验研究',diagnostic:'诊断与分析',survey:'综述',nonpaper:'非论文材料',unknown:'类型待确认',code_only:'代码项目'};
export const criterionNames={scope:'目标与覆盖',code:'代码与版本',data:'数据与划分',environment:'环境重建',settings:'实验设置',workflow:'执行流程',resources:'资源条件',results:'结果与论证'};
export const statusNames={documented:'有材料依据',needs_review:'需要复核',missing:'缺少依据',not_applicable:'不适用'};
export const executionNames={queued:'等待 GPU 执行器',cancelling:'正在停止',starting:'正在创建执行环境',running:'正在执行',completed:'执行结束',failed:'执行受阻',expired:'执行已超时',cancelled:'已停止'};
export function metricUnit(m){
 const ambiguous=m.unit_uncertain||(['%','％','percent','percentage','百分比'].includes(String(m.unit).trim().toLowerCase())&&m.value>=0&&m.value<=1&&!/[%％]|百分/.test(m.quote||''));
 return ambiguous?'（单位待核对）':m.unit||'';
}
export function inputKey(p){return JSON.stringify([p.paper?.sha256||null,p.repository?.sha256||null,p.online_task||'auto',p.online_scope||'',p.online_max_seconds||null,p.online_supply_notes||'']);}
export function hasCode(p){return Boolean(p.repository?.blob||p.repository?.remote?.repository);}
export function validateInput(p,{token='',consent=false}={}){
 const errors={};
 if(!p.paper?.blob&&!hasCode(p))errors.material='请至少上传论文 PDF 或导入代码。';
 if(p.online_restrict&&!p.online_scope?.trim())errors.scope='请填写本次只审查的表格、实验或指标。';
 const n=p.online_max_seconds;
 if(n!==''&&n!=null&&(!Number.isInteger(Number(n))||Number(n)<30||Number(n)>600))errors.seconds='请填写 30–600 秒，或留空使用默认时限。';
 if(!consent)errors.consent='请确认允许发送本次材料。';
 return errors;
}
export function checkAssessment(value){
 if(!value||value.format!=='articheck-online-assessment-v2'||!/^[a-f0-9]{32}$/.test(value.id)||value.source!=='model_api_review'||value.scientific_validation!==false)throw Error('审查报告结构或来源无效。');
 if(!value.review&&['reviewing','failed'].includes(value.status))return value;
 if(!value.review||!Array.isArray(value.review.criteria)||value.review.criteria.length!==8||!Array.isArray(value.review.findings)||!Array.isArray(value.review.metrics)||!Array.isArray(value.review.plan?.stages))throw Error('审查报告内容不完整。');
 return value;
}
export function coverageCounts(value){
 const metrics=value.review.metrics,observed=value.execution?.metrics||[];
 return {identified:metrics.length,observed:observed.filter(m=>typeof m.observed==='number').length,
  missing:metrics.filter(m=>!observed.some(o=>o.id===m.id&&typeof o.observed==='number')).length,
  gaps:value.review.coverage.gaps.length};
}
export function sessionCapability(storage=localStorage){
 let value=storage.getItem('articheck:online-owner');
 if(!/^[a-f0-9]{64}$/.test(value||'')){
  value=Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
  storage.setItem('articheck:online-owner',value);
 }
 return value;
}
