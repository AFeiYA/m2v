import test from 'node:test';
import assert from 'node:assert/strict';
import {catalogue, ensureCatalogue} from './setup-sandbox.mjs';

function mock() {
  const rows = [], writes = [];
  const paddle = {
    products:{
      list:async function*(){yield* rows;},
      create:async data => {writes.push('product');const p={...data,id:'pro_' + rows.length,status:'active',prices:[]};rows.push(p);return p;},
      get:async id => rows.find(p=>p.id===id),
    },
    prices:{create:async data => {writes.push('price');const p={...data,id:'pri_' + writes.length,status:'active',trialPeriod:null,unitPriceOverrides:[]};rows.find(p=>p.id===data.productId).prices.push(p);return p;}},
  };
  return {paddle,rows,writes};
}
test('plan is read-only and names the three agreed packages',async()=>{
  const s=mock();const plan=await ensureCatalogue(s.paddle);
  assert.equal(plan.length,3);assert.equal(s.writes.length,0);
  assert.deepEqual(plan.map(p=>p.price_cents),[499,999,2499]);
});
test('repeat setup reuses matching products and prices without recreating them',async()=>{
  const s=mock();const first=await ensureCatalogue(s.paddle,true);
  assert.equal(s.writes.length,6);
  const again=await ensureCatalogue(s.paddle,true);
  assert.equal(s.writes.length,6);
  assert.deepEqual(first.map(p=>p.variant_id),again.map(p=>p.variant_id));
  assert.ok(s.rows.every(p=>p.taxCategory==='saas'));
});
test('ambiguous product match stops before any writes',async()=>{
  const s=mock();s.rows.push({name:catalogue[0].name},{name:catalogue[0].name});
  await assert.rejects(()=>ensureCatalogue(s.paddle,true),/Duplicate/);
  assert.equal(s.writes.length,0);
});
