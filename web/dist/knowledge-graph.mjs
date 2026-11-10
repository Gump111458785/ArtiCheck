// Review-Aware Scientific Contribution Graph (学术贡献知识图谱) — see docs/功能1.md
import {sessionCapability} from './online-core.mjs';

const TYPE_COLORS={Paper:'#1d4ed8',Contribution:'#7c3aed',Claim:'#0891b2',Evidence:'#059669',ReviewFinding:'#dc2626'};
const EDGE_COLORS={HAS_CONTRIBUTION:'#94a3b8',HAS_CLAIM:'#a5b4fc',SUPPORTED_BY:'#6ee7b7',QUESTIONED_BY:'#fca5a5',POTENTIAL_CONFLICT:'#ef4444',EXTENDS:'#2563eb',COMPLEMENTARY:'#10b981',SIMILAR:'#f59e0b'};
const SUPPORT_LABEL={SUPPORTED:'审查支持',PARTIAL:'部分支持',QUESTIONED:'存在质疑',UNVERIFIED:'未核验'};
const CONFLICT_LABEL={NOVELTY_OVERLAP:'创新点重合',PARTIAL_OVERLAP:'部分重合',CONTRADICTORY_RESULT:'结果矛盾',METRIC_INCONSISTENCY:'指标不一致',INSUFFICIENT_EVIDENCE:'证据不足',NONE:'无冲突'};
const VERDICT_LABEL={CONFIRMED_CONFLICT:'候选冲突',REJECTED_CONFLICT:'已排除',NEEDS_MORE_EVIDENCE:'需更多证据'};

export class KnowledgeGraphWorkspace{
 constructor(h){this.h=h;this.data=null;this.loading=false;this.error='';this.scope='COMBINED';this.view='graph';this.selected=null;this.inspectorTab='detail';this.expanded=new Set();this.pinned=new Set();this.zoom=1;this.pan={x:0,y:0};this.query='';this.focusMode=false;this.compare=null;this.enableKg=true;this.focusProject=null;this.drag=null;}
 esc(v){return this.h.esc(v??'');}
 headers(json){let s='';try{s=sessionCapability();}catch{}return {'X-ArtiCheck-Client':'review-api',...(s?{'X-ArtiCheck-Session':s}:{}),...(json?{'Content-Type':'application/json'}:{})};}
 async api(path,payload){const res=await fetch('/v1/kg'+path,{method:payload===undefined?'GET':'POST',headers:this.headers(payload!==undefined),body:payload===undefined?undefined:JSON.stringify(payload),credentials:'same-origin'});let v;try{v=await res.json();}catch{throw Error('知识图谱服务暂未返回有效响应。');}if(!res.ok)throw Error(v?.error?.message||'知识图谱请求失败。');return v;}
 async open(projectId){
  this.focusProject=projectId||null;this.selected=null;this.compare=null;this.h.navigate('knowledge-graph');
  const p=(this.h.projects?.()||[]).find(x=>x.id===projectId);
  this.loading=true;this.error='';this.h.render();
  try{
   if(p?.online_report?.id&&this.enableKg)this.setData(await this.api('/ingest',{assessment_id:p.online_report.id,project_id:p.id,title:p.title}));
   else this.setData(await this.api('/graph?scope='+this.scope));
  }catch(err){this.error=err.message;this.setData(this.localFallback(p));}
  finally{this.loading=false;this.h.render();}
 }
 async reload(){this.loading=true;this.h.render();try{this.setData(await this.api('/graph?scope='+this.scope+(this.data?.focus_paper_id?'&paper_id='+encodeURIComponent(this.data.focus_paper_id):'')));this.error='';}catch(err){this.error=err.message;if(!this.data)this.setData(this.localFallback());}finally{this.loading=false;this.h.render();}}
 setData(d){this.data=d;this.pinned=new Set(d?.layout?.pinned||[]);const focus=d?.focus_paper_id;if(focus){this.expanded.add(focus);if(!this.selected)this.selected=focus;}}
 localFallback(p){
  const papers=(this.h.projects?.()||[]).filter(x=>x.online_report?.review).slice(0,8);
  if(p&&!papers.includes(p))papers.push(p);
  const nodes=[],edges=[];
  papers.forEach((x,i)=>{const rv=x.online_report?.review||{},pid='paper_local_'+x.id,a=2*Math.PI*i/Math.max(1,papers.length),px=520+160*Math.cos(a),py=340+160*Math.sin(a);
   nodes.push({id:pid,node_type:'Paper',label:(rv.paper_title||x.title||'论文').slice(0,38),full_title:rv.paper_title||x.title,year:null,visibility:'PRIVATE',review_status:'UNREVIEWED',abstract:rv.summary||'',x:px,y:py,layer:1,project_id:x.id});
   (rv.paper_contributions||[rv.summary].filter(Boolean)).slice(0,3).forEach((c,j)=>{const cid=pid+'_c'+j;nodes.push({id:cid,paper_id:pid,paper_title:x.title,node_type:'Contribution',label:String(c).slice(0,30),full_title:String(c),summary:String(c),datasets:[],metrics:[],baselines:[],claims:[],review_support_level:'UNVERIFIED',x:px+90*Math.cos(a+j*.5),y:py+90*Math.sin(a+j*.5),layer:2});edges.push({id:pid+'-'+cid,source:pid,target:cid,edge_type:'HAS_CONTRIBUTION',label:'包含核心贡献',layer:1});});
  });
  const focus=p?'paper_local_'+p.id:nodes[0]?.id||'';
  return {scope:'PRIVATE',focus_paper_id:focus,papers:[],nodes,edges,comparisons:[],timeline:nodes.filter(n=>n.node_type==='Paper').map(n=>({paper_id:n.id,title:n.full_title,year:n.year,visibility:'PRIVATE',review_status:'UNREVIEWED',contributions:nodes.filter(c=>c.paper_id===n.id).map(c=>({id:c.id,title:c.full_title,type:'METHOD',key_delta:c.summary,support:'UNVERIFIED'}))})),layout:{},stats:{paper_count:papers.length,contribution_count:nodes.filter(n=>n.node_type==='Contribution').length,claim_count:0,conflict_count:0},offline:true};
 }
 node(id){return this.data?.nodes?.find(n=>n.id===id);}
 visibleNodes(){
  const d=this.data;if(!d)return [];
  return d.nodes.filter(n=>{
   if(n.layer===1)return true;
   if(n.node_type==='Contribution')return true;
   if(n.node_type==='Claim')return this.expanded.has(n.parent_id);
   return this.expanded.has(n.parent_id)&&this.expanded.has(n.contrib_id);
  });
 }
 neighbors(id){const s=new Set([id]);for(const e of this.data?.edges||[]){if(e.source===id)s.add(e.target);if(e.target===id)s.add(e.source);}return s;}
 render(){
  const e=v=>this.esc(v),d=this.data;
  const toolbar=`<div class="kg-toolbar"><div class="kg-scope" role="group" aria-label="图谱范围">${[['GLOBAL','总体图谱'],['PRIVATE','我的私有图谱'],['COMBINED','我的+总体图谱']].map(([k,l])=>`<button type="button" class="${this.scope===k?'active':''}" data-kg-scope="${k}">${l}</button>`).join('')}</div><div class="kg-view" role="group">${[['graph','星图视图'],['timeline','研究脉络']].map(([k,l])=>`<button type="button" class="${this.view===k?'active':''}" data-kg-view="${k}">${l}</button>`).join('')}</div><label class="kg-search"><input type="search" data-kg-search value="${e(this.query)}" placeholder="搜索论文、贡献、数据集…"></label><label class="kg-switch"><input type="checkbox" data-kg-switch="enableKg" ${this.enableKg?'checked':''}><span>A · 生成知识图谱</span></label><button type="button" class="btn small" data-kg-action="import">添加论文引用</button><button type="button" class="btn small" data-kg-action="save-layout">保存布局</button><button type="button" class="btn small" data-kg-action="reset-view">重置视图</button></div>`;
  if(this.loading&&!d)return `<section class="kg-workspace">${toolbar}<div class="kg-loading" role="status"><span class="online-spinner"></span>正在构建论文 → 贡献 → 声明 → 证据图谱…</div></section>`;
  if(!d)return `<section class="kg-workspace">${toolbar}<div class="kg-empty"><h2>学术贡献知识图谱</h2><p>在任意已审查论文的报告页点击“探索学术贡献知识图谱”，或直接加载总体图谱。</p><button class="btn primary" data-kg-action="load">加载总体图谱</button></div></section>`;
  const st=d.stats||{};
  return `<section class="kg-workspace">${toolbar}${this.error?`<p class="kg-notice">${e(d.offline?'云端图谱服务暂不可用，已用本地审查记录生成简化图谱：':'')}${e(this.error)}</p>`:''}<div class="kg-stats"><span><strong>${st.paper_count||0}</strong>论文</span><span><strong>${st.contribution_count||0}</strong>贡献</span><span><strong>${st.claim_count||0}</strong>声明</span><span class="danger"><strong>${st.conflict_count||0}</strong>潜在冲突</span>${this.focusMode?'<button class="btn text small" data-kg-action="exit-focus">退出聚焦模式</button>':''}</div><div class="kg-main">${this.view==='timeline'?this.timelineView():this.canvasView()}<aside class="kg-inspector">${this.inspector()}</aside></div>${this.compare?this.compareView():''}</section>`;
 }
 canvasView(){
  const e=v=>this.esc(v),vis=this.visibleNodes(),ids=new Set(vis.map(n=>n.id));
  const q=this.query.trim().toLowerCase(),hit=q?new Set(vis.filter(n=>`${n.full_title} ${n.label} ${(n.datasets||[]).join(' ')}`.toLowerCase().includes(q)).map(n=>n.id)):null;
  const focusSet=this.focusMode&&this.selected?this.neighbors(this.selected):null;
  const edges=(this.data.edges||[]).filter(x=>ids.has(x.source)&&ids.has(x.target));
  const dim=id=>(focusSet&&!focusSet.has(id))||(hit&&!hit.has(id));
  const pos=id=>this.node(id);
  return `<div class="kg-canvas" data-kg-canvas><svg class="kg-svg" data-kg-svg viewBox="0 0 1040 680" role="img" aria-label="学术贡献知识图谱"><defs><marker id="kg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#94a3b8"/></marker></defs><g data-kg-viewport transform="translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})">${edges.map(x=>{const a=pos(x.source),b=pos(x.target),rel=x.layer===2;return `<g class="kg-edge ${rel?'relation':''} ${dim(x.source)&&dim(x.target)?'dim':''}" data-kg-edge="${e(x.id)}"><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${EDGE_COLORS[x.edge_type]||'#cbd5e1'}" stroke-width="${rel?2.2:1.2}" ${x.edge_type==='POTENTIAL_CONFLICT'?'stroke-dasharray="6 4"':''} marker-end="url(#kg-arrow)"/>${rel?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-4}" class="kg-edge-label">${e(x.label)}</text>`:''}</g>`;}).join('')}${vis.map(n=>{const r=n.node_type==='Paper'?22:n.node_type==='Contribution'?15:9,sel=this.selected===n.id;return `<g class="kg-node type-${n.node_type} ${sel?'selected':''} ${dim(n.id)?'dim':''} ${this.pinned.has(n.id)?'pinned':''}" data-kg-node="${e(n.id)}" transform="translate(${n.x} ${n.y})"><circle r="${r}" fill="${TYPE_COLORS[n.node_type]}" ${n.visibility==='GLOBAL'&&n.node_type==='Paper'?'stroke-dasharray="3 2"':''}/>${this.pinned.has(n.id)?`<circle r="4" cx="${r-2}" cy="${-r+2}" fill="#f59e0b"/>`:''}<text y="${r+13}" text-anchor="middle">${e(n.label)}</text><title>${e(n.full_title)}</title></g>`;}).join('')}</g></svg><div class="kg-legend">${Object.entries(TYPE_COLORS).map(([k,c])=>`<span><i style="background:${c}"></i>${{Paper:'论文',Contribution:'贡献',Claim:'声明',Evidence:'证据',ReviewFinding:'审查发现'}[k]}</span>`).join('')}<span class="hint">滚轮缩放 · 拖拽画布平移 · 拖动节点 · 双击展开 · 右键固定</span></div></div>`;
 }
 timelineView(){
  const e=v=>this.esc(v),rows=this.data.timeline||[];
  return `<div class="kg-timeline">${rows.map(t=>`<article class="kg-tl-item ${t.paper_id===this.data.focus_paper_id?'focus':''}"><div class="kg-tl-year">${e(t.year)}</div><div class="kg-tl-body"><header><h3><button class="link" data-kg-select="${e(t.paper_id)}">${e(t.title)}</button></h3><span class="kg-tag ${t.visibility==='GLOBAL'?'global':'private'}">${t.visibility==='GLOBAL'?'总体':'私有'}</span></header><ul>${(t.contributions||[]).map(c=>`<li><button class="link" data-kg-select="${e(c.id)}">${e(c.title)}</button><span class="kg-support ${e(c.support)}">${e(SUPPORT_LABEL[c.support]||c.support)}</span><p>${e(c.key_delta)}</p></li>`).join('')}</ul></div></article>`).join('')||'<p class="kg-notice">暂无脉络数据。</p>'}</div>`;
 }
 inspector(){
  const e=v=>this.esc(v),n=this.node(this.selected);
  if(!n)return `<div class="kg-insp-empty"><h3>选择一个节点</h3><p>点击论文或贡献节点查看详情、潜在冲突、邻近贡献与研究脉络。</p></div>`;
  const tabs=[['detail','贡献详情'],['conflicts','潜在冲突'],['neighbors','邻近贡献'],['lineage','研究脉络']];
  const cid=n.node_type==='Contribution'?n.id:n.contrib_id||n.parent_id;
  const cmps=(this.data.comparisons||[]).filter(c=>c.source_id===n.id||c.target_id===n.id||(n.node_type==='Paper'&&(c.source_paper_id===n.id||c.target_paper_id===n.id)));
  let body='';
  if(this.inspectorTab==='detail'){
   if(n.node_type==='Paper')body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${e(n.venue||'')} · ${e(n.year)} · ${n.visibility==='GLOBAL'?'已加入总体图谱':'私有'}</p><p>${e(n.abstract)}</p><div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起':'展开'}贡献</button>${n.editable_visibility?`<button class="btn small" data-kg-visibility="${e(n.id)}" data-vis="${n.visibility==='GLOBAL'?'PRIVATE':'GLOBAL'}">${n.visibility==='GLOBAL'?'设为私有':'加入总体图谱'}</button>`:''}</div>`;
   else if(n.node_type==='Contribution')body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${e(n.paper_title)} · <span class="kg-support ${e(n.review_support_level)}">${e(SUPPORT_LABEL[n.review_support_level]||'')}</span>${Number.isFinite(n.confidence)?' · 置信度 '+Math.round(n.confidence*100)+'%':''}</p><p>${e(n.summary)}</p><dl class="kg-dl">${[['研究问题',n.problem],['方法',n.method],['适用任务',n.applicable_task],['数据集',(n.datasets||[]).join('、')],['指标',(n.metrics||[]).join('、')],['基线',(n.baselines||[]).join('、')],['关键提升',n.key_delta],['局限',n.limitations]].filter(([,v])=>v).map(([k,v])=>`<div><dt>${k}</dt><dd>${e(v)}</dd></div>`).join('')}</dl><div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起声明':'展开声明与证据'}</button><button class="btn small" data-kg-action="focus">聚焦此贡献</button></div>`;
   else body=`<h3>${e({Claim:'实验声明',Evidence:'原文证据',ReviewFinding:'审查发现'}[n.node_type])}</h3><p>${e(n.full_title)}</p><dl class="kg-dl">${[['数据集',n.dataset],['指标',n.metric],['报告值',n.reported_value],['条件',n.condition],['支持度',SUPPORT_LABEL[n.support_status]],['出处',n.section?n.section+' · 第 '+n.page+' 页':''],['严重程度',n.severity]].filter(([,v])=>v).map(([k,v])=>`<div><dt>${k}</dt><dd>${e(v)}</dd></div>`).join('')}</dl>${n.node_type==='Claim'?`<button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起证据':'展开证据与发现'}</button>`:''}`;
  }else if(this.inspectorTab==='conflicts'){
   const list=cmps.filter(c=>c.relation_type==='POTENTIAL_CONFLICT'||c.conflict_type!=='NONE');
   body=list.map(c=>`<article class="kg-cmp-card ${e(c.conflict_type)}"><header><strong>${e(CONFLICT_LABEL[c.conflict_type]||c.conflict_type)}</strong><span>重合度 ${Math.round(c.overlap_score*100)}% · ${e(VERDICT_LABEL[c.verdict]||c.verdict)}${c.user_verified?' · 已人工复核':''}</span></header><p>${e(c.explanation)}</p><div class="kg-insp-actions"><button class="btn small primary" data-kg-compare="${e(c.id)}">并排对比</button><button class="btn small" data-kg-verify="${e(c.id)}" data-decision="confirm">确认</button><button class="btn small" data-kg-verify="${e(c.id)}" data-decision="dismiss">驳回</button><button class="btn small" data-kg-verify="${e(c.id)}" data-decision="more_evidence">需更多证据</button></div></article>`).join('')||'<p class="kg-notice">未检测到与该节点相关的候选冲突。</p>';
  }else if(this.inspectorTab==='neighbors'){
   const list=cmps.filter(c=>c.source_paper_id!==c.target_paper_id).sort((a,b)=>b.overlap_score-a.overlap_score);
   body=list.map(c=>{const other=c.source_id===cid||c.source_paper_id===n.id?{id:c.target_id,t:c.target_title,p:c.target_paper_title}:{id:c.source_id,t:c.source_title,p:c.source_paper_title};return `<article class="kg-cmp-card"><header><button class="link" data-kg-select="${e(other.id)}">${e(other.t)}</button><span>${Math.round(c.overlap_score*100)}%</span></header><p class="kg-meta">${e(other.p)} · ${e(c.relation_type)}</p><p>${e(c.explanation)}</p><button class="btn small" data-kg-compare="${e(c.id)}">学习对比</button></article>`;}).join('')||'<p class="kg-notice">暂无跨论文邻近贡献。</p>';
  }else{
   const pid=n.node_type==='Paper'?n.id:n.paper_id;
   body=`<ol class="kg-lineage">${(this.data.timeline||[]).map(t=>`<li class="${t.paper_id===pid?'current':''}"><span>${e(t.year)}</span><button class="link" data-kg-select="${e(t.paper_id)}">${e(t.title)}</button></li>`).join('')}</ol>`;
  }
  return `<div class="kg-insp-tabs">${tabs.map(([k,l])=>`<button type="button" class="${this.inspectorTab===k?'active':''}" data-kg-tab="${k}">${l}</button>`).join('')}</div><div class="kg-insp-body">${body}</div>`;
 }
 compareView(){
  const e=v=>this.esc(v),c=(this.data.comparisons||[]).find(x=>x.id===this.compare);if(!c)return '';
  return `<div class="kg-compare-backdrop" data-kg-action="close-compare"></div><section class="kg-compare" role="dialog" aria-label="双贡献并排对比"><header><div><span class="online-kicker">双贡献并排对比 · ${e(CONFLICT_LABEL[c.conflict_type]||c.relation_type)}</span><h2>${e(c.source_title)} ⇄ ${e(c.target_title)}</h2></div><button class="btn small" data-kg-action="close-compare">关闭</button></header><p>${e(c.explanation)}</p><table class="kg-compare-table"><thead><tr><th>维度</th><th>${e(c.source_paper_title)}</th><th>${e(c.target_paper_title)}</th></tr></thead><tbody>${(c.dimensions||[]).map(d=>`<tr><th>${e(d.dimension)}</th><td>${e(d.source_value)}</td><td>${e(d.target_value)}</td></tr>`).join('')}<tr><th>证据链</th><td><blockquote>${e(c.evidence_chain?.source_quote)}</blockquote></td><td><blockquote>${e(c.evidence_chain?.target_quote)}</blockquote></td></tr></tbody></table><div class="kg-insp-actions"><button class="btn primary small" data-kg-verify="${e(c.id)}" data-decision="confirm">确认冲突</button><button class="btn small" data-kg-verify="${e(c.id)}" data-decision="dismiss">驳回</button><button class="btn small" data-kg-verify="${e(c.id)}" data-decision="more_evidence">需更多证据</button></div></section>`;
 }
 afterRender(){
  const svg=document.querySelector('[data-kg-svg]');if(!svg||svg.dataset.bound)return;svg.dataset.bound='1';
  const pt=ev=>{const r=svg.getBoundingClientRect();return {x:(ev.clientX-r.left)*(1040/r.width),y:(ev.clientY-r.top)*(680/r.height)};};
  svg.addEventListener('wheel',ev=>{ev.preventDefault();const p=pt(ev),k=ev.deltaY<0?1.12:1/1.12,z=Math.min(3,Math.max(.35,this.zoom*k));this.pan.x=p.x-(p.x-this.pan.x)*(z/this.zoom);this.pan.y=p.y-(p.y-this.pan.y)*(z/this.zoom);this.zoom=z;this.applyTransform();},{passive:false});
  svg.addEventListener('pointerdown',ev=>{const g=ev.target.closest('[data-kg-node]'),p=pt(ev);if(ev.button===2)return;this.drag=g?{node:g.dataset.kgNode,start:p,moved:false}:{pan:true,start:p,origin:{...this.pan}};svg.setPointerCapture(ev.pointerId);});
  svg.addEventListener('pointermove',ev=>{if(!this.drag)return;const p=pt(ev),dx=p.x-this.drag.start.x,dy=p.y-this.drag.start.y;if(Math.abs(dx)+Math.abs(dy)>3)this.drag.moved=true;if(this.drag.pan){this.pan={x:this.drag.origin.x+dx,y:this.drag.origin.y+dy};this.applyTransform();}else if(this.drag.moved){const n=this.node(this.drag.node);if(!n)return;n.x+=dx/this.zoom;n.y+=dy/this.zoom;this.drag.start=p;this.pinned.add(n.id);this.redrawGraph();}});
  svg.addEventListener('pointerup',()=>{const d=this.drag;this.drag=null;if(d?.node&&!d.moved){this.select(d.node);}});
  svg.addEventListener('dblclick',ev=>{const g=ev.target.closest('[data-kg-node]');if(g)this.toggleExpand(g.dataset.kgNode);});
  svg.addEventListener('contextmenu',ev=>{const g=ev.target.closest('[data-kg-node]');if(!g)return;ev.preventDefault();const id=g.dataset.kgNode;this.pinned.has(id)?this.pinned.delete(id):this.pinned.add(id);this.h.toast?.(this.pinned.has(id)?'节点已固定':'节点已取消固定');this.redrawGraph();});
 }
 applyTransform(){const v=document.querySelector('[data-kg-viewport]');if(v)v.setAttribute('transform',`translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})`);}
 redrawGraph(){const c=document.querySelector('[data-kg-canvas]');if(!c){this.h.render();return;}const t=document.createElement('template');t.innerHTML=this.canvasView();const next=t.content.firstElementChild;c.replaceWith(next);this.afterRender();}
 select(id){this.selected=id;if(this.inspectorTab!=='detail'&&!this.node(id))this.inspectorTab='detail';this.h.render();}
 toggleExpand(id){this.expanded.has(id)?this.expanded.delete(id):this.expanded.add(id);if(this.node(id)?.node_type==='Paper'){}this.selected=id;this.h.render();}
 async action(a){
  if(a==='load')return this.open(null);
  if(a==='reset-view'){this.zoom=1;this.pan={x:0,y:0};this.focusMode=false;this.query='';this.h.render();return;}
  if(a==='focus'){this.focusMode=true;this.h.render();return;}
  if(a==='exit-focus'){this.focusMode=false;this.h.render();return;}
  if(a==='close-compare'){this.compare=null;this.h.render();return;}
  if(a==='save-layout'){const positions={};for(const n of this.data?.nodes||[])if(this.pinned.has(n.id))positions[n.id]={x:Math.round(n.x),y:Math.round(n.y)};try{await this.api('/layout',{positions,pinned:[...this.pinned],scope:this.scope});this.h.toast?.('布局已保存');}catch(err){this.h.toast?.('布局保存失败：'+err.message);}return;}
  if(a==='import'){const q=prompt('输入论文标题、DOI 或 arXiv 编号，作为待补充的引用记录');if(!q)return;this.loading=true;this.h.render();try{this.setData(await this.api('/import-external',{query:q}));this.error='';this.h.toast?.('已添加论文引用');}catch(err){this.h.toast?.(err.message);}finally{this.loading=false;this.h.render();}}
 }
 bind(){
  document.addEventListener('click',async ev=>{
   const copy=ev.target.closest('[data-copy-cmd]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copyCmd);this.h.toast?.('命令已复制');}catch{this.h.toast?.('复制失败，请手动选择命令');}return;}
   const kg=ev.target.closest('[data-open-kg]');if(kg){ev.preventDefault();ev.stopPropagation();this.open(kg.dataset.openKg);return;}
   const t=ev.target.closest('[data-kg-scope],[data-kg-view],[data-kg-action],[data-kg-tab],[data-kg-select],[data-kg-expand],[data-kg-compare],[data-kg-verify],[data-kg-visibility]');if(!t)return;
   if(t.dataset.kgScope){this.scope=t.dataset.kgScope;return this.reload();}
   if(t.dataset.kgView){this.view=t.dataset.kgView;return this.h.render();}
   if(t.dataset.kgTab){this.inspectorTab=t.dataset.kgTab;return this.h.render();}
   if(t.dataset.kgSelect){this.compare=null;return this.select(t.dataset.kgSelect);}
   if(t.dataset.kgExpand)return this.toggleExpand(t.dataset.kgExpand);
   if(t.dataset.kgCompare){this.compare=t.dataset.kgCompare;return this.h.render();}
   if(t.dataset.kgVerify){try{await this.api('/verify-conflict',{comparison_id:t.dataset.kgVerify,decision:t.dataset.decision});this.h.toast?.('复核结论已记录');await this.reload();}catch(err){this.h.toast?.(err.message);}return;}
   if(t.dataset.kgVisibility){if(t.dataset.vis==='GLOBAL'&&!confirm('加入总体图谱后，其他登录用户可看到该论文的图谱与关联证据。确定分享？'))return;try{await this.api('/visibility',{paper_id:t.dataset.kgVisibility,visibility:t.dataset.vis});await this.reload();}catch(err){this.h.toast?.(err.message);}return;}
   if(t.dataset.kgAction)return this.action(t.dataset.kgAction);
  },true);
  document.addEventListener('input',ev=>{if(ev.target.matches?.('[data-kg-search]')){this.query=ev.target.value;this.redrawGraph();}});
  document.addEventListener('change',ev=>{const t=ev.target;if(t.matches?.('[data-kg-switch]')){this[t.dataset.kgSwitch]=t.checked;this.h.toast?.(t.checked?'已开启知识图谱生成':'已关闭知识图谱生成');}});
 }
}
