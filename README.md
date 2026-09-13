# Counterfactual Ops

**Which uncertainty could change our decision, and what is the cheapest acceptable way to resolve it?**

Counterfactual Ops is a bounded Python prototype connecting operational decisions,
executable challenges, observations, and the conditions that permit evidence reuse.
Its first adapter tests retry safety in a disposable SQLite worker. It owns no
production execution, scheduler, credentials, or desired state.

## Web application

Run the local full-stack application from the repository root:

```sh
python3 -m counterfactual_ops.web
# open http://127.0.0.1:8787
```

The dashboard shows the decision portfolio, current support, counterexamples,
reassessment needs, and open obligations. A decision view exposes applicability
conditions and executable challenges, runs individual or full experiment suites,
and renders the append-only evidence timeline with downloadable authoritative
SQLite artifacts. The evidence view presents the complete history.

The browser can create a validated decision file under `decisions/`. Review and
commit that file before running it: the same pre-registration rule applies to web
and CLI execution. Mutating API routes accept JSON only, reject cross-origin
requests, and cannot select arbitrary files or commands. The v0 server deliberately
binds to loopback; it is a local operational workbench, not a multi-user service.

Install with `pip install .` to use `cfo-web`. The JSON API is rooted at
`/api/v1`: `overview`, `decisions`, `events`, `artifacts`, `runs`, and
`annotations`. See [the API contract](docs/web-api.md).

A split effect/completion commit duplicates an effect when the process exits
between writes. An atomic transaction passes that challenge. Both implementations
can duplicate effects after their deduplication record expires. The observer
counts durable business effects independently of worker success or logs.

## Try it

Python 3.11+ on Linux/macOS, Git, and SQLite support in Python are sufficient.
There are no runtime dependencies or services to install. From this checkout:

```sh
python3 -m unittest discover -s tests -v
python3 -m counterfactual_ops --store /tmp/cfo-demo select examples/01-split.json
python3 -m counterfactual_ops --store /tmp/cfo-demo run examples/01-split.json --all
python3 -m counterfactual_ops --store /tmp/cfo-demo assess examples/01-split.json
python3 -m counterfactual_ops --store /tmp/cfo-demo run examples/02-atomic.json --all
python3 -m counterfactual_ops --store /tmp/cfo-demo assess examples/03-related.json
python3 -m counterfactual_ops --store /tmp/cfo-demo assess examples/04-changed.json
python3 -m counterfactual_ops --store /tmp/cfo-demo run examples/05-expiry.json --all
python3 -m counterfactual_ops --store /tmp/cfo-demo verify
```

Expected assessments: `counterexample` for split commits;
`supported-under-tested-conditions` for the related atomic decision, **without a
new experiment**; `needs-reassessment` after a version/dependency change. Extending
the replay window to the exact retention boundary produces a counterexample.
Use a fresh store to repeat the demonstration independently. A `/tmp` store is
session-local. The default `evidence/` becomes cross-host-replicated when committed
and pushed with the project.

A normal `run` executes only the cheapest unresolved decision-relevant experiment.
`select` lists remaining experiments by author-supplied ordinal effort units.
It estimates no probabilities or expected monetary value. After a counterexample,
selection stops for a decision/implementation revision. `--all` explicitly runs
the regression suite; `--experiment ID` repeats one registered challenge.

Definitions and all adapter Python sources must match a Git commit **before** any
intervention. A plan containing the exact definition, source revision, adapter
hash, SQLite version, and selected experiments is appended and flushed first.
An interrupted run remains visible as an incomplete observation window. Exit 0
from the CLI means the operation completed; use `assess.status` to make a decision.
Validation, provenance, and integrity errors exit 2. Inconclusive experiments are
recorded as such and never count as supporting evidence.

Optionally install with `pip install .` to use `cfo` instead of
`python3 -m counterfactual_ops`. Installed source must match the source committed
beside the decision; a mismatched installation refuses to run.

## What the records mean

- A requirement counterexample is a durable-state violation under the recorded
  schedule. It is not a confidence decrement or an agent competence score.
- A passing experiment provides bounded support for the specified workload,
  versions, dependencies, logical replay window, and schedules. It proves no
  universal retry guarantee.
- An implementation or condition change withdraws applicability, preserving the
  historical finding. Exact condition matching governs reuse; no similarity score
  silently licenses a result.
- A paired no-fault control can support a causal explanation for a scheduled
  process exit. A violation in both arms is recorded as an observed discrepancy.
  Human hypotheses remain explicitly suspected explanations.

`obligations examples/*.json` shows unresolved material assumptions, incomplete
runs, changed conditions, counterexamples awaiting change, and unexpected effects.
Definitions share the explicit claim identity to find affected pending decisions.

```sh
python3 -m counterfactual_ops unexpected PLAN_ID --note 'Observed consequence omitted from the plan'
python3 -m counterfactual_ops hypothesis PLAN_ID --note 'A suspected explanation to challenge'
python3 -m counterfactual_ops resolve EVENT_ID --choice repair-idempotency --note 'Decision taken and implementation change reference'
```

Resolution records acknowledge an operational response. They never erase or
convert a counterexample into support. New evidence needs a new run and, for a
changed implementation, a new committed decision definition.

## Boundaries

The adapter covers one logical job, two serial attempts, SQLite-local effects,
controlled logical time, and abrupt process exit. It does not model concurrent
workers, clock skew, asynchronous TTL cleanup, power loss, external APIs, or a
production database. All worker paths are disposable and internal; JSON cannot
supply arbitrary commands or database paths. Passing state requires exactly one
row for `job-1` with the expected amount, not merely a successful job record.

The logical observation horizon is an end-of-schedule observation after both
synchronous processes finish, with no background actors. It is not a wall-clock
monitoring window. Abort/configuration restoration means stopping future calls;
it leaves committed effects intact. Data restore and compensation are explicitly
unestablished and require separate adapters and arguments.

The ledger uses OS locking, fsync, hash chaining, and content-addressed database
artifacts. It is append-only through the API, not a hostile-writer security
boundary. Compare with a prior Git revision to detect truncation or wholesale
rewrites. No automatic repair destroys or rewrites a damaged record.

See [the contract](docs/contract.md), [ordinary baseline runbook](docs/baseline-runbook.md),
and [evaluation protocol](docs/evaluation.md). The prototype demonstrates reuse
and withdrawal; a product advantage over a competent ordinary workflow remains
to be established by the comparative pilot.
