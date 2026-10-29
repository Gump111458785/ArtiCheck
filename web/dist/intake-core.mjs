export const MAX_PDF_BYTES = 20 * 1024 * 1024;
export const MAX_ZIP_BYTES = 50 * 1024 * 1024;
export const MAX_PAGES = 150;
export function githubRepository(value) {
  let url; try { url = new URL(value.trim()); } catch { throw Error('请输入完整的 GitHub 仓库地址'); }
  const parts = url.pathname.replace(/\.git\/?$/, '').split('/').filter(Boolean);
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password || parts.length !== 2 || parts.some(x => !/^[\w.-]+$/.test(x))) throw Error('请使用 https://github.com/作者/仓库 格式');
  return {owner: parts[0], name: parts[1], url: `https://github.com/${parts.join('/')}`};
}
export function paperLink(value) {
  let url; try { url = new URL(value.trim()); } catch { throw Error('请输入完整的论文链接'); }
  if (url.protocol !== 'https:' || url.username || url.password) throw Error('论文链接需要使用 HTTPS');
  return url.href;
}
export function inspectZip(buffer) {
  const view = new DataView(buffer), length = view.byteLength;
  if (length > MAX_ZIP_BYTES) throw Error('代码 ZIP 最大为 50 MB');
  let end = -1;
  for (let i = length - 22; i >= Math.max(0, length - 65557); i--) if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i+20,true) === length) {end = i; break;}
  if (end < 0) throw Error('ZIP 目录损坏或文件格式不受支持');
  const count=view.getUint16(end+10,true), disk=view.getUint16(end+4,true), otherDisk=view.getUint16(end+6,true), size=view.getUint32(end+12,true), start=view.getUint32(end+16,true);
  if (disk || otherDisk || count===65535 || count>5000 || start+size>end) throw Error('仅支持单卷 ZIP，最多 5000 个文件，不支持 ZIP64');
  let offset=start, total=0; const files=[], names=new Set();
  for(let i=0;i<count;i++){
    if(offset+46>start+size || view.getUint32(offset,true)!==0x02014b50) throw Error('ZIP 文件目录不完整');
    const flags=view.getUint16(offset+8,true), bytes=view.getUint32(offset+24,true), n=view.getUint16(offset+28,true), extra=view.getUint16(offset+30,true), comment=view.getUint16(offset+32,true);
    if(offset+46+n+extra+comment>start+size) throw Error('ZIP 文件目录越界');
    const name=new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(buffer,offset+46,n));
    if(flags&1 || name.includes('\\') || name.includes('\0') || name.startsWith('/') || /^[A-Za-z]:/.test(name) || name.split('/').includes('..') || names.has(name)) throw Error('ZIP 包含不受支持的路径、重复文件或加密文件');
    names.add(name);total+=bytes;if(total>500*1024*1024) throw Error('ZIP 解压大小超过 500 MB');
    if(!name.endsWith('/')) files.push({path:name,size:bytes}); offset+=46+n+extra+comment;
  }
  return {files,uncompressed_bytes:total};
}
export function repositoryClues(files) {
  const paths=files.map(f=>typeof f==='string'?f:f.path);
  const match=re=>paths.filter(p=>re.test(p)).slice(0,8);
  return [
    {id:'readme',label:'运行说明',files:match(/(^|\/)readme[^/]*$/i)},
    {id:'dependencies',label:'依赖定义',files:match(/(^|\/)(requirements[^/]*\.txt|pyproject\.toml|environment[^/]*\.ya?ml|package\.json|conda[^/]*\.ya?ml)$/i)},
    {id:'container',label:'环境镜像',files:match(/(^|\/)(dockerfile[^/]*|docker-compose[^/]*\.ya?ml)$/i)},
    {id:'entry',label:'实验入口线索',files:match(/(^|\/)(train|eval|evaluate|test|reproduce|run|probe)[^/]*\.(py|sh|ipynb)$/i)}
  ];
}
export function candidatesFromPages(pages) {
  const found=[];
  for(const page of pages){
    const lines=page.lines||page.text.split(/\n/);
    for(let i=0;i<lines.length;i++){
      const quote=lines.slice(Math.max(0,i-1),i+2).join(' ').replace(/\s+/g,' ').trim().slice(0,1000);
      const line=lines[i].trim();
      if(!/(accuracy|macro.?f1|micro.?f1|\bf1\b|\bauc\b|bleu|rouge|perplexity|precision|recall|准确率|召回率|精确率)/i.test(line) || !/(?:^|[\s:=()])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:%|\b)/.test(line)) continue;
      if(found.some(c=>c.page===page.number&&c.quote===quote)) continue;
      found.push({id:`candidate-${page.number}-${i}`,page:page.number,quote,text:line.slice(0,500),kind:'metric',metric:'',expected:'',tolerance:'0.001',selected:true,confirmed:false,binding:''});
      if(found.length>=30) return found;
    }
  }
  return found;
}
export function validateClaim(claim,pageCount) {
  if(!claim.text?.trim() || !claim.quote?.trim()) throw Error('请填写实验主张和论文原文依据');
  if(!Number.isInteger(Number(claim.page)) || Number(claim.page)<1 || Number(claim.page)>pageCount) throw Error('出处页码需要对应已导入论文');
  if(!['metric','split_disjoint','baseline_equal'].includes(claim.kind)) throw Error('请选择受支持的核查类型');
  if(claim.kind==='metric' && (!claim.metric?.trim() || claim.expected==='' || !Number.isFinite(Number(claim.expected)) || claim.tolerance==='' || !Number.isFinite(Number(claim.tolerance)) || Number(claim.tolerance)<0)) throw Error('请确认指标名称、报告值和非负容差');
  return true;
}
export function executionClaims(claims,manifest,pageCount,paperSha='') {
  const selected=claims.filter(c=>c.selected);if(!selected.length) throw Error('至少选择一条实验主张');if(selected.length>100)throw Error('每次最多执行 100 条主张');
  const used=new Set();
  return selected.map(c=>{
    validateClaim(c,pageCount);if(!c.confirmed) throw Error('选中的主张尚未逐条确认');
    const target=manifest.claims.find(t=>t.id===c.binding);
    if(!target || target.kind!==c.kind || used.has(target.id)) throw Error('每条主张需要绑定一个独立且类型一致的执行检查项');
    used.add(target.id);
    const spec={...target.spec};if(c.kind==='metric'){spec.expected=Number(c.expected);spec.tolerance=Number(c.tolerance);}
    return {...target,text:c.text.trim(),source:`paper:${paperSha?'sha256:'+paperSha+':':''}p${c.page}; ${c.quote.slice(0,400)}`,spec};
  });
}
export function evaluationLayers(project,run) {
  const selected=(project.claims||[]).filter(c=>c.selected);
  const resourcesReady=['data','weights'].every(k=>!project.resources?.[k+'_required']||project.preflight?.checks?.some(c=>c.id===k&&c.status==='ready'));
  const materials=resourcesReady&&!!project.paper?.pages?.length&&!!project.repository?.files?.length&&selected.length>0&&selected.every(c=>c.confirmed);
  const tools=run?.report?.evidence?.filter(e=>e.tool==='sandbox'||e.payload?.returncode!==undefined||e.payload?.payload)||[];
  const executed=run?.status==='completed'&&!!run?.report&&tools.length>0&&tools.every(e=>e.success);
  const findings=run?.report?.findings||[];
  const aligned=executed&&findings.length===selected.length&&findings.every(f=>f.verdict==='supported');
  return [
    {label:'材料与范围',status:materials?'已确认':'待补充',detail:materials?`${selected.length} 条主张有论文出处，代码材料已记录`:!resourcesReady?'所需数据或权重尚未通过本地路径预检':'需要论文正文、代码材料和已确认主张'},
    {label:'代码运行',status:run?.status==='running'?'执行中':run?.status==='cancelled'?'已停止':executed?'执行完成':run?.status==='failed'?'执行失败':'未验证',detail:executed?'选定 probe 返回成功；不代表完整训练已复现':run?.error||'需要本地执行记录'},
    {label:'指标与主张',status:aligned?'选定主张获支持':executed&&findings.some(f=>f.verdict==='issue')?'存在不一致':'无法判定',detail:executed?`${findings.filter(f=>f.verdict==='supported').length} 条获支持，${findings.filter(f=>f.verdict==='issue').length} 条有问题，${findings.filter(f=>f.verdict==='inconclusive').length} 条证据不足`:'尚无足够执行证据'}
  ];
}
