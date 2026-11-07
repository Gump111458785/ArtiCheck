import {reportVerdict} from './report-verdict.mjs';
import {metricCatalog} from './metric-catalog.mjs';
import {activityView,activityEvents,ROLE_NAMES,visibleRoles} from './review-activity.mjs';
import {inspectZip} from './intake-core.mjs';
import {taskNames,typeNames,criterionNames,statusNames,executionNames,inputKey,validateInput,checkAssessment,coverageCounts,sessionCapability,metricUnit,hasCode} from './online-core.mjs';

async function encoded(blob){const bytes=new Uint8Array(await blob.arrayBuffer());let s='';for(let n=0;n<bytes.length;n+=32768)s+=String.fromCharCode(...bytes.subarray(n,n+32768));return btoa(s);}
const uid=()=>crypto.randomUUID();

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
  else{
   if(v.summary)contributions.push(v.summary);
   if(v.classification_reason&&v.classification_reason!==v.summary)contributions.push(v.classification_reason);
   if(v.metrics?.length){
    const datasets=[...new Set(v.metrics.map(m=>m.dataset).filter(Boolean))].slice(0,4);
    const models=[...new Set(v.metrics.filter(m=>m.author_method).map(m=>m.model).filter(Boolean))].slice(0,3);
    contributions.push(`围绕 ${models.join(' / ')||'作者提出的方法'} 在 ${datasets.join('、')||'论文核心数据集'} 上报告了 ${v.metrics.length} 项可溯源图表实验指标。`);
   }
  }
 }
 return {title,abstract,contributions:contributions.slice(0,5)};
}

export class OnlineWorkspace{
 constructor(intake){this.i=intake;this.selected=null;this.tab='materials';this.token='';this.consent=false;this.errors={};this.error='';this.execNotice='';this.busy='';this.capabilities=null;this.timer=null;this.repoTimer=null;this.repoGeneration=0;this.repoPending=null;this.repoState='';this.pending=false;this.liveReport=null;this.progressTimer=null;this.activeController=null;this.userAborted=false;this.metricAudience='all';this.metricQuery='';this.activityOpen=true;this.phase='materials';this.owner=null;try{this.owner=sessionCapability();}catch{this.error='浏览器存储不可用，暂时无法保存审查身份。请允许此网站使用本地存储。';}}
 esc(value){return this.i.esc(value??'');}
 projects(){return this.i.projects.filter(p=>(p.online_account||null)===(this.i.h.account?.()?.id||null));}
 current(){return this.projects().find(p=>p.id===this.selected)||null;}
 hasExecutionSection(r,p=this.current()){
  return Boolean(r?.materials?.code||hasCode(p)||r?.execution||r?.review?.plan?.stages?.length);
 }
 async new(){this.i.h.modal('新建审查',`<form id="new-review-form"><div class="online-field"><label for="review-project-name">项目名称</label><input id="review-project-name" name="title" maxlength="160" placeholder="例如：ResNet 图表与代码核查" required><small>项目名称用于记录、侧边栏和最终报告主标题。</small></div><button class="btn primary" type="submit">创建审查项目</button></form>`);document.querySelector('#review-project-name')?.focus();}
 async createProject(title){const p={id:uid(),online_account:this.i.h.account?.()?.id||null,title:title.trim(),created_at:new Date().toISOString(),paper:null,repository:null,claims:[],resources:{},online_task:'auto',online_scope:'',online_max_seconds:'',online_auto_execute:true};if(!p.title)return;this.i.projects.unshift(p);this.selected=p.id;this.i.activeId=p.id;this.tab='materials';this.phase='materials';this.error='';this.execNotice='';this.errors={};await this.i.save(p);this.i.h.closeModal();this.i.h.navigate('api-review');}
 materialFingerprint(p){return JSON.stringify([p.paper?.sha256,p.repository?.sha256]);}
 chooseTask(p){const e=v=>this.esc(v),notes={auto:'根据论文与代码自动确定适用检查，默认覆盖可识别内容。',self_review:'检查论文数字、图表、引用与论证的一致性，可仅提供 PDF。',reproduction:'核对论文与实现，自动准备并执行适用实验，比较目标指标。',code_review:'检查代码、依赖和运行条件，不要求提供论文。'};this.i.h.modal('选择本次审查需求',`<div class="review-choice"><p>材料已初步识别：${p.paper?e(p.paper.pages?.length||0)+' 页论文':''}${p.paper&&p.repository?'，':''}${p.repository?e(p.repository.files?.length||0)+' 个代码文件':''}。选择本次检查方式。</p>${Object.entries(taskNames).map(([key,label])=>`<button data-online-task="${key}"><strong>${label}</strong><span>${notes[key]}</span></button>`).join('')}</div>`);}
 sidebar(){const p=this.current();if(!p)return '';const r=this.liveReport||p.online_report,active=Boolean(this.busy||['reviewing'].includes(r?.status)||['queued','starting','running','cancelling'].includes(r?.execution?.status)),e=v=>this.esc(v);return `<section class="sidebar-review ${active?'active':''}"><strong>${e(p.title)}</strong><div class="sidebar-review-state" role="status">${active?'<span class="online-spinner" aria-hidden="true"></span>':''}<span class="review-live-stage">${e(active?this.busy||'正在执行审查':r?.review?'报告已就绪':'准备材料')}</span></div><dl>${p.paper?`<div><dt>论文</dt><dd title="${e(p.paper.name)}">${e(p.paper.name)}</dd></div>`:''}${p.repository?`<div><dt>代码</dt><dd title="${e(p.repository.name)}">${e(p.repository.name)}</dd></div>`:''}</dl>${r?.review&&!active?'<button data-online-tab="report">查看最终报告</button>':''}</section>`;}
 async notifyFinished(p){const r=p.online_report;if(!r?.review||['queued','starting','running','cancelling'].includes(r.execution?.status)||r.status==='reviewing')return;const key=r.id+':'+(r.execution?.attempt_id||'review');if(p.online_notified===key)return;p.online_notified=key;await this.save(p);this.i.h.toast('审查已结束，最终报告已生成。');if(!['process','execution','roles'].includes(this.tab))this.tab='report';}

 ensure(){if(!this.current()){this.selected=this.projects()[0]?.id;if(!this.selected)return null;}return this.current();}
 warn(key){return this.errors[key]?`<span class="online-field-error" role="alert">! ${this.esc(this.errors[key])}</span>`:'';}
 attrs(key){return this.errors[key]?'aria-invalid="true"':'';}
 render(){const p=this.ensure(),e=v=>this.esc(v);if(!p)return `<section class="online-empty"><h2>开始一项新的研究审查</h2><p>先为项目命名，再上传论文或代码。</p><button class="btn primary" data-online="new">新建审查</button></section>`;
 const r=this.liveReport||p.online_report,stale=p.online_report&&p.online_input_key!==inputKey(p),running=Boolean(this.busy&&this.phase==='running'||r?.status==='reviewing'||['queued','starting','running','cancelling'].includes(r?.execution?.status));
 const showExec=r?.review&&this.hasExecutionSection(r,p);
 const reportReady=Boolean(r?.review&&!running);
 const ended=Boolean(r&&!r.review&&['failed','cancelled'].includes(r.status)&&!running);
 const tab=this.tab==='materials'&&!running?'materials':this.tab==='report'&&reportReady?'report':(r||running?'process':'materials');
 return `<div class="online-workspace"><div class="online-toolbar"><label for="online-project">当前项目</label><select id="online-project" data-online-project ${this.busy?'disabled':''}>${this.projects().map(x=>`<option value="${e(x.id)}" ${x.id===p.id?'selected':''}>${e(x.title)}</option>`).join('')}</select><button class="btn online-new-review" data-online="new" ${this.busy?'disabled':''}>${this.i.h.icon('plus')}新建审查</button><button type="button" class="btn online-terminal-btn ${running?'live':''}" data-online="terminal" title="打开运行终端：执行命令与实时输出">${UI_SVG.terminal}<span>终端</span>${running?'<i class="terminal-live-dot" aria-hidden="true"></i>':''}</button></div>
 <nav class="online-tabs" aria-label="审查工作区">${[['materials',r?.review?'材料管理':'准备材料'],...(reportReady?[['report','最终报告']]:[]),['process',running?'审查进行中':'过程详情']].map(([id,label])=>`<button data-online-tab="${id}" class="${tab===id?'selected':''}" aria-current="${tab===id?'page':'false'}">${label}</button>`).join('')}</nav>
 ${this.error?`<div class="online-error" role="alert"><strong>本次操作未完成</strong><p>${e(this.error)}</p></div>`:''}${stale?'<p class="online-notice">当前材料与该报告的版本不同，请重新审查。旧版依据仍予保留。</p>':''}
 ${this.busy?`<div class="online-progress" role="status"><span class="online-spinner" aria-hidden="true"></span><strong>${e(this.busy)}</strong><button type="button" class="btn danger small online-abort-btn" data-online="cancel">${UI_SVG.stop}中断运行</button></div>`:''}
 ${tab==='materials'?this.materials(p):tab==='report'&&reportReady?this.finalReport(r,p):`<div id="online-activity">${activityView(r,e,{open:this.activityOpen})}</div>${reportReady?`<div class="process-ready-banner" role="status"><div><strong>审查报告已就绪</strong><span>可继续在当前页核对过程与阶段详情，或切换至完整报告视图。</span></div><button class="btn primary" data-online-tab="report">查看最终报告</button></div>`:''}${ended?this.endedCard(r):showExec?this.execution(r,stale):r?.review?'':`<section class="review-waiting"><h2 class="live-heading"><span class="live-heading-text">正在协作审查</span><span class="live-dots" aria-hidden="true"><i></i><i></i><i></i></span></h2><p>材料已提交。实际审阅、规划与执行状态在此持续更新，可随时中断。</p></section>`}`}</div>`;}

 endedCard(r){const e=v=>this.esc(v),cancelled=r.status==='cancelled';
  const reason=cancelled?'你已手动中止本次审查，已取得的活动记录保留；未生成最终报告。':failureText(r);
  return `<section class="review-ended ${cancelled?'cancelled':'failed'}" role="status"><div class="review-ended-icon" aria-hidden="true">${cancelled?UI_SVG.stop:UI_SVG.findings}</div><div><h2>${cancelled?'审查已中止':'本次审查未完成'}</h2><p>${e(reason)}</p><div class="review-ended-actions"><button class="btn primary" data-online="submit">重新审查</button><button class="btn" data-online-tab="materials">返回材料</button></div></div></section>`;}

 finalReport(r,p=this.current()){
  const e=v=>this.esc(v),v=reportVerdict(r),rv=r.review||{};
  const projectTitle=p?.title||r?.project_title||'未命名审查项目';
  const paperMeta=extractPaperMeta(r,p);
  return `<section id="report-top-section" class="report-priority-header"><div class="report-project-banner"><div><span class="online-kicker">${e(typeNames[rv.paper_type]||'研究审查')} · ${e(taskNames[rv.task]||'自动识别')}</span><h1 class="report-project-title">${e(projectTitle)}</h1></div><div class="report-header-actions"><button class="btn primary" data-online="export">导出完整报告</button><button class="btn" data-online-tab="process">查看过程详情</button></div></div>${paperMeta?`<div class="report-paper-overview"><article class="report-paper-card"><div class="report-card-tag">论文题目与摘要</div><h2 class="report-paper-title">${e(paperMeta.title)}</h2><p class="report-paper-abstract">${e(paperMeta.abstract)}</p></article><article class="report-paper-card contributions-card"><div class="report-card-tag">${UI_SVG.spark}论文创新点与核心贡献</div><ul class="report-contributions-list">${paperMeta.contributions.map((item,idx)=>`<li><span class="contrib-index">0${idx+1}</span><p>${e(item)}</p></li>`).join('')}</ul></article></div>`:''}</section><section class="review-verdict ${v.state}" role="status"><div><span>${e(v.scope)}</span><h2>${e(v.label)}</h2><p>${e(v.reason)}</p></div><div><button class="btn" data-online="export">导出完整报告</button><button class="btn text" data-online-tab="process">过程详情</button></div></section>${this.report(r,p)}${this.observations(r)}<section class="report-evidence">${this.evidence(r)}</section>`;
 }

 observations(r){const e=v=>this.esc(v),rows=r.execution?.metrics||[];return rows.length?`<section id="report-observations-section" class="report-observations"><div class="online-section-heading"><h2>论文目标与实际观测</h2><span>${rows.length} 项</span></div><div class="online-table-wrap"><table class="online-table metric-comparison"><colgroup><col style="width:28%"><col style="width:23%"><col style="width:23%"><col style="width:26%"></colgroup><thead><tr><th>指标</th><th class="number">论文值</th><th class="number">观测值</th><th>比较结果</th></tr></thead><tbody>${rows.map(m=>`<tr><td>${e(m.metric)}</td><td class="number">${e(m.expected)} ${e(m.unit)}</td><td class="number">${m.observed==null?'未观测':e(m.observed)+' '+e(m.unit)}</td><td><span class="online-status ${m.status==='outside_tolerance'?'missing':m.status==='within_tolerance'?'documented':'needs_review'}">${e({unobserved:'无可比较输出',within_tolerance:'数值在容差内',outside_tolerance:'超出容差'}[m.status]||m.status)}</span></td></tr>`).join('')}</tbody></table></div></section>`:'';}

 railRows(p){
  const e=v=>this.esc(v),hasGpu=Boolean(this.capabilities?.compute?.capacity?.gpu),paperBusy=this.busy.includes('论文'),codeBusy=Boolean(this.repoStartedAt||this.busy.includes('代码')||this.busy.includes('源码')),codeFail=this.repoState==='读取失败'&&!hasCode(p);
  const paper=paperBusy?`<span class="rail-badge running"><span class="online-spinner" aria-hidden="true"></span>正在解析</span><small>${e(this.busy)}</small>`:p.paper?`<span class="rail-badge ready">已导入 · ${e(p.paper.pages?.length||0)} 页</span><small title="${e(p.paper.name)}">${e(p.paper.name)}</small>`:`<span class="rail-badge empty">未提供</span><small>上传 PDF 后自动解析</small>`;
  const elapsed=this.repoStartedAt?Math.max(0,Math.floor((Date.now()-this.repoStartedAt)/1000)):0;
  const code=codeBusy?`<span class="rail-badge running"><span class="online-spinner" aria-hidden="true"></span>正在读取</span><small data-rail-repo-elapsed>${e(this.repoState||this.busy||'正在读取源码…')}${this.repoStartedAt?` · 已等待 ${elapsed} 秒`:''}</small>`:codeFail?`<span class="rail-badge failed">读取失败</span><small>${e(this.error||'请检查仓库地址或改传 ZIP')}</small>`:hasCode(p)?`<span class="rail-badge ready">源码已导入 · ${e(p.repository.files?.length||0)} 个文件</span><small title="${e(p.repository.name||p.repository.url||'')}">${e(p.repository.commit?'GitHub · '+p.repository.commit.slice(0,8):(p.repository.name||'ZIP 归档'))}</small>`:p.repo_url?.trim()?`<span class="rail-badge active">待读取仓库</span><small title="${e(p.repo_url)}">${e(p.repo_url)}</small>`:`<span class="rail-badge empty">未提供</span><small>支持 ZIP 或 GitHub 仓库</small>`;
  const scope=p.online_restrict?`<span class="rail-badge active">指定范围</span><small>${e(p.online_scope?.trim()||'请填写具体图表或指标范围')}</small>`:`<span class="rail-badge info">自动识别全部适用项</span><small>覆盖全部可识别图表指标</small>`;
  const exec=p.online_auto_execute!==false?`<span class="rail-badge ${hasGpu?'gpu':'info'}">${hasGpu?'云端 CPU / 自有 GPU':'云端 CPU'}</span><small>${hasGpu?'RTX 4090 · 在线下载复现后清理':'持续运行至完成 · 支持随时手动中断'}</small>`:`<span class="rail-badge empty">仅审查材料</span><small>不启动代码实验</small>`;
  return `<div><dt>论文</dt><dd>${paper}</dd></div><div><dt>代码</dt><dd>${code}</dd></div><div><dt>范围</dt><dd>${scope}</dd></div><div><dt>执行位置</dt><dd>${exec}</dd></div>`;
 }
 materials(p){const e=v=>this.esc(v),report=p.online_report,hasReport=Boolean(report?.review),repoText=this.repoState||(p.repository?.commit?'固定提交 '+p.repository.commit.slice(0,12):''),repoStatusClass=this.repoStartedAt?'loading':this.repoState==='读取失败'?'failed':repoText?'ready':'';
 const activeTask=p.online_task||'auto';
 return `<div class="online-intake-grid"><section class="online-form"><div class="online-section-heading"><h2>论文与代码</h2><span>至少提供一项</span></div>
 <div class="online-upload-pair"><label class="online-upload ${p.paper?'has-file':''}" for="online-pdf"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.pdf}</span><span>论文 PDF</span></div><strong>${e(p.paper?.name||'上传论文')}</strong><small>${p.paper?`${p.paper.pages?.length||0} 页 · 点击替换`:'用于图表指标、数据与论证自查'}</small><input id="online-pdf" type="file" accept=".pdf,application/pdf" data-online-upload="paper" ${this.busy?'disabled':''}></label>
 <label class="online-upload ${hasCode(p)?'has-file':''}" for="online-zip"><div class="upload-card-top"><span class="upload-icon">${UI_SVG.zip}</span><span>代码 ZIP</span></div><strong>${e(p.repository?.name||'上传代码')}</strong><small>${p.repository?`${p.repository.files?.length||0} 个文件 · 点击替换`:'最大 100 MB，也可填写 GitHub 地址'}</small><input id="online-zip" type="file" accept=".zip,application/zip" data-online-upload="code" ${this.busy?'disabled':''}></label></div>${this.warn('material')}
 <div class="online-field"><label for="online-repo"><span class="field-icon-inline">${UI_SVG.github}</span>公开 GitHub 仓库 <small>可选，填入后自动读取源码</small></label><div class="online-input-action"><input id="online-repo" type="url" data-online-field="repo_url" value="${e(p.repo_url||'')}" placeholder="https://github.com/作者/仓库" ${this.busy?'disabled':''}><button class="btn" data-online="github" ${this.busy?'disabled':''}>${this.repoState==='读取失败'?'重新读取':'读取'}</button></div><div class="online-repo-state ${repoStatusClass}" role="status" ${repoStatusClass?'':'hidden'}>${this.repoStartedAt?'<span class="online-spinner" aria-hidden="true"></span>':''}<strong>${e(repoText)}</strong>${this.repoStartedAt?'<span data-repo-elapsed>已等待 0 秒</span>':''}</div></div>
 <div class="review-mode-strip" role="group" aria-label="审查模式预设">${Object.entries(taskNames).map(([k,label])=>`<button type="button" class="mode-pill ${activeTask===k?'active':''}" data-online-preset="${k}" ${this.busy?'disabled':''}><strong>${label}</strong><span>${{auto:'智能匹配流程',self_review:'表文与逻辑核查',reproduction:'代码下载与复现',code_review:'实现与依赖检查'}[k]}</span></button>`).join('')}</div>
 ${p.online_report?.execution?.needs_user||p.online_report?.availability?`<div class="online-field"><label for="online-supply">补充数据、权重或获取线索</label><textarea id="online-supply" data-online-field="online_supply_notes" maxlength="3000" placeholder="填写公开数据 / 权重地址或补充说明；文件可放入代码 ZIP。不要填写账号密码或密钥。">${e(p.online_supply_notes||'')}</textarea><small>补充后重新审查，原执行与材料版本保留在历史记录中。</small></div>`:''}<section class="online-access"><label class="online-checkbox"><input type="checkbox" data-online-consent ${this.consent?'checked':''} ${this.busy?'disabled':''}>允许处理本次材料并发送相关内容至模型服务；大文件经临时隔离环境传输，执行开启时在云端运行代码。</label>${this.warn('consent')}<small>原始材料保存在浏览器；云端审查报告保留 7 天，可随时导出。</small><div class="online-submit"><button class="btn primary" data-online="submit" ${this.busy?'disabled':''}>${hasReport?'重新审查当前材料':'开始自动审查'}</button><button type="button" class="btn online-local-btn" data-online="local" ${this.busy?'disabled':''}>${UI_SVG.monitor}<span>在本地电脑执行</span></button>${hasReport?'<button class="btn" data-online-tab="report">查看上次报告</button>':''}</div></section></section>
 <aside class="online-rail"><div class="online-rail-head"><h2>本次审查</h2><span class="rail-live-tag ${this.busy||this.repoStartedAt?'updating':''}">${this.busy||this.repoStartedAt?'正在同步':'实时状态'}</span></div><dl id="online-rail-dl">${this.railRows(p)}</dl>${hasReport?'<button class="btn" data-online-tab="report">继续查看报告</button>':''}<details><summary>材料缺失时会怎样？</summary><p>先完成能做的审查。自动获取或执行确实受阻时，再请你补充。</p></details></aside></div>`;}

 report(r,p=this.current()){const e=v=>this.esc(v),v=r.review,c=coverageCounts(r),showExec=this.hasExecutionSection(r,p);
 return `<section class="online-summary"><div><span class="online-kicker">${e(typeNames[v.paper_type])} · ${e(taskNames[v.task])}</span><h2>${r.execution?e(executionNames[r.execution.status]||r.execution.status)+' · '+(r.execution.stages?.filter(s=>s.status==='completed').length||0)+' 个阶段已执行':e(v.paper_type==='unknown'?'材料识别结果':v.paper_type==='nonpaper'?'材料适用性说明':taskNames[v.task]+'报告')}</h2><p>${e(r.execution?(v.paper_type==='code_only'?'本次审查代码实现、依赖与运行流程；论文结论对齐不属于本次范围。':v.classification_reason):v.summary)}</p>${r.execution?`<details class="online-review-origin"><summary>材料审查时的判断</summary><p>${e(v.summary)}</p></details>`:''}</div><button class="btn" data-online="export">导出报告</button></section>
 ${r.audit?`<p class="online-notice">${r.audit.status==='completed'?'交叉复核保留 '+v.findings.length+' 条建议，撤回 '+r.audit.withdrawn+' 条依据不足的建议，补充 '+r.audit.additional_metrics+' 条图表指标。':'本次交叉复核未完成，模型建议仍需人工核对。'}</p>`:''}<div class="online-counts" role="navigation" aria-label="报告核心统计跳转"><div role="button" tabindex="0" class="online-count-card" data-report-jump="metrics" title="点击跳转到图表指标与出处"><div class="count-card-head"><span class="count-icon">${UI_SVG.metrics}</span><span>识别图表指标</span></div><strong>${c.identified}<small> 项</small></strong><small class="count-jump-hint">定位指标出处 ↘</small></div><div role="button" tabindex="0" class="online-count-card" data-report-jump="findings" title="点击跳转到问题与修正建议"><div class="count-card-head"><span class="count-icon">${UI_SVG.findings}</span><span>问题与建议</span></div><strong>${v.findings.length}<small> 项</small></strong><small class="count-jump-hint">查看问题清单 ↘</small></div><div role="button" tabindex="0" class="online-count-card" data-report-jump="observations" title="点击跳转到执行观测与实验结果"><div class="count-card-head"><span class="count-icon">${UI_SVG.observed}</span><span>执行观测指标</span></div><strong>${c.observed}<small> / ${c.identified}</small></strong><small class="count-jump-hint">${r.execution?.metrics?.length?'查看对比结果 ↘':showExec?'查看实验执行 ↘':'核对指标清单 ↘'}</small></div><div role="button" tabindex="0" class="online-count-card" data-report-jump="coverage" title="点击跳转到覆盖边界"><div class="count-card-head"><span class="count-icon">${UI_SVG.coverage}</span><span>覆盖缺口</span></div><strong>${c.gaps}<small> 项</small></strong><small class="count-jump-hint">查看覆盖边界 ↘</small></div></div>
 <section id="report-criteria-section" class="online-criteria"><div class="online-section-heading"><h2>${v.task==='self_review'?'论文自查条件':'八项审查条件'}</h2><span>材料依据与执行结论分开记录</span></div><div class="online-criteria-grid">${v.criteria.map(row=>`<details class="online-criterion ${e(row.status)}"><summary><strong>${e(criterionNames[row.dimension])}</strong><span class="online-status ${e(row.status)}">${e(statusNames[row.status])}</span></summary><p>${e(row.note)}</p>${this.citation(row)}</details>`).join('')}</div></section>
 <section id="report-findings-section" class="online-findings"><div class="online-section-heading"><h2>问题与修正建议</h2><span>${v.findings.length} 项</span></div>${v.findings.map((f,n)=>`<article><header><span class="online-issue-index">${String(n+1).padStart(2,'0')}</span><h3>${e(f.title)}</h3><span class="online-severity ${e(f.severity)}">${e({high:'优先处理',medium:'建议核对',low:'补充说明'}[f.severity])}</span></header><p>${e(f.detail)}</p><div class="online-suggestion"><strong>修正建议</strong><p>${e(f.suggestion)}</p></div>${f.audit_note?`<p class="online-audit-note"><strong>交叉复核</strong> ${e(f.audit_note)}</p>`:''}${this.citation(f)}</article>`).join('')||'<p class="online-notice">本次审查未列出问题建议，不等于论文结论已验证。</p>'}</section>
 ${r.audit?.withdrawn?`<details class="online-withdrawn"><summary>查看撤回的 ${r.audit.withdrawn} 条原建议</summary>${r.audit.reviews.filter(x=>x.decision==='remove').map(x=>`<article><h3>${e(r.audit.raw_findings[x.index].title)}</h3><p>${e(x.reason)}</p></article>`).join('')}</details>`:''}${r.execution?`<button class="btn" data-online-tab="execution">${e(executionNames[r.execution.status]||r.execution.status)} · 查看实际日志</button>`:showExec?`<div class="online-notice"><strong>执行计划</strong><p>${e(v.plan.purpose||v.plan.blocked_reason||'当前任务包含可执行阶段计划。')}</p><button class="btn text" data-online-tab="execution">查看计划与执行条件</button></div>`:''}`;}

 citation(row){return row.page||row.file?`<small class="online-citation">${row.page?'PDF 第 '+this.esc(row.page)+' 页':''}${row.page&&row.file?' · ':''}${this.esc(row.file||'')}</small>`:'';}
 execution(r,stale){const e=v=>this.esc(v),x=r.execution,p=r.review.plan,isRunning=['queued','starting','running','cancelling'].includes(x?.status);
 return `<section id="online-execution-section" class="online-execution-block"><section class="online-summary"><div><span class="online-kicker">${p.hardware==='GPU'?'自有 GPU 隔离执行':'隔离云端 CPU'} · 持续运行至完成（支持随时手动中断）</span><h2>${x?e(executionNames[x.status]||x.status):'执行计划'}</h2><p>${e(p.purpose||p.blocked_reason||'当前没有适用的执行计划。')}</p></div><div class="source-actions">${!x&&p.stages.length?`<button class="btn primary" data-online="execute" ${stale||this.busy?'disabled':''}>执行本次计划</button>`:''}${isRunning?`<button class="btn" data-online="refresh">刷新状态</button><button class="btn danger online-abort-btn" data-online="cancel" ${x?.status==='cancelling'?'disabled':''}>${UI_SVG.stop}${x?.status==='cancelling'?'正在停止…':'停止执行'}</button>`:''}${x?.attempt_id&&['failed','expired','cancelled'].includes(x.status)&&(r.execution_history?.length||0)<2?`<button class="btn" data-online="retry" ${stale||this.busy?'disabled':''}>重试执行</button>`:''}<button class="btn" data-online="export">导出报告</button></div></section>${this.execNotice?`<div class="online-notice warning-notice" role="status"><strong>实验自动启动提示：</strong>${e(this.execNotice)}</div>`:''}${x?.notice?`<p class="online-notice">${e(x.notice)}</p>`:''}${!p.stages.length?`<p class="online-notice">${e(p.blocked_reason||'材料不足以生成真实执行计划。可以先查看已完成的材料审查。')}</p>`:''}
 <div class="online-stage-list">${p.stages.map((s,n)=>{const a=x?.stages?.find(z=>z.id===s.id),state=a?.status||'planned';return `<details class="online-stage stage-${e(state)}" ${state==='failed'||state==='running'?'open':''}><summary><span class="online-issue-index">${n+1}</span><strong>${e(s.title)}</strong><span class="online-status status-${e(state)} ${state==='failed'?'missing':state==='completed'?'documented':state==='running'?'running':'needs_review'}">${e({planned:'计划中',running:'执行中',completed:'已执行',failed:'执行失败',skipped:'已跳过'}[state]||state)}</span></summary><p class="online-citation">来源 ${e(s.file)}${a?.exit_code!=null?' · 退出码 '+e(a.exit_code):''}</p><pre>${e(s.command)}</pre>${a?.output?`<h3>实际输出</h3><pre class="online-output">${e(a.output)}</pre>${a.output_truncated?'<small>输出已截断，未显示部分不参与当前指标提取。</small>':''}`:''}${a?.reason?`<p>${e(a.reason)}</p>`:''}</details>`;}).join('')}</div>
 ${!x&&r.review.resource_preflight?.needs_user?`<section class="online-blocker"><h3>当前云端计算条件不足</h3><p>${e(r.review.resource_preflight.reason)}</p><p>本次评估资源：${e(r.review.resource_preflight.capacity?.cpu_count||2)} vCPU、${e(r.review.resource_preflight.capacity?.memory_mb||512)} MB 内存${r.review.resource_preflight.capacity?.gpu?'，含 GPU':'，无 GPU'}；需求来自材料分析，本次未启动实验。</p>${r.availability?`<strong>${e(r.availability.verdict)}</strong>`:'<div class="online-blocker-actions"><button class="btn" data-online="can-provide">可提供所需资源</button><button class="btn" data-online="unavailable">确认无法提供</button></div>'}<div class="online-blocker-route"><span>也可以切换执行位置</span><button class="btn" data-online="local">使用本地环境</button><button class="btn text" data-online="resources">查看云端资源配置</button></div></section>`:''}${!x&&r.review.task==='reproduction'&&!r.materials.code?`<section class="online-blocker"><h3>需要补充代码来源</h3><p>${e(r.source_discovery?.reason||'自动分析未能取得可执行源码，请补充 GitHub 地址或代码 ZIP。')}</p>${r.availability?`<strong>${e(r.availability.verdict)}</strong><button class="btn" data-online-tab="materials">补充材料</button>`:'<button class="btn" data-online="can-provide">可以补充</button><button class="btn" data-online="unavailable">确认无法获取</button>'}</section>`:''}${x?.needs_user?`<section class="online-blocker"><h3>需要补充材料</h3><p>${e(x.question)}</p>${x.user_answer?`<strong>${e(x.availability_verdict)}</strong>${x.user_answer==='can_provide'?'<button class="btn" data-online-tab="materials">补充材料</button>':''}`:'<button class="btn" data-online="can-provide">可以补充</button><button class="btn" data-online="unavailable">确认无法提供</button>'}</section>`:''}
 ${x?.environment?`<p class="online-footnote">实际实例：${e(x.environment.cpu_count)} vCPU · ${e(x.environment.memory_mb)} MB 内存 · ${e(x.environment.gpu_name||x.environment.template_id||'已验证执行环境')}${x.runtime?' · Python '+e(x.runtime.python):''}${x.elapsed_seconds!=null?' · 执行 '+e(x.elapsed_seconds)+' 秒':''}</p>`:''}<p class="online-footnote">日志和数值来自本次代码执行。进程成功、数值吻合与论文主要结论成立分别判断；本页不自动将主要结论标记为通过。</p></section>`;}

 evidence(r){
  const e=v=>this.esc(v),v=r.review;
  return `<section id="report-metrics-section" class="report-metrics-anchor"><div class="online-section-heading"><h2>图表指标与出处</h2><span>作者方法优先 · ${v.metrics.length} 项</span></div>
   ${this.metricEvidence(v.metrics)}</section>
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
  try{const value=checkAssessment(await this.request('/assessments/'+id));if(this.current()?.id!==p.id||this.progressId!==id)return;this.liveReport=value;const region=document.querySelector('#online-activity');if(region)region.innerHTML=activityView(value,v=>this.esc(v),{open:this.activityOpen});const sidebar=document.querySelector('#sidebar-review');if(sidebar)sidebar.innerHTML=this.sidebar();const waiting=document.querySelector('.online-progress');if(waiting)waiting.hidden=Boolean(value.activity?.length);}catch{} // A not-yet-claimed request is normal while parsing.
 }
 roles(r){const e=v=>this.esc(v),events=activityEvents(r).map(x=>({...x,kind:x.kind||x.title,stage:x.stage||x.detail,role:x.role||x.roles?.[0]})),roles=[['literature_reader','文献审阅','模型 API 识别材料类型、图表和引用。'],['code_inspector','代码检查','模型 API 阅读提供的源文件和依赖。'],['planner','计划编排','模型 API 生成计划；执行器按冻结计划排程。'],['experiment_runner','实验执行','隔离环境运行实际命令。'],['cross_auditor','交叉核查','校验出处、阶段退出码和数值比较。'],['reporter','报告整理','汇总审查建议、执行状态与覆盖缺口。']];return `<section class="online-roles"><h2>角色职责与记录</h2><p class="online-footnote">文献与代码审查由同一次模型请求处理；角色名称表示工作流职责。</p>${roles.map(([id,name,note])=>{const rows=events.filter(v=>(v.roles||[v.role]).includes(id));return `<details><summary><strong>${name}</strong><span>${rows.length?rows.length+' 条执行事件':id==='literature_reader'&&!r.materials.paper?'未提供论文':id==='code_inspector'&&!r.materials.code?'未提供代码':id==='literature_reader'||id==='code_inspector'?'模型审查已返回':id==='planner'&&r.review.plan.stages.length?'已生成计划':'尚无执行事件'}</span></summary><p>${note}</p>${rows.map(row=>`<div class="online-role-event"><code>${e(row.kind)}</code><span>${e(row.stage||row.status||row.reason||row.policy||'')}</span></div>`).join('')}</details>`;}).join('')}${events.length?`<section class="online-role-stream"><h3>最近执行事件</h3>${events.slice(-6).map(row=>`<div class="online-role-event"><span>${e({planner:'计划编排',experiment_runner:'实验执行',cross_auditor:'交叉核查',reporter:'报告整理'}[row.role]||row.role)}</span><strong>${e({plan_scheduled:'按冻结计划排程',stage_started:'开始执行',stage_finished:'执行结束',stage_checked:'核对阶段结果',execution_checked:'汇总执行证据',report_written:'写入报告',stopped:'结束排程'}[row.kind]||row.kind)}</strong><span>${e(r.review.plan.stages.find(s=>s.id===row.stage)?.title||row.status||row.reason||'')}</span></div>`).join('')}</section>`:''}</section>`;}
 async request(path,payload){if(!this.owner)throw Error('浏览器存储不可用，无法提交。');const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),115000);this.activeController=controller;try{const response=await fetch('/v1'+path,{method:payload===undefined?'GET':'POST',headers:{'X-ArtiCheck-Client':'review-api','X-ArtiCheck-Session':this.owner,...(payload===undefined?{}:{'Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify(payload),signal:controller.signal,credentials:'same-origin',redirect:'error'});let value;try{value=await response.json();}catch{throw Error('服务暂时没有返回有效响应，请稍后重试。');}if(!response.ok){if(response.status===401&&typeof location!=='undefined')location.assign('./login.html?next='+encodeURIComponent(location.pathname+location.hash));const error=Error(value.error?.message||'请求失败。');error.code=value.error?.code;throw error;}return value;}catch(err){if(err.name==='AbortError'){if(this.userAborted)throw Error('已按请求中断运行。');throw Error('等待服务返回超时，请刷新已有任务；不要连续重复提交。');}throw err;}finally{clearTimeout(timer);if(this.activeController===controller)this.activeController=null;}}
 async payload(p){
  const body={task:p.online_task||'auto',scope:p.online_restrict?p.online_scope:'',max_seconds:null,supplement:p.online_supply_notes||''};
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
     for(const [kind,m] of files){
      this.busy='正在传输 '+m.name+' · '+(m.blob.size/1024/1024).toFixed(1)+' MB';this.renderNow();
      const target=new URL(value.files[kind].upload_url);
      if(target.protocol!=='https:'||!['.e2b.app','.e2b.dev'].some(suffix=>target.hostname.endsWith(suffix)))throw Error('大文件传输地址无效。');
      const form=new FormData();form.append('file',m.blob,m.name);
      const response=await fetch(target.href,{method:'POST',body:form,credentials:'omit',redirect:'error',signal:AbortSignal.timeout(Math.max(1000,value.expires_at*1000-Date.now()-10000))});
      if(!response.ok)throw Error('大文件传输未完成，请重新提交；文件仍保存在当前浏览器。');
     }
     transfer={key,id:value.id,expires_at:value.expires_at,materials:Object.fromEntries(Object.entries(value.files).map(([kind,item])=>[kind,item.material]))};
     p.online_upload=transfer;p.online_upload_pending=null;await this.save(p);
    }finally{this.busy=previous;this.renderNow();}
   }
   Object.assign(body,transfer.materials);
  }else for(const [kind,m] of files)body[kind]={name:m.name,content_base64:await encoded(m.blob)};
  if(new TextEncoder().encode(JSON.stringify(body)).length>5_000_000)throw Error('材料描述过大，请缩短补充说明后重新提交。');
  return body;
 }
 async save(p){await this.i.save(p);}
 renderNow(){if(this.i.h.page?.()!=='api-review'&&this.i.h.refreshReviewSidebar){this.i.h.refreshReviewSidebar();this.afterRender();}else this.i.h.render();}
 async upload(kind,file){if(this.busy)return;const p=this.current();this.i.activeId=p.id;this.busy=kind==='paper'?'正在解析论文…':'正在读取代码…';this.renderNow();try{await this.i.upload(kind,file);if(this.i.error)throw Error(this.i.error);p.claims=[];if(!p.title)p.title=file.name.replace(/\.(pdf|zip)$/i,'');if(!p.online_task)p.online_task='auto';this.errors={};if(kind==='paper'&&!hasCode(p)&&!p.repo_url){const links=[...new Set((p.paper?.pages||[]).flatMap(v=>v.links||[]).map(u=>u.replace(/^http:/,'https:')).filter(u=>/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(u)))];if(links.length===1){p.repo_url=links[0];this.repoState='从论文发现代码链接';}}await this.save(p);}catch(err){this.error=err.message;}finally{this.busy='';this.renderNow();if(kind==='paper'&&p.repo_url&&!hasCode(p))this.github();}}
 async github(force=false,internal=false){const p=this.current(),url=p?.repo_url?.trim();if(!url)return;if(!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+(?:\.git)?\/?(?:\?[^#]*)?$/.test(url)){this.error='请填写 GitHub 仓库首页地址。';this.renderNow();return;}if(!force&&hasCode(p)&&p.repository.url===url){this.repoState='已读取固定提交 '+p.repository.commit?.slice(0,12);return;}if(this.repoPending?.url===url)return this.repoPending.promise;if(this.busy&&!internal)return;const generation=++this.repoGeneration;this.repoState='正在定位版本并读取源码…';this.repoStartedAt=Date.now();this.error='';this.renderNow();const promise=(async()=>{try{const value=await this.request('/repositories',{url,refresh:force,...(internal?{assessment_id:p.online_report.id}:{})});if(generation!==this.repoGeneration||p!==this.current()||url!==p.repo_url.trim())return;if(value.assessment)p.online_report=checkAssessment(value.assessment);let source;if(value.material.content_base64){const bytes=Uint8Array.from(atob(value.material.content_base64),c=>c.charCodeAt(0));source={...inspectZip(bytes.buffer),blob:new Blob([bytes],{type:'application/zip'}),size:bytes.byteLength};}else source={remote:value.material,files:value.files,size:value.material.bytes};p.repository={...source,kind:'github',url:value.url,commit:value.commit,name:value.material.name,sha256:value.sha256,fetched_at:value.fetched_at,cached_reference:value.cached_reference};p.claims=[];if(!p.title)p.title=value.name;this.repoState=`源码已读取 · ${value.commit.slice(0,12)}`;await this.save(p);}catch(err){if(generation===this.repoGeneration){this.repoState='读取失败';this.error=err.message;}}finally{if(generation===this.repoGeneration){this.repoPending=null;this.repoStartedAt=null;this.renderNow();}}})();this.repoPending={url,promise};return promise;}
 async execute(p,{retry=false}={}){const r=p.online_report;if(!r?.review)throw Error('请先等待材料审查完成。');if(p.online_input_key!==inputKey(p))throw Error('材料或范围已变化，请重新审查。');if(!hasCode(p))throw Error('请补充代码源码。');this.busy='正在创建云端执行环境…';this.execNotice='';this.renderNow();const body=await this.payload(p);const value=checkAssessment(await this.request('/assessments/'+r.id+'/execute',{code:body.code,plan_sha256:r.review.plan_sha256,...(retry?{retry_of:r.execution.attempt_id}:{})}));p.online_report=value;await this.save(p);this.tab='process';}
 async reviewOnce(p){
  const key=inputKey(p);
  if(!p.online_pending_request||p.online_pending_request.key!==key)p.online_pending_request={key,id:uid().replaceAll('-','')};
  await this.save(p);
  const payload={...await this.payload(p),request_id:p.online_pending_request.id};
  this.liveReport=null;this.progressId=payload.request_id;let value;
  let watching=true;const tick=async()=>{await this.pollProgress(p,payload.request_id);if(watching)this.progressTimer=setTimeout(tick,2500);};
  this.progressTimer=setTimeout(tick,1500);
  try{value=checkAssessment(await this.request('/assessments',payload));}
  finally{watching=false;this.progressId=null;clearTimeout(this.progressTimer);this.liveReport=null;}

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
  const p=this.current(),r=this.liveReport||p?.online_report;
  if(!r)return;
  if(roleId==='reporter'){
   if(r.review){this.tab='report';this.renderNow();setTimeout(()=>this.pulseSection(document.querySelector('#report-top-section')),40);}
   return;
  }
  if(roleId==='planner'||roleId==='experiment_runner'){
   if(this.hasExecutionSection(r,p)){
    if(this.tab!=='process'){this.tab='process';this.renderNow();}
    setTimeout(()=>this.pulseSection(document.querySelector('#online-execution-section')),40);
    return;
   }
  }
  if(this.tab!=='process'){this.tab='process';this.renderNow();}
  this.activityOpen=true;
  const details=document.querySelector('.review-activity-log');
  if(details)details.open=true;
  const eventTarget=document.querySelector(`[data-event-roles*="${roleId}"]`)||document.querySelector(`[data-activity-roles*="${roleId}"]`)||document.querySelector('.review-activity-log');
  this.pulseSection(eventTarget);
 }
 jumpFromCount(targetKey){
  const p=this.current(),r=this.liveReport||p?.online_report;
  if(!r?.review)return;
  if(targetKey==='observations'){
   const obs=document.querySelector('#report-observations-section');
   if(obs){this.pulseSection(obs);return;}
   if(this.hasExecutionSection(r,p)){
    this.tab='process';this.renderNow();
    setTimeout(()=>this.pulseSection(document.querySelector('#online-execution-section')),40);
    return;
   }
   this.pulseSection(document.querySelector('#report-metrics-section'));
   return;
  }
  const map={metrics:'#report-metrics-section',findings:'#report-findings-section',coverage:'#report-coverage-section'};
  const node=document.querySelector(map[targetKey]);
  if(node)this.pulseSection(node);
 }
 async action(action){
  const p=this.current();
  if(action==='terminal'){
   this.tab='process';
   this.activityOpen=true;
   this.renderNow();
   setTimeout(()=>{
    const details=document.querySelector('.review-activity-log');
    if(details)details.open=true;
    const target=document.querySelector('#online-execution-section .online-output')||document.querySelector('#online-execution-section .online-stage-list')||document.querySelector('#online-execution-section')||document.querySelector('.review-activity-log')||document.querySelector('#online-activity');
    if(target)this.pulseSection(target);
   },40);
   return;
  }
  if(action==='cancel'){
   this.userAborted=true;
   clearTimeout(this.progressTimer);clearTimeout(this.timer);
   if(this.activeController){try{this.activeController.abort();}catch{}}
   const pendingId=p?.online_pending_request?.id;
   const reportId=p?.online_report?.id;
   const reviewingNow=Boolean(pendingId||p?.online_report?.status==='reviewing'||(this.busy&&this.phase==='running'&&!p?.online_report?.execution));
   const execRunning=Boolean(p?.online_report?.execution&&['queued','starting','running','cancelling'].includes(p.online_report.execution.status));
   const targetId=execRunning?reportId:(pendingId||reportId);
   this.busy='正在停止执行…';this.error='';this.renderNow();
   try{
    if(targetId&&(execRunning||reviewingNow)){
     const cancelled=checkAssessment(await this.request('/assessments/'+targetId+'/cancel',{}));
     if(execRunning||!p.online_report?.review||p.online_report?.id===cancelled.id){
      p.online_report=cancelled;
     }
    }
    if(p){
     p.online_pending_request=null;
     await this.save(p);
    }
    this.liveReport=null;
    this.i.h.toast?.('已按请求中断运行。');
   }catch(err){
    if(p){p.online_pending_request=null;await this.save(p);}
    this.liveReport=null;
    if(err.message!=='已按请求中断运行。')this.execNotice=err.message;
   }finally{
    this.userAborted=false;this.busy='';this.phase='materials';
    this.tab=p?.online_report?'process':'materials';
    this.renderNow();
   }
   return;
  }
  if(this.busy)return;
  if(action==='new')return this.new();
  if(action==='export'){this.i.h.download('articheck-'+p.online_report.id+'.json',JSON.stringify(p.online_report,null,2));return;}
  if(action==='local'){this.i.activeId=p.id;return this.i.open(p.id,'readiness');}
  if(action==='resources'){await this.i.h.showResources?.();return;}
  if(action==='github')return this.github(true);
  this.error='';this.execNotice='';
  try{
   if(action==='submit'){
    if(this.repoPending)await this.repoPending.promise;
    this.errors=validateInput(p,{token:this.token,consent:this.consent});
    if(Object.keys(this.errors).length){
     this.tab='materials';
     this.renderNow();
     const invalid=this.errors.material?document.querySelector('#online-pdf'):document.querySelector('[aria-invalid="true"]')||document.querySelector('[data-online-consent]');
     invalid?.focus();invalid?.scrollIntoView({block:'center',behavior:'smooth'});return;
    }
    if(this.taskConfirmed!==this.materialFingerprint(p)){this.chooseTask(p);return;}
    this.phase='running';this.tab='process';
    this.busy='正在识别材料、阅读图表并核对公开资料…';this.renderNow();
    let value=await this.reviewOnce(p);
    if(value.status==='cancelled'){this.error='';return;}
    if(value.review?.task==='reproduction'&&value.review.repository_hint&&!hasCode(p)){
     p.repo_url=value.review.repository_hint;
     this.busy='已找到代码来源线索，正在自动获取源码…';this.renderNow();
     await this.github(false,true);
     if(hasCode(p)){
      this.busy='正在结合代码补充审查与执行计划…';this.renderNow();
      value=await this.reviewOnce(p);
      if(value.status==='cancelled'){this.error='';return;}
     }
    }
    this.consent=false;
    if(p.online_auto_execute!==false&&value.review?.plan.stages.length){
     this.tab='process';
     try{
      await this.execute(p);
     }catch(execErr){
      this.execNotice=execErr.message||'自动启动实验未完成，可在此手动点击“执行本次计划”重试。';
      this.error='';
     }
    }else{
     await this.notifyFinished(p);
    }
   }else if(action==='execute'||action==='retry')await this.execute(p,{retry:action==='retry'});
   else if(['refresh','can-provide','unavailable'].includes(action)){
    this.busy='正在读取任务状态…';this.renderNow();
    const suffix=action==='refresh'?'':'/feedback';
    const payload=action==='refresh'?undefined:{answer:action==='unavailable'?'unavailable':'can_provide'};
    p.online_report=checkAssessment(await this.request('/assessments/'+(p.online_report?.id||p.online_pending_request?.id)+suffix,payload));
    if(p.online_pending_request?.id===p.online_report.id){p.online_input_key=p.online_pending_request.key;if(p.online_report.status!=='reviewing')p.online_pending_request=null;}
    await this.save(p);
    if(action==='refresh')await this.notifyFinished(p);
   }
  }catch(err){
   if(err.message==='已按请求中断运行。'){this.error='';return;}
   this.error=err.message;
   if(['upload_expired','upload_unavailable','upload_start_failed'].includes(err.code)){p.online_upload=null;p.online_upload_pending=null;await this.save(p);}
   if(action==='submit'&&p.online_pending_request){
    try{
     const polled=checkAssessment(await this.request('/assessments/'+p.online_pending_request.id));
     if(!p.online_report?.review||p.online_report?.id===polled.id)p.online_report=polled;
     await this.save(p);
     if(polled.status==='reviewing'){this.error='';this.tab='process';}
     else if(polled.status==='completed'&&polled.review){p.online_pending_request=null;await this.save(p);this.error='';await this.notifyFinished(p);}
     else if(['failed','cancelled'].includes(polled.status)){p.online_pending_request=null;await this.save(p);this.error=polled.status==='cancelled'?'':failureText(polled);this.tab='process';}
    }catch{}
   }
  }finally{this.busy='';this.phase='materials';this.renderNow();}
 }
 afterRender(){clearTimeout(this.timer);clearTimeout(this.repoTicker);if(this.repoStartedAt){const tick=()=>{const sec=Math.floor((Date.now()-this.repoStartedAt)/1000),node=document.querySelector('[data-repo-elapsed]'),railNode=document.querySelector('[data-rail-repo-elapsed]');if(node)node.textContent='已等待 '+sec+' 秒';if(railNode)railNode.textContent=(this.repoState||'正在读取源码…')+' · 已等待 '+sec+' 秒';if(this.repoStartedAt)this.repoTicker=setTimeout(tick,1000);};tick();}if(!this.capabilities&&!this.pending){this.pending=true;this.request('/capabilities').then(v=>{this.capabilities=v;this.renderNow();}).catch(()=>{}).finally(()=>{this.pending=false;});}const p=this.current();if((['queued','running','starting','cancelling'].includes(p?.online_report?.execution?.status)||p?.online_report?.status==='reviewing'||p?.online_pending_request&&!p?.online_report)&&!this.busy&&!this.error)this.timer=setTimeout(()=>this.action('refresh'),3000);}
 bind(){
  document.addEventListener('submit',event=>{if(event.target.id!=='new-review-form')return;event.preventDefault();if(event.target.reportValidity())this.createProject(new FormData(event.target).get('title'));});
  document.addEventListener('click',event=>{
   const preset=event.target.closest('[data-online-preset]');
   if(preset){const p=this.current();if(!p)return;p.online_task=preset.dataset.onlinePreset;this.taskConfirmed=this.materialFingerprint(p);this.save(p);this.renderNow();return;}
   const roleBtn=event.target.closest('[data-role-jump]');
   if(roleBtn){this.jumpFromRole(roleBtn.dataset.roleJump);return;}
   const countBtn=event.target.closest('[data-report-jump]');
   if(countBtn){this.jumpFromCount(countBtn.dataset.reportJump);return;}
   const choice=event.target.closest('[data-online-task]');
   if(!choice)return;
   const p=this.current();p.online_task=choice.dataset.onlineTask;this.taskConfirmed=this.materialFingerprint(p);this.i.h.closeModal();this.action('submit');
  });
  document.addEventListener('keydown',event=>{
   if(event.key!=='Enter'&&event.key!==' ')return;
   const countBtn=event.target.closest?.('[data-report-jump]');
   if(countBtn){event.preventDefault();this.jumpFromCount(countBtn.dataset.reportJump);}
  });
  document.addEventListener('toggle',event=>{if(event.target.matches?.('.review-activity-log'))this.activityOpen=event.target.open;},true);
  document.addEventListener('change',event=>{if(event.target.matches('[data-metric-audience]')){this.metricAudience=event.target.value;this.renderNow();}});
  document.addEventListener('input',event=>{if(event.target.matches('[data-metric-query]')){this.metricQuery=event.target.value;clearTimeout(this.metricTimer);this.metricTimer=setTimeout(()=>{const position=document.querySelector('[data-metric-query]')?.selectionStart;this.renderNow();const input=document.querySelector('[data-metric-query]');input?.focus();if(position!=null)input?.setSelectionRange(position,position);},250);}});
  document.addEventListener('click',event=>{const source=event.target.closest('[data-online-page]');if(source){const p=this.current();if(!p.paper?.blob||p.paper.sha256!==p.online_report?.materials.paper){this.error='原 PDF 已变更或不在当前浏览器，请导入对应版本后查看。';this.renderNow();return;}const url=URL.createObjectURL(p.paper.blob);window.open(url+'#page='+Number(source.dataset.onlinePage),'_blank','noopener');setTimeout(()=>URL.revokeObjectURL(url),60000);return;}const tab=event.target.closest('[data-online-tab]');if(tab){this.tab=tab.dataset.onlineTab;this.renderNow();return;}const action=event.target.closest('[data-online]');if(action)this.action(action.dataset.online);});
  document.addEventListener('change',event=>{const t=event.target;if(t.matches('[data-online-upload]')&&t.files[0])this.upload(t.dataset.onlineUpload,t.files[0]);if(t.matches('[data-online-project]')){this.selected=t.value;this.tab=this.current()?.online_report?.review?'report':'materials';this.repoGeneration++;this.error='';this.execNotice='';this.errors={};this.repoState='';this.consent=false;this.renderNow();}if(t.matches('[data-online-consent]'))this.consent=t.checked;if(t.matches('[data-online-field]')){const p=this.current(),key=t.dataset.onlineField;p[key]=t.type==='checkbox'?t.checked:t.value;if(key==='online_restrict'){if(!p[key])p.online_scope='';this.renderNow();}else{const dl=document.querySelector('#online-rail-dl');if(dl)dl.innerHTML=this.railRows(p);}this.save(p);}});
  document.addEventListener('input',event=>{const t=event.target;if(t.matches('[data-online-token]')){this.token=t.value;clearTimeout(this.repoTimer);if(this.current()?.repo_url)this.repoTimer=setTimeout(()=>this.github(),1800);}if(t.matches('[data-online-field]')){const p=this.current(),key=t.dataset.onlineField;if(t.type!=='radio'&&t.type!=='checkbox')p[key]=t.value;if(key==='repo_url'){if(p.repository?.kind==='github'&&p.repository.url!==t.value.trim())p.repository=null;this.repoGeneration++;clearTimeout(this.repoTimer);this.repoTimer=setTimeout(()=>this.github(),1800);}const dl=document.querySelector('#online-rail-dl');if(dl)dl.innerHTML=this.railRows(p);clearTimeout(this.inputSave);this.inputSave=setTimeout(()=>this.save(p),250);}});
 }
}
