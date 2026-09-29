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
cost. It also emits a machine-readable completeness receipt with independent
PASS, PROGRESS, UNKNOWN, and FAIL_CLOSED dimensions. The receipt deliberately
has no aggregate completeness score: synthetic fixture coverage, generated
behavior, source binding, reverse observation, real use cases, and route quality
remain distinct claims. It keeps missing real-use-case, reverse-observation,
full-domain, and route-quality evidence UNKNOWN rather than treating finite
fixture success as universal completeness.

A 100% finite-domain result applies only to this fixture domain. The
body-codegen completeness field means accepted source AST units were represented
in the lowering; it does not claim to measure unstated user intent or prove
correctness for all integers.

The 50 explicit-return cases expose the three compiler-approved equivalent
control-flow routes. The 50 assignment cases intentionally have only the
source-preserving route. CI runs without a model service, so route selection
uses deterministic fallback. Set `GOOO_LAYA_URL` when running the cohort
locally to record actual Laya route decisions; Laya can select only among the
compiler-declared eligible routes.

GitHub Actions uploads the generated source and JSON measurement report for
each run. The report records cohort wall time and both one-core and
host-normalized average child CPU use, alongside cumulative child CPU seconds
and peak child RSS. CPU and memory observations cover Gooo CLI and generated-Go
compile/test child processes; they exclude an independently running Laya server.
This is the first sample with core-normalized resource timing; comparisons stay
UNKNOWN until a repeat from the same compiler and runner profile is bound.
The report preserves each route request digest, model revision, probability
vector, and confidence when Laya supplies them; these are route-decision
evidence, not calibration or quality evidence. The generated package and
fixture files are temporary artifacts and are not committed as product code.
