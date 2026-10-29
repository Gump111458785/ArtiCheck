import {ensureAssessment} from './assessment-core.mjs';
export const GiB=1024**3;
export function resourceState(project){const a=ensureAssessment(project);if(!a.resource_check)a.resource_check={target_label:'',target_confirmed:false,requirements:{source:'',scope:'',gpu_count:'',gpu_memory_gib:'',ram_gib:'',disk_gib:'',cpu_cores:''},report:null};return a.resource_check;}
const finite=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
export function validateEnvironment(value){
 if(!value||value.format!=='articheck-environment-v1')throw Error('请选择 ArtiCheck 服务器采集报告（articheck-environment-v1）');
 if(typeof value.collected_at!=='string'||!Number.isFinite(Date.parse(value.collected_at)))throw Error('报告缺少有效采集时间');
 const number=(v,key)=>{if(v===null||v===undefined)return null;if(!finite(v))throw Error(key+' 必须是非负数或 null');return v;};
 if(value.gpus!==null&&!Array.isArray(value.gpus))throw Error('GPU 字段必须是列表或 null（未检测）');
 const gpus=value.gpus===null?null:value.gpus.map(g=>({index:number(g.index,'GPU 序号'),name:String(g.name||'GPU').slice(0,160),total_memory_bytes:number(g.total_memory_bytes,'总显存'),free_memory_bytes:number(g.free_memory_bytes,'空闲显存'),driver:String(g.driver||'').slice(0,64)}));
 if(gpus?.length>64||gpus?.some(g=>!Number.isInteger(g.index))||new Set(gpus?.map(g=>g.index)).size!==gpus?.length&&gpus!==null)throw Error('GPU 记录超过限制或序号重复');
 if(gpus?.some(g=>g.free_memory_bytes!==null&&g.total_memory_bytes!==null&&g.free_memory_bytes>g.total_memory_bytes))throw Error('空闲显存不能超过总显存');
 const memory={total_bytes:number(value.memory?.total_bytes,'总内存'),available_bytes:number(value.memory?.available_bytes,'可用内存')};
 const disk={total_bytes:number(value.disk?.total_bytes,'总磁盘'),free_bytes:number(value.disk?.free_bytes,'空闲磁盘')};
 if(memory.available_bytes!==null&&memory.total_bytes!==null&&memory.available_bytes>memory.total_bytes||disk.free_bytes!==null&&disk.total_bytes!==null&&disk.free_bytes>disk.total_bytes)throw Error('可用资源不能超过总量');
 return {format:value.format,collected_at:value.collected_at,collector:String(value.collector||'uploaded').slice(0,80),system:{os:String(value.system?.os||'未提供').slice(0,80),architecture:String(value.system?.architecture||'').slice(0,80),python:String(value.system?.python||'').slice(0,80)},cpu:{logical_cores:number(value.cpu?.logical_cores,'CPU 核数')},memory,disk,gpus,executor:value.executor?{gpu_enabled:value.executor.gpu_enabled===true,memory_limit_bytes:number(value.executor.memory_limit_bytes,'执行器内存'),cpu_limit:number(value.executor.cpu_limit,'执行器 CPU'),max_seconds:number(value.executor.max_seconds,'执行器时间')}:null};
}
export function compareResources(state,now=Date.now()){
 const r=state.requirements,report=state.report?.data;const fresh=report&&now-Date.parse(report.collected_at)>=-300000&&now-Date.parse(report.collected_at)<=900000;
 const trusted=!!report&&fresh&&state.target_confirmed&&!!state.target_label.trim();
 const entries=[['cpu_cores','CPU 逻辑核数',report?.cpu?.logical_cores,1],['ram_gib','可用内存',report?.memory?.available_bytes,GiB],['disk_gib','所选文件系统空闲磁盘',report?.disk?.free_bytes,GiB]];
 const compare=(key,label,actual,factor)=>{const raw=r[key],need=raw===''?null:Number(raw);let status='unknown',reason='实验要求尚未填写';if(need!==null&&(!finite(need)))reason='要求必须是非负数';else if(!r.source.trim()||!r.scope.trim())reason='需要注明论文出处和实验范围';else if(need!==null&&!trusted)reason=!report?'未提供服务器报告':!fresh?'报告已过期或时间异常，请重新采集':'请确认报告对应的目标服务器';else if(need!==null&&actual!==null&&actual!==undefined){status=actual>=need*factor?'fits':'blocked';reason=status==='fits'?'快照中的资源满足此项下限':'快照中的可用资源不足';}else if(need!==null)reason='报告没有提供可比较的实测值';return {key,label,required:need,actual:actual==null?null:actual/factor,status,reason};};
 const rows=entries.map(x=>compare(...x));if(r.cpu_cores!==''&&!Number.isInteger(Number(r.cpu_cores))){rows[0].status='unknown';rows[0].reason='CPU 核数必须为非负整数';}
 const gpuCount=r.gpu_count===''?null:Number(r.gpu_count),memory=r.gpu_memory_gib===''?null:Number(r.gpu_memory_gib);
 const gpuNeedValid=finite(gpuCount)&&Number.isInteger(gpuCount);
 const gpuKnown=report?.gpus!==null&&Array.isArray(report?.gpus);
 const eligible=gpuKnown&&memory!==null&&finite(memory)?report.gpus.filter(g=>g.free_memory_bytes!==null&&g.free_memory_bytes>=memory*GiB).length:null;
 const gpu=compare('gpu_count','满足单卡空闲显存的 GPU 数',gpuCount===0?0:gpuNeedValid&&memory!==null?eligible:null,1);
 if(gpuCount!==null&&!gpuNeedValid){gpu.status='unknown';gpu.reason='GPU 数量必须为非负整数';}
 if(gpuCount>0&&memory===null){gpu.status='unknown';gpu.reason='需要填写每张 GPU 所需显存，不累加多卡显存';}
 if(gpuCount>0&&gpuKnown&&report.gpus.length<gpuCount&&trusted&&r.source.trim()&&r.scope.trim()){gpu.status='blocked';gpu.reason='已报告的 GPU 数量不足';}
 gpu.memory_gib=memory;rows.unshift(gpu);
 const executor=[];if(report?.executor&&state.report.source==='local'){if(gpuCount>0&&!report.executor.gpu_enabled)executor.push('当前本地 probe 执行器未启用 GPU');if(Number(r.ram_gib)>report.executor.memory_limit_bytes/GiB)executor.push('当前 probe 容器内存上限低于实验要求');if(Number(r.cpu_cores)>report.executor.cpu_limit)executor.push('当前 probe 容器 CPU 上限低于实验要求');}else executor.push('未验证目标服务器与实际执行器的连接和分配限制');
 return {rows,fresh:!!fresh,confirmed:trusted,status:rows.some(r=>r.status==='blocked')?'blocked':rows.every(r=>r.status==='fits')?'snapshot_fits':'unknown',executor};
}
export const materialSpecs={
 scope:{label:'实验清单 / 论文说明',fields:[]},code:{label:'版本与代码清单',fields:['commit','entrypoints','files']},data:{label:'数据清单',fields:['source','version','sha256','splits','preprocessing']},environment:{label:'环境定义 / 构建日志',fields:['os','dependencies','framework','cuda']},settings:{label:'实验配置',fields:['hyperparameters','seeds','initialization','augmentation','selection','stopping']},commands:{label:'执行流程',fields:['prepare','preprocess','train','evaluate','summarize']},resources:{label:'资源说明',fields:[]},acceptance:{label:'验收记录',fields:['reference','metric','protocol','runs','baselines','ablations']}};
export function inspectMaterial(kind,text){const spec=materialSpecs[kind];if(!spec)throw Error('材料类型无效');if(text.length>2*1024*1024)throw Error('材料超过 2 MB');let parsed=null;try{parsed=JSON.parse(text);}catch{}const fields=spec.fields.map(key=>({key,present:!!parsed&&Object.hasOwn(parsed,key)&&parsed[key]!==null&&parsed[key]!==''&&(typeof parsed[key]!=='object'||Object.keys(parsed[key]).length>0)}));return {parse:parsed?'json':'text',fields,excerpt:text.slice(0,8000),truncated:text.length>8000};}
