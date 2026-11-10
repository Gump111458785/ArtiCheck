import {ROLES,roleState,statusLabels} from './execution-core.mjs';
export const NAV_GROUPS=[
 {title:'工作入口',items:[['home','home','开始']]},
 {title:'复现工作',items:[['projects','book','论文项目'],['workbench','terminal','执行中心'],['roles','route','角色协作'],['evidence','shield','证据复核'],['api-review','code','在线审查'],['knowledge-graph','branch','知识图谱']]},
 {title:'评测与数据',items:[['evaluation','grid','系统评测'],['handoff','branch','反馈与训练交接']]},
 {title:'开发工具',items:[['help','info','帮助']]}
];
export const NAV_ITEMS=NAV_GROUPS.flatMap(g=>g.items);
export function renderNavigation({page,icon,esc,run,selectedRole='planner',expandedRoles=false,activeRuns=0,hosted=false}){
 const groups=hosted?[{title:'工作入口',items:[['home','home','开始'],['api-review','code','在线审查'],['workbench','terminal','案例与归档'],['knowledge-graph','branch','知识图谱']]},{title:'本地与开发工具',items:[['projects','book','本地项目'],['help','info','帮助']]}]:NAV_GROUPS;
 return groups.map(group=>`<div class="nav-group"><p class="nav-label">${group.title}</p>${group.items.map(([id,symbol,label])=>`<button class="nav-item ${page===id||page==='project'&&id==='projects'||page==='trace'&&id==='workbench'?'active':''}" data-action="nav" data-page="${id}" ${page===id||page==='project'&&id==='projects'?'aria-current="page"':''}>${icon(symbol)}<span>${label}</span>${id==='workbench'&&activeRuns?`<span class="nav-running">${activeRuns} 运行中</span>`:''}${id==='roles'?icon(expandedRoles?'down':'chevron'):''}</button>${id==='roles'&&expandedRoles?`<div class="nav-role-tree" aria-label="核查角色">${ROLES.map(role=>`<button class="nav-role ${page==='roles'&&selectedRole===role.id?'selected':''}" data-role-nav="${role.id}" ${page==='roles'&&selectedRole===role.id?'aria-current="true"':''}><span class="role-state-dot ${esc(roleState(run,role.id))}" aria-hidden="true"></span><span>${role.name}</span><span class="sr-only">${statusLabels[roleState(run,role.id)]}</span></button>`).join('')}</div>`:''}`).join('')}</div>`).join('');
}
