import json
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from . import adapter
from .model import digest, load, require, select, validate


def git(*args, cwd):
    return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.PIPE).decode().strip()


def preregister(path):
    path = Path(path).resolve()
    try:
        root = Path(git('rev-parse', '--show-toplevel', cwd=path.parent))
    except (OSError, subprocess.CalledProcessError):
        root = next((parent for parent in (path.parent, *path.parents)
                     if (parent / '.cfo-source.json').is_file()), None)
        require(root is not None, 'decision must belong to a Git checkout or signed release source tree')
        return preregister_release(path, root)
    installed = Path(__file__).resolve().parent
    package = root / 'counterfactual_ops'
    require(package.is_dir(), 'decision repository must contain the adapter source')
    for source in sorted(installed.glob('*.py')):
        require((package / source.name).is_file() and (package / source.name).read_bytes() == source.read_bytes(),
                f'installed adapter differs from repository source: {source.name}')
    files = [path, *sorted(package.glob('*.py'))]
    for file in files:
        relative = str(file.relative_to(root))
        try:
            git('ls-files', '--error-unmatch', '--', relative, cwd=root)
        except subprocess.CalledProcessError:
            require(False, f'commit {relative} before intervention')
        committed = subprocess.check_output(['git', 'show', f'HEAD:{relative}'], cwd=root)
        require(committed == file.read_bytes(), f'commit {relative} before intervention')
    return {'commit': git('rev-parse', 'HEAD', cwd=root), 'decision_path': str(path.relative_to(root)),
            'adapter_digest': adapter.identity(), 'sqlite_version': sqlite3.sqlite_version}


def preregister_release(path, root):
    try:
        manifest = json.loads((root / '.cfo-source.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        require(False, f'invalid release source manifest: {exc}')
    require(isinstance(manifest, dict) and set(manifest) == {'schema', 'revision', 'files'},
            'invalid release source manifest shape')
    require(manifest['schema'] == 'cfo-source/v1' and isinstance(manifest['revision'], str)
            and len(manifest['revision']) == 40 and isinstance(manifest['files'], dict),
            'invalid release source manifest')
    relative = str(path.relative_to(root))
    required = [relative, *[str(item.relative_to(root)) for item in sorted((root / 'counterfactual_ops').glob('*.py'))]]
    installed = Path(__file__).resolve().parent
    for name in required:
        file = root / name
        require(name in manifest['files'] and file.is_file(), f'release source is unregistered: {name}')
        actual = hashlib.sha256(file.read_bytes()).hexdigest()
        require(hmac_compare(actual, manifest['files'][name]), f'release source digest mismatch: {name}')
    for source in sorted(installed.glob('*.py')):
        release_source = root / 'counterfactual_ops' / source.name
        require(release_source.is_file() and release_source.read_bytes() == source.read_bytes(),
                f'installed adapter differs from release source: {source.name}')
    return {'commit': manifest['revision'], 'decision_path': relative,
            'adapter_digest': adapter.identity(), 'sqlite_version': sqlite3.sqlite_version}


def hmac_compare(actual, expected):
    return isinstance(expected, str) and len(expected) == 64 and actual == expected


def run(path, store, experiment_id=None, all_experiments=False):
    decision = load(path)
    provenance = preregister(path)
    candidates = select(decision)
    if experiment_id:
        candidates = [e for e in candidates if e['id'] == experiment_id]
        require(candidates, 'experiment missing or cannot change the decision')
    elif not all_experiments:
        needed = assess(decision, store)['next_experiments']
        candidates = [e for e in candidates if e['id'] in needed][:1]
    require(candidates, 'stop: no unresolved experiment outcome changes the choice')
    started = store.append('plan', {'decision': decision, 'provenance': provenance,
                                   'experiment_ids': [e['id'] for e in candidates], 'decision_digest': digest(decision)})
    for spec in candidates:
        with tempfile.TemporaryDirectory(prefix='cfo-') as temporary:
            try:
                result, files = adapter.experiment(Path(temporary), decision['context'], spec)
                refs = [store.put(p.read_bytes()) for p in files]
            except (RuntimeError, OSError, subprocess.SubprocessError, sqlite3.Error, ValueError) as exc:
                result, refs = {'outcome': 'inconclusive', 'error': str(exc)}, []
            store.append('result', {'plan': started['id'], 'experiment_id': spec['id'], **result, 'artifacts': refs})
    return started['id']


def signature(experiment):
    return digest({k: experiment[k] for k in ('challenge', 'fault', 'delay_ticks', 'measurement')})


def verify_result(result, store):
    """Recheck the recorded assertion against the retained authoritative state."""
    require(result['outcome'] in ('supported', 'counterexample', 'inconclusive'), 'unknown result outcome')
    if result['outcome'] == 'inconclusive':
        return
    require(len(result.get('artifacts', [])) == 2, 'resolved result requires both authoritative databases')
    for observation, ref in zip(('control', 'observation'), result['artifacts']):
        db = sqlite3.connect(':memory:')
        try:
            db.deserialize(store.artifact(ref))
            rows = [list(row) for row in db.execute('SELECT job, amount FROM effects ORDER BY rowid')]
            completed = [list(row) for row in db.execute('SELECT job, expires FROM completed ORDER BY job')]
        finally:
            db.close()
        require(rows == result[observation]['effects'] and len(rows) == result[observation]['effect_count']
                and completed == result[observation]['completed'], 'recorded observation disagrees with authoritative artifact')
    expected = 'supported' if result['observation']['effects'] == [['job-1', 100]] else 'counterexample'
    require(result['outcome'] == expected, 'recorded outcome disagrees with authoritative assertion')


def assess(decision, store):
    events = store.read()
    plans = {e['id']: e['data'] for e in events if e['kind'] == 'plan'}
    for plan in plans.values():
        validate(plan['decision'])
        require(plan.get('decision_digest') == digest(plan['decision']), 'plan definition digest mismatch')
    support, counterexamples, stale, incomplete = set(), [], [], []
    completed = set()
    relevant_plans = set()
    for event in events:
        if event['kind'] != 'result':
            continue
        result = event['data']
        verify_result(result, store)
        require(result['plan'] in plans, 'result references unknown plan')
        plan = plans[result['plan']]
        old = plan['decision']
        specs = {e['id']: e for e in old['experiments']}
        require(result['experiment_id'] in plan['experiment_ids'] and result['experiment_id'] in specs, 'result references unregistered experiment')
        key = (result['plan'], result['experiment_id'])
        require(key not in completed, 'duplicate experiment result')
        completed.add(key)
        if old['claim'] != decision['claim']:
            continue
        relevant_plans.add(result['plan'])
        changed = sorted(k for k in old['context'] if old['context'][k] != decision['context'][k])
        if plan['provenance']['adapter_digest'] != adapter.identity():
            changed.append('adapter_digest')
        if plan['provenance']['sqlite_version'] != sqlite3.sqlite_version:
            changed.append('sqlite_version')
        if changed:
            stale.append({'event': event['id'], 'changed_conditions': changed, 'historical_outcome': result['outcome']})
            continue
        sig = signature(specs[result['experiment_id']])
        if sig not in {signature(e) for e in decision['experiments']}:
            continue
        if result['outcome'] == 'supported':
            support.add(sig)
        elif result['outcome'] == 'counterexample':
            counterexamples.append(event['id'])
        else:
            incomplete.append(event['id'])
    for plan_id, plan in plans.items():
        if plan['decision']['claim'] == decision['claim']:
            relevant_plans.add(plan_id)
            for experiment_id in plan['experiment_ids']:
                if (plan_id, experiment_id) not in completed:
                    incomplete.append(f'{plan_id}:{experiment_id}')
    missing = [e['id'] for e in decision['experiments'] if signature(e) not in support]
    status = 'counterexample' if counterexamples else 'supported-under-tested-conditions' if not missing else 'needs-reassessment' if stale else 'unresolved'
    resolved = {e['data']['target'] for e in events if e['kind'] == 'resolution'}
    unexpected = [e['id'] for e in events if e['kind'] == 'unexpected' and e['data']['plan'] in relevant_plans and e['id'] not in resolved]
    return {'decision': decision['id'], 'claim': decision['claim']['id'], 'status': status,
            'unresolved_material_assumptions': [decision['claim']['id']] if missing or counterexamples else [],
            'missing_experiments': missing, 'incomplete_observation_windows': incomplete,
            'changed_conditions': stale, 'counterexamples_awaiting_change': [e for e in counterexamples if e not in resolved],
            'unexpected_consequences_awaiting_review': unexpected,
            'next_experiments': [] if counterexamples else [e['id'] for e in select(decision) if e['id'] in missing],
            'scope': decision['context']}


def annotate(store, kind, target, note, choice=None):
    require(isinstance(note, str) and note.strip(), 'note required')
    events = {e['id']: e for e in store.read()}
    require(target in events, 'unknown target event')
    event = events[target]
    if kind in ('unexpected', 'hypothesis'):
        require(event['kind'] == 'plan', 'observation or hypothesis must reference a plan')
        status = 'observed-discrepancy' if kind == 'unexpected' else 'suspected-explanation'
        return store.append(kind, {'plan': target, 'note': note, 'explanation_status': status})
    require(event['kind'] == 'unexpected' or (event['kind'] == 'result' and event['data']['outcome'] == 'counterexample'), 'resolution requires counterexample or unexpected consequence')
    plan = events[event['data']['plan']]['data']
    require(choice in plan['decision']['choices'], 'resolution choice must be a registered alternative')
    require(not any(e['kind'] == 'resolution' and e['data']['target'] == target for e in events.values()), 'already resolved')
    return store.append('resolution', {'target': target, 'note': note, 'choice': choice})
