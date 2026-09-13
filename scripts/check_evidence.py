"""Check evidence hashes and optionally the append-only contract vs a Git ref."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from counterfactual_ops.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', help='prior Git revision whose evidence must be preserved')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    count = len(Store(root / 'evidence').read())
    if args.base:
        files = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', args.base, '--', 'evidence'], cwd=root).decode().splitlines()
        for name in files:
            old = subprocess.check_output(['git', 'show', f'{args.base}:{name}'], cwd=root)
            current = (root / name).read_bytes()
            if name.endswith('events.jsonl'):
                if not current.startswith(old):
                    raise ValueError(f'ledger history rewritten: {name}')
            elif old != current:
                raise ValueError(f'old artifact modified: {name}')
    print(f'verified {count} events; append-only base: {args.base or "not supplied"}')


if __name__ == '__main__':
    main()
