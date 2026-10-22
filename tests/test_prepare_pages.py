from pathlib import Path

import pytest

from scripts import prepare_pages


@pytest.fixture
def frontend(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "frontend"
    source.mkdir(parents=True)
    monkeypatch.setattr(prepare_pages, "__file__", str(root / "scripts/prepare_pages.py"))
    for name in ("local/motion/studio.js", "local/motion/marketing-preview.js", "local/motion/lab.js", "local/motion/rhythm-studio.js", "local/motion-lab.css", "marketing/site.css", "marketing/site.js"):
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("asset")
    (source / "_redirects").write_text(
        (Path(__file__).resolve().parents[1] / "frontend/_redirects").read_text()
    )
    (source / "index.html").write_text("public home")
    for name in ("app", "pricing", "contact", "terms", "privacy", "refunds"):
        (source / f"{name}.html").write_text(f"page:{name}")
    (source / "404.html").write_text("not found")
    for name in ("lyric-editor", "gallery", "storyboard", "motion-studio", "motion-lab", "rhythm-studio"):
        (source / "local" / f"{name}.html").write_text(f"page:{name}")
        (source / f"{name}.html").symlink_to(f"local/{name}.html")
    return source


def test_pages_staging_materializes_canonical_pages(frontend, tmp_path):
    destination = tmp_path / "pages"
    prepare_pages.prepare(destination)
    for name in ("lyric-editor", "gallery", "storyboard", "motion-studio", "motion-lab", "rhythm-studio"):
        page = destination / f"{name}.html"
        assert not page.is_symlink()
        assert page.read_text() == f"page:{name}"
    assert (destination / "local/motion/studio.js").read_text() == "asset"
    assert not list((destination / "local").glob("*.html"))
    assert (destination / "404.html").read_text() == "not found"
    assert (destination / "index.html").read_text() == "public home"
    assert (destination / "app.html").read_text() == "page:app"
    assert (destination / "pricing.html").read_text() == "page:pricing"


@pytest.mark.parametrize("route", [
    "/editor /editor.html 200",
    "/editor.html /editor.html 200",
    "/motion_studio /local/motion_studio_director.html 200",
    "/* /index.html 200",
])
def test_pages_staging_rejects_canonical_redirect_loop(frontend, tmp_path, route):
    (frontend / "_redirects").write_text(route)
    destination = tmp_path / "pages"
    with pytest.raises(RuntimeError, match="Unsafe Pages HTML rewrite"):
        prepare_pages.prepare(destination)
    assert not destination.exists()


def test_pages_staging_requires_motion_lab_page(frontend, tmp_path):
    (frontend / "motion-lab.html").unlink()
    with pytest.raises(RuntimeError, match="Missing staged page: motion-lab.html"):
        prepare_pages.prepare(tmp_path / "pages")


def test_canonical_editors_include_shared_picker_and_motion_boot_controls():
    """The deployed director entry differs from the historical laboratory page."""
    from html.parser import HTMLParser

    class Page(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.ids, self.scripts = set(), []
            self.feed(html)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get('id'):
                self.ids.add(attrs['id'])
            if tag == 'script' and attrs.get('src'):
                self.scripts.append(attrs['src'].split('?')[0])

    root = Path(__file__).resolve().parents[1] / 'frontend'
    for name in ('lyric-editor.html', 'motion-studio.html'):
        page = Page((root / name).read_text())
        assert '/static/song-picker.js' in page.scripts
        if name == 'motion-studio.html':
            assert {'project-select', 'highlight-mode', 'save-design', 'my-exports'} <= page.ids
            assert '/motion/studio.js' in page.scripts
