import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def test_export_dropdown_menu_is_not_blocked_by_waveform():
    root = Path(__file__).resolve().parent.parent
    html = (root / 'frontend/local/index.html').read_text()
    
    with sync_playwright() as p:
        executable = os.environ.get('CHROME_PATH')
        options = {'executable_path': executable} if executable else {'channel': 'chrome'}
        browser = p.chromium.launch(headless=True, **options)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 800})
            page.set_content(html)
            page.add_style_tag(path=str(root / 'frontend/local/style.css'))
            
            page.evaluate('''() => {
                const btn = document.getElementById('btn-export-lyrics');
                const menu = document.getElementById('menu-export-lyrics');
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isOpen = menu.style.display === 'block';
                    menu.style.display = isOpen ? 'none' : 'block';
                });
                menu.querySelectorAll('[data-export-action]').forEach(item => {
                    item.addEventListener('click', (e) => {
                        e.stopPropagation();
                        menu.style.display = 'none';
                    });
                });
            }''')
            
            btn = page.locator('#btn-export-lyrics')
            menu = page.locator('#menu-export-lyrics')
            waveform = page.locator('#waveform-section')
            
            assert btn.is_visible()
            assert not menu.is_visible()
            
            btn.click()
            assert menu.is_visible()
            
            btn_box = btn.bounding_box()
            menu_box = menu.bounding_box()
            wf_box = waveform.bounding_box()
            
            # The dropdown menu must overflow past header bottom into waveform area
            assert menu_box['y'] >= btn_box['y'] + btn_box['height']
            assert menu_box['y'] + menu_box['height'] > wf_box['y']
            
            # The menu items must be fully visible and clickable without being blocked
            item = menu.locator('button[data-export-action="ttml-auto"]')
            assert item.is_visible()
            item.click()
            assert not menu.is_visible()
        finally:
            browser.close()
