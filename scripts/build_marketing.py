"""Build public, dependency-free pages from the checked-in catalogue (no secrets)."""
import html
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
CANONICAL_ORIGIN = 'https://fovea.si'
# Drop a recorded MP4 at this path to replace the studio sample in every hero.
# One file is enough: frontend/marketing/example-lyric-video.mp4
EXAMPLE_VIDEO = '/marketing/example-lyric-video.mp4'
EXAMPLE_FILE = FRONTEND / 'marketing' / 'example-lyric-video.mp4'
ASSET_VERSION = '20261103_convert'

BRAND_MARK = '<span class="brand-mark" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><circle cx="19" cy="19" r="2" fill="currentColor"/></svg></span>'
BRAND_HTML = '<span class="brand-name">Fovea <span class="brand-suffix">Studio</span></span>'

COPY = {
    'how': 'How it works',
    'pricing': 'Pricing',
    'faq': 'FAQ',
    'support': 'Support',
    'try': 'Try free',
    'signin': 'Sign in',
    'blurb': 'Where your characters and music become a world.',
    'independent': 'Independent creative software. Not affiliated with Suno.',
    'footer': [
        ('/pricing', 'Pricing'),
        ('/karaoke', 'Karaoke videos'),
        ('/contact', 'Contact & support'),
        ('mailto:support@fovea.si', 'Email support'),
        ('/terms', 'Terms of service'),
        ('/privacy', 'Privacy policy'),
        ('/refunds', 'Refund policy'),
    ],
}


def env_int(name):
    template = (ROOT / '.env.example').read_text()
    line = next(line for line in template.splitlines() if line.startswith(name + '='))
    return int(line.split('=', 1)[1].strip())


def rates():
    alignment = env_int('ALIGNMENT_CREDITS')
    export = env_int('MOTION_EXPORT_CREDITS')
    free = env_int('NEW_USER_PERMANENT_CREDITS')
    song = alignment + export
    return {'alignment': alignment, 'export': export, 'free': free, 'song': song}


def about_dollars(amount):
    nearest = round(amount)
    if abs(amount - nearest) < 0.05 and nearest >= 1:
        return f'${nearest}'
    return f'${amount:.2f}'


def song_count(credits, song_credits):
    songs = credits / song_credits
    if abs(songs - round(songs)) < 1e-9:
        return int(round(songs)), False
    return int(songs), True


def song_count_phrase(credits, song_credits):
    number, approximate = song_count(credits, song_credits)
    return f'about {number}' if approximate else str(number)


def catalog():
    template = (ROOT / '.env.example').read_text()
    line = next(line for line in template.splitlines() if line.startswith('BILLING_PRODUCTS_JSON='))
    return json.loads(line.split('=', 1)[1])


def creator_plan():
    return next(product for product in catalog() if product['id'] == 'creator_monthly_v2')


def plain_credit_facts():
    """Plain-language credit facts derived from the checked-in defaults. No invented prices."""
    rate = rates()
    creator = creator_plan()
    songs = creator['credits'] / rate['song']
    per_song = (creator['price_cents'] / 100) / songs
    free_number, free_approx = song_count(rate['free'], rate['song'])
    creator_number, creator_approx = song_count(creator['credits'], rate['song'])
    return {
        **rate,
        'per_song_amount': about_dollars(per_song),
        'per_song': f'about {about_dollars(per_song)} per song',
        'free_song_number': free_number,
        'free_songs': f'about {free_number} songs',
        'creator_price': f"{creator['price_cents'] / 100:.2f}",
        'creator_credits': f"{creator['credits']:,}",
        'creator_song_number': creator_number,
        'creator_songs': f'about {creator_number}' if creator_approx else str(creator_number),
        'free_approx': free_approx,
    }


def shell(title, description, content, *, page='home', path=None):
    copy = COPY
    canonical_path = '/' if page == 'home' else '/' + (path or page)
    canonical = CANONICAL_ORIGIN + canonical_path
    og_image = CANONICAL_ORIGIN + '/og-image.png'
    how_href = '/#how-it-works'
    faq_href = '/#faq'

    def nav(name, url, key, extra=''):
        current = ' aria-current="page"' if page == key else ''
        return f'<a{extra} href="{url}"{current}>{name}</a>'

    footer = ''.join(f'<a href="{url}">{html.escape(label)}</a>' for url, label in copy['footer'])
    safe_title = html.escape(title)
    safe_description = html.escape(description)

    json_ld = ''
    if page == 'home':
        facts = plain_credit_facts()
        creator_price = facts['creator_price']
        json_ld_data = {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "fovea.si",
            "url": "https://fovea.si",
            "applicationCategory": "MultimediaApplication",
            "operatingSystem": "Web",
            "description": "AI-powered lyric video maker and animated typography studio for Suno musicians and music creators.",
            "offers": [
                {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": "USD",
                    "name": "Free Starter",
                    "description": f"{facts['free']} free credits to create your first lyric videos, no credit card required"
                },
                {
                    "@type": "Offer",
                    "price": creator_price,
                    "priceCurrency": "USD",
                    "name": "Creator Monthly",
                    "description": f"{facts['creator_credits']} credits per month (about $1 per song)"
                }
            ]
        }
        json_ld = f'\n<script type="application/ld+json">{json.dumps(json_ld_data, ensure_ascii=False)}</script>'

    cf_token = (os.environ.get('CF_BEACON_TOKEN') or os.environ.get('CLOUDFLARE_WEB_ANALYTICS_TOKEN') or '').strip()
    if cf_token:
        analytics = f'\n<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token": "{html.escape(cf_token)}"}}\'></script>'
    else:
        analytics = '\n<script>(function(){const t=window.CF_BEACON_TOKEN||document.querySelector(\'meta[name="cf-beacon-token"]\')?.getAttribute(\'content\');if(t&&!document.querySelector(\'script[src*="cloudflareinsights.com/beacon.min.js"]\')){const s=document.createElement(\'script\');s.defer=true;s.src=\'https://static.cloudflareinsights.com/beacon.min.js\';s.setAttribute(\'data-cf-beacon\',JSON.stringify({token:t}));document.head.appendChild(s);}})();</script>'

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title} · Fovea Studio</title><meta name="description" content="{safe_description}">
<meta name="theme-color" content="#11130e"><meta property="og:type" content="website"><meta property="og:site_name" content="Fovea Studio"><meta property="og:locale" content="en_US">
<meta property="og:title" content="{safe_title} · Fovea Studio"><meta property="og:description" content="{safe_description}"><meta property="og:url" content="{canonical}">
<meta property="og:image" content="{og_image}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{safe_title} · Fovea Studio"><meta name="twitter:description" content="{safe_description}"><meta name="twitter:image" content="{og_image}">
<link rel="canonical" href="{canonical}">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/marketing/site.css?v={ASSET_VERSION}"><script src="/marketing/site.js?v={ASSET_VERSION}" defer></script>{json_ld}{analytics}</head>
<body><a class="skip" href="#main">Skip to content</a>
<header class="site-header"><a class="brand" href="/" aria-label="Fovea Studio home">{BRAND_MARK}{BRAND_HTML}</a>
<nav aria-label="Main navigation">{nav(copy['how'], how_href, 'how')}{nav(copy['pricing'], '/pricing', 'pricing')}{nav(copy['faq'], faq_href, 'faq')}{nav(copy['support'], '/contact', 'contact', ' class="nav-support"')}<a class="nav-try" href="/app">{copy['try']}</a><a class="sign-in" href="/app">{copy['signin']} <span aria-hidden="true">↗</span></a></nav></header>
<main id="main">{content}</main>
<footer class="site-footer"><div><a class="brand" href="/" aria-label="Fovea Studio home">{BRAND_MARK}{BRAND_HTML}</a><p>{copy['blurb']}</p><p class="fine">{copy['independent']}</p></div>
<nav aria-label="Footer">{footer}</nav><p class="copyright">© 2026 Fovea Studio</p></footer></body></html>'''


def hero_media(mode='apple', ratio='9:16'):
    wide = ' wide-hero' if ratio == '16:9' else ''
    # Empty until the MP4 exists, so the page does not request a missing file.
    # Add frontend/marketing/example-lyric-video.mp4 and rerun this script to fill the slot.
    src = EXAMPLE_VIDEO if EXAMPLE_FILE.is_file() and EXAMPLE_FILE.stat().st_size > 0 else ''
    return f'''<div class="hero-art live-hero{wide}"><div class="art-top"><span>EXAMPLE LYRIC VIDEO</span><span>{ratio}</span></div>
<div class="hero-video-slot" data-example-src="{src}" data-aspect="{ratio}">
<!-- Swap slot: add frontend/marketing/example-lyric-video.mp4, then run python3 scripts/build_marketing.py. Until then the studio lyric component plays here. -->
<video class="hero-example" controls playsinline preload="none" hidden aria-label="Example lyric video"><source type="video/mp4"></video>
<div class="live-preview hero-preview" data-preview-mode="{mode}" role="img" aria-label="Example lyric video rendered by the studio video component"><p class="preview-loading">Loading studio preview…</p></div>
</div>
<div class="art-caption"><span>STUDIO SAMPLE</span><span>SILENT</span></div></div>'''


def faq(items):
    blocks = []
    for question, answer in items:
        blocks.append(f'<details><summary>{question}</summary><p>{answer}</p></details>')
    return ''.join(blocks)


def shared_product_faq():
    facts = plain_credit_facts()
    return [
        ('Do I need to own the music?', 'You need permission to process and use the music, lyrics, and artwork. Uploading a file or pasting a public Suno link does not itself prove copyright ownership. Fovea Studio does not grant music licences and is not affiliated with Suno. You are responsible for what you upload and publish.'),
        ('Which audio formats are supported?', f'Upload MP3, WAV, or FLAC, up to {env_int("MAX_UPLOAD_SIZE_MB")} MB per file. You can also paste a public song link, including a Suno link, to import audio and lyrics. Lyrics can be pasted as text or uploaded as TXT or LRC.'),
        ('Which lyric languages are supported?', 'Set the language to auto-detect, or choose English, Chinese, Japanese, or Korean before alignment. Auto-detect follows the lyric text. Those four are the explicit languages the aligner accepts. After alignment you can still correct any word.'),
        ('How accurate is the alignment?', 'Alignment is word-level, after vocal separation, and it can be wrong. Long instrumental breaks, repeated sections, ad-libs, and lyrics that do not match the vocal are the usual trouble spots. The product does not guarantee a perfect sync, and the samples on this site use synthetic timings rather than a measured accuracy score. Listen through the song and drag a word if it is off, then export.'),
        ('How do credits work?', f'Credits pay for processing. They are not cash. A new account receives {facts["free"]} permanent credits once, with no card. That is {facts["alignment"]} credits to align a song, including vocal separation, and {facts["export"]} credits to unlock browser video exports for that song, so {facts["free"]} credits cover {facts["free_songs"]}. On Creator (${facts["creator_price"]} for {facts["creator_credits"]} credits, {facts["creator_songs"]} songs) a song is {facts["per_song"]}. After a song is unlocked, further browser exports of that song in 16:9 or 9:16, other layouts, and clips are 0 credits. Cloud server rendering, when you choose it, uses compute credits. The credit price of a song stays {facts["song"]} credits on every plan.'),
        ('How do credit reservations and expiry work?', 'Starting an alignment or a paid export reserves the quoted credits before the work runs. Success settles that reservation and does not charge it again. Failure or interruption releases the hold. Editing and previewing do not reserve credits. Monthly subscription credits expire at the end of the billing period and do not roll over. Expiring credits are used before permanent credits. The free credits on a new account are permanent and do not expire. A failed job cannot turn credits that have already expired into permanent credits.'),
    ]


def support_line():
    return '<p class="support-line">Need a hand? <a href="/contact">Contact support</a> or email <a href="mailto:support@fovea.si">support@fovea.si</a>.</p>'


def pricing_cards():
    facts = plain_credit_facts()
    cards = []
    for product in catalog():
        if product['kind'] != 'subscription':
            continue
        featured = product['id'] == 'pro_monthly_v2'
        name = product['name'].split(' (', 1)[0]
        price = f"{product['price_cents'] / 100:.2f}"
        credits = f"{product['credits']:,}"
        songs = song_count_phrase(product['credits'], facts['song'])
        description = f'Complete {songs} songs with unlimited browser exports.'
        button = 'primary' if featured else 'secondary'
        cards.append(
            f'''<article class="price-card {'featured' if featured else ''}"><span class="eyebrow">MONTHLY SUBSCRIPTION</span><h2>{name}</h2><p class="plan-description">{description}</p><p class="price"><span>${price}</span> <small>/ month</small></p><p class="credits">{credits} credits per billing month</p><ul><li>Unused monthly credits expire each billing period</li><li>Renews monthly until cancelled</li><li>Cancel in your billing portal</li><li>Lyric timing ({facts["alignment"]} credits) and video unlock ({facts["export"]} credits)</li><li>Further browser exports of an unlocked song are 0 credits</li></ul><a class="button {button}" href="/app?plan={product["id"]}#credits-section">Choose {name} <span aria-hidden="true">↗</span></a><p class="fine">USD. Taxes may apply. Final total at checkout.</p></article>'''
        )
    return '\n'.join(cards)


def home_page():
    facts = plain_credit_facts()
    return f'''<section class="hero page-width"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> FOVEA STUDIO · LYRIC VIDEOS FOR AI SONGS</p><h1>Lyric videos<br>for Suno<br><em>and AI songs.</em></h1><p class="lead">Paste a Suno link or upload a song you have permission to use. AI automatically aligns each word to the vocal. Adjust any timing, then export a word-synced MP4 in 16:9 or 9:16.</p><div class="actions"><a class="button primary" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a><a class="text-link" href="#the-look">Watch the layouts <span aria-hidden="true">↓</span></a></div><p class="fine">{facts["free"]} free credits, {facts["free_songs"]}. No card required. <a href="/contact">Contact support</a></p><div class="hero-tags"><span>Suno link or audio upload</span><span>Word-level timing edits</span><span>MP4 · 16:9 and 9:16</span></div></div>
{hero_media()}</section>
<section class="workflow page-width" id="how-it-works"><div class="section-title"><p class="eyebrow">LESS FRICTION. MORE CREATING.</p><h2>From your audio track<br>to a screen of your own.</h2></div><div class="steps"><article><span class="step-num">01</span><h3>Let AI align your lyrics</h3><p>Paste a public Suno link, or upload MP3, WAV, or FLAC plus your lyrics. AI aligns the lyrics to the vocal. Use music and lyrics you own or have permission to process.</p></article><article><span class="step-num">02</span><h3>Refine only what needs it</h3><p>Listen to the aligned lyrics. If a word needs adjusting, drag its timing boundaries and save. You stay in control.</p></article><article><span class="step-num">03</span><h3>Find your look. Export.</h3><p>Choose a layout and palette, then export the full song or selected sections as MP4 in 16:9 or 9:16.</p></article></div></section>
<section class="look-section" id="the-look"><div class="page-width"><div class="section-heading"><div><p class="eyebrow">ONE SONG. DIFFERENT STAGES.</p><h2>Let the words lead.</h2></div><p>Three layouts from the actual video renderer.<br>Watch how your lyrics can move.</p></div><div class="layout-tabs" role="group" aria-label="Layout preview"><button type="button" data-demo="apple" aria-pressed="true">01 · Portrait scroll</button><button type="button" data-demo="karaoke" aria-pressed="false">02 · Dual-line karaoke</button><button type="button" data-demo="poster" aria-pressed="false">03 · Kinetic poster</button></div><div class="demo-shell" data-mode="apple"><div class="demo-stage"><div class="live-preview demo-canvas" data-preview-mode="apple" role="img" aria-label="Live lyric video sample"><p class="preview-loading">Loading studio preview…</p></div><p class="demo-label">PORTRAIT SCROLL · 9:16</p></div><div class="demo-notes"><span class="eyebrow">THE SAME ENGINE AS YOUR VIDEO</span><h3 id="demo-title">Scrolling lyrics, word by word.</h3><p id="demo-description">Portrait lyrics move around the active line, with softened edges and a highlight that follows each word’s timing.</p><p class="fine">Live output from the studio’s video component. Original sample text and synthetic word timings; silent demonstration, not an AI alignment accuracy test.</p><button class="text-link" id="demo-replay" type="button">Play sample <span aria-hidden="true">▷</span></button><p id="demo-playback-status" class="fine" role="status" aria-live="polite">Paused sample · no audio</p><a class="text-link" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a></div></div></div></section>
<section class="faq page-width" id="faq"><p class="eyebrow">BEFORE YOU PRESS PLAY</p><h2>Questions, answered plainly.</h2>{support_line()}{faq(shared_product_faq())}</section>
<section class="bottom-cta page-width"><p class="eyebrow">YOU MADE THE MUSIC. NOW MAKE IT SEEN.</p><h2>A new stage<br>for your next song.</h2><div class="actions"><a class="button primary" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a><a class="text-link" href="/pricing">See pricing ↗</a></div><p class="fine">{facts["free"]} free credits, {facts["free_songs"]}. No card required.</p></section>'''


def landing_page(*, eyebrow, title_html, lead, steps, extra_faq=()):
    facts = plain_credit_facts()
    step_html = ''.join(
        f'<article><span class="step-num">0{index}</span><h3>{heading}</h3><p>{body}</p></article>'
        for index, (heading, body) in enumerate(steps, 1)
    )
    return f'''<section class="hero page-width"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> {eyebrow}</p><h1>{title_html}</h1><p class="lead">{lead}</p><div class="actions"><a class="button primary" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a><a class="text-link" href="#how-it-works">How it works <span aria-hidden="true">↓</span></a></div><p class="fine">{facts["free"]} free credits, {facts["free_songs"]}. No card required. <a href="/contact">Contact support</a></p></div>
{hero_media('karaoke' if 'karaoke' in eyebrow.lower() else 'apple', '16:9' if 'karaoke' in eyebrow.lower() else '9:16')}</section>
<section class="workflow page-width" id="how-it-works"><div class="section-title"><p class="eyebrow">THREE STEPS</p><h2>From the song<br>to an MP4.</h2></div><div class="steps">{step_html}</div></section>
<section class="faq page-width" id="faq"><p class="eyebrow">BEFORE YOU PRESS PLAY</p><h2>Questions, answered plainly.</h2>{support_line()}{faq(list(extra_faq) + shared_product_faq())}</section>
<section class="bottom-cta page-width"><h2>Try it on your next song.</h2><div class="actions"><a class="button primary" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a><a class="text-link" href="/pricing">See pricing ↗</a></div></section>'''


def pricing_page():
    facts = plain_credit_facts()
    billing_faq = [
        ('What does one credit buy?', f'A credit is a usage unit, not a second of video and not cash. Aligning one song is {facts["alignment"]} credits, including vocal separation and word-level timing. Unlocking browser video exports for that song is {facts["export"]} credits. Together that is {facts["song"]} credits, {facts["per_song"]} on the Creator plan (${facts["creator_price"]} for {facts["creator_credits"]} credits). Further browser exports of an unlocked song are 0 credits. Cloud server rendering, when you choose it, uses compute credits.'),
        ('How do credit reservations and expiry work?', shared_product_faq()[5][1]),
        ('Can I buy credits without a subscription?', 'Credit purchases are currently available only with a monthly subscription. The starting {0} credits do not require a card.'.format(facts['free'])),
        ('Can I cancel my subscription?', 'Yes. Sign in, open Quota & Credits, and choose Cancel renewal to use the secure billing portal. Cancellation and refunds are different: see our <a href="/refunds">refund policy</a> for payment assistance.'),
        ('What happens if an export fails?', 'The application releases the reservation for a failed job. Monthly credits that have already expired cannot be converted into permanent credits. If a completed file is missing or unusable, <a href="/contact">contact support</a>.'),
        ('Do I need to own the music?', shared_product_faq()[0][1]),
        ('How do I pay?', 'Sign in to the studio and select a package in Quota & Credits. When purchases are enabled, checkout is hosted by the secure payment provider identified before you pay. The final total, applicable taxes and supported payment methods are shown there.'),
        ('Do the previews match exported videos?', 'The public pages use the same video component and layout code as Motion Studio and its exports. They show original sample lyrics with synthetic timings, without audio. Your own song, timing, palette and design settings determine your result.'),
    ]
    return f'''<section class="pricing-hero page-width"><p class="eyebrow">YOUR MUSIC. YOUR PACE.</p><h1>Small release?<br><em>Big plans?</em></h1><p class="lead">A song is {facts["song"]} credits: {facts["alignment"]} to align the lyrics and separate the vocal, {facts["export"]} to unlock browser exports. On Creator that is {facts["per_song"]}. New accounts get {facts["free"]} free credits, {facts["free_songs"]}, and no card is required.</p><div class="actions"><a class="button primary" href="/app">Try free, no card required <span aria-hidden="true">↗</span></a><a class="text-link" href="#faq">Credit rules <span aria-hidden="true">↓</span></a></div></section><section class="price-grid page-width" aria-label="Monthly subscription plans">{pricing_cards()}</section>
<section class="pricing-notes page-width"><h2>About {about_dollars((creator_plan()["price_cents"] / 100) / (creator_plan()["credits"] / facts["song"]))} a song.</h2><div><p>Every song uses two steps: <strong>{facts["alignment"]} credits for lyric timing and vocal separation</strong>, then <strong>{facts["export"]} credits to unlock video exports</strong> for that song. Once unlocked, further <strong>browser exports</strong> of that song (16:9, 9:16, other layouts, and clips) are <strong>0 credits</strong>. Cloud server rendering, when you select it, uses compute credits.</p><p>Creator is {facts["creator_credits"]} credits, {facts["creator_songs"]} songs, <strong>{facts["per_song"]}</strong>. Pro and Studio buy more credits for the same editor. The studio shows the quote again before a paid task.</p><p class="fine">Reservation, settlement, and expiry rules are in the FAQ below. A subscription does not grant rights to third-party music.</p>{support_line()}</div></section>
<section class="faq page-width" id="faq"><p class="eyebrow">BEFORE YOU PRESS PLAY</p><h2>A few useful answers.</h2>{faq(billing_faq)}</section><section class="compact-cta page-width"><h2>Ready to find your flow?</h2><a class="button primary" href="/app">Try free, no card required ↗</a></section>'''


def build():
    facts = plain_credit_facts()
    (FRONTEND / 'index.html').write_text(shell(
        'Lyric videos for Suno and AI songs',
        f'Paste a Suno link or upload audio and lyrics. AI aligns each word, you can edit the timing, and export an MP4 in 16:9 or 9:16. {facts["free"]} free credits, {facts["free_songs"]}, no card required.',
        home_page(),
    ))
    (FRONTEND / 'pricing.html').write_text(shell(
        'Pricing',
        f'Monthly plans for lyric videos. A song is {facts["song"]} credits, {facts["per_song"]} on Creator. {facts["free"]} free credits cover {facts["free_songs"]}, no card required.',
        pricing_page(),
        page='pricing',
    ))
    (FRONTEND / 'karaoke.html').write_text(shell(
        'Karaoke lyric video maker',
        'Make a karaoke video from your audio and lyrics. Dual-line word highlighting, editable timing, and MP4 export in 16:9 or 9:16. Try free, no card required.',
        landing_page(
            eyebrow='KARAOKE LYRIC VIDEO MAKER',
            title_html='Karaoke videos<br>with a highlight<br><em>on every word.</em>',
            lead='Upload audio and lyrics, or paste a public Suno link. The dual-line layout highlights each word as it is sung. You can correct the timing, then export a 16:9 or 9:16 MP4.',
            steps=[
                ('Bring the song and the words', 'Upload MP3, WAV, or FLAC and your lyrics, or paste a public song link. Vocal separation runs with alignment unless you skip it because the file is already vocals.'),
                ('Choose the karaoke layout', 'Dual-line karaoke is the 16:9 layout: two lines near the bottom, with a highlight that follows each word. Portrait scroll and kinetic posters use the same timings.'),
                ('Export when the words sit right', 'Preview is free. The first video unlock for a song spends export credits; later browser exports of that song do not. Cloud rendering is separate when you choose it.'),
            ],
        ),
        page='karaoke',
    ))
    for stale in ('suno-lyric-video.html', 'zh.html'):
        leftover = FRONTEND / stale
        if leftover.exists():
            leftover.unlink()
    policies = {
        'contact': ('Contact & support', '''<p class="lead">Questions about your song, credits or subscription?</p><h2>Email support</h2><p>For account, billing, refund or privacy questions, email <a href="mailto:support@fovea.si">support@fovea.si</a>. Include a brief description and, for payment questions, the approximate transaction date or order identifier. Never send passwords, full card numbers, CVV codes or identity documents.</p><h2>Report a software issue</h2><p>You can also search or report a technical issue on the <a href="https://github.com/AFeiYA/m2v/issues" target="_blank" rel="noopener noreferrer">project issue tracker ↗</a>. GitHub issues are public and may require a GitHub account. Keep account details, payment receipts and private song links out of public tickets; use email for private assistance.</p><h2>Billing self-service</h2><p>Sign in and open <a href="/app#credits-section">Quota & Credits</a> to view payment history, retrieve available receipts or manage a subscription in the hosted billing portal.</p><p>For payment-provider questions, you can also use <a href="https://www.paddle.com/help" target="_blank" rel="noopener noreferrer">Paddle support ↗</a>. A cancellation request stops future renewals; it is not automatically a refund request.</p>'''),
        'terms': ('Terms of service', '''<p>Last updated: October 28, 2026.</p><p>These terms describe use of Fovea Studio, a visual music, character motion and lyric video creation service. Use the service only if you can accept these terms and are legally permitted to do so. Questions can be raised through our <a href="/contact">support channel</a>.</p><h2>Your account and content</h2><p>Keep your account secure. You are responsible for having permission to upload, import, process and publish music, lyrics, artwork and other materials. Public access to content does not establish ownership. The service does not grant music licences or permission to bypass another platform’s restrictions.</p><p>You retain your rights to your content. You permit the processing and storage needed to provide the functions you request. Do not upload unlawful content or use the service to infringe others’ rights, impersonate people or interfere with the service.</p><h2>Credits and subscriptions</h2><p>Applicable prices are shown before checkout and before paid processing. Monthly subscriptions renew until cancelled through the billing portal. Subscription credits expire each billing period and do not roll over. Credits are service usage units and are not transferable cash.</p><p>Subscriptions do not include unlimited rendering, extra storage or guaranteed turnaround. Failed jobs release credit reservations subject to expiry rules. Pricing changes are not permission to retroactively charge completed work. See <a href="/pricing">pricing</a> and the <a href="/refunds">refund policy</a>.</p><h2>Results and availability</h2><p>Automatic alignment can make mistakes. Review timing, text, artwork and your export before publishing. Processing time and browser export support depend on the input and device. We do not guarantee uninterrupted service, perfect alignment or indefinite file storage; keep independent copies of important originals and completed work.</p><h2>Payments and support</h2><p>When enabled, payments are processed through the hosted checkout and applicable purchase terms of the provider shown before you pay. When Paddle is used, Paddle acts as Merchant of Record. Checkout displays the final price and any applicable taxes. Cancellation stops future renewals; contact support separately about a refund.</p><h2>Changes and mandatory rights</h2><p>We may update these terms and identify their effective date here. Changes do not remove rights that applicable law requires us to provide. Nothing here excludes non-waivable consumer rights or liability that cannot legally be excluded.</p>'''),
        'privacy': ('Privacy policy', '''<p>Last updated: October 28, 2026.</p><p>This policy explains the data used to operate Fovea Studio. For questions, see <a href="/contact">Contact & support</a>. Do not send sensitive personal information through public support tickets.</p><h2>What the service processes</h2><ul><li>Account information: login identifiers, email and display name supplied by your sign-in method.</li><li>Creative material: song links, uploaded audio, lyrics, artwork, timing edits, design settings and generated files.</li><li>Service records: job status, credit reservations and ledger entries, purchase identifiers, subscription status and error information needed to operate and troubleshoot the service.</li></ul><h2>Why and where data is used</h2><p>We use this information to authenticate you, process requested media, save projects, deliver files, account for credits and provide support. The current service uses Firebase Authentication for login, a backend database for account and task records, and object storage such as Cloudflare R2 for media. Hosting and processing providers may operate in countries other than yours.</p><p>Features that request an external AI or media service may send the inputs required for that operation to the configured provider. Do not submit confidential material unless you are comfortable with that processing.</p><h2>Payments</h2><p>The payment provider identified at checkout handles payment credentials. When Paddle is used, it acts as Merchant of Record and its privacy policy also applies. Our application stores transaction and subscription identifiers and credit-related records; it does not collect your full card number or CVV. The payment provider’s own privacy policy also applies.</p><h2>Browser storage and analytics</h2><p>The studio uses browser storage for login session information, preferences, media caches and local edits. Shared devices should be signed out after use. Hosting providers may collect technical access and security information; Cloudflare Web Analytics may be enabled by the hosting configuration. The public pages do not require you to sign in to read product or pricing information.</p><h2>Retention and deletion</h2><p>Files and records are retained as needed to provide the service and meet operational, security and applicable recordkeeping requirements. Deleting an item in the app does not necessarily immediately remove associated backups or financial records. Keep your own copies; the service is not a permanent archival service.</p><p>Use the available project and export management controls to manage files. For account information, access, correction or deletion requests, email support@fovea.si using your account email where possible. Do not publish account details in a public ticket.</p>'''),
        'refunds': ('Refund & cancellation policy', '''<p>Last updated: October 28, 2026.</p><h2>Cancel a monthly subscription</h2><p>Sign in, open <a href="/app#credits-section">Quota & Credits</a>, and choose Cancel renewal. Use the hosted billing portal to cancel future renewals and review the effective date. Current monthly credits remain subject to the paid billing period’s expiry.</p><h2>Failed processing is handled in credits</h2><p>A failed task releases its credit reservation under the application’s expiry rules. This is a credit adjustment, not a cash refund. Expired monthly credits cannot become permanent credits through a failed job.</p><h2>Request payment assistance or a refund</h2><p>If you were charged twice, did not receive purchased credits, or cannot use a delivered result because of a service failure, contact us through <a href="/contact">Contact & support</a>. We review the transaction, credit usage and reported problem. Do not make another purchase to fix missing credits.</p><p>Refund eligibility depends on the circumstances, usage, payment-provider rules and applicable law. We do not promise an automatic refund for every purchase, and cancellation alone does not create a refund. Any mandatory withdrawal or consumer rights remain unaffected.</p><h2>What a refund changes</h2><p>Approved refunds are processed through the payment provider. The corresponding purchased credits are reversed; partial refunds can reverse a proportional amount. Credits already consumed may result in a negative balance. Refund processing time depends on the payment method and provider.</p><p>Before confirming payment, review the final price, recurring billing terms and credit expiry on <a href="/pricing">Pricing</a>.</p>'''),
    }
    for page, (title, body) in policies.items():
        content = f'<article class="policy page-width"><p class="eyebrow">FOVEA STUDIO / INFORMATION</p><h1>{title}</h1>{body}</article>'
        (FRONTEND / f'{page}.html').write_text(shell(title, f'{title} for Fovea Studio visual music creation.', content, page=page))


if __name__ == '__main__':
    build()
