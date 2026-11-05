import test from 'node:test';import assert from 'node:assert/strict';
import {metricCatalog,metricFamily} from '../../web/dist/metric-catalog.mjs';
import {activityEvents,activityView} from '../../web/dist/review-activity.mjs';
const rows=[
 {id:'M1',dataset:'CIFAR-10',metric:'test error',reference:'Table 3',protocol:'single model',model:'ResNet-110',value:6.43,unit:'%',author_method:true},
 {id:'M2',dataset:'CIFAR-10',metric:'test error',reference:'Table 3',protocol:'single model',model:'ResNet-110+++',value:6.61,unit:'%',author_method:true},
 {id:'M3',dataset:'CIFAR-10',metric:'test error',reference:'Table 3',protocol:'ensemble',model:'Baseline',value:0,unit:'%',author_method:false},
 {id:'M4',dataset:'CIFAR-10',metric:'FLOPs',reference:'Table 4',protocol:'single model',model:'ResNet-110',value:3,unit:'G',author_method:true},
 {id:'M5',dataset:'ImageNet',metric:'top-1 error',reference:'Table 3',protocol:'single crop',model:'Ours',value:23.6,unit:'%',author_method:true}
];
const flat=c=>c.datasets.flatMap(d=>d.families.flatMap(f=>f.groups.flatMap(g=>g.rows.map(x=>x.row))));
test('catalogue preserves every row, variant and exact value while separating datasets and protocols',()=>{
 const c=metricCatalog(rows);assert.equal(c.count,rows.length);assert.deepEqual(c.datasets.map(d=>d.name),['CIFAR-10','ImageNet']);assert.equal(c.datasets[0].families.length,2);
 assert.equal(c.datasets[0].families[0].groups.length,2);assert.deepEqual(new Set(flat(c)),new Set(rows));assert.equal(flat(c).find(x=>x.id==='M3').value,0);
 assert.equal(flat(c).filter(x=>x.model.includes('110')).length,3);
});
test('author/baseline and search filters produce truthful totals without rewriting evidence',()=>{
 assert.equal(metricCatalog(rows,{audience:'author'}).count,4);assert.equal(metricCatalog(rows,{audience:'baseline'}).count,1);assert.equal(metricCatalog(rows,{query:'+++'}).count,1);assert.equal(metricCatalog(rows,{query:'unknown'}).count,0);
 assert.equal(metricFamily('latency'),'效率与资源');assert.equal(metricFamily('unknown'),'其他指标');
});
test('activity joins actual server facts and execution events without creating model turns',()=>{
 const r={status:'reviewing',activity:[{roles:['literature_reader','planner'],title:'联合审阅',status:'running',time:1}],execution:{status:'running',events:[{role:'experiment_runner',kind:'stage_started',stage:'S1',time:2}]},review:{plan:{stages:[{id:'S1',title:'compile'}]}}};
 const events=activityEvents(r);assert.equal(events.length,2);assert.equal(events[1].detail,'compile');assert.equal(events[1].status,'running');assert.match(activityView(r,String),/联合审阅/);assert.equal(activityEvents({}).length,0);
});

test('a finished runtime stage no longer appears as an active agent',()=>{const r={status:'completed',execution:{status:'completed',events:[{kind:'stage_started',role:'experiment_runner',stage:'S1'},{kind:'stage_finished',role:'experiment_runner',stage:'S1',exit_code:0}]}};assert.equal(activityEvents(r).filter(x=>x.status==='running').length,0);});

import {IntakeWorkspace} from '../../web/dist/intake.mjs';
test('switching accounts hides other local projects while preserving guest and teaching projects',()=>{let user=null;const i=new IntakeWorkspace({account:()=>user,mode:()=> 'demo'});i.sample={id:'teaching',sample:true};i.projects=[{id:'guest'},{id:'alice-paper',online_account:'alice'},{id:'bob-paper',online_account:'bob'}];assert.deepEqual(i.all().map(p=>p.id),['guest','teaching']);user={id:'alice'};assert.deepEqual(i.all().map(p=>p.id),['alice-paper','teaching']);i.activeId='alice-paper';i.identityChanged();assert.equal(i.activeId,null);user={id:'bob'};assert.deepEqual(i.all().map(p=>p.id),['bob-paper','teaching']);assert.equal(i.projects.length,3);});
