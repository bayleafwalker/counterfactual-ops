"""Repeatable interventions with an independent durable-state observation."""
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
from . import worker


def identity():
    # Changes to the runner, observer, or worker invalidate previous support.
    return hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes() for n in ('adapter.py', 'worker.py', 'model.py'))).hexdigest()


def observe(path):
    with sqlite3.connect(path) as db:
        require_integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        if require_integrity != 'ok':
            raise ValueError('SQLite integrity check failed')
        rows = db.execute('SELECT job, amount FROM effects ORDER BY rowid').fetchall()
        completed = db.execute('SELECT job, expires FROM completed ORDER BY job').fetchall()
    return {'effects': [list(r) for r in rows], 'completed': [list(r) for r in completed], 'effect_count': len(rows)}


def schedule(directory, context, fault, delay):
    path = directory / 'state.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE effects(job TEXT NOT NULL, amount INTEGER NOT NULL); CREATE TABLE completed(job TEXT PRIMARY KEY, expires INTEGER NOT NULL);')
    exits = []
    for position, now in ((fault, 0), ('none', delay)):
        result = subprocess.run([sys.executable, worker.__file__, str(path), context['implementation'], position, str(now), str(context['retention_ticks'])], capture_output=True, timeout=10)
        expected = 73 if position != 'none' else 0
        if result.returncode != expected:
            raise RuntimeError(f'worker exited {result.returncode}, expected {expected}: {result.stderr.decode(errors="replace")}')
        exits.append(result.returncode)
    observation = observe(path)
    # Abort/config restore stops calls but does not delete committed effects.
    observation['after_abort_effect_count'] = observe(path)['effect_count']
    observation['process_exits'] = exits
    observation['observed_at_logical_tick'] = context['observation_horizon_ticks']
    observation['population'] = {'logical_jobs': 1, 'attempts': 2}
    observation['detection_limit'] = 'all durable effects after both synchronous processes exit; no background actors'
    return observation, path


def experiment(directory, context, spec):
    control_dir, fault_dir = directory / 'control', directory / 'intervention'
    control_dir.mkdir(parents=True)
    fault_dir.mkdir()
    control, control_path = schedule(control_dir, context, 'none', spec['delay_ticks'])
    observed, path = schedule(fault_dir, context, spec['fault'], spec['delay_ticks'])
    outcome = 'supported' if observed['effects'] == [['job-1', 100]] else 'counterexample'
    explanation = 'observed-discrepancy' if outcome == 'counterexample' else 'bounded-support'
    if outcome == 'counterexample' and control['effects'] == [['job-1', 100]] and spec['fault'] != 'none':
        explanation = 'experimentally-supported-explanation'
    return {'outcome': outcome, 'explanation_status': explanation, 'control': control, 'observation': observed,
            'causal_scope': 'paired disposable databases; only scheduled fault differs; serial logical-time model',
            'limits': 'one job, two attempts, database-local effects; no concurrency, external effects, clock skew, or power-loss claim'}, [control_path, path]
