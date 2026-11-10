// Review-Aware Scientific Contribution Graph (学术贡献知识图谱) — see docs/功能1.md
import {sessionCapability} from './online-core.mjs';

const TYPE_COLORS={Paper:'#1d4ed8',Contribution:'#7c3aed',Claim:'#0891b2',Evidence:'#059669',ReviewFinding:'#dc2626'};
const SUPPORT_LABEL={SUPPORTED:'审查支持',PARTIAL:'部分支持',QUESTIONED:'存在质疑',UNVERIFIED:'未核验'};

export class KnowledgeGraphWorkspace{
 constructor(h){this.h=h;this.data=null;this.loading=false;this.error='';this.filters={year:'',direction:'',venue:''};this.generation=0;this.selected=null;this.inspectorTab='detail';this.expanded=new Set();this.pinned=new Set();this.zoom=1;this.pan={x:0,y:0};this.query='';this.focusMode=false;this.compare=null;this.enableKg=true;this.focusProject=null;this.drag=null;}
 esc(v){return this.h.esc(v??'');}
 headers(json){let s='';try{s=sessionCapability();}catch{}return {'X-ArtiCheck-Client':'review-api',...(s?{'X-ArtiCheck-Session':s}:{}),...(json?{'Content-Type':'application/json'}:{})};}
 async api(path,payload){const res=await fetch('/v1/kg'+path,{method:payload===undefined?'GET':'POST',headers:this.headers(payload!==undefined),body:payload===undefined?undefined:JSON.stringify(payload),credentials:'same-origin'});let v;try{v=await res.json();}catch{throw Error('知识图谱服务暂未返回有效响应。');}if(!res.ok)throw Error(v?.error?.message||'知识图谱请求失败。');return v;}
 clear(){this.generation++;this.data=null;this.selected=null;this.compare=null;this.loading=false;this.error='';this.expanded.clear();this.pinned.clear();this.query='';this.focusMode=false;this.inspectorTab='detail';this.zoom=1;this.pan={x:0,y:0};this.filters={year:'',direction:'',venue:''};}
 async open(projectId){
  this.clear();
  this.h.navigate('knowledge-graph');
  const p=(this.h.projects?.()||[]).find(x=>x.id===projectId);
  return this.load(p?.online_report?.id&&this.enableKg?{assessment_id:p.online_report.id,project_id:p.id,title:p.title}:undefined);
 }
 async reload(){return this.load();}
 async load(payload){
  const version=++this.generation;
  this.loading=true;this.error='';this.h.render();
  try{
   const data=await this.api(payload?'/ingest':'/graph',payload);
   if(version!==this.generation)return;
   this.data=data;this.pinned=new Set(data.layout?.pinned||[]);
   if(!this.node(this.selected))this.selected=data.focus_paper_id||null;
  }catch(error){if(version===this.generation){this.data=null;this.error=error.message;}}
  finally{if(version===this.generation){this.loading=false;this.h.render();}}
 }
 matchingPapers(){
  return (this.data?.timeline||[]).filter(p=>Object.entries(this.filters).every(([key,value])=>!value||value===String(p[key]||'unknown')));
 }
 filterControls(){
  const e=v=>this.esc(v),papers=this.data?.timeline||[];
  return [['year','年份'],['direction','研究方向'],['venue','期刊 / 会议']].map(([key,label])=>{
   const values=[...new Set(papers.map(p=>String(p[key]||'unknown')))].sort((a,b)=>key==='year'?Number(b)-Number(a):a.localeCompare(b,'zh'));
   return `<label class="kg-filter"><span>${label}</span><select data-kg-filter="${key}"><option value="">全部</option>${values.map(v=>`<option value="${e(v)}" ${this.filters[key]===v?'selected':''}>${v==='unknown'?'未知':e(v)}</option>`).join('')}</select></label>`;
  }).join('');
 }
 node(id){return this.data?.nodes?.find(n=>n.id===id);}
 visibleNodes(){
  const d=this.data;if(!d)return [];
  const papers=new Set(this.matchingPapers().map(p=>p.paper_id));
  return d.nodes.filter(n=>{
   if(!papers.has(n.node_type==='Paper'?n.id:n.paper_id))return false;
   if(n.layer===1)return true;
   if(n.node_type==='Contribution')return this.expanded.has(n.paper_id);
   if(n.node_type==='Claim')return this.expanded.has(n.parent_id);
   return this.expanded.has(n.parent_id)&&this.expanded.has(n.contrib_id);
  });
 }
 neighbors(id){const s=new Set([id]);for(const e of this.data?.edges||[]){if(e.source===id)s.add(e.target);if(e.target===id)s.add(e.source);}return s;}
 render(){
  const e=v=>this.esc(v),d=this.data;
  const toolbar=`<div class="kg-toolbar"><div class="kg-toolbar-title"><span>当前账号的论文</span></div><div class="kg-toolbar-actions"><button type="button" class="btn small" data-kg-action="save-layout">保存布局</button><button type="button" class="btn small" data-kg-action="reset-view">重置视图</button></div></div><div class="kg-filters"><label class="kg-filter"><span>搜索</span><input type="search" data-kg-search value="${e(this.query)}" placeholder="论文、贡献或数据集"></label>${this.filterControls()}</div>`;
  if(this.loading&&!d)return `<section class="kg-workspace">${toolbar}<div class="kg-loading" role="status">正在读取知识图谱…</div></section>`;
  if(!d)return `<section class="kg-workspace">${toolbar}<div class="kg-empty"><h3>${this.error?'暂时无法读取图谱':'打开我的知识图谱'}</h3><p>${e(this.error||'从论文报告打开图谱，或加载已经保存的论文。')}</p><button class="btn primary" data-kg-action="load">加载我的图谱</button></div></section>`;
  const count=this.matchingPapers().length;
  return `<section class="kg-workspace">${toolbar}<div class="kg-stats"><span><strong>${count}</strong> / ${d.stats?.paper_count||0} 篇论文</span>${this.focusMode?'<button class="btn text small" data-kg-action="exit-focus">退出聚焦模式</button>':''}</div><div class="kg-main">${count?this.canvasView():'<div class="kg-empty">没有匹配的论文。可以调整筛选，或从论文报告打开一篇论文。</div>'}<aside class="kg-inspector">${this.inspector()}</aside></div>${this.compare?this.compareView():''}</section>`;
 }
 canvasView(){
  const e=v=>this.esc(v),visible=this.visibleNodes(),ids=new Set(visible.map(n=>n.id));
  const edges=(this.data.edges||[]).filter(edge=>ids.has(edge.source)&&ids.has(edge.target));
  const neighbors=this.selected?this.neighbors(this.selected):null,q=this.query.trim().toLowerCase();
  const hit=n=>!q||[n.full_title,n.label,...(n.datasets||[])].join(' ').toLowerCase().includes(q);
  const labels=new Map(),occupied=[];
  const priority=n=>n.id===this.selected?0:n.node_type==='Paper'?1:neighbors?.has(n.id)?2:3;
  for(const n of [...visible].sort((a,b)=>priority(a)-priority(b))){
   if(n.id!==this.selected&&!hit(n))continue;
   const label=Array.from(n.label||'').slice(0,24).join(''),w=Math.min(225,Math.max(30,Array.from(label).reduce((sum,char)=>sum+(char.codePointAt(0)>255?14:8),12)));
   const box={x:n.x-w/2,y:n.y+18,w,h:20};
   if(n.id!==this.selected&&occupied.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
   occupied.push(box);labels.set(n.id,label+(Array.from(n.label||'').length>24?'…':''));
  }
  const nodes=[...visible].sort((a,b)=>priority(b)-priority(a));
  return `<div class="kg-canvas" data-kg-canvas><svg class="kg-svg" data-kg-svg viewBox="0 0 1040 680" role="group" aria-label="学术贡献知识图谱"><g data-kg-viewport transform="translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})">${edges.map(edge=>{
   const a=this.node(edge.source),b=this.node(edge.target),active=edge.source===this.selected||edge.target===this.selected;
   return `<g class="kg-edge ${active?'active':this.selected?'dim':''}"><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>${active?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-5}" class="kg-edge-label">${e(edge.label)}</text>`:''}</g>`;
  }).join('')}${nodes.map(n=>{
   const r=n.node_type==='Paper'?17:n.node_type==='Contribution'?12:8,selected=n.id===this.selected;
   return `<g class="kg-node ${selected?'selected':!hit(n)||this.focusMode&&!neighbors?.has(n.id)?'dim':''}" data-kg-node="${e(n.id)}" transform="translate(${n.x} ${n.y})" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${e(n.full_title||n.label)}">${selected?`<circle class="kg-node-halo" r="${r+8}"/>`:''}<circle class="kg-node-mark" r="${r}" fill="${TYPE_COLORS[n.node_type]}"/>${labels.has(n.id)?`<text y="34" text-anchor="middle">${e(labels.get(n.id))}</text>`:''}<title>${e(n.full_title||n.label)}</title></g>`;
  }).join('')}</g></svg><div class="kg-legend">${Object.entries(TYPE_COLORS).map(([key,color])=>`<span><i style="background:${color}"></i>${{Paper:'论文',Contribution:'贡献',Claim:'声明',Evidence:'证据',ReviewFinding:'审查发现'}[key]}</span>`).join('')}<span class="hint">拖动平移 · 滚轮缩放 · 右键固定</span></div></div>`;
 }
 inspector(){
  const e=v=>this.esc(v),n=this.node(this.selected);

  const tabs=[['detail','节点详情'],['neighbors','邻近贡献'],['lineage','研究脉络']];
  const cid=n?.node_type==='Contribution'?n.id:n?.contrib_id||n?.parent_id;
  const cmps=(this.data.comparisons||[]).filter(c=>n&&(c.source_id===n.id||c.target_id===n.id||(n.node_type==='Paper'&&(c.source_paper_id===n.id||c.target_paper_id===n.id))));
  let body='';
  if(this.inspectorTab!=='lineage'&&!n){
   body='<p class="kg-notice">选择一个节点，右侧会显示完整名称与详情。</p>';
  }else if(this.inspectorTab==='detail'){
   if(n.node_type==='Paper')body=`<h3>${e(n.full_title)}</h3><dl class="kg-dl"><div><dt>年份</dt><dd>${e(n.year||'未知')}</dd></div><div><dt>研究方向</dt><dd>${e(n.direction||'未知')}</dd></div><div><dt>期刊 / 会议</dt><dd>${e(n.venue||'未知')}</dd></div></dl><p>${e(n.abstract)}</p><div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起':'展开'}贡献</button></div>`;
   else if(n.node_type==='Contribution')body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${e(n.paper_title)} · <span class="kg-support ${e(n.review_support_level)}">${e(SUPPORT_LABEL[n.review_support_level]||'')}</span>${Number.isFinite(n.confidence)?' · 置信度 '+Math.round(n.confidence*100)+'%':''}</p><p>${e(n.summary)}</p><dl class="kg-dl">${[['研究问题',n.problem],['方法',n.method],['适用任务',n.applicable_task],['数据集',(n.datasets||[]).join('、')],['指标',(n.metrics||[]).join('、')],['基线',(n.baselines||[]).join('、')],['关键提升',n.key_delta],['局限',n.limitations]].filter(([,v])=>v).map(([k,v])=>`<div><dt>${k}</dt><dd>${e(v)}</dd></div>`).join('')}</dl><div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起声明':'展开声明与证据'}</button><button class="btn small" data-kg-action="focus">聚焦此贡献</button></div>`;
   else body=`<h3>${e({Claim:'实验声明',Evidence:'原文证据',ReviewFinding:'审查发现'}[n.node_type])}</h3><p>${e(n.full_title)}</p><dl class="kg-dl">${[['数据集',n.dataset],['指标',n.metric],['报告值',n.reported_value],['条件',n.condition],['支持度',SUPPORT_LABEL[n.support_status]],['出处',n.section?n.section+' · 第 '+n.page+' 页':''],['严重程度',n.severity]].filter(([,v])=>v).map(([k,v])=>`<div><dt>${k}</dt><dd>${e(v)}</dd></div>`).join('')}</dl>${n.node_type==='Claim'?`<button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起证据':'展开证据与发现'}</button>`:''}`;
  }else if(this.inspectorTab==='neighbors'){
   const list=cmps.filter(c=>c.source_paper_id!==c.target_paper_id).sort((a,b)=>b.overlap_score-a.overlap_score);
   body=list.map(c=>{const other=c.source_id===cid||c.source_paper_id===n.id?{id:c.target_id,t:c.target_title,p:c.target_paper_title}:{id:c.source_id,t:c.source_title,p:c.source_paper_title};return `<article class="kg-cmp-card"><header><button class="link" data-kg-select="${e(other.id)}">${e(other.t)}</button><span>${Math.round(c.overlap_score*100)}%</span></header><p class="kg-meta">${e(other.p)} · ${e(c.relation_type)}</p><p>${e(c.explanation)}</p><button class="btn small" data-kg-compare="${e(c.id)}">学习对比</button></article>`;}).join('')||'<p class="kg-notice">暂无跨论文邻近贡献。</p>';
  }else{
   const pid=n?.node_type==='Paper'?n.id:n?.paper_id;
   body=`<ol class="kg-lineage">${this.matchingPapers().map(t=>`<li class="${t.paper_id===pid?'current':''}"><span>${e(t.year||'未知年份')}</span><button class="link" data-kg-select="${e(t.paper_id)}">${e(t.title)}</button></li>`).join('')}</ol>`;
  }
  return `<div class="kg-insp-tabs">${tabs.map(([k,l])=>`<button type="button" class="${this.inspectorTab===k?'active':''}" data-kg-tab="${k}">${l}</button>`).join('')}</div><div class="kg-insp-body">${body}</div>`;
 }
 compareView(){
  const e=v=>this.esc(v),c=(this.data.comparisons||[]).find(x=>x.id===this.compare);if(!c)return '';
  return `<div class="kg-compare-backdrop" data-kg-action="close-compare"></div><section class="kg-compare" role="dialog" aria-label="双贡献并排对比"><header><div><span class="online-kicker">双贡献并排对比</span><h2>${e(c.source_title)} ⇄ ${e(c.target_title)}</h2></div><button class="btn small" data-kg-action="close-compare">关闭</button></header><p>${e(c.explanation)}</p><table class="kg-compare-table"><thead><tr><th>维度</th><th>${e(c.source_paper_title)}</th><th>${e(c.target_paper_title)}</th></tr></thead><tbody>${(c.dimensions||[]).map(d=>`<tr><th>${e(d.dimension)}</th><td>${e(d.source_value)}</td><td>${e(d.target_value)}</td></tr>`).join('')}<tr><th>证据链</th><td><blockquote>${e(c.evidence_chain?.source_quote)}</blockquote></td><td><blockquote>${e(c.evidence_chain?.target_quote)}</blockquote></td></tr></tbody></table></section>`;
 }
 afterRender(){
  const svg=document.querySelector('[data-kg-svg]');if(!svg||svg.dataset.bound)return;svg.dataset.bound='1';
  const pt=ev=>{const r=svg.getBoundingClientRect();return {x:(ev.clientX-r.left)*(1040/r.width),y:(ev.clientY-r.top)*(680/r.height)};};
  svg.addEventListener('wheel',ev=>{ev.preventDefault();const p=pt(ev),k=ev.deltaY<0?1.12:1/1.12,z=Math.min(3,Math.max(.35,this.zoom*k));this.pan.x=p.x-(p.x-this.pan.x)*(z/this.zoom);this.pan.y=p.y-(p.y-this.pan.y)*(z/this.zoom);this.zoom=z;this.applyTransform();},{passive:false});
  svg.addEventListener('pointerdown',ev=>{const g=ev.target.closest('[data-kg-node]'),p=pt(ev);if(ev.button===2)return;this.drag=g?{node:g.dataset.kgNode,start:p,moved:false}:{pan:true,start:p,origin:{...this.pan}};svg.setPointerCapture(ev.pointerId);});
  svg.addEventListener('pointermove',ev=>{if(!this.drag)return;const p=pt(ev),dx=p.x-this.drag.start.x,dy=p.y-this.drag.start.y;if(Math.abs(dx)+Math.abs(dy)>3)this.drag.moved=true;if(this.drag.pan){this.pan={x:this.drag.origin.x+dx,y:this.drag.origin.y+dy};this.applyTransform();}else if(this.drag.moved){const n=this.node(this.drag.node);if(!n)return;n.x+=dx/this.zoom;n.y+=dy/this.zoom;this.drag.start=p;this.pinned.add(n.id);
    svg.querySelector(`[data-kg-node="${CSS.escape(n.id)}"]`)?.setAttribute('transform',`translate(${n.x} ${n.y})`);
   }});
  svg.addEventListener('pointercancel',()=>{this.drag=null;});
  svg.addEventListener('pointerup',()=>{const d=this.drag;this.drag=null;if(d?.node){if(d.moved)this.redrawGraph();else this.select(d.node);}});
  svg.addEventListener('keydown',ev=>{const node=ev.target.closest('[data-kg-node]');if(!node||!['Enter',' '].includes(ev.key))return;ev.preventDefault();this.select(node.dataset.kgNode);document.querySelector(`[data-kg-node="${CSS.escape(node.dataset.kgNode)}"]`)?.focus();});
  svg.addEventListener('contextmenu',ev=>{const g=ev.target.closest('[data-kg-node]');if(!g)return;ev.preventDefault();const id=g.dataset.kgNode;this.pinned.has(id)?this.pinned.delete(id):this.pinned.add(id);this.h.toast?.(this.pinned.has(id)?'节点已固定':'节点已取消固定');this.redrawGraph();});
 }
 applyTransform(){const v=document.querySelector('[data-kg-viewport]');if(v)v.setAttribute('transform',`translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})`);}
 redrawGraph(){const c=document.querySelector('[data-kg-canvas]');if(!c){this.h.render();return;}const t=document.createElement('template');t.innerHTML=this.canvasView();const next=t.content.firstElementChild;c.replaceWith(next);this.afterRender();}
 select(id){const n=this.node(id);if(!n)return;this.selected=id;this.inspectorTab='detail';if(n.paper_id)this.expanded.add(n.paper_id);this.h.render();}
 toggleExpand(id){this.expanded.has(id)?this.expanded.delete(id):this.expanded.add(id);this.selected=id;this.h.render();}
 async action(a){
  if(a==='load')return this.open(null);
  if(a==='reset-view'){this.zoom=1;this.pan={x:0,y:0};this.focusMode=false;this.query='';this.h.render();return;}
  if(a==='focus'){this.focusMode=true;this.h.render();return;}
  if(a==='exit-focus'){this.focusMode=false;this.h.render();return;}
  if(a==='close-compare'){this.compare=null;this.h.render();return;}
  if(a==='save-layout'){const positions={};for(const n of this.data?.nodes||[])if(this.pinned.has(n.id))positions[n.id]={x:Math.round(n.x),y:Math.round(n.y)};try{await this.api('/layout',{positions,pinned:[...this.pinned]});this.h.toast?.('布局已保存');}catch(err){this.h.toast?.('布局保存失败：'+err.message);}return;}
 }
 bind(){
  document.addEventListener('click',async ev=>{
   const copy=ev.target.closest('[data-copy-cmd]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copyCmd);this.h.toast?.('命令已复制');}catch{this.h.toast?.('复制失败，请手动选择命令');}return;}
   const kg=ev.target.closest('[data-open-kg]');if(kg){ev.preventDefault();ev.stopPropagation();this.open(kg.dataset.openKg);return;}
   const t=ev.target.closest('[data-kg-action],[data-kg-tab],[data-kg-select],[data-kg-expand],[data-kg-compare]');if(!t)return;
   if(t.dataset.kgTab){this.inspectorTab=t.dataset.kgTab;return this.h.render();}
   if(t.dataset.kgSelect){this.compare=null;return this.select(t.dataset.kgSelect);}
   if(t.dataset.kgExpand)return this.toggleExpand(t.dataset.kgExpand);
   if(t.dataset.kgCompare){this.compare=t.dataset.kgCompare;return this.h.render();}
   if(t.dataset.kgAction)return this.action(t.dataset.kgAction);
  },true);
  document.addEventListener('input',ev=>{if(ev.target.matches?.('[data-kg-search]')){this.query=ev.target.value;this.redrawGraph();}});
  document.addEventListener('change',ev=>{
   const key=ev.target.dataset?.kgFilter;
   if(!Object.hasOwn(this.filters,key))return;
   this.filters[key]=ev.target.value;
   if(!this.visibleNodes().some(node=>node.id===this.selected)){this.selected=null;this.compare=null;this.focusMode=false;}
   this.h.render();
  });
 }
}
