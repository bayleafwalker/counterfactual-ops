"""Initialize persistent evidence and start the immutable hosted workbench."""

from pathlib import Path
import os
import shutil
import sys

from .web import main as web_main


def seed_evidence(seed: Path, store: Path) -> None:
    """Copy seed content without applying image directory metadata to a PVC."""
    for source in seed.rglob("*"):
        relative = source.relative_to(seed)
        target = store / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def main(argv: list[str] | None = None) -> int:
    root = Path("/app")
    store = Path("/data/evidence")
    seed = root / "evidence"
    store.mkdir(parents=True, exist_ok=True)
    if not (store / "events.jsonl").exists() and seed.is_dir():
        seed_evidence(seed, store)
    external_origin = os.environ.get("CFO_EXTERNAL_ORIGIN")
    if not external_origin:
        raise SystemExit("CFO_EXTERNAL_ORIGIN is required")
    arguments = [
        "--root", str(root), "--store", str(store), "--host", "0.0.0.0", "--port", "8080",
        "--allow-non-loopback", "--immutable-decisions",
        "--external-origin", external_origin,
        "--trusted-proxy-header", os.environ.get("CFO_TRUSTED_PROXY_HEADER", "X-authentik-username"),
    ]
    return web_main(arguments if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
