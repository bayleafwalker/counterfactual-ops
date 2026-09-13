# Ordinary workflow comparator

Use this runbook, the same worker regression tests, and searchable incident notes.
Give the comparator the exact same experiment definitions, source revision,
workload, observations, and time budget as the Counterfactual Ops arm.

1. List the replay decision, alternatives, and the single-effect requirement.
   Check the normal, crash-gap, lost-ack, replay-window, and retention boundaries.
2. Inspect `SELECT job, amount FROM effects` in a disposable SQLite database after
   each schedule. Compare the no-fault control. A successful worker exit is not the
   assertion. A gap duplicate rejects replay for that implementation.
3. Record the failing schedule, version, transaction mechanism, identity,
   retention, replay window, observation limits, and reproduction command in an
   incident note. Preserve tests as regression checks.
4. For a related decision, search those notes. Reuse a finding if all relevant
   conditions, measurement, and required schedules match. Rerun only missing
   coverage. Record the reasoning for reuse.
5. On an implementation, dependency, or window change, keep the old finding but
   mark its use in the new decision unestablished. Check the affected tests and
   obtain fresh evidence. Do not mark the old finding false solely due to change.
6. Acknowledge counterexamples with an action. Disabling replay stops additional
   effects; it does not compensate effects already committed.

This comparator is deliberately capable of correct reuse and withdrawal. It
should not rerun everything mechanically or forget version conditions merely to
make the product look useful. Neither arm should block the healthy atomic case
within its retention window after sufficient evidence.

Incident note template:

```
Decision / requirement:
Version and dependency assumptions:
Workload / identity / retention / replay window:
Precommitted schedules and detection limits:
Observations and durable-state artifacts:
Control comparison and permissible conclusion:
Related decisions and reuse reasoning:
Change requiring reassessment:
Action and regression reference:
```
