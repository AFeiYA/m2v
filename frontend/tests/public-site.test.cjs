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
function assertPublicLinks(name, html){
 assert.doesNotMatch(html,/firebase-config|firebasejs|dashboard\.js/);
 for(const [,href] of html.matchAll(/href="(\/[^"?#]*)[^\"]*"/g)){
  if(!href||href==='/')continue;
  const file=path.join(root,href+(path.extname(href)?'':'.html'));
  assert.ok(fs.existsSync(file),`${name}: missing ${href}`);
 }
}
test('public pages are readable without auth and have valid internal links',()=>{
 for(const name of ['index','pricing','terms','privacy','refunds','contact','karaoke']){
  const html=fs.readFileSync(path.join(root,name+'.html'),'utf8');
  assert.match(html,/<html lang="en">/);
  assert.doesNotMatch(html,/suno-lyric-video|href="\/zh"/);
  assert.match(html,/property="og:title"/);assert.match(html,/property="og:description"/);
  assert.match(html,/property="og:url" content="https:\/\/fovea\.si/);
  assert.match(html,/rel="canonical" href="https:\/\/fovea\.si/);
  assert.match(html,/property="og:image" content="https:\/\/fovea\.si\/og-image\.png"/);
  assert.match(html,/name="twitter:card" content="summary_large_image"/);
  assertPublicLinks(name, html);
 }
 assert.equal(fs.existsSync(path.join(root,'zh.html')), false);
 assert.equal(fs.existsSync(path.join(root,'suno-lyric-video.html')), false);
 const appHtml=fs.readFileSync(path.join(root,'app.html'),'utf8');
 assert.match(appHtml,/id="auth-overlay"/);
 assert.match(appHtml,/rel="canonical" href="https:\/\/fovea\.si\/app"/);
 assert.match(appHtml,/property="og:image" content="https:\/\/fovea\.si\/og-image\.png"/);
 const home=fs.readFileSync(path.join(root,'index.html'),'utf8');
 assert.match(home,/type="application\/ld\+json"/);
 assert.match(home,/"name": "fovea\.si"/);
 assert.match(home,/"url": "https:\/\/fovea\.si"/);
 assert.match(home,/"price": "9\.99"/);
 assert.match(home,/"price": "19\.99"/);
 assert.match(home,/synthetic word timings/);
 assert.match(home,/Suno/);assert.match(home,/Try free, no card required/);
 assert.match(home,/class="nav-try"/);assert.match(home,/hero-video-slot/);assert.match(home,/example-lyric-video\.mp4/);
 assert.match(home,/id="faq"/);assert.match(home,/href="\/contact"/);
});
test('published packages match the checked-in official catalogue and enter authenticated billing',()=>{
 const line=fs.readFileSync(path.join(root,'../.env.example'),'utf8').split('\n').find(l=>l.startsWith('BILLING_PRODUCTS_JSON='));
 const catalog=JSON.parse(line.split('=').slice(1).join('='));
 const page=fs.readFileSync(path.join(root,'pricing.html'),'utf8');
 for(const product of catalog.filter(product=>product.kind==='subscription')){
  assert.ok(page.includes('/app?plan='+product.id+'#credits-section'));
  assert.ok(page.includes('$'+(product.price_cents/100).toFixed(2)));
  assert.ok(page.includes(product.credits.toLocaleString('en-US')+' credits'));
 }
 assert.doesNotMatch(page,/Credit pack|ONE-TIME PURCHASE|topup_200/);
 assert.doesNotMatch(page,/href="https:\/\/[^\"]*lemonsqueezy\.com\/checkout/);
 assert.match(page,/about \$1 per song/);
 assert.match(page,/about 2 songs/);
 assert.match(page,/no card/i);
 assert.match(page,/How do credit reservations and expiry work/);
 const notes=page.split('pricing-notes')[1].split('id="faq"')[0];
 assert.doesNotMatch(notes,/reserves the quoted credits/);
 assert.match(page,/\$9\.99/);assert.match(page,/\$19\.99/);assert.match(page,/\$29\.99/);
});

test('marketing previews share the video renderer rather than CSS lyric animation',()=>{
 const entry=fs.readFileSync(path.join(root,'motion/src/marketing-preview.ts'),'utf8');
 const sample=fs.readFileSync(path.join(root,'motion/src/marketing-demo.ts'),'utf8');
 assert.match(entry,/import \{RemotionPreview\} from '\.\/remotion-preview'/);
 assert.match(sample,/automaticPoster/);
 assert.doesNotMatch(entry,/service-api|firebase|archiveBrowserVideo/);
 const home=fs.readFileSync(path.join(root,'index.html'),'utf8');
 assert.match(home,/AI automatically aligns/);
 assert.ok(home.indexOf('Let AI align your lyrics')<home.indexOf('Refine only what needs it'));
 assert.doesNotMatch(home,/class="demo-lines"|class="poster-copy"/);
});

test('marketing pages on www and mv redirect to fovea.si while app pages stay on mv', () => {
  function routeWithHost(urlStr) {
    const u = new URL(urlStr);
    const redirects = [];
    const location = {
      hostname: u.hostname,
      pathname: u.pathname,
      search: u.search,
      hash: u.hash,
      replace: target => redirects.push(target)
    };
    vm.runInNewContext(source, { location, URLSearchParams, document: { querySelector: () => null } });
    return redirects;
  }
  assert.deepEqual(routeWithHost('https://www.fovea.si/pricing'), ['https://fovea.si/pricing']);
  assert.deepEqual(routeWithHost('https://mv.fovea.si/pricing'), ['https://fovea.si/pricing']);
  assert.deepEqual(routeWithHost('https://mv.fovea.si/'), ['https://fovea.si/']);
  assert.deepEqual(routeWithHost('https://mv.fovea.si/app'), []);
  assert.deepEqual(routeWithHost('https://fovea.si/pricing'), []);
});

test('llms.txt and sitemap.xml define standard SEO assets on fovea.si', () => {
  const llms = fs.readFileSync(path.join(root, 'llms.txt'), 'utf8');
  assert.match(llms, /# Fovea Studio/);
  assert.match(llms, /Suno/);
  assert.match(llms, /60 free permanent credits/);
  assert.match(llms, /\$9\.99\/month/);
  assert.match(llms, /\$19\.99\/month/);
  assert.match(llms, /20 credits for audio-to-lyric/);
  assert.match(llms, /10 credits for motion video/);
  assert.doesNotMatch(llms, /Udio/);
  assert.doesNotMatch(llms, /4K/);
  assert.match(llms, /https:\/\/fovea\.si/);

  const sitemap = fs.readFileSync(path.join(root, 'sitemap.xml'), 'utf8');
  assert.match(sitemap, /<loc>https:\/\/fovea\.si\/<\/loc>/);
  assert.match(sitemap, /<loc>https:\/\/fovea\.si\/pricing<\/loc>/);
  assert.match(sitemap, /<loc>https:\/\/fovea\.si\/karaoke<\/loc>/);
  assert.doesNotMatch(sitemap, /mv\.fovea\.si/);

  const robots = fs.readFileSync(path.join(root, 'robots.txt'), 'utf8');
  assert.match(robots, /Sitemap: https:\/\/fovea\.si\/sitemap\.xml/);
  assert.doesNotMatch(robots, /mv\.fovea\.si/);
});
