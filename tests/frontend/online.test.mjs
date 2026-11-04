import test from 'node:test';
import assert from 'node:assert/strict';
import {validateInput,inputKey,coverageCounts,sessionCapability} from '../../web/dist/online-core.mjs';
import {IntakeWorkspace} from '../../web/dist/intake.mjs';

test('partial materials are usable without manually confirmed claims or local execution bindings',()=>{
 for(const key of ['paper','repository']){
  const p={[key]:{blob:new Blob(['material']),sha256:'one'}};
  assert.deepEqual(validateInput(p,{token:'website-code',consent:true}),{});
 }
 assert.ok(validateInput({}, {token:'x',consent:true}).material);
});
test('automatic scope is optional; restricting a scope requires a value; invalid time is actionable',()=>{
 const p={paper:{blob:new Blob(['pdf'])}};
 assert.equal(validateInput(p,{token:'x',consent:true}).scope,undefined);
 assert.ok(validateInput({...p,online_restrict:true},{token:'x',consent:true}).scope);
 assert.ok(validateInput({...p,online_max_seconds:601},{token:'x',consent:true}).seconds);
 assert.equal(validateInput({...p,online_max_seconds:''},{token:'x',consent:true}).seconds,undefined);
});
test('editing code, task or scope invalidates the association with an old report',()=>{
 const p={paper:{sha256:'a'},repository:{sha256:'b'}};
 for(const mutation of [{repository:{sha256:'c'}},{online_task:'self_review'},{online_scope:'Table 2'}])assert.notEqual(inputKey(p),inputKey({...p,...mutation}));
});
test('coverage counts are calculated from identified metrics and actual observations',()=>{
 const r={review:{metrics:[{id:'M1'},{id:'M2'}],coverage:{gaps:['unreadable figure']}},execution:{metrics:[{id:'M1',observed:0},{id:'M2',observed:null}]}};
 assert.deepEqual(coverageCounts(r),{identified:2,observed:1,missing:1,gaps:1});
});
test('owner identity persists independently of the provider key and access code',()=>{
 const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const a=sessionCapability(storage);assert.match(a,/^[a-f0-9]{64}$/);assert.equal(sessionCapability(storage),a);assert.equal(values.size,1);
});
test('a manual claim starts without a fabricated page and can be collapsed, deleted and restored',async()=>{
 const i=new IntakeWorkspace({mode:()=> 'demo',page:()=> 'project',render(){},toast(){}});
 const p={id:'editing-project',claims:[],resources:{}};i.projects=[p];i.activeId=p.id;
 i.page=9;
 await i.action('add-claim',{});
 const id=p.claims[0].id;
 assert.equal(p.claims[0].page,null);
 await i.action('collapse-claim',{});assert.equal(i.activeClaimId,null);
 await i.action('delete-claim',{dataset:{id}});assert.equal(p.claims.length,0);
 await i.action('undo-claim',{});assert.equal(p.claims.length,1);assert.equal(p.claims[0].id,id);
});
