// Review-Aware Scientific Contribution Graph (学术贡献知识图谱) — see docs/功能1.md
import {encoded,sessionCapability} from './online-core.mjs';

const NODE_TYPES={Paper:['论文','#2258b4'],Contribution:['主贡献','#7754ba'],Detail:['细分贡献','#157b78']};
const MIN_NODE_GAP=68;
const PDF_CHUNK_BYTES=2_000_000;
const SEARCH_FIELDS=[
 ['paper_id','论文名称','输入论文名称'],
 ['year','年份','输入年份'],
 ['direction','研究方向','输入研究方向'],
 ['venue','期刊 / 会议','输入期刊或会议']
];
const titleKey=value=>String(value||'').normalize('NFKC').trim().toLowerCase().replace(/\s+/g,' ');
const RELATIONS={previous:'前序引用',next:'后续引用',similar:'相似研究'};

const expansionPhases={downloading:'正在获取开放原文…',reading:'正在解析并核验原文…',searching:'正在检索公开文献…',extracting:'正在核验已有贡献的关联…'};

export class KnowledgeGraphWorkspace{
 constructor(h){this.h=h;this.data=null;this.loading=false;this.error='';this.filters={paper_id:'',year:'',direction:'',venue:''};this.generation=0;this.selected=null;this.inspectorTab='detail';this.expanded=new Set();this.pinned=new Set();this.zoom=1;this.pan={x:0,y:0};this.focusMode=false;this.mutating=false;this.expansionPaper=null;this.enableKg=true;this.focusProject=null;this.drag=null;this.layoutQueue=Promise.resolve();this.initialPositions=new WeakMap();this.operations=new Map();this.taskFeedback=new Map();this.dismissedFulltext=new Set();}
 esc(v){return this.h.esc(v??'');}
 headers(json){let s='';try{s=sessionCapability();}catch{}return {'X-ArtiCheck-Client':'review-api',...(s?{'X-ArtiCheck-Session':s}:{}),...(json?{'Content-Type':'application/json'}:{})};}
 async api(path,payload){const res=await fetch('/v1/kg'+path,{method:payload===undefined?'GET':'POST',headers:this.headers(payload!==undefined),body:payload===undefined?undefined:JSON.stringify(payload),keepalive:path==='/layout',credentials:'same-origin',signal:AbortSignal.timeout(path==='/layout'||path.endsWith('/progress')?8000:110000)});let v;try{v=await res.json();}catch{throw Error('知识图谱服务暂未返回有效响应。');}if(!res.ok)throw Error(v?.error?.message||'知识图谱请求失败。');return v;}
 clear(){this.generation++;this.operations.clear();this.taskFeedback.clear();this.dismissedFulltext.clear();this.data=null;this.selected=null;this.linkSource=null;this.linkDraft=null;this.contextNode=null;this.mutating=false;this.expansionPaper=null;this.loading=false;this.error='';this.attachedPDF=null;this.expanded.clear();this.pinned.clear();this.focusMode=false;this.inspectorTab='detail';this.zoom=1;this.pan={x:0,y:0};this.filters={paper_id:'',year:'',direction:'',venue:''};}
 async open(projectId){
  await this.layoutQueue;
  this.clear();
  this.h.navigate('knowledge-graph');
  const p=(this.h.projects?.()||[]).find(x=>x.id===projectId);
  return this.load(p?.online_report?.id&&this.enableKg?{assessment_id:p.online_report.id,project_id:p.id,title:p.title}:undefined);
 }
 async reload(){return this.load();}
 async load(payload){
  this.attachedPDF=null;
  const version=++this.generation;
  this.loading=true;this.error='';this.h.render();
  let alreadyExists=false;
  try{
   const data=await this.api(payload?'/ingest':'/graph',payload);
   if(version!==this.generation)return;
   alreadyExists=data.already_exists;
   this.applyGraph(data);
   if(payload||!this.node(this.selected))this.selected=data.focus_paper_id||null;
  }catch(error){if(version===this.generation){this.data=null;this.error=error.message;}}
  finally{if(version===this.generation){this.loading=false;this.h.render();}}
  if(payload&&version===this.generation&&this.selected){
   if(alreadyExists)this.focusImported(this.selected);
   else await this.expandImported(this.selected);
  }
 }
 matchingPapers(except=''){
  return (this.data?.timeline||[]).filter(paper=>!paper.hidden&&Object.entries(this.filters)
   .every(([key,value])=>key==='paper_id'||key===except||!value||value===String(paper[key]||'unknown')));
 }
 filterControls(){
  const e=v=>this.esc(v);
  return SEARCH_FIELDS.map(([key,label,placeholder])=>{
   const value=this.filters[key];
   const current=key==='paper_id'?(this.data?.timeline||[]).find(p=>p.paper_id===value)?.title:value;
   return `<div class="kg-filter"><label for="kg-filter-${key}">${label}</label><input id="kg-filter-${key}" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="kg-options-${key}" autocomplete="off" data-kg-combo="${key}" value="${e(current==='unknown'?'未知':current)}" placeholder="${placeholder}"><div class="kg-option-menu" hidden><div id="kg-options-${key}" role="listbox" aria-label="${label}"></div><p class="kg-option-empty" role="status" hidden>没有匹配项</p></div></div>`;
  }).join('');
 }
 node(id){return this.data?.nodes?.find(n=>n.id===id);}
 updateOptions(input){
  const key=input.dataset.kgCombo, q=titleKey(input.value);
  const menu=input.nextElementSibling, list=menu.firstElementChild;
  const choices=new Map();
  for(const paper of this.matchingPapers(key)){
   const value=String(paper[key]||'unknown');
   choices.set(value,key==='paper_id'?paper.title:value==='unknown'?'未知':value);
  }
  const options=[...choices].filter(([,label])=>titleKey(label).includes(q))
   .sort((a,b)=>key==='year'?b[1].localeCompare(a[1]):a[1].localeCompare(b[1],'zh'));
  if(!q||this.filters[key])options.unshift(['','全部']);
  list.innerHTML=options.map(([value,label],index)=>`<div id="${list.id}-${index}" role="option" aria-selected="false" data-kg-option="${this.esc(value)}">${this.esc(label)}</div>`).join('');
  menu.lastElementChild.hidden=options.length>0;
  menu.hidden=false;
  input.setAttribute('aria-expanded','true');
  input.removeAttribute('aria-activedescendant');
 }
 closeOptions(input){
  input.nextElementSibling.hidden=true;
  input.setAttribute('aria-expanded','false');
  input.removeAttribute('aria-activedescendant');
  input.value=input.defaultValue;
 }
 applyFilter(input,value){
  const key=input.dataset.kgCombo;
  this.filters[key]=value;
  const node=this.node(this.filters.paper_id);
  if(node&&this.matchingPapers().some(p=>p.paper_id===node.id)){
   this.linkSource=null;
   this.select(node.id,true);
  }else{
   this.filters.paper_id='';
   if(!this.matchingPapers().some(p=>p.paper_id===this.paperId(this.selected))){
    this.selected=null;
    this.focusMode=false;
   }
   if(!value&&key==='paper_id')this.focusMode=false;
   this.h.render();
  }
  const replacement=document.getElementById(input.id);
  replacement?.focus({preventScroll:true});
  if(replacement)this.closeOptions(replacement);
 }
 comboKey(event,input){
  if(event.isComposing)return;
  const menu=input.nextElementSibling;
  if(event.key==='Escape'&&!menu.hidden){
   event.preventDefault();
   event.stopImmediatePropagation();
   this.closeOptions(input);
   return;
  }
  if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return;
  if(menu.hidden)this.updateOptions(input);
  const options=[...menu.querySelectorAll('[role="option"]')];
  const index=options.findIndex(option=>option.id===input.getAttribute('aria-activedescendant'));
  event.preventDefault();
  if(!options.length)return;
  if(event.key==='Enter'){
   const match=options.find(option=>titleKey(option.textContent)===titleKey(input.value));
   const choice=options[index]||(input.value.trim()?match||options.find(option=>option.dataset.kgOption):options[0]);
   if(choice)this.applyFilter(input,choice.dataset.kgOption);
   return;
  }
  const next=event.key==='ArrowDown'?Math.min(index+1,options.length-1):index<0?options.length-1:Math.max(0,index-1);
  options.forEach((option,i)=>option.setAttribute('aria-selected',String(i===next)));
  input.setAttribute('aria-activedescendant',options[next].id);
  options[next].scrollIntoView({block:'nearest'});
 }
 visibleNodes(){
  const d=this.data;if(!d)return [];
  const papers=new Set(this.matchingPapers().map(p=>p.paper_id));
  return d.nodes.filter(n=>{
   if(!papers.has(n.node_type==='Paper'?n.id:n.paper_id))return false;
   if(n.layer===1)return true;
   if(n.node_type==='Contribution')return this.expanded.has(n.paper_id);
   return this.expanded.has(n.paper_id)&&this.expanded.has(n.parent_id);
  });
 }
 paperDetailsExpanded(paper){
  return Boolean(paper&&this.expanded.has(paper.id)&&this.data.nodes.some(node=>
   node.node_type==='Detail'&&node.paper_id===paper.id&&this.expanded.has(node.parent_id)));
 }
 canvasControls(){
  const paper=this.node(this.selected);
  const expanded=this.paperDetailsExpanded(paper);
  const chosen=paper;
  return `<div class="kg-canvas-tools"><div class="kg-canvas-actions">
   ${paper?.node_type==='Paper'?`<button class="btn small" type="button" data-kg-expand-paper aria-expanded="${expanded}">${expanded?'收起子贡献':'展开子贡献'}</button><button class="btn small" type="button" data-kg-action="expand-literature" aria-expanded="${this.expansionPaper===paper.id}" ${this.mutating?'disabled':''}>扩展此论文</button>`:''}
   <button class="btn small" type="button" data-kg-action="link-start" ${!chosen||this.mutating?'disabled':''}>${this.linkSource?'取消连线':'建立联系'}</button>
   <button class="btn small danger" type="button" data-kg-action="delete-node" ${!chosen||this.mutating?'disabled':''}>删除节点</button>
   </div>
   ${this.linkSource?'<small class="kg-link-instruction" role="status">请选择另一篇论文或另一个贡献节点</small>':''}
   ${this.contextNode&&chosen?`<div class="kg-node-menu"><button class="btn small" data-kg-action="link-start">建立联系</button><button class="btn small" data-kg-tab="relations">查看或删除联系</button><button class="btn small" data-kg-action="pin">${this.pinned.has(chosen.id)?'取消固定':'固定位置'}</button></div>`:''}
   ${this.linkDraft?`<form class="kg-literature-form kg-link-form" data-kg-link-form>
    <strong>${this.esc(this.node(this.linkDraft.source)?.label)} ↔ ${this.esc(this.node(this.linkDraft.target)?.label)}</strong>
    <label>关系名称 <input name="label" maxlength="48" required value="${this.esc(this.linkDraft.label||'')}" placeholder="例如：扩展了实验方法"></label>
    <label>备注 <textarea name="note" maxlength="360" rows="2">${this.esc(this.linkDraft.note||'')}</textarea></label>
    <div class="kg-insp-actions"><button class="btn primary small" type="submit">保存联系</button><button class="btn small" type="button" data-kg-action="link-dismiss">取消</button></div>
   </form>`:''}</div>


  <button type="button" class="btn small kg-home-view" data-kg-action="home-view">${this.h.icon?.('home')||''}回到起始位置</button>`;
 }

 operationText(text){return text.replace(/[.…。！!]+$/u,'')+'...';}
 syncOperationOverlay(){
  const doc=globalThis.document;
  if(!doc)return;
  let overlay=this.operationOverlay;
  const canvas=doc.querySelector('[data-kg-canvas],.kg-workspace .kg-empty,.kg-workspace .kg-loading');
  if(!canvas){if(overlay)overlay.hidden=true;return;}
  const items=[...this.operations,...this.taskFeedback];
  if(!items.length){if(overlay){overlay.replaceChildren();overlay.hidden=true;}return;}
  if(!overlay){
   overlay=doc.createElement('div');
   overlay.className='kg-operation-list';
   doc.body.append(overlay);
   this.operationOverlay=overlay;
  }
  const rect=canvas.getBoundingClientRect();
  const top=Math.max(rect.top,0)+12;
  overlay.hidden=rect.bottom<=top||top>=innerHeight;
  overlay.style.left=rect.left+rect.width/2+'px';
  overlay.style.top=top+'px';
  overlay.style.width=Math.min(420,rect.width*.75)+'px';
  const keys=new Set(items.map(([id])=>id));
  for(const row of [...overlay.children])if(!keys.has(row.operationKey))row.remove();
  for(const [id,item] of items){
   const pending=this.operations.has(id);
   let row=[...overlay.children].find(child=>child.operationKey===id);
   if(!row){
    row=doc.createElement('div');
    row.operationKey=id;
    row.className='kg-task-status tone-'+(item.failed?'remove':item.tone)+(pending?' is-pending':'');
    row.innerHTML='<span role="status"></span>'+(pending?'<progress aria-label="图谱操作进度"></progress>':'')+
     (item.cancelable?'<button class="btn small danger" type="button">停止</button>':'');
    if(item.cancelable)row.lastChild.dataset.kgStop=item.id;
    overlay.append(row);
   }
   const text=this.operationText(item.text);
   if(row.firstChild.textContent!==text)row.firstChild.textContent=text;
   const stop=row.querySelector('button');
   if(stop){
    stop.disabled=Boolean(item.stopping);
    const label=item.stopping?'正在停止...':'停止';
    if(stop.textContent!==label)stop.textContent=label;
   }
  }
 }

 render(){
  const e=v=>this.esc(v),d=this.data;
  const toolbar=`<div class="kg-filters">${this.filterControls()}<form class="kg-import-paper" data-kg-import><input name="reference" maxlength="600" aria-label="标题、arXiv 或 DOI" placeholder="标题、arXiv 或 DOI" required><button class="btn small" type="submit" ${this.mutating?'disabled':''}>添加论文</button></form><label class="btn small kg-pdf-upload kg-import-file">插入论文<input type="file" aria-label="插入论文" accept="application/pdf,.pdf" data-kg-import-pdf ${this.mutating?'disabled':''}></label></div>`;
  if(this.loading&&!d)return `<section class="kg-workspace">${toolbar}<div class="kg-loading" role="status">正在读取知识图谱…</div></section>`;
  if(!d)return `<section class="kg-workspace">${toolbar}<div class="kg-empty">${this.error?`<p role="alert">${e(this.error)}</p>`:''}<button class="btn primary" data-kg-action="load">加载我的图谱</button></div></section>`;
  const count=this.matchingPapers().length;
  const expansion=this.expansionPaper&&this.node(this.expansionPaper);
  return `<section class="kg-workspace">${toolbar}<div class="kg-stats"><span><strong>${count}</strong> / ${d.stats?.paper_count||0} 篇论文</span>${this.focusMode?'<button class="btn text small" data-kg-action="exit-focus">退出聚焦模式</button>':''}</div>${expansion?this.literatureForm(expansion):''}<div class="kg-main">${count?this.canvasView():`<div class="kg-empty kg-empty-canvas">没有匹配的论文。可以调整筛选，或从论文报告打开一篇论文。</div>`}<aside class="kg-inspector">${this.inspector()}</aside></div></section>`;
 }
 paperId(id){
  const node=this.node(id);
  return node?.paper_id||node?.id;
 }
 relationEdge(edge){
  return ['CITED_BY','RELATED_WORK','SIMILAR_CONTRIBUTION','MANUAL_RELATION'].includes(edge.edge_type);
 }
 displayedEdges(ids){
  const edges=[],projected=new Map();
  const fullPairs=new Set();
  for(const edge of this.data.edges||[]){
   if(!this.relationEdge(edge)){
    if(ids.has(edge.source)&&ids.has(edge.target))edges.push(edge);
    continue;
   }
   const source=this.paperId(edge.source),target=this.paperId(edge.target);
   if(!ids.has(source)||!ids.has(target))continue;
   const pair=[source,target].sort().join(':');
   if(edge.edge_type!=='CITED_BY'&&source!==edge.source&&target!==edge.target&&ids.has(edge.source)&&ids.has(edge.target)){
    edges.push(edge);
    fullPairs.add(pair);
   }else if(source!==target){
    const prior=projected.get(pair);
    const rank={RELATED_WORK:0,CITED_BY:1,SIMILAR_CONTRIBUTION:2,MANUAL_RELATION:3};
    if(!prior||rank[prior.edge_type]<rank[edge.edge_type]){
     projected.set(pair,{...edge,source,target});
    }
   }else if(ids.has(edge.source)&&ids.has(edge.target))edges.push(edge);
  }
  for(const [pair,edge] of projected)if(!fullPairs.has(pair))edges.push(edge);
  return edges;
 }
 placeDetailNodes(nodes,edges){
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);
  const fixed=nodes.filter(node=>node.node_type==='Paper'||this.pinned.has(node.id));
  const fixedIds=new Set(fixed.map(node=>node.id));
  const placed=new Map();
  const targets=new Map();
  const width=node=>Math.min(112,Math.max(15,Array.from(node.label||'').slice(0,32)
   .reduce((sum,char)=>sum+(char.codePointAt(0)>255?7:4),6)));
  const widths=new Map(nodes.map(node=>[node.id,width(node)]));
  const separated=(node,point,other,position)=>distance(point,position)>=MIN_NODE_GAP&&
   (Math.abs(point.y-position.y)>=34||Math.abs(point.x-position.x)>=widths.get(node.id)+widths.get(other.id)+8);
  const fits=(node,point)=>[...placed].every(([id,position])=>id===node.id||separated(node,point,byId.get(id),position));
  const settle=(node,preferred)=>{
   if(fits(node,preferred)){placed.set(node.id,preferred);return;}
   for(let radius=MIN_NODE_GAP; ;radius+=MIN_NODE_GAP/2){
    for(let step=0;step<16;step++){
     const angle=step*Math.PI/8;
     const candidate={x:preferred.x+radius*Math.cos(angle),y:preferred.y+radius*Math.sin(angle)};
     if(fits(node,candidate)){placed.set(node.id,candidate);return;}
    }
   }
  };
  const stableFixed=fixed.slice().sort((a,b)=>Number(b.node_type==='Paper')-Number(a.node_type==='Paper')||Number(this.pinned.has(b.id))-Number(this.pinned.has(a.id))||a.id.localeCompare(b.id));
  for(const node of stableFixed){
   if(!this.initialPositions.has(node))this.initialPositions.set(node,{x:node.x,y:node.y});
   const point=this.initialPositions.get(node);
   if(node.node_type==='Paper'&&[...placed.values()].every(position=>distance(point,position)>=MIN_NODE_GAP))placed.set(node.id,point);
   else settle(node,point);
  }
  const pairs=[];
  for(const edge of edges){
   if(!this.relationEdge(edge))continue;
   const left=byId.get(edge.source),right=byId.get(edge.target);
   if(!left?.paper_id||!right?.paper_id||left.paper_id===right.paper_id)continue;
   const start=placed.get(left.paper_id),end=placed.get(right.paper_id);
   if(!start||!end)continue;
   const gap=distance(start,end);
   const inset=Math.min(0.33,Math.max(0.12,MIN_NODE_GAP/gap));
   const along=t=>({x:start.x+(end.x-start.x)*t,y:start.y+(end.y-start.y)*t});
   for(const [node,point] of [[left,along(inset)],[right,along(1-inset)]]){
    const suggestions=targets.get(node.id)||[];
    suggestions.push(point);
    targets.set(node.id,suggestions);
   }
   pairs.push({left,right,start,end,along,inset});
  }
  const related=[...targets.keys()].filter(id=>!fixedIds.has(id));
  for(const id of related){
   const points=targets.get(id);
   settle(byId.get(id),{x:points.reduce((sum,p)=>sum+p.x,0)/points.length,
                        y:points.reduce((sum,p)=>sum+p.y,0)/points.length});
  }
  const relationCost=(node,point,paired,pairedPoint)=>pairs.reduce((sum,row)=>{
   if(row.left===node)return sum+distance(row.start,point)+distance(point,row.right===paired?pairedPoint:placed.get(row.right.id));
   if(row.right===node)return sum+distance(row.end,point)+distance(point,row.left===paired?pairedPoint:placed.get(row.left.id));
   return sum;
  },0);
  for(let pass=0;pass<2;pass++){
   for(const {left,right,start,end,along,inset} of pairs){
    if(fixedIds.has(left.id)&&fixedIds.has(right.id))continue;
    const first=placed.get(left.id),second=placed.get(right.id);
    placed.delete(left.id);
    placed.delete(right.id);
    const offsets=[0,MIN_NODE_GAP,-MIN_NODE_GAP,MIN_NODE_GAP*2,-MIN_NODE_GAP*2];
    const axis={x:end.x-start.x,y:end.y-start.y},length=distance(start,end);
    const choices=(node,current,center)=>{
     if(fixedIds.has(node.id))return [current];
     return [current,...offsets.map(offset=>({x:center.x-axis.y*offset/length,y:center.y+axis.x*offset/length}))];
    };
    let best=[first,second];
    let bestCost=relationCost(left,first,right,second)+relationCost(right,second,left,first)-distance(first,second);
    for(const a of choices(left,first,along(inset))){
     if(!fits(left,a))continue;
     for(const b of choices(right,second,along(1-inset))){
      if(!fits(right,b)||!separated(left,a,right,b))continue;
      const cost=relationCost(left,a,right,b)+relationCost(right,b,left,a)-distance(a,b);
      if(cost<bestCost-0.001){best=[a,b];bestCost=cost;}
     }
    }
    placed.set(left.id,best[0]);
    placed.set(right.id,best[1]);
   }
  }
  for(const node of nodes){
   if(placed.has(node.id))continue;
   const parent=placed.get(node.parent_id);
   const preferred=parent?{x:parent.x,y:parent.y+MIN_NODE_GAP}:{x:node.x,y:node.y};
   settle(node,preferred);
  }
  for(const node of nodes)Object.assign(node,placed.get(node.id));
 }
 canvasView(){
  const e=v=>this.esc(v),visible=this.visibleNodes(),ids=new Set(visible.map(n=>n.id));
  const edges=this.displayedEdges(ids);
  this.placeDetailNodes(visible,edges);
  const similarityCount=edges.filter(edge=>edge.edge_type==='SIMILAR_CONTRIBUTION').length;
  const hasSimilarity=similarityCount>0;
  edges.sort((a,b)=>Number(a.edge_type==='SIMILAR_CONTRIBUTION')-Number(b.edge_type==='SIMILAR_CONTRIBUTION'));
  const selectedPaper=this.paperId(this.selected),related=new Set([selectedPaper]);
  for(const edge of this.data.edges){
   if(!this.relationEdge(edge))continue;
   const left=this.paperId(edge.source),right=this.paperId(edge.target);
   if(left===selectedPaper)related.add(right);
   if(right===selectedPaper)related.add(left);
  }
  const inFocus=id=>!this.focusMode||related.has(this.paperId(id));
  const labels=new Map(),occupied=[];
  const priority=n=>n.id===this.selected?0:n.node_type==='Paper'?1:inFocus(n.id)?2:3;
  for(const n of [...visible].sort((a,b)=>priority(a)-priority(b))){
   const label=Array.from(n.label||'').slice(0,32).join(''),w=Math.min(225,Math.max(30,Array.from(label).reduce((sum,char)=>sum+(char.codePointAt(0)>255?14:8),12)));
   const box={x:n.x-w/2,y:n.y+13,w,h:16};
   if(n.id!==this.selected&&occupied.some(b=>box.x<b.x+b.w&&box.x+box.w>b.x&&box.y<b.y+b.h&&box.y+box.h>b.y))continue;
   occupied.push(box);labels.set(n.id,label+(Array.from(n.label||'').length>32?'…':''));
  }
  const nodes=[...visible].sort((a,b)=>priority(b)-priority(a));
  return `<div class="kg-canvas ${hasSimilarity?'has-similarity':''}" data-kg-canvas ><svg class="kg-svg" data-kg-svg viewBox="0 0 1040 680" role="group" aria-label="学术贡献知识图谱"><g data-kg-viewport transform="translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})">${edges.map(edge=>{
   const a=this.node(edge.source),b=this.node(edge.target),active=this.focusMode&&inFocus(edge.source)&&inFocus(edge.target);
   const similar=edge.edge_type==='SIMILAR_CONTRIBUTION'||edge.edge_type==='MANUAL_RELATION';
   const candidate=edge.edge_type==='RELATED_WORK';
   return `<g class="kg-edge ${similar?'similar':candidate?'candidate':''} ${active?'active':!inFocus(edge.source)||!inFocus(edge.target)?'dim':''}"><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/><title>${e(edge.description||edge.label)}</title>${(active||similar&&similarityCount<=3)?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-5}" class="kg-edge-label">${e(edge.label)}</text>`:''}</g>`;
  }).join('')}${nodes.map(n=>{
   const r=n.node_type==='Paper'?11:n.node_type==='Contribution'?7:5,selected=n.id===this.selected;
   return `<g class="kg-node ${n.node_type==='Paper'?(n.read?'read':'unread'):''} ${selected?'selected':!inFocus(n.id)?'dim':''}" data-kg-node="${e(n.id)}" transform="translate(${n.x} ${n.y})" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${e(n.full_title||n.label)}">${selected?`<circle class="kg-node-halo" r="${r+4}"/>`:''}<circle class="kg-node-mark" r="${r}" fill="${n.node_type==='Paper'&&!n.read?'#b36b19':NODE_TYPES[n.node_type][1]}"/>${labels.has(n.id)?`<text y="25" text-anchor="middle">${e(labels.get(n.id))}</text>`:''}<title>${e(n.full_title||n.label)}</title></g>`;
  }).join('')}</g></svg>${this.canvasControls()}<div class="kg-legend"><span><i style="background:#2258b4"></i>已读论文</span><span><i style="background:#b36b19"></i>未读论文</span>${Object.values(NODE_TYPES).slice(1).map(([name,color])=>`<span><i style="background:${color}"></i>${name}</span>`).join('')}</div></div>`;
 }
 paperManagement(paper){
  const e=v=>this.esc(v);
  return `<select class="kg-paper-manage" data-kg-manage="${e(paper.paper_id)}" aria-label="管理 ${e(paper.title)}" ${this.mutating?'disabled':''}><option value="">管理</option><option value="${paper.hidden?'show':'hide'}">${paper.hidden?'恢复显示':'隐藏条目'}</option>${paper.source_type==='PUBLIC_LITERATURE'?'<option value="remove">移除条目</option>':''}</select>`;
 }
 literatureForm(paper){
  const e=v=>this.esc(v);
  return `<form class="kg-literature-form kg-expand-options" data-kg-literature="${e(paper.id)}"><fieldset><legend>检索关系</legend>${Object.entries(RELATIONS).map(([key,label])=>`<label><input type="checkbox" name="kind" value="${key}" checked> ${label}</label>`).join('')}</fieldset><div class="kg-insp-actions"><label>深度 <select name="depth"><option selected>2</option><option>3</option></select> 级</label><label>总计最多 <select name="max_total"><option>5</option><option selected>10</option><option>15</option></select> 篇</label><button class="btn small" type="button" data-kg-action="expand-literature">收起</button><button class="btn small primary" type="submit" ${this.mutating?'disabled':''}>${this.mutating?'正在检索…':'检索公开文献'}</button></div><small>首次匹配可能向 OpenAlex 查询论文题目或 DOI。</small></form>`;
 }
 inspector(){
  const e=v=>this.esc(v),n=this.node(this.selected);
  const tabs=[['detail','节点详情'],['relations','主要贡献'],['lineage','研究脉络']];
  let body='';
  if(this.inspectorTab==='lineage'){
   body=`<ol class="kg-lineage">${(this.data.timeline||[]).map(t=>`<li class="${t.paper_id===this.paperId(n?.id)?'current':''}"><span>${e(t.year||'未知年份')}</span><div><button class="link" data-kg-select="${e(t.paper_id)}">${e(t.title)}</button><small class="kg-reading ${t.read?'read':'unread'}">${t.read?'已读':'未读'}${t.hidden?' · 已隐藏':''}</small></div>${this.paperManagement(t)}</li>`).join('')}</ol>`;
  }else if(!n){
   body='<p class="kg-notice">选择论文或贡献，查看完整标题和依据。</p>';
  }else if(this.inspectorTab==='relations'){
   const contributions=n.node_type==='Paper'?this.data.nodes.filter(child=>child.parent_id===n.id):[n];
   const cards=contributions.map(child=>`<article class="kg-cmp-card kg-contribution-card"><h3>${e(child.full_title||child.label)}</h3>${child.summary&&child.summary!==child.full_title?`<p>${e(child.summary)}</p>`:''}${child.section||child.page?`<p class="kg-meta">${e(child.section||'方法正文')}${child.page?' · PDF 第 '+e(child.page)+' 页':''}</p>`:''}${child.quote?`<details><summary>查看原文依据</summary><blockquote>${e(child.quote)}</blockquote></details>`:''}${child.source_url?`<a href="${e(child.source_url)}" target="_blank" rel="noopener noreferrer">方法正文来源</a>`:''}</article>`).join('');
   const belongs=id=>id===n.id||(n.node_type==='Paper'&&this.node(id)?.paper_id===n.id);
   const edges=this.data.edges.filter(edge=>this.relationEdge(edge)&&(belongs(edge.source)||belongs(edge.target)))
    .sort((a,b)=>Number(b.edge_type==='SIMILAR_CONTRIBUTION')-Number(a.edge_type==='SIMILAR_CONTRIBUTION'));
   const relationCards=(edges.length&&edges.every(edge=>edge.edge_type==='CITED_BY')?'<p class="kg-notice">现有来源只核实了论文引用，尚未找到足够的贡献相似依据。</p>':'')+edges.map(edge=>{
    const from=this.node(edge.source),to=this.node(edge.target),other=belongs(edge.source)?to:from;
    return `<article class="kg-cmp-card"><h3>${e(edge.label)}</h3><p>${e(from.full_title)} ${edge.edge_type==='CITED_BY'?'→':'↔'} ${e(to.full_title)}</p><p>${e(edge.description)}</p>${edge.excerpts?.length?`<details><summary>查看双方依据</summary>${edge.excerpts.map((quote,index)=>`<p class="kg-meta">${e((index?to:from).paper_title||'')}</p><blockquote>${e(quote)}</blockquote><p class="kg-meta">${e(edge.evidence?.[index]?.section||'')} ${edge.evidence?.[index]?.page?' · 第 '+e(edge.evidence[index].page)+' 页':''} ${edge.evidence?.[index]?.source_url?`<a href="${e(edge.evidence[index].source_url)}" target="_blank" rel="noopener noreferrer">原文</a>`:''}</p>`).join('')}</details>`:''}<div class="kg-insp-actions"><button class="btn small" data-kg-select="${e(other.id)}">定位关联节点</button>${edge.source_url?`<a class="btn small" href="${e(edge.source_url)}" target="_blank" rel="noopener noreferrer">公开出处</a>`:''}<button class="btn small danger" data-kg-remove-source="${e(edge.source)}" data-kg-remove-target="${e(edge.target)}">删除联系</button></div></article>`;
   }).join('')||'<p class="kg-notice">此节点暂无可展示的引用或相似依据。可从论文节点检索公开脉络。</p>';
   const needsExtraction=n.node_type==='Paper'&&n.method_detail_status!=='grounded';
   body=(cards||(!needsExtraction?'<p class="kg-method-missing">尚无可展示的主要贡献。</p>':''))+
    (needsExtraction&&n.method_reason?`<p class="kg-method-missing">${e(n.method_reason)}</p>`:'')+
    (edges.length?`<details class="kg-relation-list"><summary>节点间联系（${edges.length}）</summary>${relationCards}</details>`:'');
  }else if(n.node_type==='Paper'){
   const metadata=[['year','年份'],['direction','研究方向'],['venue','期刊 / 会议']];
   body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${n.source_type==='PUBLIC_LITERATURE'?'公开书目':'我的审查记录'} · <strong class="kg-reading ${n.read?'read':'unread'}">${n.read?'已读':'未读'}</strong>${n.hidden?' · 已隐藏':''}</p><dl class="kg-dl">${metadata.map(([key,label])=>{
    const row=n.metadata?.[key]||{};
    return `<div><dt>${label}</dt><dd>${e(row.value||'未知')}${row.source_url?` <a href="${e(row.source_url)}" target="_blank" rel="noopener noreferrer">${e(row.source)}</a>`:row.source?` <small>${e(row.source)}</small>`:''}</dd></div>`;
   }).join('')}</dl>${n.fulltext_label&&!this.dismissedFulltext.has(n.id+':'+n.fulltext_label)?`<div class="kg-fulltext-note"><span>${e(n.fulltext_label)}</span><button type="button" class="btn text small" data-kg-dismiss-fulltext="${e(n.id+':'+n.fulltext_label)}" aria-label="关闭正文核验提示">${this.h.icon('close')}</button></div>`:''}<p>${e(n.abstract)}</p>`;
  }else{
   body=`<h3>${e(n.full_title)}</h3><p class="kg-meta">${e(n.paper_title)}</p>${n.quote?`<blockquote>${e(n.quote)}</blockquote><p>${e(n.section||'方法正文')}${n.page?' · PDF 第 '+e(n.page)+' 页':''}</p>`:''}${n.source_url?`<a href="${e(n.source_url)}" target="_blank" rel="noopener noreferrer">方法正文来源</a>`:''}${this.data.nodes.some(child=>child.parent_id===n.id)?`<div class="kg-insp-actions"><button class="btn small" data-kg-expand="${e(n.id)}">${this.expanded.has(n.id)?'收起细分贡献':'展开细分贡献'}</button></div>`:''}`;
  }
  const paper=this.node(this.paperId(n?.id));
  const local=this.localPaper(paper);
  const preferred=paper?.fallback_url;
  const lookup=preferred?.startsWith('https://arxiv.org/')?preferred:
   paper?.pdf_available||local?paper?.source_url||preferred:preferred||paper?.source_url;
  return `<div class="kg-insp-tabs">${tabs.map(([key,label])=>`<button type="button" class="${this.inspectorTab===key?'active':''}" data-kg-tab="${key}">${label}</button>`).join('')}</div><div class="kg-insp-body">${body}</div>${paper?`<footer class="kg-insp-footer">${lookup?`<a class="btn small" href="${e(lookup)}" target="_blank" rel="noopener noreferrer">${paper.pdf_available||local?'查看公开书目':'打开原文来源'}</a>`:''}${paper.pdf_available||local?`<button type="button" class="btn small primary" data-kg-view-pdf="${e(paper.id)}">查看论文</button>`:`<button type="button" class="btn small" data-kg-find-pdf="${e(paper.id)}" ${this.mutating?'disabled':''}>查找原文</button><label class="btn small primary kg-pdf-upload">插入论文<input type="file" accept="application/pdf,.pdf" data-kg-original="${e(paper.id)}" ${this.mutating?'disabled':''}></label>`}<button type="button" class="btn small" data-kg-reading="${e(paper.id)}" data-kg-reading-action="${paper.read?'unread':'read'}" ${this.mutating?'disabled':''}>${paper.read?'设为未读':'设为已读'}</button></footer>`:''}`;
 }
 localPaper(paper){
  const project=(this.h.projects?.()||[]).find(p=>p.id===paper?.project_id);
  return project?.paper?.sha256&&project.paper.sha256===project.online_report?.materials?.paper?project.paper.blob:null;
 }
 async savedPDF(paperId){
  const path='/v1/kg/papers/'+encodeURIComponent(paperId)+'/pdf?chunk=';
  const read=async n=>{
   const response=await fetch(path+n,{credentials:'same-origin',headers:this.headers(false),signal:AbortSignal.timeout(25000)});
   if(!response.ok)throw Error((await response.json().catch(()=>({}))).error?.message||'论文暂时无法读取。');
   return {blob:await response.blob(),total:Number(response.headers.get('X-ArtiCheck-Paper-Bytes')),sha:response.headers.get('X-ArtiCheck-Paper-SHA256')};
  };
  const first=await read(0), parts=[first.blob];
  if(!Number.isSafeInteger(first.total)||first.total<1||first.total>20*1024**2)throw Error('论文大小无效。');
  const count=Math.ceil(first.total/PDF_CHUNK_BYTES);
  for(let start=1;start<count;start+=3){
   const batch=await Promise.all(Array.from({length:Math.min(3,count-start)},(_,offset)=>read(start+offset)));
   if(batch.some(part=>part.total!==first.total||part.sha!==first.sha))throw Error('论文文件已更新，请重新打开。');
   parts.push(...batch.map(part=>part.blob));
  }
  const blob=new Blob(parts,{type:'application/pdf'});
  const hash=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
  const sha=Array.from(new Uint8Array(hash),byte=>byte.toString(16).padStart(2,'0')).join('');
  if(blob.size!==first.total||sha!==first.sha)throw Error('PDF 完整性校验失败，请重试。');
  return blob;
 }
 async viewPaper(paper){
  const tab=window.open('about:blank','_blank');
  if(!tab){this.h.toast?.('请允许浏览器打开论文窗口。');return;}
  tab.opener=null;
  const doc=tab.document;
  doc.documentElement.lang='zh-CN';
  doc.title='正在加载论文 · ArtiCheck';
  Object.assign(doc.body.style,{margin:'0',padding:'48px 24px',background:'#f5f7fa',color:'#172c46',font:'16px/1.6 system-ui, sans-serif'});
  const status=doc.createElement('p');
  status.setAttribute('role','status');
  status.textContent='正在加载论文…';
  doc.body.replaceChildren(status);
  try{
   const attached=this.attachedPDF?.id===paper.id?this.attachedPDF.file:null;
   const blob=attached||this.localPaper(paper)||await this.savedPDF(paper.id);
   if(tab.closed)return;
   const href=URL.createObjectURL(blob.type==='application/pdf'?blob:new Blob([blob],{type:'application/pdf'}));
   tab.location.replace(href);
   setTimeout(()=>URL.revokeObjectURL(href),120000);
  }catch(error){
   if(tab.closed)return;
   doc.title='论文加载失败 · ArtiCheck';
   status.textContent='论文加载失败。'+(error.name==='TimeoutError'?'读取超时，请关闭此页后重试。':error.message);
  }
 }
 async stagePaper(blob){
  if(blob.size>20*1024**2)throw Error('论文 PDF 最大 20 MB。');
  const request=async(path,payload)=>{
   const response=await fetch('/v1/uploads'+path,{method:'POST',credentials:'same-origin',headers:this.headers(true),body:JSON.stringify(payload)});
   const data=await response.json();
   if(!response.ok)throw Error(data.error?.message||'传输 PDF 失败。');
   return data;
  };
  const digest=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
  const sha256=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
  const id=crypto.randomUUID().replaceAll('-','');
  const close=()=>request('/'+id+'/cancel',{}).catch(()=>{});
  try{
   const upload=await request('',{request_id:id,files:[{kind:'paper',name:blob.name,bytes:blob.size,sha256}]});
   const target=new URL(upload.files.paper.upload_url);
   if(target.protocol!=='https:'||!['.e2b.app','.e2b.dev'].some(suffix=>target.hostname.endsWith(suffix)))throw Error('文件传输地址无效。');
   const form=new FormData();
   form.append('file',blob,blob.name);
   const response=await fetch(target,{method:'POST',body:form,credentials:'omit',redirect:'error',signal:AbortSignal.timeout(90000)});
   if(!response.ok)throw Error('PDF 上传未完成。');
   return {material:upload.files.paper.material,close};
  }catch(error){await close();throw error;}
 }
 focusImported(id){
  const paper=this.node(id);
  if(!paper)return;
  this.filters.paper_id='';
  const visible=this.matchingPapers().some(row=>row.paper_id===id);
  if(!visible)this.filters={paper_id:'',year:'',direction:'',venue:''};
  this.linkSource=null;
  this.select(id,true);
 }
 async expandPaper(id,options,notice=''){
  const result=await this.graphTask('/literature/expand',{paper_id:id,...options},
   {key:'expand:'+id,label:'正在扩展节点',tone:'expand'});
  if(result){
   const failed=!result.data||Boolean(result.notice||notice);
   this.finishTask(!result.data?'扩展节点失败':failed?'节点扩展有未完成项':'已扩展节点',failed,'expand');
  }
 }
 async expandImported(id,notice=''){
  if(!this.node(id))return;
  this.focusImported(id);
  await this.expandPaper(id,{kinds:Object.keys(RELATIONS),limit:5,depth:2,max_total:5},notice);
 }
 async importPaper(reference,file){
  const name=file?.name||reference;
  let transfer=null;
  let result;
  try{
   result=await this.graphTask('/papers/import',async()=>{
    if(!file)return {reference};
    if(file.size<=3_400_000)return {paper:{name:file.name,content_base64:await encoded(file)}};
    transfer=await this.stagePaper(file);
    return {paper:transfer.material};
   },{key:'import:'+name,label:'正在添加节点',tone:'add'});
  }finally{if(transfer)await transfer.close();}
  if(!result)return;
  if(!result.data){this.finishTask('添加节点失败',true);return;}
  const {focus_paper_id:id,already_exists}=result.data;
  if(already_exists){this.focusImported(id);this.finishTask('已定位到已有节点');return;}
  if(file&&this.node(id)?.pdf_available)this.attachedPDF={id,file};
  this.finishTask('已添加节点');
  await this.expandImported(id,result.notice);
 }
 async extractPaper(paper,original,{lookup=false,savedPdf=false}={}){
  if(!paper)return;
  const payload={paper_id:paper.id};
  const project=(this.h.projects?.()||[]).find(p=>p.id===paper.project_id);
  const blob=lookup||savedPdf?null:original||this.localPaper(paper);
  const tone=lookup?'lookup':savedPdf?'contribution':'add';
  const label=lookup?'正在查找节点原文':savedPdf?'正在展开子贡献':'正在保存节点论文';
  let transfer=null;
  let result;
  try{
   result=await this.graphTask('/contributions/extract',async()=>{
    if(blob&&blob.size<=3_400_000)payload.paper={name:blob.name||project?.paper?.name||'paper.pdf',content_base64:await encoded(blob)};
    else if(original){transfer=await this.stagePaper(original);payload.paper=transfer.material;}
    else if(!lookup&&!savedPdf&&project?.online_upload?.expires_at*1000>Date.now())payload.paper=project.online_upload.materials?.paper;
    return payload;
   },{key:'pdf:'+paper.id,label,tone});
  }finally{if(transfer)await transfer.close();}
  if(!result)return;
  const latest=this.node(paper.id);
  const available=result.data&&latest?.pdf_available;
  if(available&&original)this.attachedPDF={id:paper.id,file:original};
  const failed=!available||Boolean(result.notice);
  const message=lookup?(available?'已保存节点原文':'查找节点原文失败'):
   savedPdf?(latest?.detail_count?'已提取子贡献':'未能提取子贡献'):(available?'已保存节点论文':'保存节点论文失败');
  this.finishTask(failed&&available?message+'，核验未完成':message,failed||savedPdf&&!latest?.detail_count,tone);
  if(result.data&&latest?.detail_count&&this.selected===paper.id)await this.togglePaperDetails();
 }
 savePosition(id){
  const node=this.node(id);
  if(!node)return;
  const generation=this.generation;
  const change={id,x:node.x,y:node.y,pinned:this.pinned.has(id)};
  this.layoutQueue=this.layoutQueue.catch(()=>{}).then(async()=>{
   if(generation!==this.generation)return;
   try{await this.api('/layout',{change});}
   catch(error){if(generation===this.generation)this.h.toast?.('布局自动保存失败：'+error.message);}
  });
 }
 applyGraph(data){
  if((data.revision??0)<(this.data?.revision??0))return;
  const paperPositions=new Map((this.data?.nodes||[]).filter(node=>node.node_type==='Paper').map(node=>[node.id,{x:node.x,y:node.y}]));
  for(const node of data.nodes)if(node.node_type==='Paper'&&paperPositions.has(node.id))Object.assign(node,paperPositions.get(node.id));
  this.data=data;this.pinned=new Set(data.layout?.pinned||[]);
  if(!this.node(this.selected))this.selected=data.focus_paper_id||null;
 }
 renderTaskState(){
  const active=globalThis.document?.activeElement;
  const field=active?.matches?.('[data-kg-import] [name="reference"],[data-kg-combo]')?active:null;
  const draft=field&&{value:field.value,start:field.selectionStart,end:field.selectionEnd,combo:field.dataset.kgCombo,
   open:field.getAttribute('aria-expanded')==='true'};
  this.h.render();
  if(!draft)return;
  const next=draft.combo?document.getElementById('kg-filter-'+draft.combo):document.querySelector('[data-kg-import] [name="reference"]');
  if(!next)return;
  next.value=draft.value;
  next.focus({preventScroll:true});
  if(draft.start!=null)next.setSelectionRange(draft.start,draft.end);
  if(draft.combo&&!draft.open)this.closeOptions(next);
 }
 finishTask(text,failed=false,tone='add'){
  const key=Symbol();
  this.taskFeedback.set(key,{text,tone,failed});
  this.renderTaskState();
  setTimeout(()=>{if(this.taskFeedback.delete(key))this.renderTaskState();},3200);
 }
 async graphTask(path,payload,{key,label,cancelable=true,tone='add'}){
  if([...this.operations.values()].some(task=>task.key===key))return null;
  const version=this.generation;
  const task={key,label,text:label,tone,id:crypto.randomUUID().replaceAll('-',''),cancelable};
  this.operations.set(task.id,task);
  this.renderTaskState();
  const poll=async()=>{
   try{
    const {phase}=await this.api('/operations/'+task.id+'/progress');
    const status=expansionPhases[phase];
    if(status&&this.operations.has(task.id)){
     task.text=task.label+'，'+status;
     this.syncOperationOverlay();
    }
   }catch{}
   if(this.operations.has(task.id))task.timer=setTimeout(poll,1500);
  };
  try{
   await this.layoutQueue;
   if(version!==this.generation||task.cancelled)return null;
   const request=typeof payload==='function'?await payload():payload;
   if(version!==this.generation||task.cancelled)return null;
   if(cancelable)task.timer=setTimeout(poll,1000);
   const data=await this.api(path,cancelable?{...request,operation_id:task.id}:request);
   if(version!==this.generation||task.cancelled)return null;
   this.applyGraph(data);
   return {data,notice:data.method_notice||''};
  }catch(error){
   return version===this.generation&&!task.cancelled?{notice:error.name==='TimeoutError'?'图谱请求超时，请重试。':error.message}:null;
  }finally{
   clearTimeout(task.timer);
   this.operations.delete(task.id);
   if(version===this.generation)this.renderTaskState();
  }
 }
 async stopTask(task){
  if(!task||task.stopping)return;
  task.stopping=true;
  this.h.render();
  try{
   const value=await this.api('/operations/'+task.id+'/cancel',{});
   if(this.operations.has(task.id)&&value.status==='cancelled'){
    task.cancelled=true;
    clearTimeout(task.timer);
    this.operations.delete(task.id);
    this.finishTask('已停止操作',false,task.tone);
   }
  }catch(error){this.finishTask('停止操作失败',true);}
  finally{task.stopping=false;this.h.render();}
 }
 async changeLiterature(path,payload){
  if(this.mutating)return;
  const version=this.generation;
  this.mutating=true;
  this.h.render();
  try{
   await this.layoutQueue;
   if(version!==this.generation)return null;
   const data=await this.api(path,payload);
   if(version!==this.generation)return null;
   this.applyGraph(data);
   return true;
  }catch(error){
   if(version===this.generation)this.finishTask('节点操作失败',true);
  }finally{
   if(version===this.generation){
    this.mutating=false;
    this.h.render();
   }
  }
 }
 afterRender(){
  this.syncOperationOverlay();
  const svg=document.querySelector('[data-kg-svg]');if(!svg||svg.dataset.bound)return;svg.dataset.bound='1';
  const pt=ev=>{const r=svg.getBoundingClientRect();return {x:(ev.clientX-r.left)*(1040/r.width),y:(ev.clientY-r.top)*(680/r.height)};};
  svg.addEventListener('wheel',ev=>{ev.preventDefault();const p=pt(ev),k=ev.deltaY<0?1.12:1/1.12,z=Math.min(3,Math.max(.35,this.zoom*k));this.pan.x=p.x-(p.x-this.pan.x)*(z/this.zoom);this.pan.y=p.y-(p.y-this.pan.y)*(z/this.zoom);this.zoom=z;this.applyTransform();},{passive:false});
  svg.addEventListener('pointerdown',ev=>{const g=ev.target.closest('[data-kg-node]'),p=pt(ev);if(ev.button===2)return;this.drag=g?{node:g.dataset.kgNode,start:p,moved:false}:{pan:true,start:p,origin:{...this.pan}};svg.setPointerCapture(ev.pointerId);});
  svg.addEventListener('pointermove',ev=>{if(!this.drag)return;const p=pt(ev),dx=p.x-this.drag.start.x,dy=p.y-this.drag.start.y;if(Math.abs(dx)+Math.abs(dy)>3)this.drag.moved=true;if(this.drag.pan){this.pan={x:this.drag.origin.x+dx,y:this.drag.origin.y+dy};this.applyTransform();}else if(this.drag.moved){const n=this.node(this.drag.node);if(!n)return;const next={x:n.x+dx/this.zoom,y:n.y+dy/this.zoom};
    this.drag.start=p;
    if(this.data.nodes.some(other=>other!==n&&(other.node_type==='Paper'||this.pinned.has(other.id))&&Math.hypot(other.x-next.x,other.y-next.y)<MIN_NODE_GAP))return;
    this.drag.positionChanged=true;
    Object.assign(n,next);
    this.initialPositions.set(n,next);
    this.pinned.add(n.id);
    svg.querySelector(`[data-kg-node="${CSS.escape(n.id)}"]`)?.setAttribute('transform',`translate(${n.x} ${n.y})`);
   }});
  svg.addEventListener('pointercancel',()=>{const d=this.drag;this.drag=null;if(d?.node&&d.positionChanged){this.savePosition(d.node);this.redrawGraph();}});
  svg.addEventListener('pointerup',()=>{const d=this.drag;this.drag=null;if(d?.node){if(d.positionChanged){this.savePosition(d.node);this.redrawGraph();}else if(!d.moved)this.select(d.node);}});
  svg.addEventListener('keydown',ev=>{const node=ev.target.closest('[data-kg-node]');if(!node||!['Enter',' '].includes(ev.key))return;ev.preventDefault();this.select(node.dataset.kgNode);document.querySelector(`[data-kg-node="${CSS.escape(node.dataset.kgNode)}"]`)?.focus();});
  svg.addEventListener('contextmenu',ev=>{
   const target=ev.target.closest('[data-kg-node]');
   if(!target)return;
   ev.preventDefault();
   this.linkSource=null;
   this.selected=target.dataset.kgNode;
   this.contextNode=this.selected;
   this.focusMode=true;
   this.h.render();
  });
 }
 applyTransform(){const v=document.querySelector('[data-kg-viewport]');if(v)v.setAttribute('transform',`translate(${this.pan.x} ${this.pan.y}) scale(${this.zoom})`);}
 redrawGraph(){const c=document.querySelector('[data-kg-canvas]');if(!c){this.h.render();return;}const t=document.createElement('template');t.innerHTML=this.canvasView();const next=t.content.firstElementChild;c.replaceWith(next);this.afterRender();}
 select(id,center=false){const n=this.node(id);if(!n)return;if(this.linkSource&&id!==this.linkSource)return this.addRelation(id);this.focusMode=true;this.contextNode=null;if(this.selected!==id)this.expansionPaper=null;this.selected=id;this.inspectorTab='detail';
  if(n.node_type!=='Paper'){this.expanded.add(n.paper_id);if(n.node_type==='Detail')this.expanded.add(n.parent_id);}
  if(center){this.pan={x:520-n.x*this.zoom,y:340-n.y*this.zoom};}this.h.render();}
 async togglePaperDetails(){
  const paper=this.node(this.selected);
  if(paper?.node_type!=='Paper'||this.mutating)return;
  if(this.paperDetailsExpanded(paper)){
   this.expanded.delete(paper.id);
   this.h.render();
   return;
  }
  const children=this.data.nodes.filter(node=>node.parent_id===paper.id);
  if(!children.some(child=>this.data.nodes.some(node=>node.parent_id===child.id))){
   if(paper.pdf_available&&['pending','unavailable'].includes(paper.method_detail_status)){
    return this.extractPaper(paper,null,{savedPdf:true});
   }
   this.finishTask('暂无可展开的子贡献',true,'contribution');
   return;
  }
  this.expanded.add(paper.id);
  for(const child of children)this.expanded.add(child.id);
  this.finishTask('已展开子贡献',false,'contribution');
 }
 toggleExpand(id){this.expanded.has(id)?this.expanded.delete(id):this.expanded.add(id);this.selected=id;this.h.render();}
 async addRelation(target){
  if(this.mutating)return;
  const source=this.linkSource;
  const left=this.node(source),right=this.node(target);
  if(!left||!right||(left.node_type==='Paper')!==(right.node_type==='Paper')){
   this.finishTask('请选择同类节点建立链接',true);
   return;
  }
  this.linkSource=null;
  this.linkDraft={source,target};
  this.h.render();
  document.querySelector('[data-kg-link-form] input')?.focus();
 }
 async editRelation(payload){
  if(this.mutating)return;
  const generation=this.generation;
  const removing=payload.action==='remove';
  const tone=removing?'remove':'add';
  this.linkDraft=null;
  const result=await this.graphTask('/relations/edit',payload,
   {key:'relation:'+payload.source+':'+payload.target,label:removing?'正在删除节点链接':'正在建立节点链接',cancelable:false,tone});
  if(generation!==this.generation||!result)return;
  if(result.data)this.inspectorTab='relations';
  else if(!removing)this.linkDraft=payload;
  const text=removing?(result.data?'已删除节点链接':'删除节点链接失败'):(result.data?'已建立节点链接':'建立节点链接失败');
  this.finishTask(text,!result.data,tone);
 }
 async action(a){
  if(a==='link-dismiss'){this.linkDraft=null;this.h.render();return;}
  if(a==='link-start'){
   this.linkDraft=null;
   this.linkSource=this.linkSource?null:this.selected;
   this.contextNode=null;
   this.h.render();
   return;
  }
  if(a==='pin'){
   const id=this.selected;
   this.pinned.has(id)?this.pinned.delete(id):this.pinned.add(id);
   this.contextNode=null;
   this.savePosition(id);
   this.h.render();
   return;
  }
  if(a==='load')return this.open(null);
  if(a==='home-view'){this.zoom=1;this.pan={x:0,y:0};this.focusMode=false;this.h.render();return;}
  if(a==='expand-literature'){
   const open=this.expansionPaper!==this.selected;
   this.expansionPaper=open?this.selected:null;
   this.h.render();
   if(open){
    const form=document.querySelector('[data-kg-literature]');
    form?.scrollIntoView({block:'nearest'});
    form?.querySelector('input')?.focus({preventScroll:true});
   }
   return;
  }
  if(a==='focus'){this.focusMode=true;this.h.render();return;}
  if(a==='exit-focus'){this.focusMode=false;this.h.render();return;}

  if(a==='delete-node'){
   const node=this.node(this.selected);
   if(!node)return;
   const removed=new Set([node.id]);
   for(const item of this.data.nodes){
    if(node.node_type==='Paper'&&item.paper_id===node.id||item.parent_id===node.id)removed.add(item.id);
   }
   const count=this.data.edges.filter(edge=>removed.has(edge.source)||removed.has(edge.target)).length;
   if(confirm(`删除此图谱节点及其下级节点？将移除 ${count} 条关联线，原论文和审查报告会保留。`)){
    const result=await this.graphTask('/nodes/delete',{node_id:node.id},
     {key:'delete:'+node.id,label:'正在删除节点',cancelable:false,tone:'remove'});
    if(result)this.finishTask(result.data?'已删除节点':'删除节点失败',!result.data,'remove');

   }
  }
 }
 bind(){
  window.addEventListener('resize',()=>this.syncOperationOverlay());
  window.addEventListener('scroll',()=>this.syncOperationOverlay(),true);
  document.addEventListener('submit',ev=>{
   if(ev.target.matches('[data-kg-link-form]')){
    ev.preventDefault();
    if(!this.linkDraft)return;
    const form=new FormData(ev.target),label=String(form.get('label')||'').trim();
    if(!label){this.finishTask('请填写链接名称',true);return;}
    return this.editRelation({...this.linkDraft,action:'add',label,note:String(form.get('note')||'')});
   }
   if(ev.target.matches('[data-kg-import]')){
    ev.preventDefault();
    const reference=String(new FormData(ev.target).get('reference')||'').trim();
    if(reference){ev.target.reset();this.importPaper(reference);}
    return;
   }
   if(!ev.target.matches('[data-kg-literature]'))return;
   ev.preventDefault();
   const form=new FormData(ev.target),kinds=form.getAll('kind');
   if(!kinds.length){this.finishTask('请至少选择一种研究关系',true,'expand');return;}
   const paper=this.node(ev.target.dataset.kgLiterature);
   if(!paper||paper.id!==this.selected||paper.node_type!=='Paper')return;
   this.expansionPaper=null;
   this.expandPaper(paper.id,{kinds,depth:Number(form.get('depth')),max_total:Number(form.get('max_total'))});
  });
  document.addEventListener('change',ev=>{
   if(ev.target.matches('[data-kg-import-pdf]')&&ev.target.files?.[0])return this.importPaper(null,ev.target.files[0]);
   if(ev.target.matches('[data-kg-original]')&&ev.target.files?.[0])this.extractPaper(this.node(ev.target.dataset.kgOriginal),ev.target.files[0]);
  });
  document.addEventListener('click',async ev=>{
   const stop=ev.target.closest('[data-kg-stop]');
   if(stop)return this.stopTask(this.operations.get(stop.dataset.kgStop));
   const dismiss=ev.target.closest('[data-kg-dismiss-fulltext]');
   if(dismiss){this.dismissedFulltext.add(dismiss.dataset.kgDismissFulltext);return this.h.render();}
   const view=ev.target.closest('[data-kg-view-pdf]');
   if(view)return this.viewPaper(this.node(view.dataset.kgViewPdf));
   const reading=ev.target.closest('[data-kg-reading]');
   if(reading)return this.changeLiterature('/literature/paper',{paper_id:reading.dataset.kgReading,action:reading.dataset.kgReadingAction});
   const lookup=ev.target.closest('[data-kg-find-pdf]');
   if(lookup)return this.extractPaper(this.node(lookup.dataset.kgFindPdf),null,{lookup:true});
   const copy=ev.target.closest('[data-copy-cmd]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copyCmd);this.h.toast?.('命令已复制');}catch{this.h.toast?.('复制失败，请手动选择命令');}return;}
   const kg=ev.target.closest('[data-open-kg]');if(kg){ev.preventDefault();ev.stopPropagation();this.open(kg.dataset.openKg);return;}
   if(ev.target.closest('[data-kg-expand-paper]'))return this.togglePaperDetails();
   const removal=ev.target.closest('[data-kg-remove-source]');
   if(removal&&confirm('删除这条联系？')){
    return this.editRelation({source:removal.dataset.kgRemoveSource,target:removal.dataset.kgRemoveTarget,action:'remove'});
   }
   if(removal)return;
   const t=ev.target.closest('[data-kg-action],[data-kg-tab],[data-kg-select],[data-kg-expand]');if(!t)return;
   if(t.dataset.kgTab){
    this.contextNode=null;
    this.inspectorTab=t.dataset.kgTab;
    this.h.render();
    if(this.inspectorTab==='lineage'){
     const item=document.querySelector('.kg-lineage .current');
     const panel=item?.closest('.kg-insp-body');
     if(panel)panel.scrollTop+=item.getBoundingClientRect().top-panel.getBoundingClientRect().top+(item.offsetHeight-panel.clientHeight)/2;
    }
    return;
   }
   if(t.dataset.kgSelect){return this.select(t.dataset.kgSelect,true);}
   if(t.dataset.kgExpand)return this.toggleExpand(t.dataset.kgExpand);
   if(t.dataset.kgAction)return this.action(t.dataset.kgAction);
  },true);
  const combo='[data-kg-combo]';
  document.addEventListener('focusin',ev=>{if(ev.target.matches?.(combo))this.updateOptions(ev.target);});
  document.addEventListener('focusout',ev=>{if(ev.target.matches?.(combo))this.closeOptions(ev.target);});
  document.addEventListener('input',ev=>{if(ev.target.matches?.(combo)&&!ev.isComposing)this.updateOptions(ev.target);});
  document.addEventListener('compositionend',ev=>{if(ev.target.matches?.(combo))this.updateOptions(ev.target);});
  document.addEventListener('keydown',ev=>{if(ev.target.matches?.(combo))this.comboKey(ev,ev.target);},true);
  document.addEventListener('pointerdown',ev=>{
   if(ev.target.closest('[data-kg-option]'))ev.preventDefault();
  });
  document.addEventListener('click',ev=>{
   const option=ev.target.closest('[data-kg-option]');
   if(option)this.applyFilter(option.closest('.kg-filter').querySelector(combo),option.dataset.kgOption);
   else if(ev.target.matches?.(combo)&&ev.target.nextElementSibling.hidden)this.updateOptions(ev.target);
  });
  document.addEventListener('change',ev=>{
   if(ev.target.matches?.('[data-kg-manage]')){
    const action=ev.target.value;
    ev.target.value='';
    const paperId=ev.target.dataset.kgManage;
    if(action==='remove'){
     if(confirm('从个人图谱移除此公开文献？')){
      this.graphTask('/nodes/delete',{node_id:paperId},{key:'delete:'+paperId,label:'正在删除节点',cancelable:false,tone:'remove'})
       .then(result=>{if(result)this.finishTask(result.data?'已删除节点':'删除节点失败',!result.data,'remove');});
     }
    }else if(action)this.changeLiterature('/literature/paper',{paper_id:paperId,action});
    return;
   }
  });
 }
}
