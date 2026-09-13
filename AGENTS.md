# Counterfactual Ops

This is a bounded SQLite replay-safety prototype. Preserve the distinctions
between observed discrepancy, suspected explanation, experimentally supported
explanation, and evidence that has become inapplicable.

Risk surfaces: worker transaction boundaries, replay identity/retention,
independent effect assertions, pre-registration, applicability matching, and
append-only evidence. Do not add production connections or arbitrary executable
commands to decision files. No confidence scores or agent rankings.

Run `python3 -m unittest discover -s tests -v` after changing executable behavior.
Non-loopback web deployment requires authenticated mutations and gateway TLS.
Keep API decision lookup and static serving allowlisted; browser input must never
become a filesystem path, subprocess command, or SQL fragment.
Commit definitions and adapter sources before `python3 scripts/evaluate.py`.
Run `python3 scripts/check_evidence.py --base <previous-landed-commit>` before
landing changes to existing evidence. Never edit or remove historical events or
referenced objects. New sources need fresh runs; old results remain historical.

Keep the ordinary comparator competent. Automated acceptance does not establish
product superiority; human pilot measurements must remain explicitly unmeasured
until actually collected. Dependencies and workload limits belong with findings.
