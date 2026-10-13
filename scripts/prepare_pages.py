"""Stage the verified browser frontend without backend render bundles or source trees."""
from pathlib import Path
import shutil
import sys


def validate_redirects(path: Path) -> None:
    # Pages canonicalizes *.html to clean URLs, including rewrite targets.
    # Rewriting /editor to /editor.html therefore redirects back to /editor.
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 3 and fields[2] == "200":
            target = fields[1].split("?", 1)[0]
            if target.endswith(".html"):
                raise RuntimeError(
                    f"Unsafe Pages HTML rewrite at {path.name}:{line_number}: "
                    f"{fields[0]} -> {target}; use a canonical extension-less URL "
                    "or let Pages serve the HTML file directly"
                )


def prepare(destination: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "frontend"
    for asset in ("local/motion/studio.js", "local/motion/lab.js", "local/motion-lab.css", "_redirects"):
        path = source / asset
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing Pages asset: {asset}")
    validate_redirects(source / "_redirects")

    def ignore(directory, names):
        exclusions = {"node_modules", ".git", "vercel.json"}
        if Path(directory) == source:
            exclusions |= {"motion", "tests"}
        if Path(directory) == source / "local":
            exclusions.add("remotion")
            exclusions.update(name for name in names if name.endswith(".html"))
        return set(names) & exclusions

    shutil.copytree(source, destination, ignore=ignore)
    for page in ("lyric-editor.html", "gallery.html", "storyboard.html",
                 "motion-studio.html", "motion-lab.html", "404.html"):
        p = destination / page
        if not p.is_file() or p.stat().st_size == 0:
            raise RuntimeError(f"Missing staged page: {page}")
    print("Verified frontend staged for Cloudflare Pages")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
