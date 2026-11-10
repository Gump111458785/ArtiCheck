export const ROLE_NAMES={literature_reader:'文献审阅',code_inspector:'代码检查',planner:'计划编排',experiment_runner:'实验执行',cross_auditor:'交叉核查',reporter:'报告整理'};
const kinds={plan_scheduled:'按计划排程',stage_started:'开始阶段执行',stage_retry:'自动重试阶段',stage_finished:'阶段执行结束',stage_checked:'核对阶段输出',execution_checked:'汇总执行证据',report_written:'写入执行报告',stopped:'结束排程'};
const ROLE_ICONS={
 literature_reader:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v16H6.5A2.5 2.5 0 0 0 4 21.5zM8 7h7M8 11h5"/></svg>',
 code_inspector:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14"/></svg>',
 planner:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm14 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 8h7a3 3 0 0 1 0 6h-4a3 3 0 0 0 0 6h7"/></svg>',
 experiment_runner:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12l10-6z"/></svg>',
 cross_auditor:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v6c0 4.5 3 7.8 7 9 4-1.2 7-4.5 7-9V6zm-2.5 9 2 2 4-4"/></svg>',
 reporter:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h6M9 16h4"/></svg>'
};
const ROLE_HINTS={
 literature_reader:{idle:'解析论文图表与出处',jump:'查看审阅记录'},
 code_inspector:{idle:'检查源码结构与依赖',jump:'查看代码记录'},
 planner:{idle:'编排阶段执行计划',jump:'跳转至执行计划'},
 experiment_runner:{idle:'隔离沙箱与 GPU 执行',jump:'跳转至执行本次计划'},
 cross_auditor:{idle:'独立复核数字与依据',jump:'查看复核记录'},
 reporter:{idle:'生成结构化审查报告',jump:'查看最终报告'}
};

export function activityEvents(report){
 const execution=report?.execution,rows=execution?.events||[];
 return [...(report?.activity||[]),...rows.map((x,index)=>({...x,roles:[x.role],status:x.kind==='stage_started'&&execution.status==='running'&&!rows.slice(index+1).some(y=>y.kind==='stage_finished'&&y.stage===x.stage)?'running':x.kind==='stage_finished'&&x.exit_code!==0?'failed':'completed',title:kinds[x.kind]||x.kind,detail:report.review?.plan?.stages?.find(s=>s.id===x.stage)?.title||x.reason||({completed:'已结束',running:'执行中',failed:'执行受阻',cancelled:'已停止',expired:'已超时'}[x.status]||x.status)||''}))];
}

export function activityGroups(report){
 const groups=new Map();
 for(const event of activityEvents(report)){
  let key='review',title='材料审阅与计划';
  if(event.stage){key='stage:'+event.stage;title=report.review?.plan?.stages?.find(s=>s.id===event.stage)?.title||event.stage;}
  else if(event.kind){key=['stopped','execution_checked','report_written'].includes(event.kind)?'execution-result':'execution-setup';title=key==='execution-result'?'实验核查与汇总':'执行准备';}
  if(!groups.has(key))groups.set(key,{key,title,events:[]});
  groups.get(key).events.push(event);
 }
 return [...groups.values()];
}

export function visibleRoles(report){
 const hasPaper=Boolean(report?.materials?.paper||(report?.review?.paper_type&&report.review.paper_type!=='code_only'));
 const events=activityEvents(report);
 const hasCodeOrExec=Boolean(report?.materials?.code||report?.execution||report?.review?.plan?.stages?.length||events.some(x=>(x.roles||[]).some(r=>['code_inspector','experiment_runner'].includes(r))));
 return Object.entries(ROLE_NAMES).filter(([id])=>{
  if(!hasPaper&&id==='literature_reader')return false;
  if(!hasCodeOrExec&&['code_inspector','planner','experiment_runner'].includes(id))return false;
  return true;
 });
}

export function activityView(report,esc,{open=true,showLog=true,activeRole=null,cancelling=false}={}){
 const events=activityEvents(report);if(!events.length)return '';
 const isCancelling=Boolean(cancelling||report?.status==='cancelling'||report?.execution?.status==='cancelling');
 const isCancelledOrDone=['cancelled','failed','completed'].includes(report?.status)&&!['running','starting','queued','cancelling'].includes(report?.execution?.status)||['cancelled','failed','expired','completed'].includes(report?.execution?.status);
 const active=events.filter(x=>x.status==='running'),last=active.at(-1)||events.at(-1);
 const roles=visibleRoles(report);
 const running=!isCancelledOrDone&&(isCancelling||report.status==='reviewing'||['running','starting','queued','cancelling'].includes(report.execution?.status));
 const states=roles.map(([id])=>{
  const rows=events.filter(x=>(x.roles||[]).includes(id));
  const isRun=rows.some(x=>x.status==='running');
  const isFail=rows.some(x=>x.status==='failed');
  const isDone=rows.some(x=>x.status==='completed');
  if(isRun){
   if(isCancelling)return 'cancelling';
   if(isCancelledOrDone)return report?.status==='completed'&&report?.execution?.status!=='failed'&&report?.execution?.status!=='cancelled'?'completed':'failed';
   return 'running';
  }
  return isFail?'failed':isDone?'completed':'idle';
 });
 let furthest=-1;
 states.forEach((st,idx)=>{if(st==='completed'||st==='running'||st==='cancelling'||st==='failed')furthest=idx;});
 const allDone=states.length>0&&states.every(st=>st==='completed');
 const progressPct=allDone?100:roles.length<=1?100:furthest<0?8:Math.min(100,Math.round(((furthest+(states[furthest]==='running'||states[furthest]==='cancelling'?0.5:1))/roles.length)*100));

 return `<section class="review-activity ${allDone?'all-completed':''} ${isCancelling?'is-cancelling':running?'is-running':'is-static'}" aria-label="审查协作进度"><header><div>${isCancelling?'<h2 class="live-heading cancelling-heading"><span class="live-heading-text">正在安全中断审查</span><span class="cancelling-anim" aria-hidden="true"><i></i><i></i><i></i></span></h2>':running?'<h2 class="live-heading"><span class="live-heading-text">正在协作审查</span><span class="live-dots" aria-hidden="true"><i></i><i></i><i></i></span></h2>':'<h2>审查协作时间轴</h2>'}<p role="status" aria-live="polite">${isCancelling?'正在向执行环境发送中断信号并保存已完成阶段记录…':esc(last.title)+(last.detail?' · '+esc(last.detail):'')}</p></div><div class="review-activity-actions">${isCancelling?'<span class="activity-done-pill cancelling"><span class="cancelling-anim" aria-hidden="true"><i></i><i></i><i></i></span>正在中断…</span><button type="button" class="btn danger small online-abort-btn" data-online="cancel" disabled>中断中…</button>':running?'<span class="activity-done-pill live"><span class="online-spinner" aria-hidden="true"></span>正在运行</span><button type="button" class="btn danger small online-abort-btn" data-online="cancel">临时终止</button>':`<span class="activity-done-pill">${report.status==='cancelled'||report.execution?.status==='cancelled'?'已临时终止':states.includes('failed')?'已报错中断':'过程已记录'}</span>`}</div></header><div class="review-role-lanes review-timeline-axis" style="--timeline-cols:${roles.length};--timeline-progress:${progressPct}%"><div class="timeline-track" aria-hidden="true"><div class="timeline-track-fill ${allDone?'done':''}" style="width:${progressPct}%"></div></div>${roles.map(([id,label],idx)=>{
  const rows=events.filter(x=>(x.roles||[]).includes(id));
  const state=states[idx];
  const statusText=state==='cancelling'?'正在中断…':state==='running'?'进行中':state==='failed'?'已中断':state==='completed'?'已执行':rows.some(x=>x.status==='skipped')?'本次跳过':report.status==='reviewing'?'等待中':'待执行';
  const jump=ROLE_HINTS[id]?.jump||'查看详情';
  const isActive=activeRole===id;
  return `<button type="button" class="review-role-lane timeline-node ${state} ${isActive?'active-node':''}" data-role-jump="${id}" aria-expanded="${isActive?'true':'false'}" title="点击展开或收起${label}总结（${jump}）"><span class="timeline-step-num">0${idx+1}</span><span class="review-role-dot timeline-dot" aria-hidden="true">${state==='completed'?'✓':state==='failed'||state==='cancelling'?'!':ROLE_ICONS[id]||''}</span><span class="timeline-stem" aria-hidden="true"></span><span class="timeline-callout"><strong>${label}</strong><small class="timeline-state-tag">${statusText}</small><span class="timeline-jump-hint">${isActive?'再次点击收起 ▲':jump+' ↘'}</span></span></button>`;
 }).join('')}</div>${showLog?`<details class="review-activity-log" ${open?'open':''}><summary>查看 ${events.length} 条活动记录</summary><div class="activity-groups">${activityGroups(report).map(group=>{
  const groupRoles=[...new Set(group.events.flatMap(e=>e.roles||[]))].join(',');
  return `<section class="activity-group" data-activity-group="${esc(group.key)}" data-activity-roles="${esc(groupRoles)}"><h3>${esc(group.title)}<span>${group.events.length} 条记录</span></h3><ol>${group.events.map(x=>`<li class="activity-event ${esc(x.status)}" data-event-roles="${esc((x.roles||[]).join(','))}"><time>${x.time?esc(new Date(x.time*1000).toLocaleTimeString('zh-CN',{hour12:false})):''}</time><div><header><strong>${esc(x.title)}</strong><span>${esc({running:'进行中',completed:'已结束',skipped:'已跳过',failed:'未完成'}[x.status]||x.status)}</span></header><small>${(x.roles||[]).map(id=>esc(ROLE_NAMES[id]||id)).join(' / ')}</small>${x.detail?`<p>${esc(x.detail)}</p>`:''}</div></li>`).join('')}</ol></section>`;
 }).join('')}</div></details>`:''}</section>`;
}
