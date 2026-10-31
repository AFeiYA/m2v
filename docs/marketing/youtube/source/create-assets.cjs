// Rebuild the editable channel graphics from the existing logo and captured renderer frames.
// Requires sharp. Set SHARP_MODULE to its absolute module path if it is not installed locally.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require(process.env.SHARP_MODULE || 'sharp');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'assets');
fs.mkdirSync(output, {recursive: true});
const data = (file, type = 'image/png') => `data:${type};base64,${fs.readFileSync(file).toString('base64')}`;
const logo = data(path.join(__dirname, 'channel-avatar.svg'), 'image/svg+xml');
const apple = data(path.join(root, 'screenshots/02-apple-scroll-demo.png'));
const poster = data(path.join(root, 'screenshots/04-kinetic-poster-demo.png'));
const karaoke = data(path.join(root, 'screenshots/03-dual-line-karaoke-demo.png'));
const svg = (w, h, content) => `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><style>text{font-family:Arial,Helvetica,sans-serif} .label{letter-spacing:3px}</style>${content}</svg>`;
async function save(name, content, options = {}) {
  fs.writeFileSync(path.join(__dirname, `${name}.svg`), content);
  let render = sharp(Buffer.from(content));
  if (options.resize) render = render.resize(...options.resize);
  if (options.jpeg) await render.jpeg({quality: 90, chromaSubsampling: '4:4:4'}).toFile(path.join(output, `${name}.jpg`));
  else await render.png().toFile(path.join(output, `${name}.png`));
}
async function main() {
  await save('channel-avatar-800', svg(800, 800, `<rect width="800" height="800" fill="#11130e"/><image href="${logo}" x="100" y="100" width="600" height="600"/>`));
  const banner = svg(2560, 1440, `
    <defs><radialGradient id="ambient"><stop stop-color="#31421b"/><stop offset="1" stop-color="#0b0e09"/></radialGradient></defs>
    <rect width="2560" height="1440" fill="url(#ambient)"/>
    <image href="${apple}" x="105" y="240" width="380" height="676" opacity=".45"/>
    <image href="${poster}" x="2075" y="510" width="380" height="676" opacity=".55"/>
    <path d="M0 1100 C500 800 490 1270 1100 1070 S1900 880 2560 1100" fill="none" stroke="#b7f34a" stroke-opacity=".18" stroke-width="2"/>
    <path d="M0 310 C400 440 700 220 1150 340 S2050 510 2560 340" fill="none" stroke="#b7f34a" stroke-opacity=".14" stroke-width="2"/>
    <rect x="495" y="500" width="1570" height="440" rx="36" fill="#0d120b" fill-opacity=".94" stroke="#b7f34a" stroke-opacity=".17"/>
    <image href="${logo}" x="565" y="622" width="174" height="174"/>
    <text class="label" x="789" y="615" fill="#b7f34a" font-size="24" font-weight="700">MUSIC. LYRICS. MOTION.</text>
    <text x="784" y="728" fill="#f5f9ee" font-size="100" font-weight="700" letter-spacing="-4">Fovea Studio</text>
    <text x="789" y="797" fill="#c0c9b7" font-size="34">Lyric videos, from first sync to final export.</text>
    <text x="789" y="857" fill="#b7f34a" font-size="27">Tutorials &amp; creative workflows  ·  mv.fovea.si</text>
  `);
  await save('channel-banner-2560x1440', banner);
  const safeGuide = banner.replace('</svg>', '<rect x="508" y="509" width="1544" height="422" fill="none" stroke="#ffffff" stroke-width="3" stroke-dasharray="14 10"/><rect x="508" y="950" width="1544" height="70" fill="#10140d"/><text x="1280" y="996" text-anchor="middle" fill="#ffffff" font-size="27">SAFE AREA REFERENCE — do not upload this guide</text></svg>');
  fs.writeFileSync(path.join(__dirname, 'banner-safe-area-guide.svg'), safeGuide);
  await sharp(Buffer.from(safeGuide)).resize(1280, 720).png().toFile(path.join(output, 'banner-safe-area-guide.png'));
  // Native SVG uses the product's captured frames; no fabricated editor controls.
  const thumb = svg(3840, 2160, `
    <defs><radialGradient id="g"><stop stop-color="#293b15"/><stop offset="1" stop-color="#0c1009"/></radialGradient></defs>
    <rect width="3840" height="2160" fill="url(#g)"/>
    <path d="M0 1850 Q1100 1600 2200 1850 T3840 1810" stroke="#b7f34a" stroke-opacity=".20" fill="none" stroke-width="4"/>
    <image href="${logo}" x="168" y="140" width="160" height="160"/>
    <text x="370" y="246" fill="#f5f9ee" font-size="86" font-weight="700">Fovea Studio</text>
    <text class="label" x="180" y="655" fill="#b7f34a" font-size="48" font-weight="700">START HERE</text>
    <text x="165" y="970" fill="#f5f9ee" font-size="264" font-weight="900" letter-spacing="-12">YOUR SONG.</text>
    <text x="165" y="1260" fill="#b7f34a" font-size="264" font-weight="900" letter-spacing="-12">LYRIC VIDEO.</text>
    <text x="180" y="1455" fill="#c6cebe" font-size="69">AI alignment. Editable timing.</text>
    <text x="180" y="1560" fill="#c6cebe" font-size="69">Your style. Your MP4.</text>
    <rect x="180" y="1790" width="730" height="142" rx="71" fill="#b7f34a"/>
    <text x="545" y="1884" text-anchor="middle" fill="#131b0b" font-size="60" font-weight="700">FULL WALKTHROUGH</text>
    <g transform="translate(2250 315) rotate(-5 390 700)"><rect x="-12" y="-12" width="804" height="1411" rx="25" fill="#44552e"/><image href="${apple}" width="780" height="1387"/><text x="390" y="1510" text-anchor="middle" fill="#c7d2ba" font-size="46">Scrolling lyrics</text></g>
    <g transform="translate(2990 565) rotate(5 330 590)"><rect x="-12" y="-12" width="684" height="1197" rx="25" fill="#556b35"/><image href="${poster}" width="660" height="1173"/><text x="330" y="1290" text-anchor="middle" fill="#c7d2ba" font-size="46">Kinetic typography</text></g>
  `);
  await save('tutorial-01-thumbnail-3840x2160', thumb, {jpeg: true});
  await sharp(Buffer.from(thumb)).resize(1280, 720).jpeg({quality: 90}).toFile(path.join(output, 'tutorial-01-thumbnail-1280x720.jpg'));
  const formats = svg(1920, 1080, `
    <rect width="1920" height="1080" fill="#0c1009"/>
    <image href="${logo}" x="65" y="55" width="66" height="66"/><text x="152" y="101" fill="#f5f9ee" font-size="40" font-weight="700">Fovea Studio</text>
    <text x="65" y="202" fill="#b7f34a" font-size="70" font-weight="700">One song. Three lyric styles.</text>
    <image href="${apple}" x="65" y="278" width="350" height="622"/>
    <image href="${poster}" x="472" y="278" width="350" height="622"/>
    <image href="${karaoke}" x="895" y="359" width="960" height="540"/>
    <text x="65" y="968" fill="#f5f9ee" font-size="33" font-weight="700">Apple Scroll</text>
    <text x="472" y="968" fill="#f5f9ee" font-size="33" font-weight="700">Kinetic Posters</text>
    <text x="895" y="968" fill="#f5f9ee" font-size="33" font-weight="700">Dual-line Karaoke</text>
    <text x="65" y="1033" fill="#89977e" font-size="25">Actual renderer frames · Demo lyrics and timings · mv.fovea.si</text>
  `);
  await save('three-lyric-styles-1920x1080', formats);
  const watermark = fs.readFileSync(path.join(__dirname, 'channel-avatar.svg'), 'utf8')
    .replace(/<rect[^>]*\/>/g, '');
  await sharp(Buffer.from(watermark)).resize(150, 150).png().toFile(path.join(output, 'video-watermark-150.png'));
  const preview = svg(1600, 1360, `
    <rect width="1600" height="1360" fill="#e7ebdf"/>
    <text x="50" y="72" fill="#192211" font-size="37" font-weight="700">Fovea Studio · YouTube channel kit</text>
    <text x="50" y="115" fill="#637052" font-size="22">Avatar / channel banner / first tutorial thumbnail / actual renderer examples</text>
    <image href="${data(path.join(output, 'channel-avatar-800.png'))}" x="50" y="160" width="220" height="220"/>
    <image href="${data(path.join(output, 'channel-banner-2560x1440.png'))}" x="310" y="160" width="1240" height="697.5"/>
    <image href="${data(path.join(output, 'tutorial-01-thumbnail-1280x720.jpg'), 'image/jpeg')}" x="50" y="908" width="720" height="405"/>
    <image href="${data(path.join(output, 'three-lyric-styles-1920x1080.png'))}" x="810" y="908" width="740" height="416"/>
  `);
  await save('kit-preview', preview, {jpeg: true});
  const manifest = [];
  for (const file of fs.readdirSync(output).filter(f => /\.(png|jpg)$/.test(f))) {
    const absolute = path.join(output, file);
    const meta = await sharp(absolute).metadata();
    manifest.push({file, width: meta.width, height: meta.height, bytes: fs.statSync(absolute).size});
  }
  fs.writeFileSync(path.join(root, 'asset-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(JSON.stringify(manifest, null, 2));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
