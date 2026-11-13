import {criteriaDecisions,reportVerdict,reportOutcome,reportNodes,withUnit,duration} from './report-verdict.mjs';
import {metricCatalog} from './metric-catalog.mjs';
import {activityView,timelineStates,activityEvents,ROLE_NAMES,visibleRoles} from './review-activity.mjs';
import {inspectZip} from './intake-core.mjs';
import {encoded,taskNames,typeNames,criterionNames,statusNames,executionNames,inputKey,validateInput,checkAssessment,coverageCounts,sessionCapability,metricUnit,hasCode} from './online-core.mjs';

const uid=()=>crypto.randomUUID();
const shortLabel=(value,limit)=>{const chars=Array.from(String(value||''));return chars.length>limit?chars.slice(0,limit-1).join('')+'…':chars.join('');};
function concise(text,limit=180){
 const value=String(text||'').replace(/\s+/g,' ').trim();
 if(Array.from(value).length<=limit)return value;
 const first=value.match(/^.{12,}?[。！？；]|^.{12,}?[.!?;](?=\s|$)/u)?.[0];
 return first&&Array.from(first).length<=limit?first:shortLabel(value,limit);
}


const UI_SVG={
 pdf:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l5 5v13H6zM14 3v5h5M9 13h6M9 17h4"/></svg>',
 zip:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12"/></svg>',
 github:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/></svg>',
 metrics:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16M7 16V9M12 16V5M17 16v-4"/></svg>',
 findings:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 16H3zM12 9v4M12 16h.01"/></svg>',
 observed:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
 coverage:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 7v6c0 5 3.5 8.2 8 9 4.5-.8 8-4 8-9V7z"/></svg>',
 stop:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>',
 spark:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.4 5.6L20 11l-5.6 2.4L12 19l-2.4-5.6L4 11l5.6-2.4z"/></svg>',
 terminal:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4zM7 9l3 3-3 3M12 15h5"/></svg>',
 monitor:'<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>'
};

export function failureText(r){
 if(r?.error_message)return r.error_message;
 const map={
  invalid_citation:'模型返回结果未通过出处校验，请稍后重试。',
  invalid_model_output:'模型返回结果未通过结构校验，请稍后重试。',
  provider_failed:'上游模型服务响应异常，请稍后重试。',
  review_response_unavailable:'服务未在时限内返回有效审查结果，请点击重新审查。',
  budget_exhausted:'当前模型调用额度已达上限，请联系管理员。',
  user_cancelled:'你已手动中止本次审查。'
 };
 return map[r?.error]||'审查过程中断，未生成最终报告。可点击重新审查再试一次。';
}

export function extractPaperMeta(r,p){
 const v=r?.review||{};
 const hasPaper=Boolean(r?.materials?.paper||p?.paper||(v.paper_type&&v.paper_type!=='code_only'));
 if(!hasPaper)return null;
 const page0=p?.paper?.pages?.[0]?.text||'';
 const page1=p?.paper?.pages?.[1]?.text||'';
 const rawText=(page0+'\n'+page1).trim();
 const lines=page0.split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&!/^(arXiv:|page\s*\d+|\d+$)/i.test(s));
 let title=(v.paper_title||'').trim();
 if(!title){
  title=lines[0]?lines[0].slice(0,220):(p?.paper?.name?p.paper.name.replace(/\.pdf$/i,''):(p?.title||'受审学术论文'));
 }
 let abstract=(v.paper_abstract||'').trim();
 if(!abstract){
  const m=rawText.match(/(?:Abstract|摘\s*要)[:\s—\-]*([\s\S]{30,1600}?)(?:\n\s*(?:1\.?\s+Introduction|I\.\s+INTRODUCTION|Keywords|Index Terms|引\s*言|关键词)|\n\n\s*1\s|$)/i);
  if(m)abstract=m[1].replace(/\s+/g,' ').trim().slice(0,1400);
  else if(lines.length>1)abstract=lines.slice(1,10).join(' ').replace(/\s+/g,' ').trim().slice(0,1000);
  else abstract=v.summary||'论文已导入并完成结构化图表与正文审查。';
 }
 let contributions=Array.isArray(v.paper_contributions)?v.paper_contributions.map(x=>String(x||'').trim()).filter(Boolean):[];
 if(!contributions.length){
  const bulletMatches=[...rawText.matchAll(/(?:•|\*|-|\(\d+\)|\b(?:first|second|third|1\)|2\)|3\)))\s*([^\n]{20,240})/gi)].map(m=>m[1].trim());
  if(bulletMatches.length>=2)contributions=bulletMatches.slice(0,4);
  // No fallback to the overall judgement: a summary is not a contribution of the paper.
 }
 return {title,abstract,contributions:contributions.slice(0,5)};
}

export function extractCoreCodeSnippets(r,p){
 const rv=r?.review||{};
 if(Array.isArray(rv.core_code_snippets)&&rv.core_code_snippets.length)return rv.core_code_snippets.slice(0,4);
 const snippets=[];
 const stages=rv.plan?.stages||[];
 for(const st of stages.slice(0,3)){
  if(!st.command&&!st.file)continue;
  const shortFile=(st.file||'script.py').split('/').pop();
  snippets.push({
   title:`${shortFile} · ${st.title||'核心执行入口'}`,
   file:st.file||'仓库根目录',
   start_line:1,
   end_line:Math.max(1,(st.command||'').split('\n').length),
   code:st.command||`python ${st.file}`,
   explanation:`对应阶段 ${st.id}（${st.title}），定义该实验阶段的数据加载、模型推理或训练评估调用逻辑。`
  });
 }
 if(!snippets.length&&p?.repository?.files?.length){
  const files=p.repository.files.filter(f=>/\.(py|sh|cpp|cu|c|rs|js|ts)$/i.test(f.path||f.name||'')).slice(0,3);
  for(const f of files){
   const fpath=f.path||f.name||'main.py';
   const shortFile=fpath.split('/').pop();
   const crit=(rv.criteria||[]).find(c=>c.file===fpath);
   snippets.push({
    title:`${shortFile} · 核心源码模块`,
    file:fpath,
    start_line:1,
    end_line:20,
    code:f.excerpt||`# 文件路径: ${fpath}\n# 已纳入审查源码上下文（${f.bytes||f.size||0} bytes）`,
    explanation:crit?.note||'承载项目的模型结构定义、实验配置或评估主流程。'
   });
  }
 }
 return snippets.slice(0,4);
}

export function extractStageLiveLines(stageRow){
 if(Array.isArray(stageRow?.live_tail)&&stageRow.live_tail.length){
  return stageRow.live_tail.map(s=>String(s||'').trim()).filter(Boolean).slice(-3);
 }
 const raw=String(stageRow?.output||'');
 if(!raw.trim())return [];
 const lines=raw.split(/\r?\n/).map(ln=>{
  if(ln.includes('\r')){
   const segs=ln.split('\r').map(s=>s.trim()).filter(Boolean);
   return segs.at(-1)||'';
  }
  return ln.trim();
 }).filter(Boolean);
 return lines.slice(-3);
}

export function normalizeGitHubUrl(raw){
 const s=String(raw||'').trim();
 if(!s)return null;
 const direct=s.match(/^(?:https?:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?(?:\/.*|\?.*|#.*)?$/i);
 if(direct){
  const [,owner,repo]=direct;
  if(owner!=='.'&&owner!=='..'&&repo!=='.'&&repo!=='..')return `https://github.com/${owner}/${repo}`;
 }
 const shorthand=s.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?$/);
 if(shorthand&&!s.includes('://')){
  const [,owner,repo]=shorthand;
  if(owner!=='.'&&owner!=='..'&&repo!=='.'&&repo!=='..')return `https://github.com/${owner}/${repo}`;
 }
 return null;
}

export class OnlineWorkspace{
 constructor(intake){this.i=intake;this.selected=null;this.tab='materials';this.token='';this.consent=true;this.errors={};this.error='';this.execNotice='';this.busy='';this.capabilities=null;this.timer=null;this.repoTimer=null;this.repoGeneration=0;this.repoPending=null;this.repoState='';this.pending=false;this.liveReport=null;this.progressTimer=null;this.activeController=null;this.userAborted=false;this.cancelling=false;this.metricAudience='all';this.nodeOpen=new Map();this.metricQuery='';this.activityOpen=false;this.activeRoleNode=null;this.phase='materials';this.owner=null;try{this.owner=sessionCapability();}catch{this.error='浏览器存储不可用，暂时无法保存审查身份。请允许此网站使用本地存储。';}}
 esc(value){return this.i.esc(value??'');}
 projects(){return this.i.projects.filter(p=>(p.online_account||null)===(this.i.h.account?.()?.id||null));}
 current(){return this.projects().find(p=>p.id===this.selected)||null;}
 hasExecutionSection(r,p=this.current()){
  return Boolean(r?.materials?.code||hasCode(p)||r?.execution||r?.review?.plan?.stages?.length);
 }
 isInterruptedReport(r){
  if(r?.terminated_at)return false;
  if(!r)return false;
  if(['failed','cancelled'].includes(r.status))return true;
  if(['failed','cancelled','expired'].includes(r.execution?.status))return true;
  if((r.execution?.stages||[]).some(s=>s.status==='failed'))return true;
  if(!r.execution&&(r.review?.resource_preflight?.needs_user||(!r.review?.purpose&&r.review?.task==='reproduction'&&!r.materials?.code)))return true;
  return false;
 }
 async new(){this.i.h.modal('新建审查',`<form id="new-review-form"><div class="online-field"><label for="review-project-name">项目名称</label><input id="review-project-name" name="title" maxlength="160" placeholder="例如：ResNet 图表与代码核查" required></div><button class="btn primary" type="submit">创建审查项目</button></form>`);document.querySelector('#review-project-name')?.focus();}
 async createProject(title){const p={id:uid(),online_account:this.i.h.account?.()?.id||null,title:title.trim(),created_at:new Date().toISOString(),paper:null,repository:null,claims:[],resources:{},online_task:'auto',online_scope:'',online_max_seconds:'',online_auto_execute:true};if(!p.title)return;this.i.projects.unshift(p);this.selected=p.id;this.i.activeId=p.id;this.tab='materials';this.phase='materials';this.activeRoleNode=null;this.error='';this.execNotice='';this.errors={};await this.i.save(p);this.i.h.closeModal();this.i.h.navigate('api-review');}
 viewReport(p){
  return this.operationProject===p?.id&&this.liveReport?this.liveReport:p?.online_report;
 }
 isViewing(p){
  return p?.id===this.selected&&(!this.i.h.page||this.i.h.page()==='api-review');
 }
 sidebar(){const p=this.current();if(!p)return '';const r=this.viewReport(p),busy=!this.operationProject||this.operationProject===p.id?this.busy:'',isCancelling=Boolean((!this.operationProject||this.operationProject===p.id)&&this.cancelling||r?.execution?.status==='cancelling'),active=Boolean(!isCancelling&&(busy||p.online_pending_request||p.online_execution_pending||['reviewing'].includes(r?.status)||['queued','starting','running'].includes(r?.execution?.status))),e=v=>this.esc(v);return `<section class="sidebar-review ${active?'active':''} ${isCancelling?'is-cancelling':''}" role="button" tabindex="0" data-sidebar-jump="${e(p.id)}" title="点击跳转到该项目审查页面"><strong>${e(p.title)}</strong><div class="sidebar-review-state" role="status">${isCancelling?'<span class="cancelling-anim" aria-hidden="true"><i></i><i></i><i></i></span>':active?'<span class="online-spinner" aria-hidden="true"></span>':''}<span class="review-live-stage">${e(isCancelling?'正在安全中断…':active?busy||'正在执行审查':r?.terminated_at?'已终止':this.isInterruptedReport(r)?'已中断 · 待处理':r?.review?'报告已就绪':'准备材料')}</span></div><dl>${p.paper?`<div><dt>论文</dt><dd title="${e(p.paper.name)}">${e(p.paper.name)}</dd></div>`:''}${p.repository?`<div><dt>代码</dt><dd title="${e(p.repository.name)}">${e(p.repository.name)}</dd></div>`:''}</dl>${r?.review&&!active&&!isCancelling?'<button type="button" data-online-tab="report">查看最终报告</button>':''}</section>`;}
 timelineView(report,{activeRole=this.activeRoleNode,cancelling=false}={}){
  const key=report?.id;
  const live=report?.status==='reviewing'||['queued','starting','running','cancelling'].includes(report?.execution?.status);
  if(key&&this.sequence?.key!==key){
   clearTimeout(this.sequenceTimer);
   this.sequence=live?{key,cursor:0,intro:false}:null;
  }
  const sequence=this.sequence?.key===key?this.sequence:null;
  if(sequence&&report){
   sequence.report=report;
   sequence.cancelling=cancelling;
   const state=timelineStates(report,undefined,undefined,cancelling)[sequence.cursor];
   if(!cancelling&&!this.sequenceTimer&&['completed','failed','skipped'].includes(state)){
    if(state==='completed'&&!sequence.settled)sequence.intro=true;
    const step=()=>{
     this.sequenceTimer=null;
     if(this.sequence!==sequence)return;
     if(sequence.intro){sequence.intro=false;sequence.settled=true;}
     else{sequence.settled=false;sequence.cursor++;}
     const region=document.querySelector('#online-activity');
     if(region)region.innerHTML=this.timelineView(sequence.report,{cancelling:sequence.cancelling});
    };
    this.sequenceTimer=setTimeout(step,sequence.intro?240:200);
   }
  }
  return activityView(report,v=>this.esc(v),{open:false,showLog:false,activeRole,cancelling,sequence});
 }
 async notifyFinished(p){const r=p.online_report;if(r?.terminated_at||!r?.review||['queued','starting','running','cancelling'].includes(r.execution?.status)||r.status==='reviewing')return;const key=r.id+':'+(r.execution?.attempt_id||'review')+':'+(r.execution?.status||r.status||'done');if(p.online_notified===key)return;
  if(this.isViewing(p)&&this.tab==='process'&&this.sequence?.key===r.id){
   const states=timelineStates(r);
   if(this.sequence.cursor<states.length&&states.slice(this.sequence.cursor).every(state=>['completed','failed','skipped'].includes(state))){
    clearTimeout(this.finishedTimer);this.finishedTimer=setTimeout(()=>this.notifyFinished(p),500);return;
   }
  }
  p.online_notified=key;await this.save(p);if(!this.isViewing(p))return;if(this.isInterruptedReport(r)){this.tab='process';if(['failed','cancelled','expired'].includes(r.execution?.status))this.activeRoleNode='experiment_runner';this.i.h.toast?.('运行遇到问题已中断，请查看诊断并补完材料继续审查。');if(typeof document!=='undefined')setTimeout(()=>{if(typeof document!=='undefined')this.pulseSection(document.querySelector('#online-interruption-panel')||document.querySelector('#online-role-node-panel'));},60);}else{this.tab='report';this.activeRoleNode=null;this.i.h.toast?.('审查已完成，已自动跳转至最终报告。');if(typeof document!=='undefined')setTimeout(()=>{if(typeof document!=='undefined')this.pulseSection(document.querySelector('#report-top-section'));},60);}}

 ensure(){if(!this.current()){this.selected=this.projects()[0]?.id;if(!this.selected)return null;}return this.current();}
 warn(key){return this.errors[key]?`<span class="online-field-error" role="alert">! ${this.esc(this.errors[key])}</span>`:'';}
 attrs(key){return this.errors[key]?'aria-invalid="true"':'';}
 render(){const p=this.ensure(),e=v=>this.esc(v);if(!p)return `<section class="online-empty"><h2>开始一项新的研究审查</h2><p>先为项目命名，再上传论文或代码。</p><button class="btn primary" data-online="new">新建审查</button></section>`;
 const ownOperation=!this.operationProject||this.operationProject===p.id;
 const busy=ownOperation?this.busy:'';
 const r=this.viewReport(p),stale=this.reportStale(r,p),isCancelling=Boolean(ownOperation&&this.cancelling||r?.execution?.status==='cancelling'),running=Boolean(isCancelling||busy&&this.phase==='running'||p.online_pending_request||p.online_execution_pending||r?.status==='reviewing'||['queued','starting','running','cancelling'].includes(r?.execution?.status));
 const showExec=r?.review&&this.hasExecutionSection(r,p);
 const reportReady=Boolean(r?.review&&(!running||r.terminated_at));
 const ended=Boolean(r&&!r.review&&['failed','cancelled'].includes(r.status)&&!running);
 const terminated=Boolean(r?.terminated_at),interrupted=this.isInterruptedReport(r)&&!running&&!terminated;
 const tab=this.tab==='materials'&&!running&&!terminated?'materials':this.tab==='report'&&reportReady?'report':(r||running?'process':'materials');
 const activeRole=this.activeRoleNode;
 return `<div class="online-workspace"><div class="online-toolbar"><label for="online-project">当前项目</label><select id="online-project" data-online-project ${this.busy?'disabled':''}>${this.projects().map(x=>`<option value="${e(x.id)}" ${x.id===p.id?'selected':''}>${e(x.title)}</option>`).join('')}</select><button class="btn online-new-review" data-online="new" ${this.busy?'disabled':''}>${this.i.h.icon('plus')}新建审查</button>${extractPaperMeta(r,p)?`<button type="button" class="btn kg-entry-btn" data-open-kg="${e(p.id)}">${UI_SVG.spark}<span>加入知识图谱</span></button>`:''}</div>
 <nav class="online-tabs" aria-label="审查工作区">${[...(!terminated?[['materials',r?.review?'材料管理':'准备材料']]:[]),...(reportReady?[['report','最终报告']]:[]),['process',isCancelling?'正在中断…':running?'在线审查':'过程详情']].map(([id,label])=>`<button data-online-tab="${id}" class="${tab===id?'selected':''}" aria-current="${tab===id?'page':'false'}">${label}</button>`).join('')}</nav>
 ${ownOperation&&this.error?`<div class="online-error" role="alert"><strong>本次操作未完成</strong><p>${e(this.error)}</p></div>`:''}${stale?'<p class="online-notice">当前材料与该报告的版本不同，请重新审查。旧版依据仍予保留。</p>':''}
 ${(busy||running)?`<div class="online-progress ${isCancelling?'is-cancelling':''}" role="status">${isCancelling?'<span class="cancelling-anim" aria-hidden="true"><i></i><i></i><i></i></span>':'<span class="online-spinner" aria-hidden="true"></span>'}<strong>${e(isCancelling?'正在安全中断审查并保存已完成记录…':busy||(p.online_execution_pending?'正在创建执行环境…':'正在提交审查…'))}</strong><button type="button" class="btn danger small online-abort-btn" data-online="cancel" ${isCancelling&&!p.online_cancel_error?'disabled':''}>${UI_SVG.stop}${p.online_cancel_error?'重试中断':isCancelling?'正在中断…':'中断运行'}</button></div>`:''}
 ${tab==='materials'?this.materials(p):tab==='report'&&reportReady?this.finalReport(r,p):`<div id="online-activity">${this.timelineView(r,{activeRole,cancelling:isCancelling})}</div>${terminated?'<div class="online-notice" role="status"><strong>已终止</strong><p>已取得的证据保留在本次记录。</p><button class="btn small" data-online="new">新建审查</button></div>':ended?this.endedCard(r,p):interrupted?this.interruptionPanel(r,p):''}${activeRole&&r?this.renderRoleNodePanel(activeRole,r,p,stale):terminated?'':running&&showExec&&['queued','starting','running','cancelling'].includes(r?.execution?.status)?this.execution(r,stale):!r?.review&&!ended?`<section class="review-waiting"><h2 class="live-heading"><span class="live-heading-text">${isCancelling?'正在安全中断审查':'正在协作审查'}</span><span class="live-dots" aria-hidden="true"><i></i><i></i><i></i></span></h2><p>${isCancelling?'正在通知执行节点停止并保存已有记录…':'材料已提交。实际审阅、规划与执行状态在此持续更新，可随时中断运行。'}</p></section>`:''}`}</div>`;}

 endedCard(r,p=this.current()){const e=v=>this.esc(v),cancelled=r.status==='cancelled';
  const reason=cancelled?'本次审查已中断，已取得的活动记录保留；补充或修正材料后可继续审查。':failureText(r);
  const events=activityEvents(r),failedEv=events.find(x=>x.status==='failed')||events.at(-1);
  const stepName=failedEv?.roles?.[0]?(ROLE_NAMES[failedEv.roles[0]]||failedEv.roles[0]):'材料审阅与解析';
  return `<section id="online-interruption-panel" class="review-ended interruption-diagnosis-panel ${cancelled?'cancelled':'failed'}" role="status"><div class="review-ended-icon" aria-hidden="true">${cancelled?UI_SVG.stop:UI_SVG.findings}</div><div class="interruption-body"><div class="interruption-head"><span class="interruption-step-badge">中断节点 · ${e(stepName)}</span><h2>${cancelled?'审查已中断':'审查在此步骤中断'}</h2></div><p class="interruption-reason">${e(reason)}</p><div class="interruption-remedy-box"><h3>纠正或补完材料后继续审查</h3><div class="online-upload-pair compact-upload-pair"><label class="online-upload ${p?.paper?'has-file':''}" for="interrupted-pdf"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.pdf}</span><span>替换/补充论文 PDF</span></div><strong>${e(p?.paper?.name||'上传论文 PDF')}</strong><input id="interrupted-pdf" type="file" accept=".pdf,application/pdf" data-online-upload="paper"></label><label class="online-upload ${hasCode(p)?'has-file':''}" for="interrupted-zip"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.zip}</span><span>替换/补充代码 ZIP</span></div><strong>${e(p?.repository?.name||'上传代码 ZIP')}</strong><input id="interrupted-zip" type="file" accept=".zip,application/zip" data-online-upload="code"></label></div><div class="online-field"><label for="interrupted-supply">补充说明、修正参数或缺失数据线索</label><textarea id="interrupted-supply" data-online-field="online_supply_notes" maxlength="3000" placeholder="说明修正后的运行入口、依赖版本、公开数据集/权重地址或审查范围补充说明…">${e(p?.online_supply_notes||'')}</textarea></div><div class="review-ended-actions"><button class="btn primary" data-online="resume-review">补充并继续审查</button><button type="button" class="btn danger" data-online="terminate-review">终止本次审查</button><button class="btn" data-online-tab="materials">前往材料管理页</button></div></div></div></section>`;}

 interruptionPanel(r,p=this.current()){
  const e=v=>this.esc(v),x=r?.execution,rv=r?.review||{};
  const failedStage=(x?.stages||[]).find(s=>s.status==='failed');
  const cancelled=x?.status==='cancelled'||r?.status==='cancelled';
  const timedOut=x?.status==='expired'||failedStage?.timed_out;
  let stepLabel='04 实验执行';
  let problemTitle='实验复现阶段执行报错中断';
  let problemDetail='';
  let suggestion='请检查报错日志，补充缺失的数据集、预训练权重、依赖说明，或上传修正后的代码包后继续审查。';
  if(cancelled){
   problemTitle='本次复现已中断';
   problemDetail=x?.notice||'运行已按指令安全中断，已完成阶段的日志与证据已保留。';
   suggestion='如需调整代码、补充权重或修改补充说明，可在下方直接更新材料并继续审查，或终止本次审查。';
  }else if(failedStage){
   stepLabel=`04 实验执行 · 阶段 ${failedStage.id}（${failedStage.title}）`;
   problemTitle=timedOut?`阶段 ${failedStage.id}（${failedStage.title}）运行超时中断`:`阶段 ${failedStage.id}（${failedStage.title}）报错中断（退出码 ${failedStage.exit_code??1}）`;
   const tailLines=extractStageLiveLines(failedStage);
   problemDetail=tailLines.length?tailLines.join('\n'):(failedStage.output||'命令返回非零退出码，后续阶段已自动中断（fail-fast）。').slice(-600);
   if(timedOut)suggestion=failedStage.reason||x?.notice||'本次执行已达到时限，已保留日志。';
   else if(x?.question)suggestion=x.question;
   if(failedStage.retry_count)suggestion=`已自动重试 ${failedStage.retry_count} 次。 `+suggestion;
  }else if(!x&&rv.resource_preflight?.needs_user){
   stepLabel='03 计划编排 · 运行条件预检';
   problemTitle='运行环境预检受阻';
   problemDetail=rv.resource_preflight.reason||rv.plan?.blocked_reason||'当前任务存在未满足的数据或环境依赖。';
  }else if(!x&&rv.task==='reproduction'&&!r.materials?.code){
   stepLabel='02 代码检查 · 源码缺失';
   problemTitle='缺少可执行代码仓库';
   problemDetail=r.source_discovery?.reason||'复现评估需要作者源码，当前仅提供了论文 PDF 且未能自动定位公开仓库。';
   suggestion='请在下方粘贴 GitHub 仓库地址或上传代码 ZIP 后继续审查。';
  }else{
   problemDetail=x?.question||rv.plan?.blocked_reason||'执行过程中遇到阻碍，请核对材料后重试。';
  }
  return `<section id="online-interruption-panel" class="interruption-diagnosis-panel" role="region" aria-label="中断问题诊断与材料补完"><div class="interruption-header"><span class="interruption-step-badge">${e(stepLabel)}</span><h2>${e(problemTitle)}</h2><p>${e(suggestion)}</p></div>${failedStage?`<div class="interruption-cmd-box"><div class="interruption-cmd-meta"><span>中断命令</span><span>退出码 ${e(failedStage.exit_code??'N/A')}</span></div><pre class="interruption-cmd">$ ${e(failedStage.command)}</pre>${problemDetail?`<pre class="interruption-log-tail">${e(problemDetail)}</pre>`:''}</div>`:`<p class="interruption-reason-box">${e(problemDetail)}</p>`}<div class="interruption-remedy-box"><h3>纠正或补完材料以继续审查</h3><div class="online-upload-pair compact-upload-pair"><label class="online-upload ${p?.paper?'has-file':''}" for="remedy-pdf"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.pdf}</span><span>论文 PDF</span></div><strong>${e(p?.paper?.name||'上传或替换论文')}</strong><input id="remedy-pdf" type="file" accept=".pdf,application/pdf" data-online-upload="paper"></label><label class="online-upload ${hasCode(p)?'has-file':''}" for="remedy-zip"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.zip}</span><span>代码 ZIP</span></div><strong>${e(p?.repository?.name||'上传或替换代码 ZIP')}</strong><input id="remedy-zip" type="file" accept=".zip,application/zip" data-online-upload="code"></label></div><div class="online-field"><label for="remedy-repo"><span class="field-icon-inline">${UI_SVG.github}</span>补充或更换 GitHub 仓库地址</label><div class="online-input-action"><input id="remedy-repo" type="url" data-online-field="repo_url" value="${e(p?.repo_url||'')}" placeholder="https://github.com/作者/仓库 或 作者/仓库"><button class="btn" type="button" data-online="github">读取仓库</button></div></div><div class="online-field"><label for="remedy-supply">补充缺失数据/权重线索或修正运行说明</label><textarea id="remedy-supply" data-online-field="online_supply_notes" maxlength="3000" placeholder="填写公开数据/预训练权重下载链接、正确的运行参数或环境补充说明…">${e(p?.online_supply_notes||'')}</textarea></div><div class="interruption-actions"><button type="button" class="btn primary" data-online="resume-review">纠正/补完材料并继续审查</button><button type="button" class="btn danger" data-online="terminate-review">终止本次审查</button>${r?.review?`<button type="button" class="btn text" data-online-tab="report">查看当前报告</button>`:''}</div></div></section>`;
 }

 renderRoleNodePanel(roleId,r,p=this.current(),stale=false){
  const e=v=>this.esc(v),rv=r?.review||{},x=r?.execution;
  const label=ROLE_NAMES[roleId]||roleId;
  const closeBtn=`<button type="button" class="btn small text role-panel-close" data-role-jump="${e(roleId)}" aria-label="收起节点报告" title="收起节点报告"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4l12 12M16 4L4 16"/></svg></button>`;
  if(!rv.criteria){
   const events=activityEvents(r).filter(ev=>(ev.roles||[]).includes(roleId));
   return `<section id="online-role-node-panel" class="role-node-summary-panel"><header class="role-node-panel-head"><div><span class="online-kicker">节点实时状态</span><h3>${e(label)}</h3></div>${closeBtn}</header><p>${e(events.at(-1)?.title||'正在等待该节点返回结构化审阅结果…')}</p></section>`;
  }
  if(roleId==='literature_reader'){
   const meta=extractPaperMeta(r,p);
   const authorMetrics=(rv.metrics||[]).filter(m=>m.author_method);
   return `<section id="online-role-node-panel" class="role-node-summary-panel"><header class="role-node-panel-head"><div><span class="online-kicker">01 · 文献审阅节点报告</span><h3>${e(meta?.title||rv.paper_title||p?.title||'论文文献审阅总结')}</h3></div>${closeBtn}</header>${meta?`<section class="role-paper-abstract"><h4>摘要</h4><p>${e(meta.abstract)}</p></section><div class="role-node-grid role-paper-grid"><div class="role-node-block"><h4>作者自述贡献（${meta.contributions.length} 项，模型概括）</h4><ul class="role-node-list">${meta.contributions.map(c=>`<li>${e(c)}</li>`).join('')}</ul></div><div class="role-node-block"><h4>提取图表指标概览（共 ${rv.metrics?.length||0} 项，作者方法 ${authorMetrics.length} 项）</h4><ul class="role-node-list">${(rv.metrics||[]).slice(0,6).map(m=>`<li><strong>${e(m.reference)} · ${e(m.model)}</strong>（${e(m.dataset)} / ${e(m.metric)}）：<code>${e(m.value)} ${e(metricUnit(m))}</code>${m.page?` · <button type="button" class="btn text small" data-online-page="${e(m.page)}">PDF 第 ${e(m.page)} 页</button>`:''}</li>`).join('')||'<li>未从图表中提取到定量实验指标</li>'}</ul></div></div>`:`<p class="role-node-lead">${e(rv.summary)}</p>`}</section>`;
  }
  if(roleId==='code_inspector'){
   const snippets=extractCoreCodeSnippets(r,p);
   const codeCrit=(rv.criteria||[]).filter(c=>['code','environment','data','resources'].includes(c.dimension));
   const deps=x?.runtime?.inferred_dependencies||[];
   return `<section id="online-role-node-panel" class="role-node-summary-panel role-code-review"><header class="role-node-panel-head"><div><span class="online-kicker">02 · 代码检查节点报告</span><h3>源码结构、依赖与核心实现检查</h3></div>${closeBtn}</header><p class="role-node-lead">已审查上下文源码文件 ${e(rv.coverage?.code_files_in_context||0)} / ${e(rv.coverage?.total_code_files||0)} 个${deps.length?`，自动识别第三方依赖：${e(deps.join(', '))}`:''}。</p><div class="role-node-grid"><div class="role-node-block"><h4>代码与环境完备性判定</h4><dl class="role-code-criteria">${codeCrit.map(c=>`<div><dt>${e(criterionNames[c.dimension])}<span class="online-status ${e(c.status)}">${e(statusNames[c.status])}</span></dt><dd>${e(concise(c.note))}</dd></div>`).join('')||'<div><dd>暂无结构化条件记录。</dd></div>'}</dl></div><div class="role-node-block"><h4>核心代码片段定位</h4>${snippets.length?snippets.map(s=>`<details class="role-code-mini"><summary><strong>${e(s.title)}</strong><small title="${e(s.file)}">${e(s.file.split('/').at(-1))}</small></summary><p>${e(concise(s.explanation))}</p><pre><code>${e(s.code)}</code></pre></details>`).join(''):'<p>当前未提供代码或未提取到可执行脚本片段。</p>'}</div></div></section>`;
  }
  if(roleId==='planner'){
   const plan=rv.plan||{stages:[],needs:[],metric_patterns:[]};
   return `<section id="online-role-node-panel" class="role-node-summary-panel"><header class="role-node-panel-head"><div><span class="online-kicker">03 · 计划编排节点报告</span><h3>实验验证阶段与指标绑定计划</h3></div>${closeBtn}</header>${plan.stages?.length?`<div class="role-stage-plan-list">${plan.stages.map((s,idx)=>`<div class="role-plan-item"><div class="role-plan-item-head"><strong>[${idx+1}/${plan.stages.length}] ${e(s.id)} · ${e(s.title)}</strong><span>${e(s.file.split('/').at(-1))}</span></div><pre class="terminal-cmd">$ ${e(s.command)}</pre></div>`).join('')}</div>`:`<p class="online-notice">${e(plan.blocked_reason||'当前无可执行阶段计划。')}</p>`}</section>`;
  }
  if(roleId==='experiment_runner'){
   return `<section id="online-role-node-panel" class="role-node-summary-panel"><header class="role-node-panel-head"><div><span class="online-kicker">04 · 实验执行节点报告</span><h3>隔离环境实际命令与动态输出</h3></div>${closeBtn}</header>${this.execution(r,stale)}</section>`;
  }
  if(roleId==='cross_auditor'){
   const obs=x?.metrics||[];
   return `<section id="online-role-node-panel" class="role-node-summary-panel role-cross-review"><header class="role-node-panel-head"><div><span class="online-kicker">05 · 交叉核查节点报告</span><h3>证据出处、复核记录与数值比对（${rv.findings?.length||0} 项问题）</h3></div>${closeBtn}</header><p class="role-node-lead">${r.audit?.status==='completed'?`交叉复核保留 ${rv.findings.length} 条有效问题建议，撤回 ${r.audit.withdrawn||0} 条依据不足的建议，补充 ${r.audit.additional_metrics||0} 条图表指标。`:'已完成图表原文出处校验与阶段执行状态核对。'}</p>${obs.length?this.observations(r):''}<div class="online-findings role-audit-findings"><h4>${this.isSelfReview(r)?'保留的问题与修正建议':'保留的证据与差异'}</h4>${this.findingCards(this.isSelfReview(r)?rv.findings:rv.findings.map(f=>({...f,suggestion:''})))||'<p>本次未保留问题建议。</p>'}</div></section>`;
  }
  if(roleId==='reporter'){
   const o=reportOutcome(r,p,{stale:this.reportStale(r,p)}),state={pass:'passed',fail:'failed'}[o.tone]||'pending';
   return `<section id="online-role-node-panel" class="role-node-summary-panel"><header class="role-node-panel-head"><div><span class="online-kicker">06 · 报告整理节点报告</span><h3>最终审查结论与报告汇总</h3></div><div class="role-panel-actions"><button type="button" class="btn primary small" data-online-tab="report">进入完整最终报告</button>${closeBtn}</div></header><div class="role-verdict-summary ${e(state)}"><strong>${e(o.headline)}</strong><p>${e(o.note||o.sub||o.verdict?.reason||'')}</p></div><p class="role-node-lead">${e(rv.summary)}</p></section>`;
  }
  return '';
 }

 criteriaSection(r,p){
  const e=v=>this.esc(v),rows=criteriaDecisions(r,p);
  if(!rows.length)return '';
  return `<section id="report-criteria-section" class="online-criteria"><div class="online-section-heading"><h2>${r.materials?.paper&&!r.materials?.code?'论文审查条件':'八项审查条件'}</h2></div>${r.terminated_at?'<p>终止前的条件记录</p>':''}<div class="online-criteria-grid">${rows.map(row=>`<a class="online-criterion criterion-jump ${e(row.status)}" href="#criterion-${e(row.dimension)}" data-criterion-jump="${e(row.dimension)}"><strong>${e(criterionNames[row.dimension])}</strong><span class="online-status ${e(row.status)}">${row.manuallyReviewed?'通过 · 已复核':r.terminated_at&&row.status==='needs_review'?'终止前未复核':e(statusNames[row.status])}</span></a>`).join('')}</div></section>`;
 }
 criteriaDetails(r,p,details=criteriaDecisions(r,p)){
  const e=v=>this.esc(v),rows=criteriaDecisions(r,p);
  if(!rows.length)return '';
  return `<section class="criterion-details" aria-labelledby="criterion-details-title"><div class="online-section-heading"><h2 id="criterion-details-title">审查条件详细说明</h2></div><div class="criterion-details-list">${rows.map(row=>`<article id="criterion-${e(row.dimension)}" class="criterion-detail" tabindex="-1"><header><h3>${e(criterionNames[row.dimension])}</h3><span class="online-status ${e(row.status)}">${row.manuallyReviewed?'通过 · 已复核':r.terminated_at&&row.status==='needs_review'?'终止前未复核':e(statusNames[row.status])}</span></header><p>${e(details.find(item=>item.dimension===row.dimension)?.note||"详见上方对应问题。")}</p>${this.citation(row)}${!r.terminated_at&&row.status==='needs_review'?`<button class="btn small" type="button" data-confirm-criterion="${e(row.dimension)}">已复核</button>`:row.status==='missing'&&!r.terminated_at&&this.isSelfReview(r)?`<button class="btn small" type="button" data-supply-criterion="${e(row.dimension)}">去修改</button>`:''}</article>`).join('')}</div></section>`;
 }
 async confirmCriterion(dimension){
  const p=this.current(),r=p?.online_report;
  if(r?.terminated_at||!criteriaDecisions(r,p).some(row=>row.dimension===dimension&&row.status==='needs_review'))return;
  p.online_criteria_review={reportId:r.id,dimensions:[...new Set([...(p.online_criteria_review?.reportId===r.id?p.online_criteria_review.dimensions:[]),dimension])]};
  await this.save(p);
  this.renderNow();
  document.getElementById('criterion-'+dimension)?.focus({preventScroll:true});
 }
 supplyCriterion(dimension){
  const p=this.current(),r=p?.online_report;
  if(r?.terminated_at||!criteriaDecisions(r,p).some(row=>row.dimension===dimension&&row.status==='missing'))return;
  this.supplyReport=r.id;
  this.tab='materials';
  this.renderNow();
  const field=document.querySelector('#online-supply');
  field?.focus({preventScroll:true});
  field?.scrollIntoView({block:'center',behavior:'smooth'});
 }
 findingCards(findings){
  const e=v=>this.esc(v),severity={high:'优先处理',medium:'建议核对',low:'补充说明'};
  return (findings||[]).map((f,n)=>`<article class="report-finding" ${f.index==null?'':`id="report-issue-${f.index}"`}><header><span class="online-issue-index">${String(n+1).padStart(2,'0')}</span><h3>${e(concise(f.title,75))}</h3><span class="online-severity ${e(f.severity)}">${e(severity[f.severity])}</span></header><p class="finding-evidence">${e(concise(f.detail))}</p>${f.suggestion?`<div class="online-suggestion"><strong>修正建议</strong><p>${e(concise(f.suggestion,130))}</p></div>`:''}${this.citation(f)}${f.audit_note||f.detail!==concise(f.detail)||f.suggestion&&f.suggestion!==concise(f.suggestion,130)?`<details class="finding-source"><summary>完整依据</summary><p>${e(f.detail)}</p>${f.suggestion?`<p><strong>修正建议</strong> ${e(f.suggestion)}</p>`:''}${f.audit_note?`<p><strong>交叉复核</strong> ${e(f.audit_note)}</p>`:''}</details>`:''}</article>`).join('');
 }

 // Final report: basic information → result (by purpose) → process timeline → collapsed appendix.
 reportStale(r,p){return Boolean(r?.review&&p?.online_report?.id===r.id&&p.online_input_key&&p.online_input_key!==inputKey(p));}
 finalReport(r,p=this.current()){
  const e=v=>this.esc(v),self=this.isSelfReview(r),v=r.review||{};
  const conflicts=this.conflictState?.id===r.id?this.conflictState:null;
  const {outcome:o,nodes,notApplicable}=reportNodes(r,p,{stale:this.reportStale(r,p),conflicts:conflicts?.items??null,conflictError:Boolean(conflicts?.error)});
  const paperMeta=o.paper?extractPaperMeta(r,p):null;
  return `<section id="report-top-section" class="rpt" data-report-purpose="${e(o.purpose)}" data-report-materials="${e(o.materials)}">
   ${this.reportInfo(r,p,o,paperMeta)}
   ${self?this.selfResult(r,o,nodes):this.otherResult(r,o,nodes)}
   ${this.reportFlow(r,p,o,nodes,notApplicable)}
   ${this.reportAppendix(r,p,o,paperMeta)}
  </section>`;
 }
 reportInfo(r,p,o,paperMeta){
  const e=v=>this.esc(v),v=r.review||{},x=r.execution,cov=v.coverage||{},self=o.purpose==='self_review';
  const times=(r.activity||[]).map(a=>a.time).filter(t=>typeof t==='number');
  const reviewSeconds=times.length>1?Math.max(...times)-Math.min(...times):null;
  const finished=Math.max(...times,typeof x?.finished_at==='number'?x.finished_at:0);
  const repo=p?.repository,repoName=repo?.repo_name||repo?.remote?.repository||repo?.name?.replace(/\.zip$/i,'')||'名称未记录',commit=repo?.commit||repo?.remote?.commit;
  const meta=[
   ['论文',o.paper?(paperMeta?.title||p?.paper?.name||'已提交'):'未提交','paper',o.paper?` · ${cov.total_paper_pages??p?.paper?.pages?.length??'—'} 页`:''],
   ['代码',o.code?(p?.shared?repo?.name||repoName:repoName+(commit?' @'+String(commit).slice(0,7):'')):'未提交','code',o.code?` · ${cov.total_code_files??repo?.files?.length??'—'} 个文件`:''],
   ['完成时间',finished>0?new Date(finished*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'],
   ['用时',[reviewSeconds!=null?'审阅 '+duration(reviewSeconds):'',x?.elapsed_seconds!=null?'执行 '+duration(x.elapsed_seconds):''].filter(Boolean).join(' · ')||'未记录']];
  const observed=(x?.metrics||[]).filter(m=>typeof m.observed==='number').length;
  const scope=[
   o.paper?`论文 ${cov.paper_pages_in_context??'—'}/${cov.total_paper_pages??'—'} 页`:'',
   o.code?`代码 ${cov.code_files_in_context??'—'}/${cov.total_code_files??'—'} 个文件进入审阅`:'',
   o.paper?`图表指标 ${(v.metrics||[]).length} 项${o.code?`，其中 ${observed} 项实测`:''}`:'',
   o.code?(o.run?.done?`运行 ${o.run.done}/${o.run.total} 个阶段`:'未运行代码'):'',
   self&&o.paper?'相关工作只比较你知识图谱中的论文':'',
   (cov.gaps||[]).length?`覆盖缺口 ${(cov.gaps||[]).length} 项`:''].filter(Boolean);
  return `<header class="rpt-info">
   <div class="rpt-title-row"><h2 class="rpt-project">${e(p?.title||r.project_title||'未命名审查项目')}</h2><span class="rpt-chip ${self?'neutral':'info'}">${self?'审查自己':'审查别人'}</span>
    ${p?.shared?'':'<div class="rpt-actions"><button class="btn primary" data-online="export">'+(self?'导出修改清单':'导出报告')+'</button><button class="btn" data-online-tab="process">查看过程详情</button></div>'}</div>
   <dl class="rpt-meta">${meta.map(([label,value,kind,suffix=''])=>{
    const file=p?.shared?.files?.[kind];
    const name=file?`<a class="shared-case-download" href="#public-cases" data-archive-action="case-download" data-case-id="${e(p.shared.id)}" data-case-kind="${kind}" title="${e(file)}">${e(value)}</a>`:e(value);
    return `<div><dt>${label}</dt><dd>${name}${e(suffix)}</dd></div>`;
   }).join('')}</dl>
   <p class="rpt-scope"><strong>核验范围</strong>${e(scope.join(' · ')||'仅限提交的材料')}${(cov.gaps||[]).length?' · <button type="button" class="rpt-link" data-report-anchor="rpt-appendix-coverage">查看覆盖边界</button>':''}</p>
  </header>`;
 }
 reportItems(r,groups,nodes,{numbered=0}={}){
  const e=v=>this.esc(v),title=Object.fromEntries(nodes.map((n,i)=>[n.id,`${'①②③④⑤⑥⑦⑧⑨'[i]||i+1} ${n.title}`]));
  let n=numbered;
  return groups.filter(([,,,items])=>items.length).map(([key,label,hint,items])=>`<section class="rpt-group" data-report-group="${key}"><h3><span class="rpt-chip ${{fix:'fail',weakens:'fail',optimize:'warn',gaps:'warn',confirm:'neutral'}[key]}">${label}</span><span>${hint} · ${items.length}</span></h3>
   ${items.map(item=>{n++;const actions=!r.terminated_at&&item.dimension?(item.status==='needs_review'?`<button type="button" class="btn small" data-confirm-criterion="${e(item.dimension)}">标记为已确认</button>`:`<button type="button" class="btn small" data-supply-criterion="${e(item.dimension)}">补充材料</button>`):'';
    return `<article class="rpt-item"><span class="rpt-num">${String(n).padStart(2,'0')}</span><div class="rpt-item-body">
     <div class="rpt-item-head"><strong>${e(item.title)}</strong>${item.location?`<span class="rpt-loc">${e(item.location)}</span>`:''}${title[item.node]?`<button type="button" class="rpt-link" data-report-anchor="rpt-node-${e(item.node)}">流程 ${e(title[item.node])}</button>`:''}</div>
     ${item.fact?`<p class="rpt-fact">${e(item.fact)}</p>`:''}${item.suggestion?`<p class="rpt-suggest"><strong>建议</strong>${e(item.suggestion)}</p>`:''}${actions?`<div class="rpt-item-actions">${actions}</div>`:''}</div></article>`;}).join('')}</section>`).join('');
 }
 selfResult(r,o,nodes){
  const e=v=>this.esc(v);
  const groups=[['fix','修改建议','有直接证据的错误',o.groups.fix],['optimize','优化建议','结论可能成立，但不够扎实',o.groups.optimize],['confirm','待你确认','我们没看到，不算你的错',o.groups.confirm]];
  return `<section class="rpt-result tone-${e(o.tone)}" aria-labelledby="rpt-result-title"><p class="rpt-kicker">审查结果</p>
   ${o.note?`<p class="rpt-flag" role="status">${e(o.note)}</p>`:''}
   <h2 id="rpt-result-title" class="rpt-headline"><span class="rpt-head-main">${e(o.headline)}</span>${o.sub?`<span class="rpt-head-sub">${e(o.sub)}</span>`:''}</h2>
   ${o.code&&o.run?`<p class="rpt-reason">代码${e(o.run.label)}${o.run.total?`（${o.run.done}/${o.run.total} 个阶段）`:''}${o.run.reason?' · '+e(o.run.reason):''}</p>`:''}
   ${this.reportItems(r,groups,nodes)||'<p class="rpt-empty">核验范围内没有需要修改或确认的内容。</p>'}</section>`;
 }
 otherResult(r,o,nodes){
  const e=v=>this.esc(v);
  const groups=[['weakens','削弱结论','指标偏离、确认的错误或执行失败',o.groups.weakens],['gaps','可信度缺口','信息缺失或论文与代码不一致',o.groups.gaps],['confirm','待确认','本次材料或时间不足以判断',o.groups.confirm]];
  const innovation=o.paper?`<section class="rpt-innov" aria-labelledby="rpt-innov-title"><h3 id="rpt-innov-title">创新点</h3>
   ${o.innovations.length?o.innovations.map((item,i)=>`<article class="rpt-item"><span class="rpt-num rpt-num-lg">${i+1}</span><div class="rpt-item-body">
    <div class="rpt-item-head"><strong>${e(item.title)}</strong><span class="rpt-chip ${{supported:'pass',unsupported:'fail',uncovered:'neutral',stated:'neutral'}[item.status]}">${e(item.statusLabel)}</span></div>
    ${item.summary?`<p class="rpt-fact">${e(item.summary)}</p>`:''}
    <p class="rpt-quote"><span class="rpt-loc">第 ${e(item.page)} 页${item.section?' · '+e(item.section):''}</span>“${e(item.quote)}”</p>
    ${item.evidence?`<p class="rpt-evidence ${e(item.status)}">${e(item.evidence)}</p>`:''}</div></article>`).join(''):'<p class="rpt-empty">未能从原文提取有逐字出处的创新点，本报告不以摘要代替。</p>'}</section>`:'<p class="rpt-note">未提交论文，无法提取创新点。</p>';
  return `<section class="rpt-result tone-${e(o.tone)}" aria-labelledby="rpt-result-title"><p class="rpt-kicker">审查结果</p>
   ${o.note?`<p class="rpt-flag" role="status">${e(o.note)}</p>`:''}
   <h2 id="rpt-result-title" class="rpt-headline is-verdict">${e(o.verdict.title)}：<span class="rpt-verdict tone-${e(o.verdict.tone)}">${e(o.verdict.label)}</span></h2>
   ${o.verdict.reason?`<p class="rpt-reason">${e(o.verdict.reason)}</p>`:''}
   <dl class="rpt-facts">${o.facts.map(f=>`<div><dt>${e(f.label)}</dt><dd><strong>${e(f.value)}</strong>${f.unit?` <span>${e(f.unit)}</span>`:''}</dd></div>`).join('')}</dl>
   ${innovation}
   <section class="rpt-issues" aria-labelledby="rpt-issues-title"><h3 id="rpt-issues-title">存疑与差异</h3>
   ${this.reportItems(r,groups,nodes)||'<p class="rpt-empty">核验范围内没有发现存疑或差异。</p>'}</section></section>`;
 }
 reportFlow(r,p,o,nodes,notApplicable){
  const e=v=>this.esc(v),clock=t=>typeof t==='number'?new Date(t*1000).toLocaleTimeString('zh-CN',{hour12:false}):'—';
  const tone={pass:'pass',issue:'fail',fail:'fail',confirm:'neutral',running:'info',unreached:'neutral',skipped:'neutral',interrupted:'warn'};
  return `<section class="rpt-flow" aria-labelledby="rpt-flow-title"><div class="rpt-section-head"><h2 id="rpt-flow-title">审查流程</h2><span>${nodes.length} 个节点 · 有问题的节点默认展开并列出量化差距，其余点击展开查看完整记录</span></div>
   <ol class="rpt-timeline">${nodes.map((n,i)=>{const key=r.id+':'+n.id,open=this.nodeOpen?.has(key)?this.nodeOpen.get(key):['fail','issue','confirm'].includes(n.state);
    return `<li class="rpt-node state-${e(n.state)}" id="rpt-node-${e(n.id)}"><span class="rpt-time">${e(clock(n.time))}</span><span class="rpt-dot" aria-hidden="true"></span>
     <details data-report-node="${e(key)}" ${open?'open':''}><summary><strong>${'①②③④⑤⑥⑦⑧⑨'[i]||i+1} ${e(n.title)}</strong>${n.badge?`<span class="rpt-chip ${tone[n.state]||'neutral'}">${e(n.badge)}</span>`:''}<span class="rpt-node-sum">${e(n.summary)}</span></summary>
     <div class="rpt-node-body">${this.nodeBody(n,r,p,o)}</div></details></li>`;}).join('')}
   ${notApplicable.length?`<li class="rpt-node state-na"><span class="rpt-time">—</span><span class="rpt-dot" aria-hidden="true"></span><div class="rpt-na"><span>${e(notApplicable.join(' · '))}</span><span class="rpt-chip neutral">不适用</span><span>本次未提交${o.paper?'代码':'论文'}</span></div></li>`:''}</ol></section>`;
 }
 nodeBody(n,r,p,o){
  const e=v=>this.esc(v),v=r.review||{},x=r.execution;
  if(n.id==='material')return `<dl class="rpt-kv"><div><dt>审查目的</dt><dd>${o.purpose==='self_review'?'审查自己：纠错并给出修改与优化建议':'审查别人：评估合理性与可复现性，不给建议'}</dd></div><div><dt>材料类型</dt><dd>${e(typeNames[v.paper_type]||'待确认')}${v.classification_reason?' · '+e(v.classification_reason):''}</dd></div>${r.public_paper_identifier?`<div><dt>公开标识</dt><dd>${e(r.public_paper_identifier.value||r.public_paper_identifier.id||'')}</dd></div>`:''}</dl>`;
  if(n.id==='review')return `<div class="rpt-parts">${n.parts.map(part=>`<div class="rpt-part ${part.findings.length?'has-issue':''}"><div class="rpt-part-head"><strong>${e(part.name)}</strong><span class="rpt-chip ${part.findings.length?'fail':'pass'}">${part.findings.length?part.findings.length+' 处':'通过'}</span></div>${part.facts?`<p>${e(part.facts)}</p>`:''}${part.findings.map(f=>`<p class="rpt-line"><strong>${e(f.title)}</strong>${f.page?` <span class="rpt-loc">PDF 第 ${e(f.page)} 页</span>`:''}</p>`).join('')}</div>`).join('')}</div>`;
  if(n.id==='audit')return n.withdrawn?.length?`<p>撤回的条目不会出现在结果中：</p><ul class="rpt-list">${n.withdrawn.map(w=>`<li><strong>${e(w.title)}</strong> · ${e(w.reason)}</li>`).join('')}</ul>`:`<p>${e(n.summary)}</p>`;
  if(n.id==='related')return this.conflictsSection(r)||`<p>${e(n.summary)}</p>`;
  if(n.id==='plan')return n.stages.length?`<ol class="rpt-list">${n.stages.map(s=>`<li><strong>${e(s.id)} ${e(s.title)}</strong> <span class="rpt-loc">${e(s.file||'')}</span><code class="rpt-cmd">${e(concise(s.command,200))}</code></li>`).join('')}</ol>${(v.plan?.needs||[]).length?`<p class="rpt-note">所需资源：${e(v.plan.needs.map(x=>x.name+(x.required?'（必需）':'')).join('、'))}</p>`:''}`:`<p>${e(n.summary)}</p>`;
  if(n.id==='run')return n.stages.length?`<div class="online-table-wrap"><table class="online-table rpt-table"><thead><tr><th scope="col">阶段</th><th scope="col" class="number">用时</th><th scope="col" class="number">退出码</th><th scope="col">记录</th></tr></thead><tbody>${n.stages.map(s=>`<tr class="${s.status==='failed'?'is-fail':''}"><td>${e(s.id)} ${e(s.title)}</td><td class="number">${e(s.duration||'—')}</td><td class="number">${s.exit==null?'—':e(s.exit)}</td><td>${e(s.status==='skipped'?s.reason||'已跳过':s.reason||s.tail.join(' / ')||({completed:'完成',failed:'失败',running:'执行中'}[s.status]||s.status))}</td></tr>`).join('')}</tbody></table></div>${x?.runtime?`<p class="rpt-note">运行环境：Python ${e(x.runtime.python||'3.x')}${(x.runtime.auto_provisioned_packages||[]).length?` · 自动补齐依赖 ${x.runtime.auto_provisioned_packages.length} 个`:''}${x.runtime.workspace_cleaned?' · 隔离环境与临时依赖已清理':''}</p>`:''}${p?.shared?'':'<button type="button" class="btn small" data-online-tab="process">查看逐阶段日志</button>'}`:`<p>${e(n.summary)}</p>`;
  if(n.id==='metrics'){
   if(!n.rows?.length)return `<p>${e(n.summary)}</p>`;
   const bad=n.rows.filter(m=>m.status==='outside_tolerance');
   return `${bad.map(m=>`<div class="rpt-gap"><div class="rpt-gap-name"><span>指标</span><strong>${e(m.metric)}</strong></div><div><span>论文</span><strong>${e(withUnit(m.expected,m.unit))}</strong></div><div><span>实测</span><strong>${e(withUnit(m.observed,m.unit))}</strong></div><div><span>差距</span><strong class="is-fail">${e(m.gap)}</strong></div><div><span>容差</span><strong>±${e(m.tolerance)}</strong></div><p>${m.source?'出处 '+e(m.source)+' · ':''}观测来自阶段 ${e(m.stage_id||'—')} 的标准输出${m.basis?' · '+e(m.basis):''}</p></div>`).join('')}
    <div class="online-table-wrap"><table class="online-table rpt-table"><thead><tr><th scope="col">指标</th><th scope="col" class="number">论文</th><th scope="col" class="number">实测</th><th scope="col" class="number">差距</th><th scope="col" class="number">容差</th><th scope="col">结果</th></tr></thead><tbody>${n.rows.map(m=>`<tr class="${m.status==='outside_tolerance'?'is-fail':''}"><td>${e(m.metric)}</td><td class="number">${e(withUnit(m.expected,m.unit))}</td><td class="number">${e(withUnit(m.observed,m.unit))}</td><td class="number">${e(m.gap||'—')}</td><td class="number">±${e(m.tolerance)}</td><td>${e({within_tolerance:'在容差内',outside_tolerance:'超出容差',unobserved:'未取得观测'}[m.status]||m.status)}</td></tr>`).join('')}</tbody></table></div>
    <p class="rpt-note">容差由服务端按论文印刷精度限定，且不超过报告值的 1%；数值吻合不等于论文主要结论成立。</p>`;
  }
  return `<p>${e(n.summary)}</p>`;
 }
 reportAppendix(r,p,o,paperMeta){
  const e=v=>this.esc(v),v=r.review||{};
  const item=(id,label,hint,body)=>body?`<details class="rpt-appendix-item" id="${id}" data-report-appendix="${e(r.id)}:${id}" ${this.nodeOpen?.get(r.id+':'+id)?'open':''}><summary><span>${label}</span><span class="rpt-hint">${e(hint)}</span></summary><div class="rpt-appendix-body">${body}</div></details>`:'';
  return `<section class="rpt-appendix" aria-labelledby="rpt-appendix-title"><h2 id="rpt-appendix-title">附录</h2>
   ${item('rpt-appendix-metrics','图表指标全表',`${(v.metrics||[]).length} 项 · 作者方法优先`,o.paper?this.metricEvidence(v.metrics||[]):'')}
   ${item('rpt-appendix-paper','论文摘要与作者自述贡献','模型概括，未逐字核验',paperMeta?`<h3>${e(paperMeta.title)}</h3><p>${e(paperMeta.abstract)}</p>${paperMeta.contributions.length?`<ul>${paperMeta.contributions.map(c=>`<li>${e(c)}</li>`).join('')}</ul>`:''}`:'')}
   ${item('rpt-appendix-code','核心代码与实现解析','关键实现片段',o.code?this.coreCodeSection(r,p):'')}
   ${item('rpt-appendix-criteria','八项审查条件','按维度的材料依据',this.criteriaSection(r,p)+this.criteriaDetails(r,p))}
   ${item('rpt-appendix-coverage','覆盖边界与公开资料',`${(v.coverage?.gaps||[]).length} 项覆盖缺口`,this.evidence(r,{omitMetrics:true}))}
   ${p?.shared?'':'<div class="rpt-appendix-item rpt-appendix-link"><span>原始日志与角色事件</span><button type="button" class="rpt-link" data-online-tab="process">前往过程详情</button></div>'}
  </section>`;
 }

 isSelfReview(r){return r.review?.purpose?r.review.purpose==='self_review':r.review?.task!=='reproduction';}

 conflictsSection(report){
  if(!(report.review?.purpose==='self_review'||!report.review?.purpose&&report.review?.task==='self_review'))return '';
  const e=v=>this.esc(v),state=this.conflictState?.id===report.id?this.conflictState:null;
  const statuses={CONFIRMED_CONFLICT:'人工确认',REJECTED_CONFLICT:'人工排除',NEEDS_MORE_EVIDENCE:'待核实'};
  const actions=[['confirm','确认冲突'],['dismiss','排除'],['more_evidence','需补证据']];
  return `<section class="online-findings report-conflicts" data-report-conflicts="${e(report.id)}"><div class="online-section-heading"><h2>潜在冲突</h2></div><p>只比较当前账号已加入图谱的论文。候选项基于报告中已有的相似内容和实验信息。</p>${state?.error?`<p role="alert">${e(state.error)}</p><button class="btn small" data-conflict-retry>重试</button>`:state?.items?state.items.map(item=>`<article><header><h3>${e(item.source_paper_title)} 与 ${e(item.target_paper_title)}</h3><span class="pill">${e(statuses[item.verdict]||'待核实')}</span></header><p>${e(item.explanation)}</p><dl><dt>${e(item.source_title)}</dt><dd><blockquote>${e(item.evidence_chain?.source_quote||'暂无定位依据')}</blockquote></dd><dt>${e(item.target_title)}</dt><dd><blockquote>${e(item.evidence_chain?.target_quote||'暂无定位依据')}</blockquote></dd></dl><div class="kg-insp-actions">${actions.map(([key,label])=>`<button class="btn small" data-conflict-id="${e(item.id)}" data-conflict-decision="${key}" ${state.saving?'disabled':''}>${label}</button>`).join('')}</div></article>`).join('')||'<p>本次未发现需要核对的候选项。</p>':'<p role="status">正在核对候选项…</p>'}</section>`;
 }
 async loadConflicts(id,decision){
  const state={id,items:decision?this.conflictState?.items:null,saving:Boolean(decision)};
  this.conflictState=state;
  if(decision)this.renderNow();
  try{
   const path='/kg/assessments/'+encodeURIComponent(id)+'/conflicts';
   if(decision)await this.request(path,decision);
   if(this.conflictState!==state)return;
   state.items=(await this.request(path)).items;
  }catch(error){state.error=error.message;}
  finally{if(this.conflictState===state){state.saving=false;this.renderNow();}}
 }

 coreCodeSection(r,p=this.current()){
  const e=v=>this.esc(v),snippets=extractCoreCodeSnippets(r,p);
  if(!snippets.length)return '';
  return `<section id="report-code-section" class="report-code-section"><div class="online-section-heading"><h2>核心代码与实现解析</h2><span>${snippets.length} 处关键实现</span></div><div class="report-code-list">${snippets.map((s,idx)=>`<article class="report-code-item"><header class="report-code-head"><div class="report-code-title"><span>0${idx+1}</span><h3>${e(s.title)}</h3></div><span class="online-citation">${e(s.file)}${s.start_line?` · 第 ${e(s.start_line)}${s.end_line&&s.end_line!==s.start_line?`–${e(s.end_line)}`:''} 行`:''}</span></header><p class="report-code-explanation">${e(s.explanation)}</p><pre class="report-code-pre"><code>${e(s.code)}</code></pre></article>`).join('')}</div></section>`;
 }

 observations(r){const e=v=>this.esc(v),rows=r.execution?.metrics||[];return rows.length?`<section id="report-observations-section" class="report-observations"><div class="online-section-heading"><h2>论文目标与实际观测</h2><span>${rows.length} 项</span></div><div class="online-table-wrap"><table class="online-table metric-comparison"><colgroup><col style="width:28%"><col style="width:23%"><col style="width:23%"><col style="width:26%"></colgroup><thead><tr><th>指标</th><th class="number">论文值</th><th class="number">观测值</th><th>比较结果 / 容差</th></tr></thead><tbody>${rows.map(m=>`<tr><td>${e(m.metric)}</td><td class="number">${e(m.expected)} ${e(m.unit)}</td><td class="number">${m.observed==null?'未观测':e(m.observed)+' '+e(m.unit)}</td><td><span class="online-status ${m.status==='outside_tolerance'?'missing':m.status==='within_tolerance'?'documented':'needs_review'}">${e({unobserved:'无可比较输出',within_tolerance:'数值在容差内',outside_tolerance:'超出容差'}[m.status]||m.status)}</span>${m.tolerance==null?'':` <small>±${e(m.tolerance)} ${e(m.unit)}</small>`}</td></tr>`).join('')}</tbody></table></div></section>`:'';}

 purposeChoice(p){
  return `<fieldset class="review-task-options review-purpose" id="review-purpose"><legend>审查目的</legend>${[['self_review','自我审查'],['reproduce_other','复现他人']].map(([key,label])=>`<label><input type="radio" name="online-purpose" value="${key}" data-online-purpose ${p.online_purpose===key?'checked':''}><strong>${label}</strong></label>`).join('')}${this.errors.purpose?'<p class="online-field-error" role="alert">请选择审查目的。</p>':''}</fieldset>`;
 }
 railRows(p){
  const e=v=>this.esc(v),paperBusy=this.busy.includes('论文'),codeBusy=Boolean(this.repoStartedAt||this.busy.includes('代码')||this.busy.includes('源码')),codeFail=this.repoState==='读取失败'&&!hasCode(p);
  const paper=paperBusy?`<span class="rail-badge running"><span class="online-spinner" aria-hidden="true"></span>正在解析</span><small>${e(this.busy)}</small>`:p.paper?`<span class="rail-badge ready">已导入 · ${e(p.paper.pages?.length||0)} 页</span><small title="${e(p.paper.name)}">${e(p.paper.name)}</small>`:`<span class="rail-badge empty">未提供</span><small>上传 PDF 后自动解析</small>`;
  const elapsed=this.repoStartedAt?Math.max(0,Math.floor((Date.now()-this.repoStartedAt)/1000)):0;
  const repoDisplayName=p.repository?.repo_name||p.repository?.name?.replace(/\.zip$/i,'')||p.title||'';
  const code=codeBusy?`<span class="rail-badge running"><span class="online-spinner" aria-hidden="true"></span>正在读取</span><small data-rail-repo-elapsed>${e(this.repoState||this.busy||'正在读取源码…')}${this.repoStartedAt?` · 已等待 ${elapsed} 秒`:''}</small>`:codeFail?`<span class="rail-badge failed">读取失败</span><small>${e(this.error||'请检查仓库地址或改传 ZIP')}</small>`:hasCode(p)?`<span class="rail-badge ready rail-source-name">源码已读取 · ${e(repoDisplayName)}${p.repository.commit?' ('+e(p.repository.commit.slice(0,8))+')':''}</span>`:p.repo_url?.trim()?`<span class="rail-badge active">待读取仓库</span><small title="${e(p.repo_url)}">${e(p.repo_url)}</small>`:`<span class="rail-badge empty">未提供</span><small>支持 ZIP 或 GitHub 仓库</small>`;
  return `<div><dt>论文</dt><dd>${paper}</dd></div><div><dt>代码</dt><dd>${code}</dd></div>`;
 }
 materials(p){const e=v=>this.esc(v),report=p.online_report,hasReport=Boolean(report?.review),repoDisplayName=p.repository?.repo_name||p.repository?.name?.replace(/\.zip$/i,'')||p.title||'',repoText=this.repoState||(p.repository?.commit?`源码已读取 · ${repoDisplayName} (${p.repository.commit.slice(0,8)})`:hasCode(p)&&repoDisplayName?`源码已读取 · ${repoDisplayName}`:''),repoStatusClass=this.repoStartedAt?'loading':this.repoState==='读取失败'?'failed':repoText.startsWith('支持粘贴')?'hint':repoText?'ready':'';
 return `<div class="online-intake-grid"><section class="online-form"><div class="online-section-heading"><h2>论文与代码</h2><span>至少提供一项</span></div>
 <div class="online-upload-pair"><label class="online-upload ${p.paper?'has-file':''}" for="online-pdf"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.pdf}</span><span>论文 PDF</span></div><strong>${e(p.paper?.name||'上传论文')}</strong><small>${p.paper?`${p.paper.pages?.length||0} 页 · 点击替换`:'用于图表指标、数据与论证自查'}</small><input id="online-pdf" type="file" accept=".pdf,application/pdf" data-online-upload="paper" ${this.busy?'disabled':''}></label>
 <label class="online-upload ${hasCode(p)?'has-file':''}" for="online-zip"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.zip}</span><span>代码 ZIP</span></div><strong>${e(p.repository?.name||'上传代码')}</strong><small>${p.repository?`${p.repository.files?.length||0} 个文件 · 点击替换`:'最大 100 MB，也可填写 GitHub 地址'}</small><input id="online-zip" type="file" accept=".zip,application/zip" data-online-upload="code" ${this.busy?'disabled':''}></label></div>${this.warn('material')}
 <div class="online-field"><label for="online-repo"><span class="field-icon-inline">${UI_SVG.github}</span>公开 GitHub 仓库 <small>可选，填入后自动读取源码</small></label><div class="online-input-action"><input id="online-repo" type="url" data-online-field="repo_url" value="${e(p.repo_url||'')}" placeholder="https://github.com/作者/仓库 或 作者/仓库" ${this.busy&&!this.parsingPaper?'disabled':''}><button class="btn" data-online="github" ${this.busy?'disabled':''}>${this.repoState==='读取失败'?'重新读取':'读取'}</button></div><div class="online-repo-state ${repoStatusClass}" role="status" ${repoStatusClass?'':'hidden'}>${this.repoStartedAt?'<span class="online-spinner" aria-hidden="true"></span>':''}<strong class="repo-state-label" title="${e(repoText)}">${e(repoText)}</strong>${this.repoStartedAt?'<span data-repo-elapsed>已等待 0 秒</span>':''}</div></div>
 ${!p.online_report?.terminated_at&&(p.online_report?.execution?.needs_user||p.online_report?.availability||p.online_report?.id&&p.online_report.id===this.supplyReport)?`<div class="online-field"><label for="online-supply">补充数据、权重或获取线索</label><textarea id="online-supply" data-online-field="online_supply_notes" maxlength="3000" placeholder="填写公开数据 / 权重地址或补充说明；文件可放入代码 ZIP。不要填写账号密码或密钥。">${e(p.online_supply_notes||'')}</textarea><small>补充后重新审查，原执行与材料版本保留在历史记录中。</small></div>`:''}<section class="online-access"><div class="online-submit"><button class="btn primary" data-online="submit" ${this.busy?'disabled':''}>${hasReport?'重新审查当前材料':'开始审查'}</button>${this.isInterruptedReport(p.online_report)?'<button type="button" class="btn danger" data-online="terminate-review">终止本次审查</button>':''}<button type="button" class="btn online-local-btn" data-online="local" ${this.busy?'disabled':''}>${UI_SVG.monitor}<span>在本地电脑执行</span></button>${hasReport?`<button class="btn" data-online-tab="report">查看上次报告</button>`:''}</div></section></section>
 <aside class="online-rail has-task-choice"><div class="online-rail-head"><h2>本次审查</h2><span class="rail-live-tag ${this.busy||this.repoStartedAt?'updating':''}">${this.busy||this.repoStartedAt?'正在同步':'实时状态'}</span></div><dl id="online-rail-dl">${this.railRows(p)}</dl>${hasReport?'<button class="btn" data-online-tab="report">继续查看报告</button>':''}${this.purposeChoice(p)}</aside></div>`;}

 citation(row){return row.page||row.file?`<small class="online-citation">${row.page?'PDF 第 '+this.esc(row.page)+' 页':''}${row.page&&row.file?' · ':''}${this.esc(row.file||'')}</small>`:'';}
 execution(r,stale){const e=v=>this.esc(v),pending=this.current()?.online_execution_pending,
 x=pending&&pending.id===r.id&&(!r.execution||r.execution.attempt_id===pending.retry_of)?{status:'starting'}:r.execution,
 p=r.review.plan,retryCancel=this.current()?.online_cancel_error,terminated=Boolean(r.terminated_at),isRunning=!terminated&&['queued','starting','running','cancelling'].includes(x?.status);

 return `<section id="online-execution-section" class="online-execution-block"><section class="online-summary"><div><h2>${x?e(executionNames[x.status]||x.status):'执行计划'}</h2>${!p.stages.length&&p.blocked_reason?`<p>${e(p.blocked_reason)}</p>`:!x&&p.stages.length&&!terminated?'<p>实验尚未启动。</p>':''}</div><div class="source-actions">${!terminated&&!x&&p.stages.length?`<button class="btn primary" data-online="execute" ${stale||this.busy||this.cancelling?'disabled':''}>执行本次计划</button>`:''}${isRunning?`<button class="btn" data-online="refresh">刷新状态</button><button class="btn danger online-abort-btn" data-online="cancel" ${x?.status==='cancelling'&&!retryCancel?'disabled':''}>${UI_SVG.stop}${retryCancel?'重试中断':x?.status==='cancelling'?'正在终止…':'中断运行'}</button>`:''}${!terminated&&x?.attempt_id&&['failed','expired','cancelled'].includes(x.status)&&(r.execution_history?.length||0)<2?`<button class="btn" data-online="retry" ${stale||this.busy||this.cancelling?'disabled':''}>重试执行</button>`:''}<button class="btn" data-online="export">导出报告</button></div></section>${this.execNotice?`<div class="online-notice warning-notice" role="status"><strong>实验自动启动提示：</strong>${e(this.execNotice)}</div>`:''}${!p.stages.length?`<p class="online-notice">${e(p.blocked_reason||'材料不足以生成真实执行计划。可以先查看已完成的材料审查。')}</p>`:''}
 ${p.stages.length?`<div class="online-terminal-box online-stage-list" role="region" aria-label="动态运行终端"><div class="terminal-topbar"><div class="terminal-dots" aria-hidden="true"><i></i><i></i><i></i></div><div class="terminal-title">${UI_SVG.terminal}<span>实验复现运行终端</span></div><div class="terminal-topbar-right"><div class="terminal-live-state ${isRunning?'running':x?.status||'planned'}">${isRunning?'<span class="online-spinner" aria-hidden="true"></span>':''}<span>${e(x?executionNames[x.status]||x.status:'尚未启动')}</span></div></div></div><div class="terminal-stream-body" data-terminal-key="${e(r.id)}:${e(x?.attempt_id||'planned')}">${p.stages.map((s,n)=>{const a=x?.stages?.find(z=>z.id===s.id),state=a?.status==='running'&&x.status==='cancelled'?'skipped':a?.status||'planned',liveLines=extractStageLiveLines(a);return `<div class="online-stage stage-${e(state)}"><div class="terminal-stage-head"><span class="terminal-step-num">[${n+1}/${p.stages.length}]</span><strong class="terminal-stage-title">${e(s.title)}</strong>${a?.exit_code!=null?`<span class="online-citation">退出码 ${e(a.exit_code)}</span>`:''}${a?.retry_count&&state==='running'?`<span class="online-citation">正在重试 ${e(a.retry_count)} / 3</span>`:''}<span class="online-status status-${e(state)} ${state==='failed'?'missing':state==='completed'?'documented':state==='running'?'running':'needs_review'}">${e({planned:'计划中',running:'执行中',completed:'已执行',failed:a?.timed_out?'超时中断':'报错中断',skipped:'已跳过'}[state]||state)}</span></div><div class="terminal-cmd-row"><span class="terminal-prompt">$</span><pre class="terminal-cmd">${e(s.command)}</pre></div>${liveLines.length?`<div class="terminal-live-tail" role="log" aria-label="阶段最新输出"><pre class="terminal-tail-lines">${liveLines.map(ln=>e(ln)).join('\n')}</pre></div>`:''}${a?.reason?`<p class="terminal-reason">${e(a.reason)}</p>`:''}</div>`;}).join('')}</div></div>`:''}
 ${!terminated&&!x&&r.review.resource_preflight?.needs_user?`<section class="online-blocker"><h3>运行前条件待确认</h3><p>${e(r.review.resource_preflight.reason)}</p>${r.availability?`<strong>${e(r.availability.verdict)}</strong>`:'<div class="online-blocker-actions"><button class="btn" data-online="can-provide">可补充所需材料</button><button class="btn" data-online="unavailable">确认无法提供</button></div>'}<div class="online-blocker-route"><span>也可以切换执行方式</span><button class="btn" data-online="local">使用本地环境</button></div></section>`:''}${!terminated&&!x&&r.review.task==='reproduction'&&!r.materials.code?`<section class="online-blocker"><h3>需要补充代码来源</h3><p>${e(r.source_discovery?.reason||'自动分析未能取得可执行源码，请补充 GitHub 地址或代码 ZIP。')}</p>${r.availability?`<strong>${e(r.availability.verdict)}</strong><button class="btn" data-online-tab="materials">补充材料</button>`:'<button class="btn" data-online="can-provide">可以补充</button><button class="btn" data-online="unavailable">确认无法获取</button>'}</section>`:''}${!terminated&&x?.needs_user?`<section class="online-blocker"><h3>需要补充材料</h3><p>${e(x.question)}</p>${x.user_answer?`<strong>${e(x.availability_verdict)}</strong>${x.user_answer==='can_provide'?'<button class="btn" data-online-tab="materials">补充材料</button>':''}`:'<button class="btn" data-online="can-provide">可以补充</button><button class="btn" data-online="unavailable">确认无法提供</button>'}</section>`:''}
 ${x?.runtime?`<p class="online-footnote">运行环境：Python ${e(x.runtime.python||'3.x')}${x.elapsed_seconds!=null?' · 耗时 '+e(x.elapsed_seconds)+' 秒':''}${x.runtime?.workspace_cleaned?' · 隔离环境与临时依赖库已清理':''}</p>`:''}<p class="online-footnote">日志和数值来自本次代码执行。进程成功、数值吻合与论文主要结论成立分别判断；本页不自动将主要结论标记为通过。</p></section>`;}

 evidence(r,{omitMetrics=false}={}){
  const e=v=>this.esc(v),v=r.review;
  return `${omitMetrics?'':`<section id="report-metrics-section" class="report-metrics-anchor"><div class="online-section-heading"><h2>图表指标与出处</h2><span>作者方法优先 · ${v.metrics.length} 项</span></div>
   ${this.metricEvidence(v.metrics)}</section>`}
   ${v.visual_observations?.length?`<section class="online-coverage"><h2>曲线观察</h2><p>下列内容来自图像估读，用于定位，不作为精确数值验收目标。</p>${v.visual_observations.map(o=>`<article class="online-notice"><strong>${e(o.reference)} · 第 ${o.page} 页</strong><p>${e(o.note)}</p><button class="btn text" data-online-page="${o.page}">对照原图</button></article>`).join('')}</section>`:''}
   <section class="online-coverage"><h2>公开资料核对</h2><p>${e({completed:r.source_lookup?.cached?'已读取缓存的公开来源':'已检索公开来源',no_results:'未找到可用的公开来源',failed:'本次公开检索未完成',not_requested:'本次依据已提供材料开展内部核对'}[r.source_lookup?.status]||'本次未调用公开检索')}</p>
    ${(v.web_checks||[]).map(c=>`<article class="online-notice"><strong>${e(c.claim)}</strong><p>${e({supported:'有对应依据',contradicted:'发现不一致',unresolved:'证据不足'}[c.status])} · ${e(c.note)}</p><a href="${e(c.url)}" target="_blank" rel="noreferrer">查看引用来源</a></article>`).join('')}
    ${r.web_sources?.length?`<ul>${r.web_sources.map(source=>`<li><a href="${e(source.url)}" target="_blank" rel="noreferrer">${e(source.title||source.url)}</a></li>`).join('')}</ul>`:''}
   </section>
   <section id="report-coverage-section" class="online-coverage"><h2>覆盖边界</h2><p>${e(v.coverage.note)}</p><ul>${v.coverage.gaps.map(g=>`<li>${e(g)}</li>`).join('')||'<li>模型未列出额外缺口。仍以实际提供的页面和代码片段为审查范围。</li>'}</ul><p class="online-footnote">提供上下文：${e(v.coverage.paper_pages_in_context)} 页论文文字、${e(v.coverage.paper_images_in_context||0)} 张原页图像、${e(v.coverage.code_files_in_context)} / ${e(v.coverage.total_code_files)} 个代码文件。</p></section>`;
 }
 metricEvidence(metrics){
  const e=v=>this.esc(v),catalog=metricCatalog(metrics,{audience:this.metricAudience,query:this.metricQuery});
  if(!metrics.length)return '<p class="online-notice">没有通过出处核验的图表数字。正文中的零散数字未转换为实验指标。</p>';
  return `<div class="metric-toolbar"><label for="metric-search">查找指标<input id="metric-search" type="search" value="${e(this.metricQuery)}" placeholder="模型、图表或数据集" data-metric-query></label><label for="metric-audience">展示对象<select id="metric-audience" data-metric-audience><option value="all" ${this.metricAudience==='all'?'selected':''}>全部方法</option><option value="author" ${this.metricAudience==='author'?'selected':''}>作者方法</option><option value="baseline" ${this.metricAudience==='baseline'?'selected':''}>对照方法</option></select></label><span>显示 ${catalog.count} / ${metrics.length} 项</span></div><div class="metric-catalog">${catalog.datasets.map((d,di)=>`<details class="metric-dataset" ${di===0?'open':''}><summary><strong>${e(d.name)}</strong><span>${d.count} 项 · ${d.families.length} 类</span></summary>${d.families.map(f=>`<section class="metric-family"><h3>${e(f.name)}<span>${f.count} 项</span></h3>${f.groups.map((g,gi)=>`<details class="metric-protocol" ${gi===0?'open':''}><summary><strong>${e(g.reference)}</strong><span class="metric-protocol-label" title="${e(g.protocol)}">${e(g.protocol||'未标注评测协议')}</span><span>${g.rows.length} 项</span></summary><div class="online-table-wrap"><table class="online-table"><thead><tr><th>模型 / 方法</th><th>指标</th><th class="number">报告值</th><th>出处</th></tr></thead><tbody>${g.rows.map(({row:m})=>`<tr class="${m.author_method?'author-method':''}"><td><strong>${e(m.model)}</strong>${m.author_method?'<span>作者方法</span>':'<span>对照方法</span>'}</td><td>${e(m.metric)}</td><td class="number">${e(m.value)} ${e(metricUnit(m))}</td><td><details><summary>第 ${e(m.page)} 页 · 原文</summary><blockquote>${e(m.quote)}</blockquote><small>${m.evidence_kind==='image_reading'?'来自页面图像识别，建议对照原图核对':'已与该页提取文字对应'}</small><button class="btn text" data-online-page="${e(m.page)}">打开 PDF 原页</button></details></td></tr>`).join('')}</tbody></table></div></details>`).join('')}</section>`).join('')}</details>`).join('')||'<p class="online-notice">没有匹配的指标，请调整筛选。</p>'}</div>`;
 }
 async pollProgress(p,id){
  try{const value=checkAssessment(await this.request('/assessments/'+id));if(this.progressId!==id)return;this.liveReport=value;if(!this.isViewing(p))return;const region=document.querySelector('#online-activity');if(region)region.innerHTML=this.timelineView(value,{activeRole:this.activeRoleNode});const sidebar=document.querySelector('#sidebar-review');if(sidebar)sidebar.innerHTML=this.sidebar();}catch{} // A not-yet-claimed request is normal while parsing.
 }
 roles(r){const e=v=>this.esc(v),events=activityEvents(r).map(x=>({...x,kind:x.kind||x.title,stage:x.stage||x.detail,role:x.role||x.roles?.[0]})),roles=[['literature_reader','文献审阅','模型 API 识别材料类型、图表和引用。'],['code_inspector','代码检查','模型 API 阅读提供的源文件和依赖。'],['planner','计划编排','模型 API 生成计划；执行器按冻结计划排程。'],['experiment_runner','实验执行','隔离环境运行实际命令。'],['cross_auditor','交叉核查','校验出处、阶段退出码和数值比较。'],['reporter','报告整理','汇总审查建议、执行状态与覆盖缺口。']];return `<section class="online-roles"><h2>角色职责与记录</h2><p class="online-footnote">文献与代码审查由同一次模型请求处理；角色名称表示工作流职责。</p>${roles.map(([id,name,note])=>{const rows=events.filter(v=>(v.roles||[v.role]).includes(id));return `<details><summary><strong>${name}</strong><span>${rows.length?rows.length+' 条执行事件':id==='literature_reader'&&!r.materials.paper?'未提供论文':id==='code_inspector'&&!r.materials.code?'未提供代码':id==='literature_reader'||id==='code_inspector'?'模型审查已返回':id==='planner'&&r.review.plan.stages.length?'已生成计划':'尚无执行事件'}</span></summary><p>${note}</p>${rows.map(row=>`<div class="online-role-event"><code>${e(row.kind)}</code><span>${e(row.stage||row.status||row.reason||row.policy||'')}</span></div>`).join('')}</details>`;}).join('')}${events.length?`<section class="online-role-stream"><h3>最近执行事件</h3>${events.slice(-6).map(row=>`<div class="online-role-event"><span>${e({planner:'计划编排',experiment_runner:'实验执行',cross_auditor:'交叉核查',reporter:'报告整理'}[row.role]||row.role)}</span><strong>${e({plan_scheduled:'按冻结计划排程',stage_started:'开始执行',stage_finished:'执行结束',stage_checked:'核对阶段结果',execution_checked:'汇总执行证据',report_written:'写入报告',stopped:'结束排程'}[row.kind]||row.kind)}</strong><span>${e(r.review.plan.stages.find(s=>s.id===row.stage)?.title||row.status||row.reason||'')}</span></div>`).join('')}</section>`:''}</section>`;}
 async request(path,payload,{track=true}={}){if(!this.owner)throw Error('浏览器存储不可用，无法提交。');const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),115000);if(track&&payload!==undefined)this.activeController=controller;try{const response=await fetch('/v1'+path,{method:payload===undefined?'GET':'POST',headers:{'X-ArtiCheck-Client':'review-api','X-ArtiCheck-Session':this.owner,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal,credentials:'same-origin',redirect:'error'});let value;try{value=await response.json();}catch{throw Error('服务暂时没有返回有效响应，请稍后重试。');}if(!response.ok){if(response.status===401&&typeof location!=='undefined')location.assign('./login.html?next='+encodeURIComponent(location.pathname+location.hash));const error=Error(value.error?.message||'请求失败。');error.code=value.error?.code;throw error;}return value;}catch(err){if(err.name==='AbortError'){if(track&&this.userAborted)throw Error('已按请求中断运行。');throw Error('等待服务返回超时，请刷新已有任务；不要连续重复提交。');}throw err;}finally{clearTimeout(timer);if(this.activeController===controller)this.activeController=null;}}
 checkOperation(generation){
  if(generation!==(this.pollGeneration||0))throw Error('已按请求中断运行。');
 }
 async payload(p,generation=this.pollGeneration||0){
  this.checkOperation(generation);
  const body={task:p.online_task||'auto',...(p.online_purpose?{purpose:p.online_purpose}:{}),scope:p.online_restrict?p.online_scope:'',max_seconds:null,supplement:p.online_supply_notes||''};
  const files=[['paper',p.paper],['code',p.repository]].filter(([,m])=>m?.blob);
  if(p.repository?.remote)body.code=p.repository.remote;
  if(files.reduce((n,[,m])=>n+m.blob.size,0)>3_000_000){
   const key=JSON.stringify(files.map(([kind,m])=>[kind,m.sha256,m.name,m.blob.size]));
   let transfer=p.online_upload;
   if(!transfer||transfer.key!==key||transfer.expires_at*1000<Date.now()+180000){
    if(!p.online_upload_pending||p.online_upload_pending.key!==key)p.online_upload_pending={key,id:uid().replaceAll('-','')};
    await this.save(p);
    const previous=this.busy;this.busy='正在建立大文件传输通道…';this.renderNow();
    try{
     const value=await this.request('/uploads',{request_id:p.online_upload_pending.id,files:files.map(([kind,m])=>({kind,name:m.name,bytes:m.blob.size,sha256:m.sha256}))});
     this.checkOperation(generation);
     for(const [kind,m] of files){
      this.checkOperation(generation);
      this.busy='正在传输 '+m.name+' · '+(m.blob.size/1024/1024).toFixed(1)+' MB';this.renderNow();
      const target=new URL(value.files[kind].upload_url);
      if(target.protocol!=='https:'||!['.e2b.app','.e2b.dev'].some(suffix=>target.hostname.endsWith(suffix)))throw Error('大文件传输地址无效。');
      const form=new FormData();form.append('file',m.blob,m.name);
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),Math.max(1000,value.expires_at*1000-Date.now()-10000));
      this.activeController=controller;
      let response;
      try{response=await fetch(target.href,{method:'POST',body:form,credentials:'omit',redirect:'error',signal:controller.signal});}
      finally{clearTimeout(timeout);if(this.activeController===controller)this.activeController=null;}
      this.checkOperation(generation);
      if(!response.ok)throw Error('大文件传输未完成，请重新提交；文件仍保存在当前浏览器。');
     }
     transfer={key,id:value.id,expires_at:value.expires_at,materials:Object.fromEntries(Object.entries(value.files).map(([kind,item])=>[kind,item.material]))};
     p.online_upload=transfer;p.online_upload_pending=null;await this.save(p);
    }finally{if(generation===(this.pollGeneration||0)){this.busy=previous;this.renderNow();}}
   }
   Object.assign(body,transfer.materials);
  }else for(const [kind,m] of files)body[kind]={name:m.name,content_base64:await encoded(m.blob)};
  this.checkOperation(generation);
  if(new TextEncoder().encode(JSON.stringify(body)).length>5_000_000)throw Error('材料描述过大，请缩短补充说明后重新提交。');
  return body;
 }
 async save(p){await this.i.save(p);}
 renderNow(){if(this.i.h.page?.()!=='api-review'&&this.i.h.refreshReviewSidebar){this.i.h.refreshReviewSidebar();this.afterRender();}else this.i.h.render();}
 async upload(kind,file){if(this.busy)return;const p=this.current();this.i.activeId=p.id;this.parsingPaper=kind==='paper';this.busy=kind==='paper'?'正在解析论文…':'正在读取代码…';this.renderNow();try{await this.i.upload(kind,file);if(this.i.error)throw Error(this.i.error);p.claims=[];if(!p.title)p.title=file.name.replace(/\.(pdf|zip)$/i,'');if(!p.online_task)p.online_task='auto';this.errors={};if(kind==='code'){const label=file.name.replace(/\.zip$/i,'')||p.title||'';this.repoState=`源码已读取 · ${label}`;}if(!p.online_purpose&&kind==='paper'&&!hasCode(p)&&!p.repo_url){const links=[...new Set((p.paper?.pages||[]).flatMap(v=>v.links||[]).map(u=>normalizeGitHubUrl(u)).filter(Boolean))];if(links.length===1){p.repo_url=links[0];this.repoState='从论文发现代码链接';}}await this.save(p);}catch(err){this.error=err.message;}finally{this.parsingPaper=false;this.busy='';this.renderNow();if(kind==='paper'&&p===this.current()&&p.repo_url&&!hasCode(p)){clearTimeout(this.repoTimer);this.github();}}}
 async github(force=false,internal=false,p=this.current()){const rawUrl=p?.repo_url?.trim();if(!rawUrl)return;const url=normalizeGitHubUrl(rawUrl);if(!url){if(force){this.repoState='支持粘贴 GitHub 仓库任意链接或 用户名/仓库名';this.error='';this.renderNow();}return;}if(url!==rawUrl)p.repo_url=url;if(!force&&hasCode(p)&&p.repository.url===url){const label=p.repository.repo_name||p.repository.name?.replace(/\.zip$/i,'')||p.title||'';this.repoState=`源码已读取 · ${label} (${p.repository.commit?.slice(0,8)||''})`;return;}if(this.repoPending?.url===url)return this.repoPending.promise;if(this.busy&&!internal)return;const generation=++this.repoGeneration;this.repoState='正在定位版本并读取源码…';this.repoStartedAt=Date.now();this.error='';this.renderNow();const promise=(async()=>{try{const value=await this.request('/repositories',{url,refresh:force,...(internal?{assessment_id:p.online_report.id}:{})});if(generation!==this.repoGeneration||!internal&&p!==this.current()||normalizeGitHubUrl(p.repo_url)!==url)return;if(value.assessment)p.online_report=checkAssessment(value.assessment);let source;if(value.material.content_base64){const bytes=Uint8Array.from(atob(value.material.content_base64),c=>c.charCodeAt(0));source={...inspectZip(bytes.buffer),blob:new Blob([bytes],{type:'application/zip'}),size:bytes.byteLength};}else source={remote:value.material,files:value.files,size:value.material.bytes};p.repository={...source,kind:'github',url:value.url,commit:value.commit,name:value.material.name,repo_name:value.name,sha256:value.sha256,fetched_at:value.fetched_at,cached_reference:value.cached_reference};p.claims=[];if(!p.title)p.title=value.name;const label=value.name||p.title||value.material.name.replace(/\.zip$/i,'');this.repoState=`源码已读取 · ${label} (${value.commit.slice(0,8)})`;await this.save(p);}catch(err){if(generation===this.repoGeneration){this.repoState='读取失败';this.error=err.message;}}finally{if(generation===this.repoGeneration){this.repoPending=null;this.repoStartedAt=null;this.renderNow();}}})();this.repoPending={url,promise};return promise;}
 async execute(p,{retry=false,generation=this.pollGeneration||0}={}){
  const r=p.online_report;
  this.checkOperation(generation);
  if(r?.terminated_at)throw Error('本次审查已终止。');
  if(!r?.review)throw Error('请先等待材料审查完成。');
  if(p.online_input_key!==inputKey(p))throw Error('材料或范围已变化，请重新审查。');
  if(!hasCode(p))throw Error('请补充代码源码。');
  p.online_execution_pending={id:r.id,retry_of:retry?r.execution.attempt_id:null};
  this.busy='正在提交实验并创建执行环境…';this.execNotice='';this.renderNow();
  await this.save(p);
  let value;
  try{
   const body=await this.payload(p,generation);
   value=checkAssessment(await this.request('/assessments/'+r.id+'/execute',{code:body.code,plan_sha256:r.review.plan_sha256,...(retry?{retry_of:r.execution.attempt_id}:{})}));
  }catch(error){
   if(generation===(this.pollGeneration||0)&&['no_executable_plan','plan_changed','retry_changed','material_changed','assessment_terminated','compute_budget_exhausted','sandbox_not_configured'].includes(error.code)){
    p.online_execution_pending=null;
    await this.save(p);
   }
   throw error;
  }
  this.checkOperation(generation);
  p.online_report=value;p.online_execution_pending=null;
  await this.save(p);
  if(this.isViewing(p))this.tab='process';
 }
 async reviewOnce(p,generation){
  this.checkOperation(generation);
  const key=inputKey(p);
  if(!p.online_pending_request||p.online_pending_request.key!==key)p.online_pending_request={key,id:uid().replaceAll('-','')};
  const requestId=p.online_pending_request.id;
  await this.save(p);
  const payload={...await this.payload(p,generation),request_id:requestId};
  this.liveReport=null;this.progressId=payload.request_id;let value;
  let watching=true;const tick=async()=>{await this.pollProgress(p,payload.request_id);if(watching)this.progressTimer=setTimeout(tick,2500);};
  this.progressTimer=setTimeout(tick,1500);
  try{value=checkAssessment(await this.request('/assessments',payload));}
  finally{watching=false;if(this.progressId===requestId){this.progressId=null;clearTimeout(this.progressTimer);this.liveReport=null;}}

  this.checkOperation(generation);
  if(p.online_report?.id&&p.online_report.id!==value.id)p.online_history=[...(p.online_history||[]),{report:p.online_report,input_key:p.online_input_key}].slice(-20);
  p.online_report=value;p.online_input_key=key;
  if(value.status!=='reviewing')p.online_pending_request=null;
  await this.save(p);
  return value;
 }
 pulseSection(target){
  if(!target)return;
  target.scrollIntoView({behavior:'smooth',block:'start'});
  target.classList.remove('section-highlight-pulse');
  void target.offsetWidth;
  target.classList.add('section-highlight-pulse');
  setTimeout(()=>target.classList.remove('section-highlight-pulse'),1800);
 }
 jumpFromRole(roleId){
  const p=this.current(),r=this.viewReport(p);
  if(!r)return;
  if(this.tab!=='process')this.tab='process';
  this.activeRoleNode=this.activeRoleNode===roleId?null:roleId;
  this.renderNow();
  if(this.activeRoleNode&&typeof document!=='undefined'){
   setTimeout(()=>{if(typeof document!=='undefined')this.pulseSection(document.querySelector('#online-role-node-panel')||document.querySelector('#online-execution-section'));},40);
  }
 }
 async action(action,p=this.current(),resumeTask=null){
  if(action==='terminal'){
   this.tab='process';
   this.activeRoleNode='experiment_runner';
   this.renderNow();
   setTimeout(()=>{
    const target=document.querySelector('#online-execution-section .online-terminal-box')||document.querySelector('#online-execution-section')||document.querySelector('#online-role-node-panel')||document.querySelector('#online-activity');
    if(target)this.pulseSection(target);
   },40);
   return;
  }
  if(action==='resume-review'){
   if(!p||p.online_report?.terminated_at)return;
   this.consent=true;
   this.tab='materials';
   this.renderNow();
   return;
  }
  if(action==='terminate-review'){
   if(!p?.online_report?.id||this.cancelling||!confirm('终止本次审查？已取得的证据会保留。'))return;
   if(p.online_pending_request||p.online_execution_pending||['queued','starting','running','cancelling'].includes(p.online_report.execution?.status)||p.online_report.status==='reviewing'){
    if(!await this.action('cancel',p,true))return;
    if(p.online_report?.terminated_at)return;
    if(['queued','starting','running','cancelling'].includes(p.online_report?.execution?.status))return;
   }
   const page=this.i.h.page?.();
   let terminated=false;
   this.operationProject=p.id;
   this.busy='正在终止本次审查…';this.error='';this.renderNow();
   const dismissNotice=this.i.h.toast?.('正在终止审查…',{persistent:true,tone:'pending'});
   try{
    p.online_report=checkAssessment(await this.request('/assessments/'+p.online_report.id+'/terminate',{}));
    p.online_pending_request=null;await this.save(p);this.liveReport=null;if(this.isViewing(p))this.tab='process';
    terminated=true;
    this.i.h.toast?.('本次审查已终止',{tone:'success'});
   }catch(error){this.error=error.message;this.i.h.toast?.('终止审查失败：'+error.message,{tone:'error'});}
   finally{
    dismissNotice?.();
    this.busy='';this.operationProject=null;this.renderNow();
    if(terminated&&p.id===this.selected&&this.i.h.page?.()===page&&typeof window!=='undefined')window.scrollTo({top:0,behavior:'instant'});
   }
   return;
  }
  if(action==='cancel'){
   if(!p||this.cancelling||this.operationProject&&this.operationProject!==p.id)return false;
   this.operationProject=p.id;
   this.userAborted=true;
   this.cancelling=true;
   p.online_cancel_error=false;
   this.pollGeneration=(this.pollGeneration||0)+1;
   this.progressId=null;this.repoGeneration++;this.repoPending=null;this.repoStartedAt=null;
   clearTimeout(this.progressTimer);clearTimeout(this.timer);
   if(this.activeController){try{this.activeController.abort();}catch{}}
   const pendingId=p?.online_pending_request?.id;
   const reportId=p?.online_report?.id;
   const reviewingNow=Boolean(pendingId||p?.online_report?.status==='reviewing'||(this.busy&&this.phase==='running'&&!p?.online_report?.execution));
   const execRunning=Boolean(p?.online_report?.execution&&['queued','starting','running','cancelling'].includes(p.online_report.execution.status));
   const executionRequest=p.online_execution_pending;
   const targetId=executionRequest?.id||(execRunning?reportId:(pendingId||reportId));
   if(p&&execRunning&&p.online_report?.execution){
    p.online_report={...p.online_report,execution:{...p.online_report.execution,status:'cancelling',notice:'正在等待执行器停止并清理环境。'}};
   }else if(p&&reviewingNow&&!p.online_report?.review){
    p.online_report={...(p.online_report||{id:targetId||uid().replaceAll('-',''),format:'articheck-online-assessment-v2',source:'model_api_review',scientific_validation:false,review:null,execution:null,execution_performed:false}),status:'cancelled',error:'user_cancelled',activity:[...(p.online_report?.activity||[]),{title:'审查已手动中止',roles:['reporter'],status:'failed',time:Date.now()/1000}]};
   }
   this.busy='';this.error='';this.liveReport=null;
   this.tab=p?.online_report?'process':'materials';
   this.renderNow();
   try{
    if(targetId&&(execRunning||reviewingNow||executionRequest)){
     const cancelled=checkAssessment(await this.request('/assessments/'+targetId+'/cancel',
      {...(executionRequest?{execution_request:true,retry_of:executionRequest.retry_of}:{}),
       ...(resumeTask===true?{terminate:true}:{})}));
     if(execRunning||executionRequest||!p.online_report?.review||p.online_report?.id===cancelled.id){
      p.online_report=cancelled;
      if(p.online_pending_request?.id===cancelled.id)p.online_input_key=p.online_pending_request.key;
     }
    }
    if(p.online_upload_pending?.id){
     await this.request('/uploads/'+p.online_upload_pending.id+'/cancel',{});
     p.online_upload_pending=null;
    }
    p.online_pending_request=null;p.online_execution_pending=null;
    await this.save(p);
    this.i.h.toast?.(p.online_report?.execution?.status==='cancelling'?'已请求中断，正在清理运行环境。':'已按请求中断运行。');
    return true;
   }catch(err){
    p.online_cancel_error=true;
    this.execNotice=err.message;
    await this.save(p);
    this.i.h.toast?.('中断未确认，可再次点击中断。',{tone:'error'});
    return false;
   }finally{
    this.userAborted=false;this.cancelling=false;this.busy='';this.phase='materials';
    this.operationProject=null;
    if(this.isViewing(p))this.tab=p?.online_report?'process':'materials';
    this.renderNow();
   }
   return;
  }
  if((this.busy||this.cancelling)&&action!=='export')return;
  if(action==='new')return this.new();
  if(action==='export'){
   const report=p.online_report,reviewed=criteriaDecisions(report,p).filter(row=>row.manuallyReviewed).map(row=>row.dimension);
   const {v:_review,x:_execution,...outcome}=reportOutcome(report,p,{stale:this.reportStale(report,p)});
   const exported={...report,verdict:reportVerdict(report,p),outcome,...(reviewed.length?{human_criteria_review:{source:'browser',passed_dimensions:reviewed}}:{})};
   if(!this.isSelfReview(report)){
    exported.review={...report.review,findings:report.review.findings.map(({suggestion,...finding})=>finding)};
    if(report.audit?.raw_findings)exported.audit={...report.audit,raw_findings:report.audit.raw_findings.map(({suggestion,...finding})=>finding)};
   }
   this.i.h.download('articheck-'+report.id+'.json',JSON.stringify(exported,null,2));
   return;
  }
  if(action==='local'){this.i.activeId=p?.id||this.i.activeId;return this.i.h.navigate?.('projects');}
  if(action==='resources'){await this.i.h.showResources?.();return;}
  if(action==='github')return this.github(true);
  const silentRefresh=action==='refresh-silent';
  if(silentRefresh)action='refresh';
  const startGen=this.pollGeneration||0;
  if(!silentRefresh){this.operationProject=p?.id;this.error='';this.execNotice='';}
  try{
   if(action==='submit'){
    if(p.online_report?.terminated_at)throw Error('本次审查已终止，请新建审查。');
    if(!this.isViewing(p))return;
     if(this.repoPending)await this.repoPending.promise;
    this.checkOperation(startGen);
    this.errors=validateInput(p,{token:this.token,consent:this.consent});
    if(!p.online_purpose)this.errors.purpose=true;
    if(Object.keys(this.errors).length){
     this.tab='materials';
     this.renderNow();
     const invalid=this.errors.purpose?document.querySelector('[data-online-purpose]'):this.errors.material?document.querySelector('#online-pdf'):document.querySelector('[aria-invalid="true"]')||document.querySelector('[data-online-consent]');
     invalid?.focus();invalid?.scrollIntoView({block:'center',behavior:'smooth'});return;
    }
    if(!this.isViewing(p))return;
    p.online_task=p.online_purpose?'auto':resumeTask||p.online_task||'auto';
    this.operationProject=p.id;this.phase='running';this.tab='process';this.activeRoleNode=null;
    this.busy='正在识别材料、阅读图表并核对公开资料…';this.renderNow();
    let value=await this.reviewOnce(p,startGen);
    if(value.status==='cancelled'||startGen!==(this.pollGeneration||0))return;
    if(!p.online_purpose&&value.review?.task==='reproduction'&&value.review.repository_hint&&!hasCode(p)){
     p.repo_url=value.review.repository_hint;
     this.busy='已找到代码来源线索，正在自动获取源码…';this.renderNow();
     await this.github(false,true,p);
     if(hasCode(p)&&startGen===(this.pollGeneration||0)){
      this.busy='正在结合代码补充审查与执行计划…';this.renderNow();
      value=await this.reviewOnce(p,startGen);
      if(value.status==='cancelled'||startGen!==(this.pollGeneration||0))return;
     }
    }
    this.consent=true;
    if(p.online_auto_execute!==false&&value.review?.plan.stages.length&&startGen===(this.pollGeneration||0)){
     if(this.isViewing(p))this.tab='process';
     try{
      await this.execute(p,{generation:startGen});
     }catch(execErr){
      if(startGen===(this.pollGeneration||0)){
       this.execNotice=execErr.message||'自动启动实验未完成，可在此手动点击“执行本次计划”重试。';
       this.error='';
      }
     }
    }else if(startGen===(this.pollGeneration||0)){
     await this.notifyFinished(p);
    }
   }else if(action==='execute'||action==='retry')await this.execute(p,{retry:action==='retry',generation:startGen});
   else if(['refresh','can-provide','unavailable'].includes(action)){
    if(!silentRefresh){this.busy='正在读取任务状态…';this.renderNow();}
    const suffix=action==='refresh'?'':'/feedback';
    const payload=action==='refresh'?undefined:{answer:action==='unavailable'?'unavailable':'can_provide'};
    const nextReport=checkAssessment(await this.request('/assessments/'+(action==='refresh'?(p.online_pending_request?.id||p.online_report?.id):p.online_report?.id)+suffix,payload));
    if(startGen!==(this.pollGeneration||0)||this.cancelling)return;
    p.online_report=nextReport;
    if(p.online_execution_pending&&nextReport.execution?.attempt_id&&nextReport.execution.attempt_id!==p.online_execution_pending.retry_of)p.online_execution_pending=null;
    if(p.online_pending_request?.id===p.online_report.id){p.online_input_key=p.online_pending_request.key;if(p.online_report.status!=='reviewing')p.online_pending_request=null;}
    await this.save(p);
    if(action==='refresh')await this.notifyFinished(p);
   }
  }catch(err){
   if(err.message==='已按请求中断运行。'||startGen!==(this.pollGeneration||0)||this.cancelling)return;
   if(silentRefresh)return;
   this.error=err.message;
   if(['upload_expired','upload_unavailable','upload_start_failed'].includes(err.code)){p.online_upload=null;p.online_upload_pending=null;await this.save(p);}
   if(action==='submit'&&p.online_pending_request){
    try{
     const polled=checkAssessment(await this.request('/assessments/'+p.online_pending_request.id));
     if(startGen!==(this.pollGeneration||0)||this.cancelling)return;
     if(!p.online_report?.review||p.online_report?.id===polled.id){
      p.online_report=polled;
      if(p.online_pending_request?.id===polled.id)p.online_input_key=p.online_pending_request.key;
     }
     await this.save(p);
     if(polled.status==='reviewing'&&this.isViewing(p)){this.error='';this.tab='process';}
     else if(polled.status==='completed'&&polled.review){p.online_pending_request=null;await this.save(p);this.error='';await this.notifyFinished(p);}
     else if(['failed','cancelled'].includes(polled.status)){p.online_pending_request=null;await this.save(p);if(this.isViewing(p)){this.error=polled.status==='cancelled'?'':failureText(polled);this.tab='process';}}
    }catch{}
   }
  }finally{if(!this.cancelling&&startGen===(this.pollGeneration||0)){this.busy='';this.phase='materials';this.operationProject=null;this.renderNow();}}
 }
 afterRender(){const reportId=document.querySelector('[data-report-conflicts]')?.dataset.reportConflicts;if(reportId&&this.conflictState?.id!==reportId)this.loadConflicts(reportId);clearTimeout(this.timer);clearTimeout(this.repoTicker);if(this.repoStartedAt){const tick=()=>{const sec=Math.floor((Date.now()-this.repoStartedAt)/1000),node=document.querySelector('[data-repo-elapsed]'),railNode=document.querySelector('[data-rail-repo-elapsed]');if(node)node.textContent='已等待 '+sec+' 秒';if(railNode)railNode.textContent=(this.repoState||'正在读取源码…')+' · 已等待 '+sec+' 秒';if(this.repoStartedAt)this.repoTicker=setTimeout(tick,1000);};tick();}if(!this.capabilities&&!this.pending){this.pending=true;this.request('/capabilities').then(v=>{this.capabilities=v;this.renderNow();}).catch(()=>{}).finally(()=>{this.pending=false;});}const pending=this.projects().filter(p=>!p.online_report?.terminated_at&&(['queued','running','starting','cancelling'].includes(p.online_report?.execution?.status)||p.online_report?.status==='reviewing'||p.online_pending_request||p.online_execution_pending));if(pending.length&&!this.busy&&!this.cancelling)this.timer=setTimeout(()=>{const index=(this.pollProjectIndex||0)%pending.length;this.pollProjectIndex=index+1;this.action('refresh-silent',pending[index]);},2500);}
 bind(){
  document.addEventListener('submit',event=>{if(event.target.id==='new-review-form'){event.preventDefault();if(event.target.reportValidity()){const form=new FormData(event.target);this.createProject(form.get('title'));}}});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){const p=this.current();if((['queued','running','starting','cancelling'].includes(p?.online_report?.execution?.status)||p?.online_report?.status==='reviewing'||p?.online_pending_request||p?.online_execution_pending)&&!this.busy)this.action('refresh-silent');}});
  document.addEventListener('click',event=>{
   const conflictAction=event.target.closest('[data-conflict-retry],[data-conflict-id]');
   if(conflictAction){
    const id=conflictAction.closest('[data-report-conflicts]').dataset.reportConflicts;
    this.loadConflicts(id,conflictAction.dataset.conflictId?{comparison_id:conflictAction.dataset.conflictId,decision:conflictAction.dataset.conflictDecision}:undefined);
    return;
   }
   const sidebarJump=event.target.closest('[data-sidebar-jump]');
   if(sidebarJump&&!event.target.closest('[data-online-tab]')){
    const pid=sidebarJump.dataset.sidebarJump;
    if(pid)this.selected=pid;
    const p=this.current(),r=this.viewReport(p);
    const running=Boolean((!this.operationProject||this.operationProject===p?.id)&&this.busy||r?.status==='reviewing'||['queued','starting','running','cancelling'].includes(r?.execution?.status));
    this.tab=running?'process':this.isInterruptedReport(r)?'process':r?.review?'report':r?'process':'materials';
    if(this.i.h.page?.()!=='api-review')this.i.h.navigate('api-review');
    else this.renderNow();
    return;
   }
   const roleBtn=event.target.closest('[data-role-jump]');
   if(roleBtn){this.jumpFromRole(roleBtn.dataset.roleJump);return;}
   const criterion=event.target.closest('[data-criterion-jump],[data-confirm-criterion],[data-supply-criterion]');
   if(criterion){
    event.preventDefault();
    if(criterion.dataset.confirmCriterion)this.confirmCriterion(criterion.dataset.confirmCriterion);
    else if(criterion.dataset.supplyCriterion)this.supplyCriterion(criterion.dataset.supplyCriterion);
    else{
     const detail=document.getElementById('criterion-'+criterion.dataset.criterionJump);
     detail?.focus({preventScroll:true});
     this.pulseSection(detail);
    }
    return;
   }
   const anchor=event.target.closest('[data-report-anchor]');
   if(anchor){
    const target=document.getElementById(anchor.dataset.reportAnchor);
    const details=target?.matches?.('details')?target:target?.closest('details[data-report-details],details[data-report-node],details[data-report-appendix]');
    const inner=target?.querySelector?.(':scope > details[data-report-node]');
    if(details)details.open=true;
    if(inner)inner.open=true;
    this.pulseSection(target);
    return;
   }

  });
  document.addEventListener('keydown',event=>{
   if(event.key!=='Enter'&&event.key!==' ')return;
   const sidebarJump=event.target.closest?.('[data-sidebar-jump]');
   if(sidebarJump&&!event.target.closest?.('[data-online-tab]')){
    event.preventDefault();
    sidebarJump.click();
    return;
   }
  });
  document.addEventListener('toggle',event=>{if(event.target.matches?.('.review-activity-log'))this.activityOpen=event.target.open;const key=event.target.dataset?.reportNode||event.target.dataset?.reportAppendix;if(key)this.nodeOpen.set(key,event.target.open);},true);
  document.addEventListener('change',event=>{if(event.target.matches('[data-metric-audience]')){this.metricAudience=event.target.value;this.renderNow();}});
  document.addEventListener('input',event=>{if(event.target.matches('[data-metric-query]')){this.metricQuery=event.target.value;clearTimeout(this.metricTimer);this.metricTimer=setTimeout(()=>{const position=document.querySelector('[data-metric-query]')?.selectionStart;this.renderNow();const input=document.querySelector('[data-metric-query]');input?.focus();if(position!=null)input?.setSelectionRange(position,position);},250);}});
  document.addEventListener('click',event=>{const source=event.target.closest('[data-online-page]');if(source){const p=this.current();if(!p.paper?.blob||p.paper.sha256!==p.online_report?.materials.paper){this.error='原 PDF 已变更或不在当前浏览器，请导入对应版本后查看。';this.renderNow();return;}const url=URL.createObjectURL(p.paper.blob);window.open(url+'#page='+Number(source.dataset.onlinePage),'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(url),60000);return;}const tab=event.target.closest('[data-online-tab]');if(tab){this.tab=tab.dataset.onlineTab;if(this.i.h.page?.()!=='api-review')this.i.h.navigate('api-review');else this.renderNow();return;}const action=event.target.closest('[data-online]');if(action)this.action(action.dataset.online);});
  document.addEventListener('change',event=>{
   if(!event.target.matches('[data-online-purpose]'))return;
   const project=this.current();
   if(!project)return;
   project.online_purpose=event.target.value;
   delete this.errors.purpose;
   document.querySelector('#review-purpose .online-field-error')?.remove();
   this.save(project);
  });
  document.addEventListener('change',event=>{const t=event.target;if(t.matches('[data-online-upload]')&&t.files[0])this.upload(t.dataset.onlineUpload,t.files[0]);if(t.matches('[data-online-project]')){this.selected=t.value;this.activeRoleNode=null;this.tab=this.current()?.online_report?.review?'report':'materials';this.repoGeneration++;this.error='';this.execNotice='';this.errors={};this.repoState='';this.consent=true;this.renderNow();}if(t.matches('[data-online-consent]'))this.consent=t.checked;if(t.matches('[data-online-field]')){const p=this.current(),key=t.dataset.onlineField;p[key]=t.type==='checkbox'?t.checked:t.value;if(key==='online_restrict'){if(!p[key])p.online_scope='';this.renderNow();}else{const dl=document.querySelector('#online-rail-dl');if(dl)dl.innerHTML=this.railRows(p);}this.save(p);}});
  document.addEventListener('input',event=>{const t=event.target;if(t.matches('[data-online-token]')){this.token=t.value;clearTimeout(this.repoTimer);if(this.current()?.repo_url)this.repoTimer=setTimeout(()=>this.github(),1800);}if(t.matches('[data-online-field]')){const p=this.current(),key=t.dataset.onlineField;if(t.type!=='radio'&&t.type!=='checkbox')p[key]=t.value;if(key==='repo_url'){if(p.repository?.kind==='github'&&p.repository.url!==t.value.trim())p.repository=null;this.repoGeneration++;clearTimeout(this.repoTimer);this.repoTimer=setTimeout(()=>this.github(),1800);}const dl=document.querySelector('#online-rail-dl');if(dl)dl.innerHTML=this.railRows(p);clearTimeout(this.inputSave);this.inputSave=setTimeout(()=>this.save(p),250);}});
 }
}
