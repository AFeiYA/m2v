"""Exercise the content/UI message boundary in an isolated browser, without Suno or accounts."""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_floating_controls_submit_current_song_and_remember_visibility():
    root = Path(__file__).resolve().parent.parent / 'chrome_extension'
    with sync_playwright() as playwright:
        executable = os.environ.get('CHROME_PATH')
        options = {'executable_path': executable} if executable else {'channel': 'chrome'}
        browser = playwright.chromium.launch(headless=True, **options)
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 720})
            page.on('dialog', lambda dialog: dialog.accept())
            page.set_content('<body></body>')
            page.evaluate('''() => {
                window.saved = {}; window.changes = []; window.requests = [];
                window.chrome = {
                    storage: { onChanged: { addListener: fn => changes.push(fn) }, local: {
                        get: (keys, cb) => {
                            const data = Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, saved[k]]));
                            cb?.(data); return Promise.resolve(data);
                        },
                        set: data => {
                            Object.assign(saved, data);
                            changes.forEach(fn => fn(Object.fromEntries(Object.entries(data).map(([k,v]) => [k, {newValue: v}])), 'local'));
                            return Promise.resolve();
                        },
                    }},
                    permissions: { contains: async () => true },
                    runtime: { id: 'test-extension', onMessage: { addListener: () => {} }, sendMessage: (request, callback) => {
                        requests.push(request); callback({status: 'ok'});
                    }},
                };
                window.addEventListener('message', event => {
                    if (event.data.type === 'FOVEA_CAPTURE_REQUEST') {
                        window.postMessage({type: 'FOVEA_CAPTURE_BY_SONG_ID', track: {songId: 'song-b', title: 'B'}, section: event.data.section, duration: event.data.duration}, '*');
                    }
                });
            }''')
            page.add_style_tag(path=str(root / 'content.css'))
            page.add_script_tag(path=str(root / 'ui.js'))
            page.add_script_tag(path=str(root / 'content.js'))
            page.locator('.fovea-collapse').click()
            assert page.locator('.fovea-btn-main').is_hidden()
            assert page.evaluate('saved.barCollapsed') is True
            page.locator('.fovea-collapse').click()
            page.locator('.fovea-btn-main').click()
            page.wait_for_function('requests.length === 1')
            assert page.evaluate('requests[0].action') == 'EXPORT_VIDEO_BY_SONG_ID'
            assert page.evaluate('requests[0].track.songId') == 'song-b'
            page.evaluate('chrome.storage.local.set({barHidden: true})')
            assert page.locator('#fovea-suno-floating-btn').is_hidden()
            page.evaluate('chrome.storage.local.set({barHidden: false})')
            assert page.locator('#fovea-suno-floating-btn').is_visible()
            box = page.locator('#fovea-suno-floating-btn').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 375
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.evaluate('''() => {
                Object.defineProperty(chrome.runtime, 'id', { get() { throw new Error('Extension context invalidated.'); } });
                window.postMessage({type: 'FOVEA_CAPTURE_BY_SONG_ID', track: {songId: 'stale'}}, '*');
            }''')
            page.wait_for_function('!document.getElementById("fovea-suno-floating-btn")')
            assert 'Refresh this Suno page' in page.locator('#fovea-toast-overlay').inner_text()
            page.evaluate('document.body.appendChild(document.createElement("div"))')
            page.wait_for_timeout(1700)
            assert page.evaluate('requests.length') == 1
            assert errors == []
        finally:
            browser.close()
