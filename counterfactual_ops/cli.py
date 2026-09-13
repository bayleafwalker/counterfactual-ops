import argparse
import json
from pathlib import Path
import subprocess
import sys
from .engine import annotate, assess, run
from .model import load, select
from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description='Which uncertainty could change the decision?')
    parser.add_argument('--store', default='evidence', help='repository-local evidence directory')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'select', 'run', 'assess'):
        p = commands.add_parser(command)
        p.add_argument('decision', type=Path)
        if command == 'run':
            group = p.add_mutually_exclusive_group()
            group.add_argument('--experiment')
            group.add_argument('--all', action='store_true', help='explicit full regression run, including already supported cases')
    p = commands.add_parser('obligations')
    p.add_argument('decisions', type=Path, nargs='+')
    commands.add_parser('verify')
    for command in ('unexpected', 'hypothesis', 'resolve'):
        p = commands.add_parser(command)
        p.add_argument('target')
        p.add_argument('--note', required=True)
        if command == 'resolve':
            p.add_argument('--choice', required=True)
    args = parser.parse_args(argv)
    store = Store(args.store)
    try:
        if args.command == 'validate':
            result = {'valid': True, 'decision': load(args.decision)['id']}
        elif args.command == 'select':
            decision = load(args.decision)
            needed = assess(decision, store)['next_experiments']
            candidates = [e for e in select(decision) if e['id'] in needed]
            result = {'experiments': candidates, 'stop': not candidates}
        elif args.command == 'run':
            result = {'plan': run(args.decision, store, args.experiment, args.all)}
        elif args.command == 'assess':
            result = assess(load(args.decision), store)
        elif args.command == 'obligations':
            result = [assess(load(p), store) for p in args.decisions]
        elif args.command == 'verify':
            result = {'verified_events': len(store.read())}
        elif args.command in ('unexpected', 'hypothesis'):
            result = annotate(store, args.command, args.target, args.note)
        else:
            result = annotate(store, 'resolution', args.target, args.note, args.choice)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'cfo: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
