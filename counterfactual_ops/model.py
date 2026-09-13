"""Small, strict decision contract for the SQLite replay adapter."""
import hashlib
import json


class Invalid(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(ok, message):
    if not ok:
        raise Invalid(message)


def keys(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected.split()), f"{where}: expected keys {expected}")


def strings(values, where):
    require(isinstance(values, list) and values and all(isinstance(v, str) and v.strip() for v in values), f"{where}: nonempty strings required")
    require(len(values) == len(set(values)), f"{where}: duplicate values")


def validate(d):
    keys(d, "schema id objective choices status_quo claim context challenges experiments recovery", "decision")
    require(d['schema'] == 'cfo/v1', 'unsupported schema')
    for field in ('id', 'objective'):
        require(isinstance(d[field], str) and d[field].strip(), f'{field}: nonempty string required')
    strings(d['choices'], 'choices')
    require(len(d['choices']) >= 3 and d['status_quo'] in d['choices'], 'include proposed action, alternative, and status quo')
    keys(d['claim'], 'id statement kind predicate', 'claim')
    require(d['claim']['predicate'] == 'exactly-one-durable-effect-per-logical-job', 'unsupported assertion')
    require(d['claim']['kind'] == 'requirement', 'v0 supports requirements, not probabilistic forecasts')
    require(all(isinstance(v, str) and v.strip() for v in d['claim'].values()), 'claim fields must be nonempty')
    c = d['context']
    keys(c, 'implementation implementation_version effect_type identity retention_ticks replay_window_ticks workload observation_horizon_ticks dependencies', 'context')
    require(c['implementation'] in ('split', 'atomic'), 'unknown implementation')
    require(isinstance(c['implementation_version'], str) and c['implementation_version'].strip(), 'version required')
    require(c['effect_type'] == 'database-local' and c['identity'] == 'logical-job-id', 'unsupported effect or identity')
    require(c['workload'] == 'one-job-serial-replay', 'unsupported workload')
    for name in ('retention_ticks', 'replay_window_ticks', 'observation_horizon_ticks'):
        require(type(c[name]) is int and 0 <= c[name] <= 1000000, f'{name}: bounded integer required')
    require(c['retention_ticks'] > 0, 'retention must be positive')
    require(c['observation_horizon_ticks'] >= c['replay_window_ticks'], 'observation horizon is incomplete')
    require(isinstance(c['dependencies'], dict) and c['dependencies'] and all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in c['dependencies'].items()), 'explicit dependency versions required')
    strings(d['challenges'], 'challenges')
    require({'crash-gap', 'lost-ack', 'expired-identity'} <= set(d['challenges']), 'required failure modes omitted')
    require(isinstance(d['experiments'], list) and d['experiments'], 'experiments required')
    ids, coverage = set(), set()
    for e in d['experiments']:
        keys(e, 'id challenge fault delay_ticks cost outcomes measurement', 'experiment')
        require(isinstance(e['id'], str) and e['id'] and e['id'] not in ids, 'duplicate or missing experiment id')
        ids.add(e['id'])
        require(e['challenge'] in d['challenges'], 'unknown challenge')
        require(e['fault'] in ('none', 'after_effect', 'after_commit'), 'unsupported fault')
        require(type(e['delay_ticks']) is int and 0 <= e['delay_ticks'] <= c['replay_window_ticks'], 'experiment outside replay window')
        require(type(e['cost']) is int and e['cost'] > 0, 'cost must be positive effort units')
        keys(e['outcomes'], 'supported counterexample inconclusive', 'outcomes')
        require(all(v in d['choices'] for v in e['outcomes'].values()), 'outcomes must map to choices')
        keys(e['measurement'], 'authority population detection_limit', 'measurement')
        require(canonical(e['measurement']) == canonical({'authority': 'sqlite-effects-table', 'population': 1, 'detection_limit': 'every durable row for job-1 at end of schedule'}), 'adapter cannot establish this measurement')
        coverage.add((e['fault'], e['delay_ticks']))
    required = {('none', 0), ('after_effect', 0), ('after_commit', 0), ('none', c['replay_window_ticks'])}
    for boundary in (c['retention_ticks'] - 1, c['retention_ticks']):
        if boundary <= c['replay_window_ticks']:
            required.add(('none', boundary))
    require(required <= coverage, f'missing objective-derived coverage: {sorted(required - coverage)}')
    keys(d['recovery'], 'abort restore_configuration restore_data compensate_effects', 'recovery')
    require(all(isinstance(v, str) and v.strip() for v in d['recovery'].values()), 'recovery promises and limits required')
    return d


def load(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, f'duplicate JSON key: {k}')
            result[k] = v
        return result
    with open(path) as f:
        return validate(json.load(f, object_pairs_hook=unique))


def select(d, resolved=()):
    """Ordinal cost only: no invented probability or expected-value estimate."""
    return sorted((e for e in d['experiments'] if e['id'] not in resolved and len(set(e['outcomes'].values())) > 1), key=lambda e: (e['cost'], e['id']))
