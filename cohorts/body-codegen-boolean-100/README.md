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

`exhaustive_boolean_domain` is a full-domain claim for Boolean inputs only.
Real workflows, Laya route quality, and unrestricted body-codegen completeness
remain UNKNOWN. The receipt has no aggregate score, and the generated package
and fixture files remain temporary CI artifacts.
