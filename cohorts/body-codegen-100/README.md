# Direct Gooo body-codegen cohort

This cohort sends 100 generated `.gooo` activity bodies through the public
`gooo body-codegen --json` command. It forms a separate cohort from the
sidecar-based 100-intent/lowering matrix in the repository root.

The 100 cases are the cross product of ten Boolean condition shapes, five
integer result pairs, and two source forms: explicit branch returns, and a
`let` result followed by conditional assignment and return. CI binds each
generated report to the pinned Gooo source revision, then compiles and executes
all generated functions on the same declared domain of 25 integer values
(-12 through 12), for 2,500 checked outputs.

The report keeps separate measures for finite-domain behavior, source-body AST
coverage, type checking, replay equality, eligible route choices, and process
cost. A 100% finite-domain result applies only to this fixture domain. The
body-codegen completeness field means that accepted source AST units were
represented in the lowering; it does not claim to measure unstated user intent
or prove correctness for all integers.

The 50 explicit-return cases expose the three compiler-approved equivalent
control-flow routes. The 50 assignment cases intentionally have only the
source-preserving route. CI runs without a model service, so route selection
uses deterministic fallback. Set `GOOO_LAYA_URL` when running the cohort
locally to record actual Laya route decisions; Laya can select only among the
compiler-declared eligible routes.

GitHub Actions uploads the generated source and JSON measurement report for
each run. The generated package and fixture files are temporary artifacts and
are not committed as product code.
