/** Read-only by default. --apply provisions missing LIVE billing configuration,
 * never makes a purchase, changes an existing price or activates website sales. */
import {Paddle,Environment,LogLevel} from '@paddle/paddle-node-sdk';
import {mkdir,writeFile,chmod} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {ensureCatalogue,events} from './setup-sandbox.mjs';

async function main(){
 const key=process.env.PADDLE_API_KEY||'';
 if(!key.startsWith('pdl_live_'))throw Error('A live API key is required; sandbox keys cannot provision production.');
 const apply=process.argv.includes('--apply');
 const paddle=new Paddle(key,{environment:Environment.production,logLevel:LogLevel.error});
 const rest=async(method,resource,body)=>{
  const response=await fetch('https://api.paddle.com/'+resource,{method,
   headers:{Authorization:'Bearer '+key,'Paddle-Version':'1','Content-Type':'application/json'},
   ...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw Error('Paddle setup check failed; verify API permissions and merchant approval.');
  return (await response.json()).data;
 };
 let site,hook;
 if(apply){
  site=new URL(process.env.BILLING_SITE_URL||'');hook=new URL(process.env.PADDLE_WEBHOOK_URL||'');
  if(site.protocol!=='https:'||site.username||site.password||site.pathname!=='/'||site.search||site.hash||
    hook.protocol!=='https:'||hook.username||hook.password||hook.search||hook.hash||hook.pathname!=='/api/payments/webhook/paddle'||
    [site.hostname,hook.hostname].some(h=>h==='localhost'||h.endsWith('trycloudflare.com')))
   throw Error('Set a stable HTTPS BILLING_SITE_URL origin and backend PADDLE_WEBHOOK_URL.');
  const domains=await rest('GET','checkout-domains?domain='+encodeURIComponent(site.hostname)+'&status=approved&per_page=200');
  if(!domains.some(d=>d.domain===site.hostname&&d.status==='approved'))throw Error('Paddle must approve the exact checkout hostname first.');
  const checkout=await rest('GET','settings/checkout-url');
  if(checkout.default_url&&checkout.default_url!==site.origin+'/app')throw Error('Existing default payment link differs. Review it in Paddle before proceeding.');
 }
 const rows=await ensureCatalogue(paddle,apply,'production');
 console.log(JSON.stringify({environment:'production',apply,catalogue:rows},null,2));
 if(!apply)return;
 let token;
 for await(const t of paddle.clientTokens.list({status:['active']}))if(t.name==='Fovea production'||t.name==='Sonicflow production'){token=t;break;}
 token||=await paddle.clientTokens.create({name:'Fovea production'});
 if(!token.token.startsWith('live_'))throw Error('Client token environment does not match.');
 const matches=(await paddle.notificationSettings.list()).filter(n=>n.destination===hook.href);
 if(matches.length>1)throw Error('Duplicate notification destinations need review.');
 let notification=matches[0];
 if(!notification)notification=await paddle.notificationSettings.create({description:'Fovea production',
  destination:hook.href,type:'url',subscribedEvents:events,trafficSource:'platform',includeSensitiveFields:false});
 else{
  const subscribed=notification.subscribedEvents.map(e=>e.name);
  if(!notification.active||notification.trafficSource==='simulation'||events.some(e=>!subscribed.includes(e)))
   notification=await paddle.notificationSettings.update(notification.id,{active:true,
    subscribedEvents:[...new Set([...subscribed,...events])],trafficSource:'platform'});
 }
 if(!notification.endpointSecretKey)throw Error('Signing secret could not be read; configure it privately.');
 const current=await rest('GET','settings/checkout-url');
 if(!current.default_url)await rest('PATCH','settings/checkout-url',{default_url:site.origin+'/app'});
 const config={BILLING_ENABLED:'false',BILLING_PROVIDER:'paddle',PADDLE_LIVE_ENABLED:'false',
  BILLING_ALLOW_TEST_TRANSACTIONS:'false',PADDLE_ENVIRONMENT:'production',PADDLE_API_KEY:key,PADDLE_SANDBOX_API_KEY:'',
  PADDLE_CLIENT_TOKEN:token.token,PADDLE_WEBHOOK_SECRET:notification.endpointSecretKey,
  PADDLE_WEBHOOK_URL:hook.href,BILLING_SITE_URL:site.origin,
  BILLING_PRODUCTS_JSON:JSON.stringify(rows.map(({variant_id,product_id,needs_product,needs_price,...p})=>({...p,variant_id})))};
 const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
 await mkdir(path.join(root,'work'),{recursive:true});
 const output=path.join(root,'work','paddle-live.env');
 await writeFile(output,Object.entries(config).map(([k,v])=>k+'='+v).join('\n')+'\n',{mode:0o600});await chmod(output,0o600);
 console.log('Private config saved to work/paddle-live.env (0600). Website billing remains disabled. Follow docs/PADDLE_GO_LIVE_ZH.md.');
}
main().catch(()=>{console.error('Live setup stopped. Check the live key, API permissions, domain approval, URLs and existing catalog. No credentials or raw provider errors displayed.');process.exitCode=1;});
