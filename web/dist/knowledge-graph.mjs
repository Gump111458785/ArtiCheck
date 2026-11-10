// Review-Aware Scientific Contribution Graph (学术贡献知识图谱) — see docs/功能1.md
import {sessionCapability} from './online-core.mjs';

const NODE_TYPES={Paper:['论文','#2258b4'],Contribution:['主贡献','#7754ba'],Detail:['细分贡献','#157b78']};
const RELATIONS={previous:'前序引用',next:'后续引用',similar:'相似研究'};

export class KnowledgeGraphWorkspace{
 constructor(h){this.h=h;this.data=null;this.loading=false;this.error='';this.filters={year:'',direction:'',venue:''};this.generation=0;this.selected=null;this.inspectorTab='detail';this.expanded=new Set();this.pinned=new Set();this.zoom=1;this.pan={x:0,y:0};this.query='';this.focusMode=false;this.mutating=false;this.notice='';this.enableKg=true;this.focusProject=null;this.drag=null;}
 esc(v){return this.h.esc(v??'');}
 headers(json){let s='';try{s=sessionCapability();}catch{}return {'X-ArtiCheck-Client':'review-api',...(s?{'X-ArtiCheck-Session':s}:{}),...(json?{'Content-Type':'application/json'}:{})};}
 async api(path,payload){const res=await fetch('/v1/kg'+path,{method:payload===undefined?'GET':'POST',headers:this.headers(payload!==undefined),body:payload===undefined?undefined:JSON.stringify(payload),credentials:'same-origin'});let v;try{v=await res.json();}catch{throw Error('知识图谱服务暂未返回有效响应。');}if(!res.ok)throw Error(v?.error?.message||'知识图谱请求失败。');return v;}
 clear(){this.generation++;this.data=null;this.selected=null;this.mutating=false;this.notice='';this.loading=false;this.error='';this.expanded.clear();this.pinned.clear();this.query='';this.focusMode=false;this.inspectorTab='detail';this.zoom=1;this.pan={x:0,y:0};this.filters={year:'',direction:'',venue:''};}
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
  const papers=new Set(this.matchingPapers().filter(p=>!p.hidden).map(p=>p.paper_id));
  return d.nodes.filter(n=>{
   if(!papers.has(n.node_type==='Paper'?n.id:n.paper_id))return false;
   if(n.layer===1)return true;
   if(n.node_type==='Contribution')return this.expanded.has(n.paper_id);
   return this.expanded.has(n.paper_id)&&this.expanded.has(n.parent_id);
  });
 }
 neighbors(id){const s=new Set([id]);for(const e of this.data?.edges||[]){if(e.source===id)s.add(e.target);if(e.target===id)s.add(e.source);}return s;}
 render(){
  const e=v=>this.esc(v),d=this.data;
  const toolbar=`<div class="kg-toolbar"><div class="kg-toolbar-title"><span>个人论文与已发现的公开文献</span></div><div class="kg-toolbar-actions"><button type="button" class="btn small" data-kg-action="save-layout">保存布局</button><button type="button" class="btn small" data-kg-action="reset-view">重置视图</button></div></div><div class="kg-filters"><label class="kg-filter"><span>搜索</span><input type="search" data-kg-search value="${e(this.query)}" placeholder="论文或贡献"></label>${this.filterControls()}</div>`;
  if(this.loading&&!d)return `<section class="kg-workspace">${toolbar}<div class="kg-loading" role="status">正在读取知识图谱…</div></section>`;
  if(!d)return `<section class="kg-workspace">${toolbar}<div class="kg-empty"><h3>${this.error?'暂时无法读取图谱':'打开我的知识图谱'}</h3><p>${e(this.error||'从论文报告打开图谱，或加载已经保存的论文。')}</p><button class="btn primary" data-kg-action="load">加载我的图谱</button></div></section>`;
  const count=this.matchingPapers().filter(p=>!p.hidden).length;
  return `<section class="kg-workspace">${toolbar}${this.notice?`<p class="kg-notice" role="status">${e(this.notice)}</p>`:''}<div class="kg-stats"><span><strong>${count}</strong> / ${d.stats?.paper_count||0} 篇论文</span>${this.focusMode?'<button class="btn text small" data-kg-action="exit-focus">退出聚焦模式</button>':''}</div><div class="kg-main">${count?this.canvasView():'<div class="kg-empty">没有匹配的论文。可以调整筛选，或从论文报告打开一篇论文。</div>'}<aside class="kg-inspector">${this.inspector()}</aside></div></section>`;
 }
 canvasView(){
  const e=v=>this.esc(v),visible=this.visibleNodes(),ids=new Set(visible.map(n=>n.id));
  const edges=(this.data.edges||[]).filter(edge=>ids.has(edge.source)&&ids.has(edge.target));
  const neighbors=this.selected?this.neighbors(this.selected):null,q=this.query.trim().toLowerCase();
  const hit=n=>!q||[n.full_title,n.label].join(' ').toLowerCase().includes(q);
  const labels=new Map(),occupied=[];
  const priority=n=>n.id===this.selected?0:n.node_type==='Paper'?1:neighbors?.has(n.id)?2:3;
  for(const n of [...visible].sort((a,b)=>priority(a)-priority(b))){
   if(n.id!==this.selected&&!hit(n))continue;
   const label=Array.from(n.label||'').slice(0,32).join(''),w=Math.min(225,Math.max(30,Array.from(label).reduce((sum,char)=>sum+(char.codePointAt(0)>255?14:8),12)));
   const box={x:n.x-w/2,y:n.y+13,w,h:16};
   if(n.id!==this.selected&&occupied.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
   occupied.push(box);labels.set(n.id,label+(Array.from(n.label||'').length>32?'…':''));
  }
  const nodes=[...visible].sort((a,b)=>priority(b)-priority(a));
  return `<div class="kg-canvas" data-kg-canvas><svg class="kg-svg" data-kg-svg viewBox="0 0 1040 680" role="group" aria-label="学术贡献知识图谱"><defs><marker id="kg-citation-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#5175a8"/></marker></defs><g data-kg-viewport transform="translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})">${edges.map(edge=>{
   const a=this.node(edge.source),b=this.node(edge.target),active=edge.source===this.selected||edge.target===this.selected;
   const citation=edge.edge_type==='CITED_BY',similar=edge.edge_type==='SIMILAR_CONTRIBUTION';
   const length=Math.hypot(b.x-a.x,b.y-a.y)||1;
   return `<g class="kg-edge ${citation?'citation':similar?'similar':''} ${active?'active':this.selected?'dim':''}"><line x1="${a.x}" y1="${a.y}" x2="${citation?b.x-13*(b.x-a.x)/length:b.x}" y2="${citation?b.y-13*(b.y-a.y)/length:b.y}" ${citation?'marker-end="url(#kg-citation-arrow)"':''}/><title>${e(edge.description||edge.label)}</title>${active?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-5}" class="kg-edge-label">${e(edge.label)}</text>`:''}</g>`;
  }).join('')}${nodes.map(n=>{
   const r=n.node_type==='Paper'?11:n.node_type==='Contribution'?7:5,selected=n.id===this.selected;
   return `<g class="kg-node ${n.node_type==='Paper'&&!n.read?'unread':''} ${selected?'selected':!hit(n)||this.focusMode&&!neighbors?.has(n.id)?'dim':''}" data-kg-node="${e(n.id)}" transform="translate(${n.x} ${n.y})" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${e(n.full_title||n.label)}">${selected?`<circle class="kg-node-halo" r="${r+4}"/>`:''}<circle class="kg-node-mark" r="${r}" fill="${NODE_TYPES[n.node_type][1]}"/>${labels.has(n.id)?`<text y="25" text-anchor="middle">${e(labels.get(n.id))}</text>`:''}<title>${e(n.full_title||n.label)}</title></g>`;
  }).join('')}</g></svg><div class="kg-legend">${Object.values(NODE_TYPES).map(([name,color])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}<span class="hint">空心论文未读 · 拖动平移 · 滚轮缩放</span></div></div>`;
 }
 paperActions(paper){
  const e=v=>this.esc(v),disabled=this.mutating?'disabled':'';
  return `<div class="kg-insp-actions"><button class="btn small" data-kg-paper="${e(paper.id)}" data-kg-choice="${paper.read?'unread':'read'}" ${disabled}>${paper.read?'标记未读':'标记已读'}</button><button class="btn small" data-kg-paper="${e(paper.id)}" data-kg-choice="${paper.hidden?'show':'hide'}" ${disabled}>${paper.hidden?'恢复显示':'隐藏'}</button>${paper.source_type==='PUBLIC_LITERATURE'?`<button class="btn small danger" data-kg-paper="${e(paper.id)}" data-kg-choice="remove" ${disabled}>移除</button>`:''}</div>`;
 }
 literatureForm(paper){
  const e=v=>this.esc(v);
  return `<form class="kg-literature-form" data-kg-literature="${e(paper.id)}"><fieldset><legend>扩展此论文</legend>${Object.entries(RELATIONS).map(([key,label])=>`<label><input type="checkbox" name="kind" value="${key}" checked> ${label}</label>`).join('')}</fieldset><div class="kg-insp-actions"><label>每类 <select name="limit"><option>3</option><option>5</option><option>8</option></select> 篇</label><button class="btn small primary" type="submit" ${this.mutating?'disabled':''}>${this.mutating?'正在检索…':'检索公开文献'}</button></div><small>首次匹配可能向 OpenAlex 查询论文题目或 DOI。</small></form>`;
 }
 inspector(){
  const e=v=>this.esc(v),n=this.node(this.selected);
  const tabs=[['detail','节点详情'],['relations','关联依据'],['lineage','研究脉络']];
  let body='';
  if(this.inspectorTab==='lineage'){
   body=`<ol class="kg-lineage">${(this.data.timeline||[]).map(t=>`<li class="${t.paper_id===n?.id?'current':''}"><span>${e(t.year||'未知年份')}</span><div><button class="link" data-kg-select="${e(t.paper_id)}">${e(t.title)}</button><small>${t.read?'已读':'未读'}${t.hidden?' · 已隐藏':''}</small></div></li>`).join('')}</ol>`;
  }else if(!n){
   body='<p class="kg-notice">选择论文或贡献，查看完整标题和依据。</p>';
  }else if(this.inspectorTab==='relations'){
   const edges=this.data.edges.filter(edge=>['CITED_BY','SIMILAR_CONTRIBUTION'].includes(edge.edge_type)&&(edge.source===n.id||edge.target===n.id));
   body=edges.map(edge=>{
    const from=this.node(edge.source),to=this.node(edge.target),other=edge.source===n.id?to:from;
    return `<article class="kg-cmp-card"><h3>${e(edge.label)}</h3><p>${e(from.full_title)} ${edge.edge_type==='CITED_BY'?'→':'↔'} ${e(to.full_title)}</p><p>${e(edge.description)}</p><div class="kg-insp-actions"><button class="btn small" data-kg-select="${e(other.id)}">定位关联节点</button>${edge.source_url?`<a class="btn small" href="${e(edge.source_url)}" target="_blank" rel="noopener noreferrer">公开出处</a>`:''}</div></article>`;
   }).join('')||'<p class="kg-notice">此节点暂无可展示的引用或相似依据。可从论文节点检索公开脉络。</p>';
  }else if(n.node_type==='Paper'){
   const metadata=[['year','年份'],['direction','研究方向'],['venue','期刊 / 会议']];
   body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${n.source_type==='PUBLIC_LITERATURE'?'公开书目':'我的审查记录'} · <strong>${n.read?'已读':'未读'}</strong>${n.hidden?' · 已隐藏':''}</p><dl class="kg-dl">${metadata.map(([key,label])=>{
    const row=n.metadata?.[key]||{};
    return `<div><dt>${label}</dt><dd>${e(row.value||'未知')}${row.source_url?` <a href="${e(row.source_url)}" target="_blank" rel="noopener noreferrer">${e(row.source)}</a>`:row.source?` <small>${e(row.source)}</small>`:''}</dd></div>`;
   }).join('')}</dl><p>${e(n.abstract)}</p><div class="kg-insp-actions">${this.data.nodes.some(child=>child.parent_id===n.id)?`<button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起主贡献':'展开主贡献'}</button>`:''}${n.source_url?`<a class="btn small" href="${e(n.source_url)}" target="_blank" rel="noopener noreferrer">查看公开书目</a>`:''}</div>${this.paperActions(n)}${this.literatureForm(n)}`;
  }else{
   body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${e(n.paper_title)}</p>${n.quote?`<blockquote>${e(n.quote)}</blockquote><p>PDF 第 ${e(n.page)} 页</p>`:''}${n.source_url?`<a href="${e(n.source_url)}" target="_blank" rel="noopener noreferrer">公开摘要来源</a>`:''}${this.data.nodes.some(child=>child.parent_id===n.id)?`<div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起细分贡献':'展开细分贡献'}</button></div>`:''}`;
  }
  return `<div class="kg-insp-tabs">${tabs.map(([key,label])=>`<button type="button" class="${this.inspectorTab===key?'active':''}" data-kg-tab="${key}">${label}</button>`).join('')}</div><div class="kg-insp-body">${body}</div>`;
 }
 async changeLiterature(path,payload){
  if(this.mutating)return;
  const version=this.generation;
  this.mutating=true;this.notice='';this.h.render();
  try{
   const data=await this.api(path,payload);
   if(version!==this.generation)return;
   this.data=data;this.pinned=new Set(data.layout?.pinned||[]);
   if(!this.node(this.selected))this.selected=data.focus_paper_id||null;
   if(path.endsWith('/expand')){
    this.notice='公开脉络已更新。可在右侧选择论文继续检索。';
    this.pan={x:0,y:0};this.zoom=1;
   }
  }catch(error){if(version===this.generation)this.notice=error.message;}
  finally{if(version===this.generation){this.mutating=false;this.h.render();}}
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
 select(id,center=false){const n=this.node(id);if(!n)return;this.selected=id;this.inspectorTab='detail';
  if(n.node_type!=='Paper'){this.expanded.add(n.paper_id);if(n.node_type==='Detail')this.expanded.add(n.parent_id);}
  if(center){this.pan={x:520-n.x*this.zoom,y:340-n.y*this.zoom};}this.h.render();}
 toggleExpand(id){this.expanded.has(id)?this.expanded.delete(id):this.expanded.add(id);this.selected=id;this.h.render();}
 async action(a){
  if(a==='load')return this.open(null);
  if(a==='reset-view'){this.zoom=1;this.pan={x:0,y:0};this.focusMode=false;this.query='';this.h.render();return;}
  if(a==='focus'){this.focusMode=true;this.h.render();return;}
  if(a==='exit-focus'){this.focusMode=false;this.h.render();return;}

  if(a==='save-layout'){const positions={};for(const n of this.data?.nodes||[])if(this.pinned.has(n.id))positions[n.id]={x:Math.round(n.x),y:Math.round(n.y)};try{await this.api('/layout',{positions,pinned:[...this.pinned]});this.h.toast?.('布局已保存');}catch(err){this.h.toast?.('布局保存失败：'+err.message);}return;}
 }
 bind(){
  document.addEventListener('submit',ev=>{
   if(!ev.target.matches('[data-kg-literature]'))return;
   ev.preventDefault();
   const form=new FormData(ev.target),kinds=form.getAll('kind');
   if(!kinds.length){this.h.toast?.('请至少选择一种研究关系');return;}
   const paper=this.node(ev.target.dataset.kgLiterature);
   if(!paper)return;
   if(!paper.source_url&&!confirm('使用论文题目或 DOI 在 OpenAlex 查找公开文献？'))return;
   this.changeLiterature('/literature/expand',{paper_id:paper.id,kinds,limit:Number(form.get('limit'))});
  });
  document.addEventListener('click',async ev=>{
   const copy=ev.target.closest('[data-copy-cmd]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copyCmd);this.h.toast?.('命令已复制');}catch{this.h.toast?.('复制失败，请手动选择命令');}return;}
   const kg=ev.target.closest('[data-open-kg]');if(kg){ev.preventDefault();ev.stopPropagation();this.open(kg.dataset.openKg);return;}
   const t=ev.target.closest('[data-kg-action],[data-kg-tab],[data-kg-select],[data-kg-expand],[data-kg-choice]');if(!t)return;
   if(t.dataset.kgTab){this.inspectorTab=t.dataset.kgTab;return this.h.render();}
   if(t.dataset.kgSelect){return this.select(t.dataset.kgSelect,true);}
   if(t.dataset.kgExpand)return this.toggleExpand(t.dataset.kgExpand);
   if(t.dataset.kgChoice){
    if(t.dataset.kgChoice==='remove'&&!confirm('从个人图谱移除此公开文献？'))return;
    return this.changeLiterature('/literature/paper',{paper_id:t.dataset.kgPaper,action:t.dataset.kgChoice});
   }
   if(t.dataset.kgAction)return this.action(t.dataset.kgAction);
  },true);
  document.addEventListener('input',ev=>{if(ev.target.matches?.('[data-kg-search]')){this.query=ev.target.value;this.redrawGraph();}});
  document.addEventListener('change',ev=>{
   const key=ev.target.dataset?.kgFilter;
   if(!Object.hasOwn(this.filters,key))return;
   this.filters[key]=ev.target.value;
   if(!this.visibleNodes().some(node=>node.id===this.selected)){this.selected=null;this.focusMode=false;}
   this.h.render();
  });
 }
}
