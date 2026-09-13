#!/usr/bin/env python3
"""Build the immutable source manifest embedded in release images."""

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, default=Path(".cfo-source.json"))
    args = parser.parse_args()
    if len(args.revision) != 40 or any(char not in "0123456789abcdef" for char in args.revision):
        parser.error("revision must be a lowercase 40-character Git object id")
    root = args.root.resolve()
    files = [*sorted((root / "counterfactual_ops").glob("*.py")),
             *sorted((root / "examples").glob("*.json"))]
    payload = {
        "schema": "cfo-source/v1",
        "revision": args.revision,
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    output = args.output if args.output.is_absolute() else root / args.output
    output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
