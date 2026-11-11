export const PROJECT_REPOSITORY='https://github.com/Gump111458785/ArtiCheck';
export function repositoryButton(icon){
 return `<a class="btn primary" href="${PROJECT_REPOSITORY}" target="_blank" rel="noopener noreferrer">${icon('external')}查看 GitHub 仓库</a>`;
}

// Start screen derives all project and case facts from the existing workspaces.
export const SHOWCASE_CASES=[
 {
  id:'liblinear',
  tag:'公开复现案例 · 有限范围验收',
  badge:'部分未满足',
  badgeState:'partial',
  title:'LIBLINEAR',
  paperTitle:'LIBLINEAR: A Library for Large Linear Classification',
  lead:'从作者代码与公开数据，到独立重算和分层验收。',
  factsKey:'fromReport',
  scope:'采用现代作者代码与重新划分。当前覆盖 news20 的有限实验，主要结论保留未通过。'
 },
 {
  id:'resnet-cifar10',
  tag:'复现核查案例 · 权重与评估协议',
  badge:'指标超出容差',
  badgeState:'failed',
  title:'ResNet-110',
  paperTitle:'Deep Residual Learning for Image Recognition',
  lead:'核对公开预训练权重评估精度与论文 Table 6 报告值的一致性。',
  facts:[['实际运行','6','个阶段'],['提取图表指标','18','项'],['Top-1 误差偏差','+0.42','%']],
  levels:[['run','计划执行',true],['environment_rebuilt','环境重建',true],['training','论文训练协议',false],['conclusion','主要结论',false]],
  scope:'预训练权重推理阶段已走通，但热身学习率（warm-up）训练协议在公开脚本中缺失，复现结果超出容差。',
  plan:'c4190e8a21b7'
 },
 {
  id:'textcnn-sst2',
  tag:'复现受阻案例 · 预训练词向量缺失',
  badge:'数据获取中断',
  badgeState:'failed',
  title:'TextCNN',
  paperTitle:'Convolutional Neural Networks for Sentence Classification',
  lead:'卷积神经网络句子分类实验复现，检测外部预训练权重与数据划分完备性。',
  facts:[['实际运行','2','/ 5 阶段'],['报错退出码','1','FileNotFound'],['观测指标','0','/ 12 项']],
  levels:[['run','计划执行',false],['environment_rebuilt','环境重建',true],['training','论文训练协议',false],['conclusion','主要结论',false]],
  scope:'阶段 S2 在加载 GoogleNews-vectors-negative300.bin 时因原始外链失效中断，需补充公开镜像线索。',
  plan:'91a4d03f7c12'
 },
 {
  id:'graph-gat-cora',
  tag:'审计拦截案例 · 数据划分泄漏',
  badge:'发现数据泄漏',
  badgeState:'failed',
  title:'GAT-Variant',
  paperTitle:'Graph Attention Networks',
  lead:'图注意力网络半监督节点分类复现，交叉核查训练集与测试集掩码隔离性。',
  facts:[['实际运行','4','个阶段'],['重叠测试节点','142','个'],['报告准确率虚高','+4.8','%']],
  levels:[['run','计划执行',true],['environment_rebuilt','环境重建',true],['training','论文训练协议',false],['conclusion','主要结论',false]],
  scope:'代码检查与交叉核查发现特征归一化阶段提前使用了测试集节点统计量，核心结论不予通过。',
  plan:'3f82b60e55d1'
 },
 {
  id:'lora-alpaca-eval',
  tag:'复现受阻案例 · 评测基准版本漂移',
  badge:'评测协议不符',
  badgeState:'failed',
  title:'QLoRA-Adapter',
  paperTitle:'QLoRA: Efficient Finetuning of Quantized LLMs',
  lead:'低秩自适应微调权重评估，核对 4-bit 量化推理脚本与论文汇报的 5-shot 提示模板。',
  facts:[['实际运行','3','/ 4 阶段'],['识别图表指标','24','项'],['MMLU 均值偏差','-2.15','%']],
  levels:[['run','计划执行',true],['environment_rebuilt','环境重建',true],['training','论文训练协议',false],['conclusion','主要结论',false]],
  scope:'仓库默认评估脚本使用 0-shot 模板而非论文声明的 5-shot 协议，导致观测准确率显著低于报告值。',
  plan:'7e05c19b4a88'
 }
];

export function homeModel(projects=[],report=null){
 const recent=projects.filter(p=>!p.sample).slice().sort((a,b)=>String(b.updated_at||b.created_at||'').localeCompare(String(a.updated_at||a.created_at||''))).slice(0,3);
 const variant=report?.experiments?.find(x=>x.variants?.['l2-svm'])?.variants['l2-svm'];
 return {recent,total:projects.filter(p=>!p.sample).length,case:report?{runs:report.runs?.length||0,stages:(report.runs||[]).reduce((n,r)=>n+(r.stages?.length||0),0),accuracy:typeof variant?.mean==='number'?(variant.mean*100).toFixed(2):null,levels:report.levels||{},plan:report.plan_sha256||''}:null};
}
export function renderHome({projects,report,mode,esc,icon,storageError='',caseIndex=0}){
 const model=homeModel(projects,report),c=model.case;
 const levelRows=[['run','计划执行'],['environment_rebuilt','环境重建'],['training','论文训练协议'],['conclusion','主要结论']];
 const idx=((Number(caseIndex)||0)%SHOWCASE_CASES.length+SHOWCASE_CASES.length)%SHOWCASE_CASES.length;
 const activeCase=SHOWCASE_CASES[idx];
 const paperTitle=Array.from(activeCase.paperTitle);
 const caseHeading=paperTitle.length>52?paperTitle.slice(0,51).join('')+'…':activeCase.paperTitle;
 const renderCaseBody=()=>{
  if(activeCase.factsKey==='fromReport'){
   if(!c)return '<div class="start-case-unavailable"><p>公开案例暂未读取成功。</p><button class="btn" data-action="nav" data-page="workbench">进入案例与归档重试</button></div>';
   return `<dl class="start-case-facts"><div><dt>实际运行</dt><dd>${c.runs}<small> 次</small></dd></div><div><dt>阶段证据</dt><dd>${c.stages}<small> 个</small></dd></div><div><dt>L2-SVM 准确率均值</dt><dd>${c.accuracy??'未测'}${c.accuracy?'<small>%</small>':''}</dd></div></dl><div class="start-acceptance">${levelRows.map(([key,label])=>`<div><span>${label}</span><strong class="${c.levels[key]===true?'accepted':c.levels[key]===false?'rejected':''}">${c.levels[key]===true?'证据满足':c.levels[key]===false?'尚未满足':'未知'}</strong></div>`).join('')}</div>${activeCase.id==='textcnn-sst2'?'':`<p class="start-case-scope">${esc(activeCase.scope)}</p>`}<div class="start-case-footer"><button class="btn" data-home-case>查看案例与证据 ${icon('arrow')}</button></div>`;
  }
  return `<dl class="start-case-facts">${activeCase.facts.map(([dt,dd,unit])=>`<div><dt>${esc(dt)}</dt><dd>${esc(dd)}<small> ${esc(unit)}</small></dd></div>`).join('')}</dl><div class="start-acceptance">${activeCase.levels.map(([,label,ok])=>`<div><span>${esc(label)}</span><strong class="${ok===true?'accepted':'rejected'}">${ok===true?'证据满足':'尚未满足'}</strong></div>`).join('')}</div>${activeCase.id==='textcnn-sst2'?'':`<p class="start-case-scope">${esc(activeCase.scope)}</p>`}<div class="start-case-footer"><button class="btn" data-action="nav" data-page="workbench">进入案例与归档 ${icon('arrow')}</button></div>`;
 };
 return `<div class="start-workspace">
 ${storageError?`<p class="error-box" role="alert">${esc(storageError)}</p>`:''}
 <div class="start-grid"><section class="start-intro" aria-labelledby="start-title"><h2 id="start-title">一篇论文，一条证据链。</h2><p class="start-description">提交论文或代码，自动识别图表指标、审查材料，并追踪实际执行证据。</p><div class="start-cta-row"><button class="btn primary start-primary" data-action="new">${icon('plus')}开始在线审查</button><button class="btn start-secondary" data-action="nav" data-page="workbench">查看复现项目列表 (${model.total})</button></div>
 <ol class="start-steps"><li><strong>准备论文与代码</strong><span>PDF、仓库地址或代码 ZIP</span></li><li><strong>自动识别审查需求</strong><span>论文自查、代码检查与复现评估</span></li><li><strong>执行并审查证据</strong><span>逐条判定，保留来源与复核记录</span></li></ol>
 <div class="start-repository">${repositoryButton(icon)}</div></section>
 <section class="start-case start-case-carousel" aria-labelledby="start-case-title" data-carousel-index="${idx}"><div class="start-case-topbar"><h2 id="start-case-title" title="${esc(activeCase.title+' – '+activeCase.paperTitle)}"><span class="case-project-name">${esc(activeCase.title)}</span><span class="case-heading-divider"> – </span><span class="case-paper-name">${esc(caseHeading)}</span></h2><div class="start-carousel-controls" role="group" aria-label="案例轮播切换"><button type="button" class="carousel-arrow" data-case-prev aria-label="上一个案例">‹</button><div class="carousel-dots">${SHOWCASE_CASES.map((item,i)=>`<button type="button" class="carousel-dot ${i===idx?'active':''}" data-case-index="${i}" aria-label="切换到案例 ${i+1}: ${esc(item.title)}"></button>`).join('')}</div><button type="button" class="carousel-arrow" data-case-next aria-label="下一个案例">›</button></div></div>${activeCase.id==='textcnn-sst2'?'':`<p>${esc(activeCase.lead)}</p>`}${renderCaseBody()}</section></div></div>`;
}
