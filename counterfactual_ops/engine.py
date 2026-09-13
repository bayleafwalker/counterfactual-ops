import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from . import adapter
from .model import digest, load, require, select


def git(*args, cwd):
    return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.PIPE).decode().strip()


def preregister(path):
    path = Path(path).resolve()
    root = Path(git('rev-parse', '--show-toplevel', cwd=path.parent))
    installed = Path(__file__).resolve().parent
    package = root / 'counterfactual_ops'
    require(package.is_dir(), 'decision repository must contain the adapter source')
    for source in sorted(installed.glob('*.py')):
        require((package / source.name).is_file() and (package / source.name).read_bytes() == source.read_bytes(),
                f'installed adapter differs from repository source: {source.name}')
    files = [path, *sorted(package.glob('*.py'))]
    for file in files:
        relative = str(file.relative_to(root))
        git('ls-files', '--error-unmatch', '--', relative, cwd=root)
        committed = subprocess.check_output(['git', 'show', f'HEAD:{relative}'], cwd=root)
        require(committed == file.read_bytes(), f'commit {relative} before intervention')
    return {'commit': git('rev-parse', 'HEAD', cwd=root), 'decision_path': str(path.relative_to(root)),
            'adapter_digest': adapter.identity(), 'sqlite_version': sqlite3.sqlite_version}


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


def assess(decision, store):
    events = store.read()
    plans = {e['id']: e['data'] for e in events if e['kind'] == 'plan'}
    support, counterexamples, stale, incomplete = set(), [], [], []
    completed = set()
    relevant_plans = set()
    for event in events:
        if event['kind'] != 'result':
            continue
        result = event['data']
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
