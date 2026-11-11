import {ROLES,kindLabels,sourceLabels,statusLabels,executionRecords,filterRecords,recordCounts,progressText,roleEvents,rolePayload,roleState,fullRoleRun} from './execution-core.mjs';
import {validateReproductionReport} from './reproduction-core.mjs';
import {reportVerdict} from './report-verdict.mjs';
import {hasCode,taskNames} from './online-core.mjs';

const date=value=>value?value.slice(0,16).replace('T',' '):'未记录时间';
const archiveStates={draft:'待启动',reviewing:'正在审阅',queued:'执行中',reproducing:'正在复现',cancelling:'正在中断',waiting:'等待资源',interrupted:'已中断',completed:'已完成',terminated:'已终止'};
const archiveInProgress=new Set(['reviewing','queued','reproducing','cancelling']);
const archiveExecutionFilters={in_progress:'审查中',...Object.fromEntries(Object.entries(archiveStates).filter(([key])=>key!=='terminated'&&!archiveInProgress.has(key)))};
const matchesStatus=(item,key)=>key==='in_progress'?archiveInProgress.has(item.statusKey):item.statusKey===key;
const archiveVerdicts={unassessed:'待验收',passed:'通过',issues:'发现问题',failed:'未通过',inapplicable:'不适用'};
const archiveMaterials={paper_only:'仅论文',code_only:'仅代码',both:'论文与代码',none:'待提交材料'};
const tabsFor=kind=>kind==='full'?[['overview','任务概览'],['roles','角色协作'],['trace','阶段与输出'],['evidence','证据复核'],['report','完整报告']]:[['overview','任务概览'],['roles','角色协作'],['trace','执行事件'],['evidence','证据复核']];

export class ExecutionCenter {
 constructor(hooks){
  this.h=hooks;
  this.filters={query:'',kind:'all',source:'all',status:'all',project:'all'};
  this.orderFilter='all';
  this.archiveFilters={
   projectName:'',
   paperName:'',
   codeName:'',
   verdict:'all',
   execution:'all',
   material:'all',
   taskType:'all',
   dateRange:'all'
  };
  this.selected=null;
  this.detail=false;
  this.tab='overview';
  this.role='planner';
  this.roleRunId=null;
  this.loading=false;
  this.error='';
  this.selectionVersion=0;
  this.probeCache=new Map();
  this.fullCache=new Map();
  this.roleCache=new Map();
  this.limit=25;
  this.updatedAt=null;
  this.timer=null;
 }
 get rep(){return this.h.reproduction();}
 onlineOrderItems(){
  const projects=(this.h.projects?.()||[]).filter(p=>!p.sample);
  const items=projects.map(p=>{
   const r=p.online_report;
   const ex=r?.execution;
   const stages=r?.review?.plan?.stages||[];
   const execStages=ex?.stages||[];
   const codeBound=Boolean(hasCode(p)||r?.materials?.code);
   const paperOnly=Boolean(!codeBound&&(p.paper||r?.materials?.paper));
   const terminated=Boolean(r?.terminated_at);
   const isCancelling=!terminated&&Boolean(this.h.isProjectCancelling?.(p.id)||ex?.status==='cancelling');
   const reviewingNow=!terminated&&!isCancelling&&Boolean(r?.status==='reviewing'||(!r&&p.online_pending_request));
   const waiting=!terminated&&Boolean(ex?.needs_user||(!ex&&(r?.review?.resource_preflight?.needs_user||(r?.review?.task==='reproduction'&&!codeBound))));
   const interrupted=Boolean(['failed','cancelled'].includes(r?.status)||['failed','cancelled','expired'].includes(ex?.status)||execStages.some(stage=>stage.status==='failed'));
   const statusKey=terminated?'terminated':isCancelling?'cancelling':reviewingNow?'reviewing':
    ex?.status==='running'?'reproducing':['queued','starting'].includes(ex?.status)?'queued':
    waiting?'waiting':interrupted?'interrupted':r?.review?'completed':'draft';
   const completedCount=execStages.filter(stage=>stage.status==='completed').length;
   const totalStages=codeBound?stages.length:0;
   const verdict=r?.review?reportVerdict(r,p):null;
   const verdictKey=verdict?.label==='不适用'?'inapplicable':verdict?.state==='passed'?'passed':verdict?.state==='failed'?'failed':statusKey==='completed'&&r?.review?.findings?.length?'issues':'unassessed';
   const statusTone=['waiting','interrupted','cancelling'].includes(statusKey)?'amber':
    statusKey==='completed'&&['failed','issues'].includes(verdictKey)?'red':statusKey==='completed'&&verdictKey==='passed'?'green':
    statusKey==='queued'?'green':['reviewing','reproducing'].includes(statusKey)?'blue':'neutral';
   const statusLabel=statusTone==='red'?'未通过':statusKey==='completed'&&statusTone!=='green'?(verdictKey==='inapplicable'?'不适用':'执行结束'):archiveStates[statusKey];
   const materialKey=paperOnly?'paper_only':codeBound?(p.paper||r?.materials?.paper?'both':'code_only'):'none';
   const rawTime=p.updated_at||r?.updated_at||p.created_at||new Date().toISOString();
   const ts=Date.parse(rawTime)||0;
   const priorityRank=['reviewing','queued','reproducing','cancelling'].includes(statusKey)?0:['waiting','interrupted'].includes(statusKey)?1:statusKey==='draft'?2:3;
   const taskKey=r?.review?.task||p.online_task||(paperOnly?'self_review':'auto');
   const taskLabel=paperOnly&&taskKey==='auto'?'仅论文审阅':(taskNames[taskKey]||'自动识别');
   return {
    id:p.id,
    title:p.title||'未命名审查项目',
    rawTime,
    timestamp:ts,
    createdAt:date(rawTime),
    paperName:p.paper?.name||r?.review?.paper_title||'未上传论文 PDF',
    codeName:codeBound?(p.repository?.repo_name||p.repository?.name||p.repo_url||'已绑定代码'):'仅论文（无代码）',
    paperOnly,
    codeBound,
    taskKey,
    taskLabel,
    statusKey,
    statusLabel,
    verdictKey,
    statusTone, materialKey,
    totalStages,
    completedCount,
    metricsCount:r?.review?.metrics?.length||0,
    findingsCount:r?.review?.findings?.length||0,
    hasReport:Boolean(r?.review),
    hasPaper:Boolean(r?.review && !['code_only','nonpaper'].includes(r.review.paper_type) && (p.paper||r.materials?.paper||r.review.paper_title)),
    priorityRank
   };
  });
  return items.sort((a,b)=>a.priorityRank!==b.priorityRank?a.priorityRank-b.priorityRank:b.timestamp-a.timestamp);
 }
 matchesArchiveFilter(item){
  const f=this.archiveFilters;
  if(this.orderFilter!=='all'&&!matchesStatus(item,this.orderFilter))return false;
  if(f.projectName&&!item.title.toLowerCase().includes(f.projectName.trim().toLowerCase()))return false;
  if(f.paperName&&!item.paperName.toLowerCase().includes(f.paperName.trim().toLowerCase()))return false;
  if(f.codeName&&!item.codeName.toLowerCase().includes(f.codeName.trim().toLowerCase()))return false;
  if(f.verdict!=='all'&&item.verdictKey!==f.verdict)return false;
  if(f.execution!=='all'&&!matchesStatus(item,f.execution))return false;
  if(f.material!=='all'&&item.materialKey!==f.material)return false;
  if(f.taskType!=='all'&&item.taskKey!==f.taskType)return false;
  if(f.dateRange!=='all'&&item.timestamp){
   const now=Date.now();
   const diffDays=(now-item.timestamp)/(1000*3600*24);
   if(f.dateRange==='today'&&diffDays>1.5)return false;
   if(f.dateRange==='7d'&&diffDays>7.5)return false;
   if(f.dateRange==='30d'&&diffDays>30.5)return false;
  }
  return true;
 }
 renderOrderCenter(){
  const e=this.h.esc;
  const items=this.onlineOrderItems();
  const filtered=items.filter(item=>this.matchesArchiveFilter(item));
  const tabs=[['all','全部条目',items.length],['completed','已完成',items.filter(item=>matchesStatus(item,'completed')).length],['in_progress','审查中',items.filter(item=>matchesStatus(item,'in_progress')).length]];
  const f=this.archiveFilters;
  return `<section class="repro-order-center archive-table-center" aria-label="案例与归档表格条目中心">
   <header class="repro-order-header">
    <div>
     <h2>项目归档</h2>
     <p>按材料或审查结果查找项目。进行中和待处理的项目排在前面。</p>
    </div>
    <div class="repro-order-tabs" role="group" aria-label="项目条目状态快速筛选">
     ${tabs.map(([id,label,cnt])=>`<button type="button" class="order-tab-btn ${this.orderFilter===id?'active':''}" data-order-filter="${id}">${label}<span>${cnt}</span></button>`).join('')}
    </div>
   </header>
   <form class="archive-filter-panel" data-archive-filter-form aria-label="案例与归档多条件筛选栏">
    <div class="archive-filter-grid">
     <div class="archive-filter-field archive-search-field">
      <label for="af-project">项目名称</label>
      <input id="af-project" type="search" data-archive-input="projectName" value="${e(f.projectName)}" placeholder="输入项目名称关键词…">
     </div>
     <div class="archive-filter-field archive-search-field">
      <label for="af-paper">论文名称</label>
      <input id="af-paper" type="search" data-archive-input="paperName" value="${e(f.paperName)}" placeholder="输入 PDF 文件名或论文标题…">
     </div>
     <div class="archive-filter-field archive-search-field">
      <label for="af-code">代码 / 仓库名</label>
      <input id="af-code" type="search" data-archive-input="codeName" value="${e(f.codeName)}" placeholder="输入 ZIP 名称或 GitHub 仓库…">
     </div>
     ${[
      ['verdict','审查结论',archiveVerdicts],
      ['execution','执行状态',archiveExecutionFilters],
      ['material','材料类型',archiveMaterials],
      ['taskType','任务类型',taskNames]
     ].map(([key,label,values])=>`<div class="archive-filter-field"><label for="af-${key}">${label}</label><select id="af-${key}" data-archive-select="${key}"><option value="all">全部</option>${Object.entries(values).map(([value,name])=>`<option value="${value}" ${f[key]===value?'selected':''}>${name}</option>`).join('')}</select></div>`).join('')}
     <div class="archive-filter-field">
      <label for="af-date">更新时间</label>
      <select id="af-date" data-archive-select="dateRange">
       <option value="all" ${f.dateRange==='all'?'selected':''}>全部时间</option>
       <option value="today" ${f.dateRange==='today'?'selected':''}>今日内</option>
       <option value="7d" ${f.dateRange==='7d'?'selected':''}>最近 7 天</option>
       <option value="30d" ${f.dateRange==='30d'?'selected':''}>最近 30 天</option>
      </select>
     </div>
    </div>
    <div class="archive-filter-actions">
     <span class="archive-filter-count">显示 <strong>${filtered.length}</strong> / ${items.length} 个项目</span>
     <div class="archive-filter-btns">
      <button type="submit" class="btn primary small">${this.h.icon('search')}查询</button>
      <button type="button" class="btn small" data-archive-action="reset">重置筛选</button>
     </div>
    </div>
   </form>
   ${filtered.length?`<div class="archive-table-card">
    <table class="archive-data-table" aria-label="案例与归档项目表格">
     <thead>
      <tr>
       <th style="width:22%">项目名称与任务类型</th>
       <th style="width:24%">论文与代码材料</th>
       <th style="width:17%">执行状态与审查结论</th>
       <th style="width:15%">指标与核查统计</th>
       <th style="width:11%">更新时间</th>
       <th style="width:11%">操作</th>
      </tr>
     </thead>
     <tbody>
      ${filtered.map(item=>`<tr class="archive-table-row status-${e(item.statusKey)} ${item.priorityRank<=1?'is-priority-pinned':''}">
       <td class="archive-col-project">
        <div class="archive-project-cell">
         <button type="button" class="order-title-link" data-order-open="${e(item.id)}" data-order-tab="${item.statusKey==='completed'?'report':item.statusKey==='draft'?'materials':'process'}">${e(item.title)}</button>
         <span class="archive-task-sub">${e(item.taskLabel)}</span>
        </div>
       </td>
       <td class="archive-col-materials">
        <div class="archive-material-line" title="${e(item.paperName)}"><span class="mat-tag paper">论文</span><span class="mat-name">${e(item.paperName)}</span></div>
        <div class="archive-material-line" title="${e(item.codeName)}"><span class="mat-tag ${item.codeBound?'code':'nocode'}">代码</span><span class="mat-name">${e(item.codeName)}</span></div>
       </td>
       <td class="archive-col-status">
        <span class="order-status-pill tone-${item.statusTone}">${e(item.statusLabel)}</span>
       </td>
       <td class="archive-col-metrics">
        <div class="archive-metrics-inline">
         ${item.codeBound&&item.totalStages?`<span>阶段 <strong>${item.completedCount}/${item.totalStages}</strong></span>`:`<span>模式 <strong>${item.paperOnly?'纯论文审阅':'材料审查'}</strong></span>`}
         <span>指标 <strong>${item.metricsCount}</strong></span>
         <span>建议 <strong>${item.findingsCount}</strong></span>
        </div>
       </td>
       <td class="archive-col-date">
        <time class="order-date">${e(item.createdAt)}</time>
       </td>
       <td class="archive-col-actions">
        <div class="order-actions-col">
         ${item.statusKey==='cancelling'?'<button type="button" class="btn small" disabled>正在中断</button>':
          ['reviewing','queued','reproducing'].includes(item.statusKey)?`<button type="button" class="btn primary small" data-order-open="${e(item.id)}" data-order-tab="process">查看进度</button><button type="button" class="btn small" data-order-cancel="${e(item.id)}">中断运行</button>`:
          ['waiting','interrupted'].includes(item.statusKey)?`<button type="button" class="btn primary small" data-order-open="${e(item.id)}" data-order-tab="process">查看诊断</button><button type="button" class="btn danger small" data-order-terminate="${e(item.id)}">终止审查</button>`:
          item.statusKey==='terminated'?`<button type="button" class="btn small" data-order-open="${e(item.id)}" data-order-tab="process">查看记录</button>`:
          item.hasReport?`<button type="button" class="btn primary small" data-order-open="${e(item.id)}" data-order-tab="report">查看报告</button>`:
          `<button type="button" class="btn small" data-order-open="${e(item.id)}" data-order-tab="materials">准备材料</button>`}
        </div>
       </td>
      </tr>`).join('')}
     </tbody>
    </table>
   </div>`:`<div class="repro-order-empty"><p>当前筛选条件下没有匹配的项目条目。可点击“重置筛选”查看全部记录，或点击右上角“新建复现”提交论文或代码。</p></div>`}
  </section>`;
 }
 rows(){const state=this.h.state();return executionRecords({jobs:this.rep.registry,publicCase:this.rep.catalogCase,runs:state.runs,tasks:state.tasks,projects:this.h.projects(),mode:state.mode}).map(row=>{
  if(row.kind==='full'&&this.fullCache.has(row.key)){const {job,report}=this.fullCache.get(row.key);return executionRecords({jobs:[{...job,...row.job}],projects:this.h.projects(),selected:{job:{...job,...row.job},report}})[0];}return row;
 });}
 current(){return this.rows().find(row=>row.key===this.selected)||null;}
 probe(row=this.current()){const state=this.h.state();return row?.kind==='probe'?(state.run?.id===row.id?state.run:this.probeCache.get(row.id)||row.run):null;}
 roleRun(){const rows=this.rows();const row=rows.find(r=>r.key===this.roleRunId)||rows.find(r=>r.key===this.selected)||rows.find(r=>r.kind==='probe')||rows[0];return {row,run:row?.kind==='full'?this.fullRoles(row):this.probe(row)};}
 fullRoles(row){if(!row||row.kind!=='full')return null;const data=row.source==='public_case'?row.report?.role_trace||null:this.roleCache.get(row.key)||null;return fullRoleRun(data,row.status);}
 async loadRoles(row){try{this.roleCache.set(row.key,await this.h.request('/api/reproduction/runs/'+encodeURIComponent(row.id)+'/roles'));}catch(error){this.roleCache.set(row.key,{...this.roleCache.get(row.key),error:error.message});}}
 async init(){try{this.rep.catalogCase=this.rep.catalogCase||await this.rep.loadPublicCase();this.rep.caseReport=null;}catch(error){this.error='公开案例读取失败：'+error.message;}this.rep.openExecution=key=>this.open(key);this.rep.onReviewNavigate=(_key,tab)=>{if(!['workbench','evidence','trace'].includes(this.h.state().page)||!this.detail)return false;this.tab=tab;return true;};}
 async refresh(){this.error='';try{await this.h.refresh();await this.rep.loadRegistry();const row=this.current();if(this.detail&&row?.source==='runtime')await this.open(row.key,this.tab,false);if(this.h.state().page==='roles'){const selected=this.roleRun().row;if(selected?.kind==='full'&&selected.source==='runtime')await this.loadRoles(selected);}this.updatedAt=new Date().toISOString();}catch(error){this.error=error.message;}this.h.render();}
 async open(key,tab='overview',navigate=true){const row=this.rows().find(r=>r.key===key);if(!row)return;const version=++this.selectionVersion;this.selected=key;this.tab=tab;this.detail=true;this.loading=true;this.error='';if(navigate)this.h.navigate('workbench');else this.h.render();try{
  if(row.kind==='full'&&row.source==='runtime'){
   const job=await this.h.request('/api/reproduction/runs/'+encodeURIComponent(row.id));
   const report=job.report_ready?validateReproductionReport(await this.h.request(job.report_url)):null;
   if(report&&report.plan_sha256!==job.plan_sha256)throw Error('任务与报告的计划版本不一致');
   if(version!==this.selectionVersion)return;this.fullCache.set(key,{job,report});await this.loadRoles(row);if(version!==this.selectionVersion)return;this.roleRunId=key;
  }else if(row.kind==='probe'){const run=await this.h.selectProbe(row.id);if(version!==this.selectionVersion)return;this.probeCache.set(row.id,run);this.roleRunId=row.key;}else if(row.kind==='full'){this.roleRunId=key;}
 }catch(error){if(version===this.selectionVersion)this.error=error.message;}finally{if(version===this.selectionVersion){this.loading=false;this.h.render();}}}
 resetList(status=this.filters.status){this.selectionVersion++;this.detail=false;this.loading=false;this.filters.status=status;this.error='';}
 route(page,originProject=null){
  if(page==='roles')return;
  const tab=page==='trace'?'trace':page==='evidence'?'evidence':'overview';
  if(originProject){const id=originProject.assessment?.reproduction?.job?.id,key=id?'full:'+id:originProject.run_id?'probe:'+originProject.run_id:null;if(key&&this.rows().some(r=>r.key===key)){this.open(key,tab,false);return;}this.selected=null;}
  if(page==='workbench')this.resetList();else if(this.current()){return this.open(this.current().key,tab,false);}else{this.resetList(page==='evidence'?'attention':'all');}
 }
 heading(page){if(page==='roles')return '角色协作';if(this.detail&&this.current())return this.current().title;return page==='evidence'?'证据复核':'案例与归档';}
 subtitle(page){if(page==='roles')return '六个角色 · 短时核查与完整实验的职责、输入输出与实际事件';if(this.detail&&this.current()){const row=this.current();return `${kindLabels[row.kind]} · ${sourceLabels[row.source]} · ${statusLabels[row.status]||row.status}`;}const rows=this.rows();return `${this.onlineOrderItems().length} 个在线审查项目 · ${rows.filter(r=>r.source!=='runtime').length} 份基线归档案例`;}
 actions(page){if(page==='roles')return '<button class="btn" data-center-refresh>刷新核查记录</button>';if(this.detail)return '<button class="btn" data-center-back>返回案例与归档</button>';return `<button class="btn" data-center-refresh>${this.h.icon('refresh')}刷新记录</button><button class="btn primary" data-action="new">${this.h.icon('plus')}新建复现</button>`;}
 render(page){return `${this.error?`<p class="error-box" role="alert">${this.h.esc(this.error)}</p>`:''}${page==='roles'?this.rolesView():this.detail&&this.current()?this.detailView():this.listView(page)}`;}
 listView(page){const e=this.h.esc,all=this.rows(),base=filterRecords(all,{...this.filters,status:'all'}),counts=recordCounts(base),rows=filterRecords(all,this.filters),statusTabs=[['all','全部归档',counts.all],['active','执行中',counts.active],['attention','需关注',counts.attention],['completed','已完成',counts.completed]];return `${this.renderOrderCenter()}<section class="execution-list"><div class="execution-list-head"><div><span class="online-kicker">系统内置与本机基线档案</span><h3>公共复现案例与核查归档库</h3></div><div class="execution-state-tabs" role="group" aria-label="任务状态筛选">${statusTabs.map(([id,label,count])=>`<button data-center-status="${id}" aria-pressed="${this.filters.status===id}" class="${this.filters.status===id?'active':''}">${label}<span>${count}</span></button>`).join('')}</div></div><div class="execution-toolbar"><label class="execution-search">${this.h.icon('search')}<span class="sr-only">搜索任务、版本或运行 ID</span><input data-center-query value="${e(this.filters.query)}" placeholder="搜索公共案例名称、计划版本或运行 ID"></label><div class="execution-filters"><label><span class="sr-only">执行方式</span><select data-center-filter="kind" aria-label="执行方式">${[['all','全部执行方式'],['full','完整实验'],['probe','短时核查']].map(([id,label])=>`<option value="${id}" ${this.filters.kind===id?'selected':''}>${label}</option>`).join('')}</select></label><label><span class="sr-only">记录来源</span><select data-center-filter="source" aria-label="记录来源">${[['all','全部来源'],['runtime','本机执行'],['public_case','公开 CI 归档'],['teaching','教学归档']].map(([id,label])=>`<option value="${id}" ${this.filters.source===id?'selected':''}>${label}</option>`).join('')}</select></label></div></div><div class="execution-table-meta"><p>显示 ${Math.min(rows.length,this.limit)} / ${rows.length} 条记录</p><span>${this.updatedAt?'更新于 '+date(this.updatedAt):this.h.state().mode==='runtime'?'已读取本机记录':'预览模式 · 归档数据'}</span></div><div class="execution-table-wrap"><table class="execution-table"><thead><tr><th>复现任务</th><th>执行方式 / 来源</th><th>状态</th><th class="num">执行进度</th><th>更新时间</th><th><span class="sr-only">任务操作</span></th></tr></thead><tbody>${rows.slice(0,this.limit).map(row=>`<tr><td class="record-identity"><button data-center-open="${e(row.key)}">${e(row.title)}</button><small>${row.plan_sha256?'计划 '+e(row.plan_sha256.slice(0,12)):row.id?'运行 '+e(row.id.slice(0,12)):'独立公开案例'}${row.source==='public_case'?' · 有限范围验收':''}</small></td><td><span>${kindLabels[row.kind]}</span><small>${sourceLabels[row.source]}</small></td><td><span class="record-status ${row.status}"><i aria-hidden="true"></i>${statusLabels[row.status]||e(row.status)}</span></td><td class="record-progress num"><span>${e(progressText(row))}</span><small>${row.phases===null?row.kind==='full'?'完整计划见任务详情':'六角色核查流程':row.phases+' 个阶段'}</small></td><td class="record-date">${e(date(row.created_at))}</td><td class="record-action"><button class="btn text" data-center-open="${e(row.key)}">查看任务 ${this.h.icon('chevron')}</button></td></tr>`).join('')}</tbody></table>${rows.length?'':`<div class="execution-empty"><h2>${all.length?'没有符合条件的记录':'还没有执行记录'}</h2><p>${all.length?'调整任务状态、执行方式或来源，继续查找。':'从论文项目准备材料，绑定计划后启动实验。'}</p><button class="btn" ${all.length?'data-center-clear':'data-action="new"'}>${all.length?'清除筛选':'新建复现项目'}</button></div>`}</div>${rows.length>this.limit?'<button class="btn" data-center-more>再显示 25 条</button>':''}</section>`;}
 detailView(){const row=this.current(),e=this.h.esc,full=row.kind==='full',data=full?(row.source==='public_case'?{report:row.report,source:row.source}:this.fullCache.get(row.key)):null,report=data?.report;return `<section class="execution-detail"><div class="record-context-bar"><span><span class="record-status ${row.status}"><i aria-hidden="true"></i>${statusLabels[row.status]||e(row.status)}</span></span><span>${sourceLabels[row.source]}</span><span>${date(row.created_at)}</span><div class="record-context-actions">${row.source==='runtime'?'<button class="btn text" data-center-refresh>刷新任务</button>':''}${(row.source==='runtime'||row.kind==='probe')&&['running','queued'].includes(row.status)?'<button class="btn danger" data-center-stop>停止执行</button>':''}${report||this.probe(row)?.report?`<button class="btn" data-center-export>${full?'导出证据包':'导出核查报告'}</button>`:''}${!full&&!['running','queued'].includes(row.status)?`<button class="btn" data-action="rerun">${row.source==='teaching'?'回放此核查':'重新核查'}</button>`:''}</div></div>${row.plan_sha256?`<div class="record-version"><span>冻结计划 <code>${e(row.plan_sha256.slice(0,16))}</code></span>${report?.source_manifest_sha256?`<span>源码清单 <code>${e(report.source_manifest_sha256.slice(0,16))}</code></span>`:''}<span>${e(progressText(row))}${row.phases===null?'':' · '+row.phases+' 个阶段'}</span></div>`:''}${row.source==='public_case'?'<p class="record-provenance">公开 CI 证据 · 仅覆盖 LIBLINEAR 的 news20 CPU 实验，Figure 1、rcv1 与效率结论尚未覆盖。<a href="'+e(report.provenance?.workflow_url||'#')+'" target="_blank" rel="noopener">查看来源</a></p>':row.source==='teaching'?'<p class="record-provenance">自制教学仓库的归档证据 · 用于体验核查流程。</p>':''}<div class="execution-detail-tabs" role="group" aria-label="任务详情视图">${tabsFor(row.kind).map(([id,label])=>`<button data-center-tab="${id}" aria-pressed="${this.tab===id}" class="${this.tab===id?'active':''}">${label}</button>`).join('')}</div>${this.loading?'<div class="execution-loading" role="status">正在读取任务证据…</div>':full?this.tab==='roles'?this.roleFlow(this.fullRoles(row))+this.roleBody(this.fullRoles(row),row):report?this.rep.review.render(report,{source:row.source,job:data.job||row.job},e,{embedded:true,tab:this.tab}):`<div class="execution-empty"><h2>${row.status==='failed'?'执行未生成报告':'报告尚未生成'}</h2><p>${e(data?.job?.error||'任务状态已保留，刷新后读取最新证据。')}</p></div>`:this.tab==='roles'?this.roleFlow(this.probe())+this.roleBody(this.probe(),row):this.tab==='overview'?this.probeOverview(row):this.h.probeView(this.tab)}</section>`;}
 probeOverview(row){const e=this.h.esc,run=this.probe(row),findings=run?.findings||run?.report?.findings||[],issues=findings.filter(f=>f.verdict==='issue'),missing=findings.filter(f=>f.verdict==='inconclusive');return `<div class="probe-task-overview"><section class="probe-verdict-summary"><h2>${!run?.report?(['running','queued'].includes(run?.status)?'核查正在执行':run?.status==='cancelled'?'本次核查已停止':'尚无核查报告'):issues.length?'发现 '+issues.length+' 条不一致':missing.length?'有 '+missing.length+' 条证据不足':'核查记录已生成'}</h2><p>${findings.length} 条主张已有判定 · ${run?.report?Number(run.report.elapsed_seconds).toFixed(2)+' 秒原始执行':'报告尚未生成'}</p><button class="btn" data-center-tab="evidence">打开逐条证据</button></section><section class="probe-role-overview"><div class="section-heading"><h2>角色协作状态</h2><button class="btn text" data-center-tab="roles">查看角色记录</button></</div>${this.roleFlow(run)}<p class="small-note">${e(run?.report?.policy||run?.planner||'策略未记录')} · ${run?.events?.length||0} 条原始事件</p></section><section class="probe-findings-overview"><div class="section-heading"><h2>主张判定</h2><button class="btn text" data-center-tab="trace">查看执行事件</button></div>${findings.map(f=>`<div class="probe-finding-row"><strong>${e(f.claim_id)}</strong><span class="${f.verdict==='issue'?'finding-negative':''}">${{issue:'发现不一致',supported:'证据支持',inconclusive:'证据不足'}[f.verdict]||e(f.verdict)}</span><p>${e(f.reason)}</p></div>`).join('')||'<p class="assessment-empty">尚无主张判定。</p>'}</section></div>`;}
 roleFlow(run){const e=this.h.esc,isFull=run?.mode==='full';const groups=isFull?[{title:'材料审计',ids:['literature','code']},{title:'冻结计划排程',ids:['planner']},{title:'构建与执行',ids:['experiment']},{title:'逐阶段核查',ids:['audit']},{title:'分层验收',ids:['report']}]:[{title:'并行预检',ids:['literature','code']},{title:'选择主张',ids:['planner']},{title:'取得证据',ids:['experiment']},{title:'逐条判定',ids:['audit']},{title:'保存记录',ids:['report']}];return `<div class="role-flow" aria-label="核查角色协作顺序">${groups.map(group=>`<div class="role-flow-group"><span>${group.title}</span>${group.ids.map(id=>{const role=ROLES.find(r=>r.id===id),state=roleState(run,id);return `<button data-center-role="${id}" class="${this.role===id?'selected':''}"><span class="role-state-dot ${state}" aria-hidden="true"></span>${e(role.name)}<small>${statusLabels[state]}</small></button>`;}).join('')}</div>`).join('')}</div><p class="role-flow-caption">${isFull?'材料审计在执行前完成；Planner 按冻结计划排程，执行与交叉核查逐阶段交替。':'文献与代码并行预检；规划、执行与交叉核查按主张迭代。'}</p>`;}
 rolesView(){const {row,run}=this.roleRun(),e=this.h.esc,rows=this.rows();return `<section class="roles-workspace"><div class="role-task-bar"><label for="role-run-select">当前任务</label><select id="role-run-select" data-center-role-run>${rows.length?rows.map(x=>`<option value="${e(x.key)}" ${row?.key===x.key?'selected':''}>${e(x.title)} · ${kindLabels[x.kind]} · ${sourceLabels[x.source]}</option>`).join(''):'<option value="">尚无核查或实验记录</option>'}</select><span>${row?sourceLabels[row.source]:'角色接口说明'}</span></div>${this.roleFlow(run)}${this.roleBody(run,row)}<p class="role-boundary">短时核查中 Planner 选择主张或停止；完整实验中 Planner 按冻结计划排程（frozen_plan），角色事件来自执行器写入的 roles.jsonl，不由界面生成。</p></section>`;}
 roleBody(run,row){const e=this.h.esc,base=ROLES.find(r=>r.id===this.role)||ROLES[2],isFull=run?.mode==='full',role=isFull?{...base,...base.full}:base,events=roleEvents(run,role.id),state=roleState(run,role.id),label=event=>event.kind==='role'?event.summary||event.event:this.h.eventText(event),tag=event=>event.kind==='role'?event.event+' · '+event.status:event.kind;return `<div class="role-detail-layout"><section class="role-contract"><div class="role-detail-title"><h2>${e(role.name)}</h2><span class="record-status ${state}"><i aria-hidden="true"></i>${statusLabels[state]}</span></div><p class="role-english-name">${role.english}</p><p>${e(role.job)}</p><dl class="role-contract-fields"><div><dt>输入</dt><dd><code>${e(role.input)}</code></dd></div><div><dt>输出</dt><dd><code>${e(role.output)}</code></dd></div><div><dt>当前上下文</dt><dd>${e(row?.title||'尚未选择任务')}</dd></div></dl><button class="btn text" data-action="nav" data-page="contracts">查看接口契约 ${this.h.icon('arrow')}</button></section><section class="role-event-panel"><div class="section-heading"><h2>实际事件记录</h2><span>${events.length} 条</span></div><p class="small-note">${isFull?'执行器写入的 roles.jsonl 原始事件；每条附负责阶段、状态与证据文件。':role.id==='literature'||role.id==='code'?'两个预检角色共享 preflight 事件；下方仅展开本角色数据。':'来自本次任务的原始轨迹，展开查看输入、动作与输出。'}</p>${run?.error?`<p class="error-box" role="alert">角色记录读取失败：${e(run.error)}。可刷新重试；已有记录可能过期。</p>`:''}${events.slice(-8).map((event,index)=>`<details class="role-event"><summary><span>${e(label(event))}</span><small>${e(tag(event))}${event.sequence?' · #'+event.sequence:''}</small></summary><pre>${e(JSON.stringify(rolePayload(event,role.id),null,2))}</pre></details>`).join('')||(isFull&&!run.available&&!run.error?'<div class="role-empty-record"><p>本次完整实验没有角色记录。</p><span>该归档早于角色标注接入，只保留阶段证据；请在“阶段与输出”查看，重跑后读取 roles.jsonl。</span></div>':'<div class="role-empty-record"><p>没有该角色的执行记录。</p><span>职责与接口说明已保留；启动核查或实验后再读取实际事件。</span></div>')}${events.length>8?`<p class="small-note">显示最近 8 / ${events.length} 条，角色原始记录保留在任务的 roles.jsonl。</p>`:''}</section></div>`;}
 updateListResults(){const root=document.querySelector('.execution-list');if(!root)return;const template=document.createElement('template');template.innerHTML=this.listView(this.h.state().page);for(const selector of ['.execution-state-tabs','.execution-table-meta','.execution-table-wrap']){const previous=root.querySelector(selector),next=template.content.querySelector(selector);if(previous&&next)previous.replaceWith(next);}const previous=root.querySelector('[data-center-more]'),next=template.content.querySelector('[data-center-more]');if(previous&&next)previous.replaceWith(next);else if(previous)previous.remove();else if(next)root.appendChild(next);}
 updateOrderTable(){
  const root=document.querySelector('.repro-order-center');
  if(!root)return;
  const template=document.createElement('template');
  template.innerHTML=this.renderOrderCenter();
  const nextCenter=template.content.querySelector('.repro-order-center');
  if(!nextCenter)return;
  for(const sel of ['.repro-order-tabs','.archive-filter-count','.archive-table-card','.repro-order-empty']){
   const prev=root.querySelector(sel),next=nextCenter.querySelector(sel);
   if(prev&&next)prev.replaceWith(next);
   else if(prev&&!next)prev.remove();
   else if(!prev&&next)root.appendChild(next);
  }
 }
 afterRender(){clearTimeout(this.timer);const state=this.h.state();if(state.mode!=='runtime'||!['workbench','evidence','trace','roles'].includes(state.page)||this.loading)return;const row=this.current(),roleRow=state.page==='roles'?this.roleRun().row:null;const active=this.rows().some(r=>r.source==='runtime'&&['running','queued'].includes(r.status));if(!active||document.querySelector('.role-event[open],.review-station details[open],.review-decision:focus-within')||document.activeElement?.matches('input,textarea,select'))return;this.timer=setTimeout(async()=>{try{await this.h.refresh();await this.rep.loadRegistry();if(this.detail&&row?.kind==='full'&&row.source==='runtime'&&this.selected===row.key){const job=await this.h.request('/api/reproduction/runs/'+encodeURIComponent(row.id));const report=job.report_ready?validateReproductionReport(await this.h.request(job.report_url)):null;if(report&&report.plan_sha256!==job.plan_sha256)throw Error('报告版本不匹配');if(this.selected===row.key){this.fullCache.set(row.key,{job,report});await this.loadRoles(row);}}if(roleRow?.kind==='full'&&roleRow.source==='runtime')await this.loadRoles(roleRow);this.updatedAt=new Date().toISOString();}catch(error){this.error=error.message;}this.h.render();},3000);}
 bind(){
  document.addEventListener('toggle',event=>{if(event.target.matches?.('.role-event,.trace-run,.trace-stage'))this.afterRender();},true);
  document.addEventListener('focusout',event=>{if(event.target.closest?.('.execution-list,.review-decision'))setTimeout(()=>this.afterRender(),0);});
  document.addEventListener('input',event=>{
   const t=event.target;
   if(t.matches('[data-archive-input]')){
    this.archiveFilters[t.dataset.archiveInput]=t.value;
    this.updateOrderTable();
    return;
   }
   if(!t.matches('[data-center-query]'))return;
   this.filters.query=t.value;this.limit=25;this.updateListResults();this.afterRender();
  });
  document.addEventListener('change',async event=>{
   const el=event.target;
   if(el.matches('[data-archive-select]')){
    this.archiveFilters[el.dataset.archiveSelect]=el.value;
    this.updateOrderTable();
    return;
   }
   if(el.dataset.centerFilter){this.filters[el.dataset.centerFilter]=el.value;this.limit=25;this.h.render();}
   if(el.matches('[data-center-role-run]')){this.roleRunId=el.value;const row=this.rows().find(r=>r.key===el.value);try{if(row?.kind==='probe'){const run=await this.h.selectProbe(row.id);this.probeCache.set(row.id,run);}else if(row?.kind==='full'&&row.source==='runtime')await this.loadRoles(row);}catch(error){this.error=error.message;}this.h.render();}
  });
  document.addEventListener('submit',event=>{
   if(!event.target.matches('[data-archive-filter-form]'))return;
   event.preventDefault();
   this.h.render();
  });
  document.addEventListener('click',async event=>{
   const el=event.target.closest('[data-archive-action],[data-order-filter],[data-order-open],[data-order-cancel],[data-order-terminate],[data-center-open],[data-center-status],[data-center-tab],[data-center-back],[data-center-clear],[data-center-more],[data-center-refresh],[data-center-stop],[data-center-export],[data-center-role],[data-role-nav]');
   if(!el)return;
   try{
    if(el.dataset.archiveAction==='reset'){
     this.orderFilter='all';
     this.archiveFilters={projectName:'',paperName:'',codeName:'',verdict:'all',execution:'all',material:'all',taskType:'all',dateRange:'all'};
     this.h.render();
     return;
    }
    if(el.dataset.orderFilter){this.orderFilter=el.dataset.orderFilter;this.h.render();return;}
    if(el.dataset.orderOpen){this.h.openOnlineOrder?.(el.dataset.orderOpen,el.dataset.orderTab||'process');return;}
    if(el.dataset.orderTerminate){await this.h.terminateOnlineOrder?.(el.dataset.orderTerminate);return;}
    if(el.dataset.orderCancel){await this.h.cancelOnlineOrder?.(el.dataset.orderCancel);return;}
    if(el.dataset.centerOpen){await this.open(el.dataset.centerOpen,this.h.state().page==='evidence'?'evidence':'overview');return;}
    if(el.dataset.centerStatus){this.filters.status=el.dataset.centerStatus;this.limit=25;}
    if(el.dataset.centerTab)this.tab=el.dataset.centerTab;
    if(el.hasAttribute('data-center-back')){this.resetList();this.h.navigate('workbench');return;}
    if(el.hasAttribute('data-center-clear'))this.filters={query:'',kind:'all',source:'all',status:'all',project:'all'};
    if(el.hasAttribute('data-center-more'))this.limit+=25;
    if(el.hasAttribute('data-center-refresh')){await this.refresh();return;}
    if(el.dataset.centerRole||el.dataset.roleNav){this.role=el.dataset.centerRole||el.dataset.roleNav;if(el.dataset.roleNav)this.h.navigate('roles');else if(this.h.state().page!=='roles')this.tab='roles';}
    if(el.hasAttribute('data-center-stop')){const row=this.current();if(row){await this.h.cancel(row);await this.refresh();return;}}
    if(el.hasAttribute('data-center-export')){const row=this.current();if(row.kind==='probe'){this.h.download('articheck-probe-report.json',JSON.stringify(this.probe(row).report,null,2));return;}const data=row.source==='public_case'?{report:row.report,source:'public_case'}:{...this.fullCache.get(row.key),source:'runtime'};const {view}=this.rep.review.context(data.report,data);this.h.download('articheck-evidence-review.json',JSON.stringify({format:'articheck-evidence-review-v1',source:data.source,report:data.report,reviews:view.reviews},null,2));}
   }catch(error){this.error=error.message;}
   this.h.render();
  });
 }
}
