const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../billing.js'),'utf8');
function setup(){
 const nodes=new Map(),calls=[],redirects=[],storage=new Map();let ready;
 const element=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',innerHTML:'',hidden:false,handlers:{},addEventListener(k,v){this.handlers[k]=v}});return nodes.get(id)};
 const catalog={test_mode:true,credit_policy:'Monthly credits expire each billing period. Permanent credits never expire.',subscription_policy:'Monthly automatic renewal until cancelled.',products:[{id:'pack',name:'<Credit pack>',credits:500,kind:'topup',price_cents:500,currency:'USD'},{id:'monthly',name:'Creator',credits:1000,kind:'subscription',price_cents:500,currency:'USD'},{id:'monthly_plus',name:'Creator Plus',credits:2500,kind:'subscription',price_cents:1000,currency:'USD'}]};
 const context={currentUser:{id:'alice'},document:{getElementById:element,addEventListener(k,v){ready=v}},location:{search:'',href:'https://mv.fovea.si/#credits-section'},URL,URLSearchParams,crypto:{randomUUID:()=> 'random-checkout-key-001'},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},setTimeout:()=>1,clearTimeout(){},loadCredits:async()=>{context.creditLoads++},creditLoads:0,
  window:{location:{assign:url=>redirects.push(url)},history:{replaceState(){}}},
  api:async(url,options)=>{calls.push({url,options});let data=url.endsWith('/packages')?catalog:url.endsWith('/status')?{subscriptions:[]}:url.includes('/orders?')?{orders:[],total:0}:url.endsWith('/checkout')?{state:'open',url:'https://demo.lemonsqueezy.com/checkout/test'}:{credits_confirmed:false};return {ok:true,json:async()=>data};}};
 vm.createContext(context);vm.runInContext(source,context);ready();return {context,element,calls,redirects,storage,catalog};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('billing explains recurring terms, escapes names and does not grant credits from prices',async()=>{
 const s=setup();await s.context.window.m2vBilling.refresh();
 assert.match(s.element('billing-notice').textContent,/TEST MODE/);assert.match(s.element('billing-notice').textContent,/automatic renewal/);
 assert.doesNotMatch(s.element('billing-products').innerHTML,/Credit pack|ONE-TIME PACK/);assert.match(s.element('billing-products').innerHTML,/Subscribe monthly/);
 assert.match(s.element('billing-products').innerHTML,/1,000 credits per billing month/);
 assert.match(s.element('billing-products').innerHTML,/2,500 credits per billing month/);

 assert.match(s.element('billing-products').innerHTML,/expire at the end of each billing period/);
 assert.equal(s.context.creditLoads,0);assert.equal(s.element('billing-refresh').hidden,false);
});
test('checkout double click sends one server request and reuses a scoped retry key',async()=>{
 const s=setup();await s.context.window.m2vBilling.refresh();
 const button={dataset:{billingBuy:'monthly'},disabled:false};const click=()=>s.element('billing-panel').handlers.click({target:{closest:()=>button}});
 click();click();await flush();
 assert.equal(s.calls.filter(c=>c.url.endsWith('/checkout')).length,1);
 const request=s.calls.find(c=>c.url.endsWith('/checkout')).options.json;
 assert.deepEqual(JSON.parse(JSON.stringify(request)),{product_id:'monthly',idempotency_key:'random-checkout-key-001'});
 assert.equal(s.storage.get('m2v-billing-checkout:alice:monthly'),'random-checkout-key-001');
 assert.equal(s.redirects.length,1);assert.equal(s.context.creditLoads,0);
});
test('disabled billing has no purchasable cards and preserves the credit interface',async()=>{
 const s=setup();s.context.api=async()=>({ok:false,status:404,json:async()=>({})});
 await s.context.window.m2vBilling.refresh();assert.match(s.element('billing-notice').textContent,/not enabled/);
 assert.equal(s.element('billing-products').textContent,'');assert.equal(s.element('billing-reconcile').hidden,true);
});
test('late billing responses cannot populate a newly signed-in account',async()=>{
 const s=setup();let finish;
 s.context.api=()=>new Promise(resolve=>finish=resolve);
 const pending=s.context.window.m2vBilling.refresh();s.context.currentUser={id:'bob'};s.context.window.m2vBilling.reset();
 finish({ok:true,json:async()=>s.catalog});await pending;
 assert.equal(s.element('billing-products').textContent,'');assert.equal(s.element('billing-subscriptions').textContent,'');
});
test('a checkout return URL alone never confirms payment or increases a balance',async()=>{
 const s=setup();s.context.location.search='?checkout='+'a'.repeat(64);
 await s.context.window.m2vBilling.refresh();await flush();
 assert.match(s.element('billing-return-status').textContent,/Waiting for payment confirmation/);
 assert.equal(s.context.creditLoads,0);
});

test('a public pricing selection is displayed without automatically starting checkout',async()=>{
 const s=setup();s.context.location.search='?plan=monthly';
 await s.context.window.m2vBilling.refresh();
 assert.match(s.element('billing-return-status').textContent,/Selected plan: Creator/);
 assert.equal(s.calls.filter(c=>c.url.endsWith('/checkout')).length,0);
 assert.equal(s.redirects.length,0);
});

test('Paddle opens a sandbox transaction and never grants credits from the browser event',async()=>{
 const s=setup(),opened=[],initialized=[];
 let callback;
 s.context.window.Paddle={Environment:{set:value=>assert.equal(value,'sandbox')},
  Initialize:options=>{initialized.push(options);callback=options.eventCallback},
  Checkout:{open:value=>opened.push(value)}};
 const api=s.context.api;
 s.context.api=async(url,options)=>url.endsWith('/checkout')?{ok:true,json:async()=>({provider:'paddle',state:'open',
  checkout_id:'a'.repeat(64),transaction_id:'txn_'+'1'.repeat(26),environment:'sandbox',client_token:'test_fixture',
  success_url:'https://mv.fovea.si/app?checkout='+'a'.repeat(64)})}:api(url,options);
 await s.context.window.m2vBilling.refresh();
 const button={dataset:{billingBuy:'monthly'},disabled:false};
 s.element('billing-panel').handlers.click({target:{closest:()=>button}});await flush();
 assert.equal(opened.length,1);assert.equal(initialized[0].token,'test_fixture');
 assert.equal(opened[0].transactionId,'txn_'+'1'.repeat(26));
 callback({name:'checkout.completed'});await flush();
 assert.equal(s.context.creditLoads,0);assert.equal(s.redirects.length,0);
 assert.match(s.element('billing-return-status').textContent,/Waiting for payment confirmation/);
});

test('Paddle refuses a live token paired with sandbox environment',async()=>{
 const s=setup(),api=s.context.api;
 s.context.api=async(url,options)=>url.endsWith('/checkout')?{ok:true,json:async()=>({provider:'paddle',state:'open',
  transaction_id:'txn_'+'1'.repeat(26),environment:'sandbox',client_token:'live_fixture'})}:api(url,options);
 await s.context.window.m2vBilling.refresh();
 s.element('billing-panel').handlers.click({target:{closest:()=>({dataset:{billingBuy:'monthly'},disabled:false})}});await flush();
 assert.match(s.element('billing-return-status').textContent,/Invalid Paddle checkout environment/);
 assert.equal(s.context.creditLoads,0);
});

test('Paddle uses production SDK mode only with a matching live token',async()=>{
 const s=setup(),opened=[],modes=[],api=s.context.api;
 s.context.window.Paddle={Environment:{set:x=>modes.push(x)},Initialize(){},Checkout:{open:x=>opened.push(x)}};
 s.context.api=async(url,opt)=>url.endsWith('/checkout')?{ok:true,json:async()=>({provider:'paddle',state:'open',
  checkout_id:'a'.repeat(64),transaction_id:'txn_'+'1'.repeat(26),environment:'production',client_token:'live_fixture',
  success_url:'https://mv.fovea.si/app?checkout='+'a'.repeat(64)})}:api(url,opt);
 await s.context.window.m2vBilling.refresh();
 s.element('billing-panel').handlers.click({target:{closest:()=>({dataset:{billingBuy:'monthly'},disabled:false})}});await flush();
 assert.deepEqual(modes,['production']);assert.equal(opened.length,1);assert.equal(s.context.creditLoads,0);
});

test('Paddle email transaction links are resolved by the authenticated backend before opening',async()=>{
 const s=setup(),api=s.context.api,opened=[],history=[];
 const transaction='txn_'+'3'.repeat(26);s.context.location.search='?_ptxn='+transaction;
 s.context.location.href='https://mv.fovea.si/app?_ptxn='+transaction;
 s.context.window.history.replaceState=(_,__,url)=>history.push(url);
 s.context.window.Paddle={Environment:{set(){}},Initialize(){},Checkout:{open:x=>opened.push(x)}};
 s.context.api=async(url,opt)=>url.endsWith('/paddle/transactions/'+transaction)?{ok:true,json:async()=>({provider:'paddle',state:'open',
  checkout_id:'b'.repeat(64),transaction_id:transaction,environment:'sandbox',client_token:'test_fixture',success_url:'https://mv.fovea.si/app'})}:api(url,opt);
 await s.context.window.m2vBilling.refresh();
 assert.equal(opened.length,1);assert.equal(opened[0].transactionId,transaction);
 assert.equal(history[0],'/app#credits-section');assert.equal(s.context.creditLoads,0);
});

test('An unowned transaction link never loads or opens checkout',async()=>{
 const s=setup(),api=s.context.api;let opened=false;
 s.context.location.search='?_ptxn=txn_'+'3'.repeat(26);
 s.context.window.Paddle={Environment:{set(){}},Initialize(){},Checkout:{open:()=>opened=true}};
 s.context.api=async(url,opt)=>url.includes('/paddle/transactions/')?{ok:false,status:404,json:async()=>({detail:'Checkout not found'})}:api(url,opt);
 await s.context.window.m2vBilling.refresh();
 assert.equal(opened,false);assert.match(s.element('billing-return-status').textContent,/Checkout not found/);
});

test('existing subscriptions disable new purchases while retaining billing management',async()=>{
 const s=setup(),original=s.context.api;
 s.context.api=async(url,options)=>url.endsWith('/status')?{ok:true,json:async()=>({plan_changes_supported:false,subscriptions:[{id:'sub-owned',status:'active',ends_at:null}]})}:original(url,options);
 await s.context.window.m2vBilling.refresh();
 assert.match(s.element('billing-products').innerHTML,/disabled/);
 assert.match(s.element('billing-products').innerHTML,/Manage your existing subscription/);
 assert.match(s.element('billing-subscriptions').innerHTML,/Cancel renewal/);
 assert.match(s.element('billing-subscriptions').innerHTML,/Update payment method/);
});
