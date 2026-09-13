# Prototype evaluation and product decision

The automated acceptance exercise uses committed definitions and actual worker
subprocesses. `python3 scripts/evaluate.py` writes a JSON report to stdout. It
checks unfamiliar failure discovery, an atomic healthy case, reuse by a related
decision without another run, support withdrawal on a dependency/version change,
and a defect at the exact retention boundary. Run it after committing sources.
It writes to a temporary evidence store unless `--store PATH` is supplied.

Its metrics are deterministic decision errors, unnecessary blocks of healthy
cases, worker experiment count, elapsed machine time, and evidence bytes. Machine
time is not investigator effort. Definition bytes are a maintenance-size proxy,
not a measurement of the human cost of keeping them accurate. Do not describe
these checks as comparative product validation.

The ordinary comparator is [a competent runbook](baseline-runbook.md), the same
regression tests, and searchable notes. Both can reach the correct answers. The
product's value must come from maintaining evidence-to-decision relationships
reliably with less repeated human work. The three-situation pilot below is the
remaining product experiment; human comparative measurements are not fabricated
by the automated demonstration.

## Preregistered comparative pilot

Use paired participants or teams, alternating which workflow they use first.
Give both the same evidence and a fixed 30-minute budget per situation. Avoid
repeating identical task answers for the same participant; use isomorphic worker
variants with known defects and healthy cases. Record prior familiarity. Retain
assignment, start/end times, queries, experiments, decisions, and record edits.

1. **Unfamiliar failure.** A worker can report success despite duplication. Ask for
   the next acceptable experiment and the replay decision. Include a healthy
   atomic variant and a split-write variant; conceal the label, not the source.
2. **Related change.** A second decision uses the same mechanism and conditions.
   Make the previous note/evidence discoverable in both arms. Observe whether
   participants reuse it correctly, duplicate work, or miss a relevant caveat.
3. **Changed implementation.** Change the transaction boundary or shorten
   retention. Ask which support still applies and what must be tested. Include an
   irrelevant documentation-only change to measure unnecessary invalidations.

For each arm and situation, record:

| Metric | Counting rule |
| --- | --- |
| Missed defects | Unsafe replay enabled despite an available distinguishing counterexample |
| Unnecessary blocks | Healthy replay blocked after all required applicable evidence is available |
| Investigation effort | Active minutes and experiment count; report separately |
| Maintenance cost | Active minutes and record edits needed for correct reuse/reassessment |
| Withdrawal errors | Stale support reused, or old finding incorrectly declared false |

Publish individual results and paired differences. Do not turn them into a single
score. Small samples support a local engineering decision, not a general efficacy
claim. Keep failed and healthy cases, drop no inconvenient runs, and distinguish
missing observations from zero errors.

Proceed as a separate product only if situations 2 and 3 repeatedly prevent
errors or save active work relative to the ordinary comparator without increasing
missed defects or unnecessary blocks. If gains come only from the worker tests,
package the adapter as a testing tool. If maintenance exceeds saved effort, stop
or narrow the record contract. No agent rankings or invented confidence updates.
