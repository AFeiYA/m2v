"""Stage the verified browser frontend without backend render bundles or source trees."""
from pathlib import Path
import shutil
import sys


def prepare(destination: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "frontend"
    for asset in ("local/motion/studio.js", "local/motion/lab.js", "local/motion-lab.css", "_redirects"):
        path = source / asset
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing Pages asset: {asset}")

    def ignore(directory, names):
        exclusions = {"node_modules", ".git", "vercel.json"}
        if Path(directory) == source:
            exclusions |= {"motion", "tests"}
        if Path(directory) == source / "local":
            exclusions.add("remotion")
        return set(names) & exclusions

    shutil.copytree(source, destination, ignore=ignore)
    for page in ("editor.html", "lyric_editor.html", "gallery.html", "storyboard.html", "motion_studio.html"):
        p = destination / page
        if not p.is_file() or p.stat().st_size == 0:
            raise RuntimeError(f"Missing staged page: {page}")
    print("Verified frontend staged for Cloudflare Pages")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
