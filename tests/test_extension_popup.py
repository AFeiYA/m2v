import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def test_server_draft_is_not_used_and_history_clear_keeps_active_jobs():
    root = Path(__file__).resolve().parent.parent / 'chrome_extension'
    with sync_playwright() as playwright:
        executable = os.environ.get('CHROME_PATH')
        options = {'executable_path': executable} if executable else {'channel': 'chrome'}
        browser = playwright.chromium.launch(headless=True, **options)
        try:
            page = browser.new_page()
            page.on('dialog', lambda dialog: dialog.accept())
            page.set_content((root / 'popup.html').read_text())
            page.evaluate('''() => {
                window.data = { videoJobs: [
                    {taskId: 'a', title: 'A', status: 'running'},
                    {taskId: 'b', title: 'B', status: 'downloaded'},
                ], pendingVideoJob: {taskId: 'b'}, downloads: [] };
                window.sent = []; window.permissions = [];
                window.chrome = {
                    storage: { onChanged: { addListener: () => {} }, local: {
                        get: (keys, cb) => {
                            const result = Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, data[k]]));
                            cb?.(result); return Promise.resolve(result);
                        },
                        set: async values => Object.assign(data, values),
                        remove: async key => { delete data[key]; },
                    }},
                    permissions: {
                        contains: async () => false,
                        request: async request => { permissions.push(request.origins[0]); return true; },
                    },
                    tabs: {
                        query: async () => [{id: 1, url: 'https://suno.com/song/b'}],
                        sendMessage: (id, request, cb) => cb({title: 'B', songId: 'b', is_public: true}),
                    },
                    runtime: {sendMessage: (request, cb) => {
                        sent.push(request); cb({status: 'ok', data: {filename: 'B.mp3'}});
                    }},
                };
            }''')
            page.add_script_tag(path=str(root / 'ui.js'))
            page.add_script_tag(path=str(root / 'popup.js'))
            page.evaluate('document.dispatchEvent(new Event("DOMContentLoaded"))')
            page.wait_for_function('document.querySelectorAll("#jobSelect option").length === 2')
            page.locator('#serverInput').fill('http://insecure.example')
            page.locator('#btnDownloadMp3').click()
            page.wait_for_function('sent.length === 1')
            assert page.evaluate('sent[0].serverUrl') == 'https://mv.fovea.si'
            page.locator('#btnSaveServer').click()
            page.wait_for_function('!document.getElementById("errorDetails").hidden')
            assert page.evaluate('data.serverUrl') is None
            page.locator('#serverInput').fill('https://custom.example')
            page.locator('#btnSaveServer').click()
            page.wait_for_function('data.serverUrl === "https://custom.example"')
            assert page.evaluate('permissions[0]') == 'https://custom.example/*'
            page.locator('#btnClearHistory').click()
            page.wait_for_function('data.videoJobs.length === 1')
            assert page.evaluate('data.videoJobs[0].taskId') == 'a'
            assert page.evaluate('data.pendingVideoJob') is None
        finally:
            browser.close()
