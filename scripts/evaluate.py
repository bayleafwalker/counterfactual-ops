"""Mechanical acceptance demonstration; no fabricated human comparison metrics."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from counterfactual_ops.engine import assess, run
from counterfactual_ops.model import load
from counterfactual_ops.store import Store


def evaluate(directory):
    root = Path(__file__).resolve().parents[1]
    started = time.monotonic()
    store = Store(directory)
    if store.read():
        raise ValueError('evaluation requires a fresh store')
    decisions = [root / 'examples' / name for name in ('01-split.json', '02-atomic.json', '03-related.json', '04-changed.json', '05-expiry.json')]
    results = []
    for index, path in enumerate(decisions):
        before = len(store.read())
        if index in (0, 1, 4):
            run(path, store, all_experiments=True)
        result = assess(load(path), store)
        results.append({'decision': result['decision'], 'status': result['status'], 'events_added': len(store.read()) - before,
                        'counterexamples': len(result['counterexamples_awaiting_change']), 'stale_results': len(result['changed_conditions'])})
    expected = ['counterexample', 'supported-under-tested-conditions', 'supported-under-tested-conditions', 'needs-reassessment', 'counterexample']
    errors = sum(result['status'] != wanted for result, wanted in zip(results, expected))
    report = {'exercise': 'mechanical-acceptance-v1', 'results': results, 'decision_errors': errors,
              'missed_defects': sum(results[i]['status'] != 'counterexample' for i in (0, 4)),
              'unnecessary_healthy_blocks': sum(results[i]['status'] != 'supported-under-tested-conditions' for i in (1, 2)),
              'reuse_experiments': sum(e['kind'] == 'result' and e['data']['plan'] in {p['id'] for p in store.read() if p['kind'] == 'plan' and p['data']['decision']['id'] == results[2]['decision']} for e in store.read()),
              'experiment_pairs': sum(e['kind'] == 'result' for e in store.read()),
              'elapsed_machine_seconds': round(time.monotonic() - started, 4),
              'evidence_bytes': sum(p.stat().st_size for p in Path(directory).rglob('*') if p.is_file()),
              'definition_bytes': sum(p.stat().st_size for p in decisions),
              'human_investigation_effort': None, 'human_maintenance_cost': None,
              'comparative_advantage': 'unmeasured; see docs/evaluation.md and docs/baseline-runbook.md'}
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', type=Path)
    args = parser.parse_args()
    if args.store:
        raise SystemExit(evaluate(args.store))
    with tempfile.TemporaryDirectory(prefix='cfo-evaluation-') as directory:
        raise SystemExit(evaluate(directory))
