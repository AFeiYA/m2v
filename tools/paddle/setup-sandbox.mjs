/* Additive sandbox setup using Paddle's official SDK. Never prints secrets. */
import {Paddle, Environment, LogLevel} from '@paddle/paddle-node-sdk';
import {chmod, mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

export const catalogue = [
  {
    "id": "creator_monthly_v2",
    "name": "Creator (300 Credits/mo)",
    "kind": "subscription",
    "credits": 300,
    "price_cents": 999,
    "currency": "USD"
  },
  {
    "id": "pro_monthly_v2",
    "name": "Pro (800 Credits/mo)",
    "kind": "subscription",
    "credits": 800,
    "price_cents": 1999,
    "currency": "USD"
  },
  {
    "id": "studio_monthly_v2",
    "name": "Studio (1,500 Credits/mo)",
    "kind": "subscription",
    "credits": 1500,
    "price_cents": 2999,
    "currency": "USD"
  }
];
export const events = ['transaction.completed','transaction.payment_failed','transaction.past_due','transaction.canceled',
  'subscription.created','subscription.activated','subscription.updated','subscription.canceled','subscription.paused',
  'subscription.resumed','subscription.past_due','adjustment.created','adjustment.updated'];

export function matchingPrice(price, product) {
  const cycle = price.billingCycle;
  return price.status === 'active' && price.taxMode === 'external' && price.unitPrice.amount === String(product.price_cents) && price.unitPrice.currencyCode === 'USD' &&
    !price.trialPeriod && !price.unitPriceOverrides?.length && price.quantity?.minimum === 1 && price.quantity?.maximum === 1 &&
    (product.kind === 'topup' ? !cycle : cycle?.interval === 'month' && cycle.frequency === 1);
}

export async function ensureCatalogue(paddle, apply = false, label = 'sandbox') {
  const existing = [];
  for await (const product of paddle.products.list({status:['active'],include:['prices']})) existing.push(product);
  const result = [];
  for (const wanted of catalogue) {
    let matches = existing.filter(p => p.customData?.fovea_catalog === wanted.id || p.name === wanted.name);
    if (matches.length > 1) throw Error('Duplicate matching products require review: ' + wanted.id);
    let product = matches[0];
    if (product && product.taxCategory !== 'saas') throw Error('Existing product tax category requires review: ' + wanted.id);
    if (!product && apply) product = await paddle.products.create({name:wanted.name,taxCategory:'saas',
      description:'Fovea Studio visual music and lyric video creation software credits.',customData:{fovea_catalog:wanted.id}});
    const prices = product?.prices || [];
    matches = prices.filter(p => matchingPrice(p, wanted));
    if (matches.length > 1) throw Error('Duplicate matching prices require review: ' + wanted.id);
    let price = matches[0];
    if (!price && apply) price = await paddle.prices.create({productId:product.id,description:wanted.id + ' USD ' + label,
      name:'Monthly',taxMode:'external',
      unitPrice:{amount:String(wanted.price_cents),currencyCode:'USD'},quantity:{minimum:1,maximum:1},
      ...(wanted.kind === 'subscription' ? {billingCycle:{interval:'month',frequency:1}} : {})});
    if (apply) {
      const verified = await paddle.products.get(product.id,{include:['prices']});
      if (!verified.prices?.some(p => p.id === price.id && matchingPrice(p,wanted))) throw Error('Created price could not be verified');
    }
    result.push({...wanted,variant_id:price?.id || null,product_id:product?.id || null,
      needs_product:!product,needs_price:!price});
  }
  return result;
}

async function main() {
  const key = process.env.PADDLE_SANDBOX_API_KEY || process.env.PADDLE_API_KEY || '';
  if (!key.startsWith('pdl_sdbx_')) throw Error('Set a Paddle sandbox API key in the local environment first. Live keys are rejected.');
  const apply = process.argv.includes('--apply');
  let app;
  if (apply) {
    app = new URL(process.env.PADDLE_SANDBOX_APP_URL || '');
    if (app.protocol !== 'https:' || app.username || app.password || app.pathname !== '/' || app.search || app.hash)
      throw Error('PADDLE_SANDBOX_APP_URL must be the HTTPS origin of your isolated test app or tunnel.');
  }
  const paddle = new Paddle(key,{environment:Environment.sandbox,logLevel:LogLevel.error});
  const rows = await ensureCatalogue(paddle,apply);
  console.log(JSON.stringify({environment:'sandbox',apply,catalogue:rows},null,2));
  if (!apply) return;
  let token;
  for await (const t of paddle.clientTokens.list({status:['active']})) {
    if (t.name === 'Sonicflow sandbox') {token = t; break;}
  }
  token ||= await paddle.clientTokens.create({name:'Sonicflow sandbox'});
  if (!token.token.startsWith('test_')) throw Error('Unexpected client token environment');
  const destination = app.origin + '/api/payments/webhook/paddle';
  const destinations = (await paddle.notificationSettings.list()).filter(d => d.destination === destination);
  if (destinations.length > 1) throw Error('Duplicate notification destinations require manual review');
  let notification = destinations[0];
  if (!notification) notification = await paddle.notificationSettings.create({description:'Sonicflow sandbox',
    destination,type:'url',subscribedEvents:events,trafficSource:'platform',includeSensitiveFields:false});
  else {
    const subscribed = notification.subscribedEvents.map(e => e.name);
    if (!notification.active || notification.trafficSource === 'simulation' || events.some(e => !subscribed.includes(e)))
      notification = await paddle.notificationSettings.update(notification.id,{
        active:true,subscribedEvents:[...new Set([...subscribed,...events])],
        ...(notification.trafficSource === 'simulation' ? {trafficSource:'all'} : {})});
  }
  if (!notification.endpointSecretKey) throw Error('Notification signing secret could not be read');
  // A separate simulation destination may be added later. Do not grant application
  // credits from made-up simulator payloads; fulfillment re-reads real API resources.
  const config = {
    BILLING_ENABLED:'true',BILLING_PROVIDER:'paddle',BILLING_ALLOW_TEST_TRANSACTIONS:'true',
    PADDLE_WEBHOOK_URL:destination,PADDLE_LIVE_ENABLED:'false',PADDLE_ENVIRONMENT:'sandbox',PADDLE_SANDBOX_API_KEY:key,PADDLE_API_KEY:'',
    PADDLE_CLIENT_TOKEN:token.token,PADDLE_WEBHOOK_SECRET:notification.endpointSecretKey,
    BILLING_SITE_URL:app.origin,
    BILLING_PRODUCTS_JSON:JSON.stringify(rows.map(({variant_id,product_id,needs_product,needs_price,...p}) => ({...p,variant_id}))),
  };
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
  await mkdir(path.join(root,'work'),{recursive:true});
  const output = path.join(root,'work','paddle-sandbox.env');
  await writeFile(output,Object.entries(config).map(([k,v]) => `${k}=${v}`).join('\n') + '\n',{mode:0o600});
  await chmod(output,0o600);
  console.log('Private sandbox configuration saved to work/paddle-sandbox.env. No credentials printed.');
  // Settings APIs are not exposed by SDK 3.10. Read first, set only if missing.
  try {
    const endpoint = 'https://sandbox-api.paddle.com/settings/checkout-url';
    const headers = {'Authorization':'Bearer ' + key,'Content-Type':'application/json','Paddle-Version':'1'};
    const current = await fetch(endpoint,{headers,signal:AbortSignal.timeout(15000)});
    if (!current.ok) throw Error('settings permission required');
    const existing = (await current.json()).data?.default_url;
    if (!existing) {
      const updated = await fetch(endpoint,{method:'PATCH',headers,body:JSON.stringify({default_url:app.origin+'/app'}),signal:AbortSignal.timeout(15000)});
      if (!updated.ok) throw Error('checkout settings update failed');
      console.log('Missing sandbox default payment link configured.');
    } else console.log('Existing sandbox default payment link preserved; verify it loads Paddle Checkout.');
  } catch {
    console.log('Set the sandbox default payment link in Checkout > Checkout configuration to ' + app.origin + '/app');
  }
  console.log('Notification destination reused/created: ' + notification.id + '. Tax category: saas. No live account changed.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch(() => {console.error('Sandbox setup stopped. Check the local sandbox key, required permissions, app URL and existing catalog. No raw provider response or credentials are logged.');process.exitCode=1;});
}
