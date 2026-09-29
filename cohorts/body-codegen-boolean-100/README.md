# Exhaustive Boolean-domain body-codegen cohort

This cohort sends 100 generated `.gooo` activity bodies through the public
`gooo body-codegen --json` command. The plan crosses five Boolean conditions,
four true/false result pairs, and five source-body styles. Styles include
direct branch returns and local initialization, assignment, and overwrite
patterns.

Boolean input has exactly two values. The runner compiles all generated Go
functions and checks both `false` and `true` against a separately written
oracle, for 200 outputs. It binds source and generated digests to each
compiler report, requires compiler type checking, internal emission replay,
route-equivalence receipts, and external deterministic CLI repeats.

The [PR CI run](https://github.com/kimjooyoon/gooo-metaprogramming-experiments/actions/runs/36627399107)
passed: all 200 outputs matched, all 100 route receipts passed, and all 100
external repeats matched. With Laya disabled on the GitHub runner, the recorded
Gooo CLI invocation p50 was 2.77 ms; this is a fallback-path timing sample, not
a Laya response-latency measurement.

`exhaustive_boolean_domain` is a full-domain claim for Boolean inputs only.
Real workflows, Laya route quality, and unrestricted body-codegen completeness
remain UNKNOWN. The shared v2 receipt also records declaration and source-AST
coverage, provenance, execution and repository-write boundaries, permissions,
network configuration, reverse observation, and whether a compatible semantic
baseline exists. Every unresolved dimension retains its reason and next
operation; the first one is exposed as `first_unresolved`. There is no aggregate
score, and the generated package and fixture files remain temporary CI
artifacts. CI validates this receipt and the affine cohort's receipt against
the same schema.
