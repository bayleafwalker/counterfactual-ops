# Decision and evidence contract, version 0

Definitions are JSON, validated by `counterfactual_ops.model.validate`. Unknown
fields and unsupported adapter semantics fail closed. The examples are executable
specifications. There is intentionally no general ontology or plugin interface.

| Field | Meaning |
| --- | --- |
| choices / status_quo | Proposed action, meaningful alternative, and doing nothing |
| claim | Stable identity, statement, requirement kind, and the adapter's executable predicate |
| context | Exact applicability conditions, including implementation version and dependency assumptions |
| challenges | Explicit objections: crash gap, lost acknowledgement, expired identity |
| experiments | Controlled schedule, cost, authoritative measurement, and precommitted outcome-to-choice mapping |
| recovery | Distinct abort, configuration, data, and compensation promises or explicit limits |

V0 has one material assumption per decision. Split decisions when they need
independent assumptions. Reuse joins the full claim and experiment measurement /
fault / delay / challenge signature, exact context, adapter content digest, and
runtime SQLite version. Decision name, objective, and cost may differ without
changing the finding. There is no transitive claim graph, probabilistic forecast
scoring, or inference about an untested mechanism. Dependency versions are supplied
by the author; the internal executable adapter and SQLite version are measured.

The objective imposes required coverage independent of agent-selected predictions:
normal replay, exits after the effect and after commit, the maximum permitted
replay delay, and either side of expiry when inside that window. This is a bounded
schedule set, not exhaustive cross-product coverage. The claim is expressly about
these schedules. Failures can coexist: the split implementation also fails at the
retention boundary. Tests exercise both mechanisms rather than assuming mutually
exclusive explanations.

An experiment with the same choice for every outcome is excluded by the stopping
rule. Such an experiment does not count as resolved coverage; revise the decision
or state why no experiment is worth doing. Ranking uses declared cost, then ID;
it is not an automatic experiment designer or a claim of optimal information gain.

Plans preserve the entire definition before worker execution. Each result links
the plan and experiment, stores both independent durable-state observations,
process exit codes, scope limits, and two hashed SQLite artifacts. `supported`
means exactly one expected effect in the intervention arm. `counterexample` means
the predicate failed. Runner or observation failure means `inconclusive`.
A control failure limits causal attribution; it does not hide an intervention
counterexample. Retention boundary experiments are descriptive paired observations;
v0 does not infer a causal mechanism solely from worker success.

A plan without all its results is incomplete. A later supported run does not erase
an earlier applicable counterexample. A `resolution` chooses a recorded alternative
and cites the action in prose; it acknowledges the obligation without falsifying
history. Unexpected consequences are independently appended. Suspected explanations
are suggestions and cannot establish support.

Pre-registration is enforced against local Git HEAD. Publication before execution
is not required. Git and the hash chain establish reproducibility and detect
accidental tampering, not a trusted timestamp against a malicious operator.
Concurrent mutation of source during a run is outside this local prototype's
trust boundary. Run the checked-out tests under a single stable revision.

The ledger is intentionally inspectable NDJSON and opaque SHA-256-named objects.
SQLite artifacts can be inspected with any SQLite reader. Retain the complete
ledger and all referenced objects. Do not prune or edit events. Replicate through
Git and verify against the prior committed history with `scripts/check_evidence.py`.
