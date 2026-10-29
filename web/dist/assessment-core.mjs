export const dimensions = [
 ['scope','复现目标','论文版本、核心结论、对应图表与未覆盖实验'],
 ['code','代码与版本','核心方法、数据处理、训练与评估入口；论文对应 commit'],
 ['data','数据与划分','获取条件、版本与校验和、训练/验证/测试划分、预处理'],
 ['environment','环境重建','操作系统、依赖锁定、框架/CUDA、干净环境构建日志'],
 ['settings','实验设置','超参数、种子、初始化、训练轮数、增强、模型选择与停止规则'],
 ['commands','执行流程','数据准备 → 训练 → 评估 → 汇总；输入输出与中间产物'],
 ['resources','计算与预算','CPU/GPU、显存、内存、磁盘、耗时与费用；区分小规模与完整实验'],
 ['acceptance','结果验收','参考结果、指标实现、基线与消融、容差或重复实验统计']
];
export const levels = {run:'运行成功',evaluation:'评估复现',training:'训练复现',conclusion:'主要结论复现'};
export const states = {unreviewed:'未核查',documented:'已记录依据',blocked:'存在阻塞',na:'不适用'};
export const blockers = {materials:'材料缺失',environment:'环境问题',budget:'预算不足',execution:'执行错误',statistics:'统计证据不足',mismatch:'结果不一致',author:'需询问作者'};
export function ensureAssessment(p){
 if(!p.assessment)p.assessment={version:1,paper_version:'',target:'evaluation',criteria:{},experiments:[],independent:{reviewer:'',environment:'',from_readme:false,notes:''},obstacles:[]};
 const a=p.assessment;for(const [id] of dimensions)if(!a.criteria[id])a.criteria[id]={status:'unreviewed',evidence:''};return a;
}
export function assessmentSummary(p){const a=ensureAssessment(p),entries=dimensions.map(([id])=>a.criteria[id]);const core=a.experiments.filter(e=>e.core);return {documented:entries.filter(e=>e.status==='documented'&&e.evidence.trim()).length,blocked:entries.filter(e=>e.status==='blocked').length,remaining:entries.filter(e=>e.status==='unreviewed').length,core:core.length,covered:core.filter(e=>(e.claim_ids||[]).some(id=>p.claims.some(c=>c.id===id&&c.selected))).length,experiments:a.experiments.length};}
export function validateAssessment(a){for(const [id]of dimensions){const c=a.criteria[id];if(!states[c?.status])throw Error('检查状态无效');if(['documented','blocked','na'].includes(c.status)&&!c.evidence.trim())throw Error('记录依据、阻塞或不适用原因后再保存');}for(const e of a.experiments){if(!e.title.trim())throw Error('实验名称不能为空');if(!levels[e.level])throw Error('复现层级无效');}return a;}
export function invalidateAssessment(p){const a=p.assessment;if(!a)return;for(const c of Object.values(a.criteria)){c.status='unreviewed';}a.independent.from_readme=false;if(a.resource_check)a.resource_check.target_confirmed=false;}
export function fixtureEvaluation(samples){
 const injected={clean:null,metric_average:'C1',split_leakage:'C2',baseline_budget:'C3'};
 const rows=samples.flatMap(s=>{if(!(s.sample_id in injected))throw Error('未知教学真值');return s.manifest.claims.map(c=>{const f=s.report.findings.find(f=>f.claim_id===c.id);return {variant:s.sample_id,claim_id:c.id,text:c.text,label:c.id===injected[s.sample_id]?1:0,verdict:f?.verdict||'inconclusive',reason:f?.reason||'缺少结果',run_id:s.report.run_id};});});
 let tp=0,fp=0,tn=0,fn=0,abstain=0;for(const r of rows){if(r.verdict==='inconclusive')abstain++;if(r.label){if(r.verdict==='issue')tp++;else fn++;}else if(r.verdict==='issue')fp++;else if(r.verdict==='supported')tn++;}
 const div=(a,b)=>b?a/b:null;const f1=(t,f,n)=>div(2*t,2*t+f+n)??0;
 // Unknown negative predictions contribute to the normal-class false negatives.
 return {rows,tp,fp,tn,fn,abstain,macro_f1:(f1(tp,fp,fn)+f1(tn,rows.filter(r=>r.label&&r.verdict==='supported').length,fp+rows.filter(r=>!r.label&&r.verdict==='inconclusive').length))/2,recall:div(tp,tp+fn),fpr:div(fp,rows.filter(r=>!r.label).length),abstention:div(abstain,rows.length),repositories:1,variants:samples.length};
}
export function projectExport(project,executionAssessment){const clean=JSON.parse(JSON.stringify(project,(key,value)=>key==='blob'?undefined:value));clean.paper_review=clean.assessment||null;clean.assessment=executionAssessment;clean.format='articheck-review-project-v1';clean.exported_at=new Date().toISOString();return clean;}
