const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..');
const source=fs.readFileSync(path.join(root,'marketing/site.js'),'utf8');
function route(url){
 const u=new URL(url,'https://mv.fovea.si'),redirects=[];
 const location={pathname:u.pathname,search:u.search,hash:u.hash,replace:u=>redirects.push(u)};
 vm.runInNewContext(source,{location,URLSearchParams,document:{querySelector:()=>null}});
 return redirects;
}
test('public home preserves legacy workspaces and payment returns without redirecting ordinary visitors',()=>{
 assert.deepEqual(route('/'),[]);assert.deepEqual(route('/#how-it-works'),[]);
 assert.deepEqual(route('/pricing'),[]);assert.deepEqual(route('/#the-look'),[]);
 assert.deepEqual(route('/#motion-studio-section?song=abc'),['/app#motion-studio-section?song=abc']);
 assert.deepEqual(route('/?checkout=receipt#credits-section'),['/app?checkout=receipt#credits-section']);
 assert.deepEqual(route('/?redirect=%2Flyric-editor%2Fabc'),['/app?redirect=%2Flyric-editor%2Fabc']);
 assert.deepEqual(route('/app?checkout=receipt#credits-section'),[]);
});
test('public pages are English, readable without auth and have valid internal links',()=>{
 for(const name of ['index','pricing','terms','privacy','refunds','contact']){
  const html=fs.readFileSync(path.join(root,name+'.html'),'utf8');
  assert.match(html,/<html lang="en">/);assert.doesNotMatch(html,/firebase-config|firebasejs|dashboard\.js/);
  for(const [,href] of html.matchAll(/href="(\/[^"?#]*)[^\"]*"/g)){
   if(!href||href==='/')continue;
   const file=path.join(root,href+(path.extname(href)?'':'.html'));
   assert.ok(fs.existsSync(file),`${name}: missing ${href}`);
  }
 }
 assert.match(fs.readFileSync(path.join(root,'app.html'),'utf8'),/id="auth-overlay"/);
 assert.match(fs.readFileSync(path.join(root,'index.html'),'utf8'),/illustrative layout preview/);
});
test('published packages match the checked-in official catalogue and enter authenticated billing',()=>{
 const line=fs.readFileSync(path.join(root,'../.env.example'),'utf8').split('\n').find(l=>l.startsWith('BILLING_PRODUCTS_JSON='));
 const catalog=JSON.parse(line.split('=').slice(1).join('='));
 const page=fs.readFileSync(path.join(root,'pricing.html'),'utf8');
 for(const product of catalog){
  assert.ok(page.includes('/app?plan='+product.id+'#credits-section'));
  assert.ok(page.includes('$'+(product.price_cents/100).toFixed(2)));
  assert.ok(page.includes(product.credits.toLocaleString('en-US')+' credits'));
 }
 assert.doesNotMatch(page,/href="https:\/\/[^\"]*lemonsqueezy\.com\/checkout/);
});
