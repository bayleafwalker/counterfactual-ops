import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from counterfactual_ops import adapter
from counterfactual_ops.engine import assess
from counterfactual_ops.model import Invalid, digest, load, select, validate
from counterfactual_ops.store import Store

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.decision = load(ROOT / 'examples/02-atomic.json')

    def test_coverage_cannot_omit_crash_gap(self):
        self.decision['experiments'] = [e for e in self.decision['experiments'] if e['fault'] != 'after_effect']
        with self.assertRaisesRegex(Invalid, 'coverage'):
            validate(self.decision)

    def test_http_probe_cannot_resolve_effect_claim(self):
        self.decision['experiments'][0]['measurement']['authority'] = 'http-200'
        with self.assertRaisesRegex(Invalid, 'measurement'):
            validate(self.decision)

    def test_incomplete_horizon_rejected(self):
        self.decision['context']['observation_horizon_ticks'] = 0
        with self.assertRaisesRegex(Invalid, 'horizon'):
            validate(self.decision)

    def test_forecast_is_not_a_requirement(self):
        self.decision['claim']['kind'] = '95%-forecast'
        with self.assertRaisesRegex(Invalid, 'probabilistic'):
            validate(self.decision)

    def test_no_decision_value_means_stop(self):
        for experiment in self.decision['experiments']:
            experiment['outcomes'] = dict.fromkeys(experiment['outcomes'], 'keep-manual-recovery')
        self.assertEqual(select(validate(self.decision)), [])

    def test_unknown_conditions_and_boolean_times_rejected(self):
        for name, value in [('retention_ticks', True), ('effect_type', 'external-api'), ('workload', 'concurrent')]:
            with self.subTest(name=name):
                decision = copy.deepcopy(self.decision)
                decision['context'][name] = value
                with self.assertRaises(Invalid):
                    validate(decision)

    def test_expiration_boundary_required(self):
        self.decision['context']['replay_window_ticks'] = 10
        self.decision['context']['observation_horizon_ticks'] = 10
        with self.assertRaisesRegex(Invalid, 'coverage'):
            validate(self.decision)


class AdapterTests(unittest.TestCase):
    def experiment(self, implementation, fault, delay=0):
        decision = load(ROOT / 'examples/02-atomic.json')
        decision['context']['implementation'] = implementation
        spec = dict(decision['experiments'][0], fault=fault, delay_ticks=delay)
        with tempfile.TemporaryDirectory() as directory:
            return adapter.experiment(Path(directory), decision['context'], spec)[0]

    def test_crash_between_writes_is_counterexample_with_control(self):
        result = self.experiment('split', 'after_effect')
        self.assertEqual(result['observation']['effect_count'], 2)
        self.assertEqual(result['control']['effect_count'], 1)
        self.assertEqual(result['explanation_status'], 'experimentally-supported-explanation')
        self.assertEqual(result['observation']['process_exits'], [73, 0])
        self.assertEqual(result['observation']['after_abort_effect_count'], 2)

    def test_atomic_transaction_survives_crash_schedules(self):
        for fault in ('none', 'after_effect', 'after_commit'):
            with self.subTest(fault=fault):
                self.assertEqual(self.experiment('atomic', fault)['outcome'], 'supported')

    def test_lost_ack_does_not_duplicate_split_effect(self):
        self.assertEqual(self.experiment('split', 'after_commit')['outcome'], 'supported')

    def test_retention_boundary_in_both_implementations(self):
        for implementation in ('split', 'atomic'):
            self.assertEqual(self.experiment(implementation, 'none', 9)['outcome'], 'supported')
            result = self.experiment(implementation, 'none', 10)
            self.assertEqual(result['outcome'], 'counterexample')
            self.assertEqual(result['control']['effect_count'], 2)
            self.assertEqual(result['explanation_status'], 'observed-discrepancy')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)

    def test_chain_tampering_detected(self):
        self.store.append('note', {'text': 'original'})
        path = Path(self.temp.name) / 'events.jsonl'
        path.write_text(path.read_text().replace('original', 'modified'))
        with self.assertRaisesRegex(Invalid, 'integrity'):
            self.store.read()

    def test_artifact_tampering_detected(self):
        ref = self.store.put(b'authoritative-state')
        self.store.append('note', {'artifacts': [ref]})
        (Path(self.temp.name) / 'objects' / ref).write_bytes(b'changed')
        with self.assertRaisesRegex(Invalid, 'integrity'):
            self.store.read()

    def test_concurrent_append_preserves_chain(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.store.append('note', {'n': i}), range(20)))
        self.assertEqual(len(self.store.read()), 20)

    def test_pending_plan_survives_interrupted_runner(self):
        decision = load(ROOT / 'examples/02-atomic.json')
        self.store.append('plan', {'decision': decision, 'decision_digest': digest(decision), 'experiment_ids': ['normal']})
        result = assess(decision, self.store)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(len(result['incomplete_observation_windows']), 1)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'counterfactual_ops', self.root / 'counterfactual_ops', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'examples', self.root / 'examples')
        self.command('git', 'init', '-b', 'main')
        self.command('git', 'config', 'user.email', 'tests@example.invalid')
        self.command('git', 'config', 'user.name', 'Tests')
        self.command('git', 'add', '.')
        self.command('git', 'commit', '-m', 'Preregister decisions and adapter')

    def command(self, *args):
        return subprocess.run(args, cwd=self.root, capture_output=True, text=True, check=True)

    def cli(self, *args):
        return json.loads(self.command(sys.executable, '-m', 'counterfactual_ops', *args).stdout)

    def test_find_reuse_and_withdraw_support(self):
        self.cli('run', 'examples/01-split.json', '--all')
        split = self.cli('assess', 'examples/01-split.json')
        self.assertEqual(split['status'], 'counterexample')
        self.assertEqual(len(split['counterexamples_awaiting_change']), 1)
        self.cli('run', 'examples/02-atomic.json', '--all')
        supported = self.cli('assess', 'examples/02-atomic.json')
        self.assertEqual(supported['status'], 'supported-under-tested-conditions')
        before = self.cli('verify')['verified_events']
        related = self.cli('assess', 'examples/03-related.json')
        self.assertEqual(related['status'], 'supported-under-tested-conditions')
        self.assertEqual(self.cli('verify')['verified_events'], before)
        self.assertTrue(self.cli('select', 'examples/03-related.json')['stop'])
        changed = self.cli('assess', 'examples/04-changed.json')
        self.assertEqual(changed['status'], 'needs-reassessment')
        self.assertFalse(changed['counterexamples_awaiting_change'])
        self.assertTrue(changed['changed_conditions'])
        self.assertEqual(self.cli('assess', 'examples/01-split.json')['status'], 'counterexample')

    def test_expiry_cannot_reuse_short_window_support(self):
        self.cli('run', 'examples/02-atomic.json', '--all')
        self.assertEqual(self.cli('assess', 'examples/05-expiry.json')['status'], 'needs-reassessment')
        self.cli('run', 'examples/05-expiry.json', '--all')
        self.assertEqual(self.cli('assess', 'examples/05-expiry.json')['status'], 'counterexample')

    def test_uncommitted_prediction_cannot_be_rewritten(self):
        path = self.root / 'examples/01-split.json'
        path.write_text(path.read_text().replace('enable-replay', 'renamed-replay'))
        result = subprocess.run([sys.executable, '-m', 'counterfactual_ops', 'run', str(path)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('commit examples/01-split.json', result.stderr)
        self.assertFalse((self.root / 'evidence/events.jsonl').exists())

    def test_uncommitted_worker_rejected(self):
        path = self.root / 'counterfactual_ops/worker.py'
        path.write_text(path.read_text() + '\n# modified\n')
        result = subprocess.run([sys.executable, '-m', 'counterfactual_ops', 'run', 'examples/01-split.json'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('commit counterfactual_ops/worker.py', result.stderr)

    def test_next_experiment_is_cheapest_remaining(self):
        self.assertEqual(self.cli('select', 'examples/01-split.json')['experiments'][0]['id'], 'normal')
        self.cli('run', 'examples/01-split.json')
        self.assertEqual(self.cli('select', 'examples/01-split.json')['experiments'][0]['id'], 'crash-gap')
        self.cli('run', 'examples/01-split.json')
        self.assertTrue(self.cli('select', 'examples/01-split.json')['stop'])

    def test_unexpected_and_resolution_do_not_rewrite_evidence(self):
        plan = self.cli('run', 'examples/01-split.json', '--all')['plan']
        unexpected = self.cli('unexpected', plan, '--note', 'Operator observed an unanticipated latency cost')['id']
        before = self.cli('assess', 'examples/01-split.json')
        self.assertEqual(before['unexpected_consequences_awaiting_review'], [unexpected])
        self.cli('resolve', unexpected, '--choice', 'keep-manual-recovery', '--note', 'Retain manual recovery while investigating latency')
        target = before['counterexamples_awaiting_change'][0]
        self.cli('resolve', target, '--choice', 'repair-idempotency', '--note', 'Replace split commits with an atomic transaction')
        after = self.cli('assess', 'examples/01-split.json')
        self.assertEqual(after['counterexamples_awaiting_change'], [])
        self.assertEqual(after['unexpected_consequences_awaiting_review'], [])
        self.assertEqual(after['status'], 'counterexample')

    def test_hypothesis_never_establishes_support(self):
        plan = self.cli('run', 'examples/01-split.json')['plan']
        event = self.cli('hypothesis', plan, '--note', 'Maybe the transaction is atomic')
        self.assertEqual(event['data']['explanation_status'], 'suspected-explanation')
        self.assertEqual(self.cli('assess', 'examples/01-split.json')['status'], 'unresolved')

    def test_outcome_cannot_disagree_with_authoritative_artifact(self):
        self.cli('run', 'examples/01-split.json', '--all')
        path = self.root / 'evidence/events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines()]
        previous = None
        for event in events:
            if event['kind'] == 'result' and event['data']['outcome'] == 'counterexample':
                event['data']['outcome'] = 'supported'
            event['previous'] = previous
            del event['hash']
            event['hash'] = digest(event)
            previous = event['hash']
        path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        result = subprocess.run([sys.executable, '-m', 'counterfactual_ops', 'assess', 'examples/01-split.json'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('authoritative assertion', result.stderr)

    def test_observation_failure_is_inconclusive_not_support(self):
        decision = load(self.root / 'examples/02-atomic.json')
        store = Store(self.root / 'other-evidence')
        provenance = {'adapter_digest': adapter.identity(), 'sqlite_version': __import__('sqlite3').sqlite_version}
        plan = store.append('plan', {'decision': decision, 'decision_digest': digest(decision), 'provenance': provenance, 'experiment_ids': ['normal']})
        store.append('result', {'plan': plan['id'], 'experiment_id': 'normal', 'outcome': 'inconclusive', 'error': 'timeout', 'artifacts': []})
        result = assess(decision, store)
        self.assertEqual(result['status'], 'unresolved')
        self.assertTrue(result['incomplete_observation_windows'])
        self.assertIn('normal', result['missing_experiments'])


if __name__ == '__main__':
    unittest.main()
