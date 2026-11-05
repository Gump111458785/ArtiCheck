// Group verified rows without merging model variants, units or evaluation protocols.
const clean=value=>String(value??'').trim();
export function metricFamily(metric){
 const s=clean(metric).toLowerCase();
 if(/robust|corrupt|attack|ood|鲁棒|扰动|泛化/.test(s))return '鲁棒性与泛化';
 if(/accuracy|top[ -]?[15]|error|precision|recall|f[ -]?1|auc|ap\b|iou|dice|ndcg|mrr|hit.rate|准确|错误率|精度|召回/.test(s))return '预测质量';
 if(/latency|time|speed|throughput|fps|flops|memory|parameter|cost|时延|时间|吞吐|显存|参数|成本/.test(s))return '效率与资源';
 if(/loss|perplexity|ppl|bleu|rouge|meteor|损失|困惑/.test(s))return '损失与生成质量';
 if(/robust|corrupt|attack|ood|鲁棒|扰动|泛化/.test(s))return '鲁棒性与泛化';
 return '其他指标';
}
export function metricCatalog(metrics,{audience='all',query=''}={}){
 const datasets=new Map(),q=clean(query).toLowerCase();let count=0;
 for(const [index,row] of metrics.entries()){
  if(audience==='author'&&!row.author_method||audience==='baseline'&&row.author_method)continue;
  if(q&&!Object.values(row).filter(x=>typeof x==='string'||typeof x==='number').join(' ').toLowerCase().includes(q))continue;
  const dataset=clean(row.dataset)||'未标注数据集',family=metricFamily(row.metric);
  if(!datasets.has(dataset))datasets.set(dataset,{name:dataset,count:0,families:new Map()});
  const d=datasets.get(dataset);if(!d.families.has(family))d.families.set(family,{name:family,count:0,groups:new Map()});
  const f=d.families.get(family),label=clean(row.reference)||'未标注图表',protocol=clean(row.protocol),key=JSON.stringify([label,protocol]);
  if(!f.groups.has(key))f.groups.set(key,{reference:label,protocol,rows:[]});
  f.groups.get(key).rows.push({row,index});d.count++;f.count++;count++;
 }
 return {count,datasets:[...datasets.values()].map(d=>({...d,families:[...d.families.values()].map(f=>({...f,groups:[...f.groups.values()].map(g=>({...g,rows:g.rows.sort((a,b)=>Number(b.row.author_method)-Number(a.row.author_method)||a.index-b.index)}))}))}))};
}
