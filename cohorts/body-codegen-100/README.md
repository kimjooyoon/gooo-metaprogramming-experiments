# Direct Gooo body-codegen cohort

This cohort sends 100 generated `.gooo` activity bodies through the public
`gooo body-codegen --json` command. It forms a separate cohort from the
sidecar-based 100-intent/lowering matrix in the repository root.

The 100 cases are the cross product of ten Boolean condition shapes, five
integer result pairs, and two source forms: explicit branch returns, and a
`let` result followed by conditional assignment and return. CI binds each
generated report to the pinned Gooo source revision, then compiles and executes
all generated functions over 29 declared inputs: the original 25 values
(-12 through 12) plus four signed `int64` edge values, for 2,900 checked
outputs. The four added values are `MinInt64`, `MinInt64+1`, `MaxInt64-1`, and
`MaxInt64`; CI requires all 400 case/edge pairs to execute and match.

The report keeps separate measures for finite-domain behavior, source-body AST
coverage, type checking, replay equality, eligible route choices, and process
cost. Each generated case also carries a compiler-derived route-equivalence
receipt. The receipt canonicalizes the source and emitted control-flow forms,
normalizing only the declared if/else-return rewrites; other accepted bodies
must retain the same formatted Go AST. The cohort binds those semantic digests
to the exact input and generated-source digests. It establishes equivalence
inside the closed, typechecked body profile, not intent coverage or behavior
over all `int64` values. It also emits a machine-readable completeness receipt with independent
PASS, PROGRESS, UNKNOWN, and FAIL_CLOSED dimensions. The receipt deliberately
has no aggregate completeness score: synthetic fixture coverage, generated
behavior, source binding, reverse observation, real use cases, and route quality
remain distinct claims. It keeps missing real-use-case, reverse-observation,
unrestricted full-domain, and route-quality evidence UNKNOWN rather than treating
finite fixture success as universal completeness.

The separate `int64_extreme_boundary_behavior` dimension reports those 400
edge observations without converting four boundary samples into full-domain
proof. The edge samples alone do not establish full-domain behavior; the scoped
partition proof below uses the actual supported condition grammar.

The plan's current conditions are Boolean combinations of 13 comparisons
between `input` and signed integer literals. They change truth only at seven
integer transition points (`-2, 0, 1, 2, 3, 5, 6`), so the full signed
`int64` domain has eight truth-stable cells for this profile. CI checks one
representative in each cell (`MinInt64, -2, 0, 1, 2, 3, 5, 6`) against the
independent condition oracle and compiled generated functions. It records
`partitioned_int64_semantics` as 100/100 only when the declared input set
contains every representative, all generated routes have equivalence receipts,
and the compiled run passes. This proves the 100 constant-result fixtures over
the declared comparison profile; general Gooo bodies and other predicate
operators remain outside the proof.

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

To exercise the seeded probability sampler against a live local Laya service,
also set `GOOO_BODY_CODEGEN_SAMPLE_SEED` to a caller-chosen seed. The runner
passes it to each `gooo body-codegen --sample-seed` invocation and repeats the
invocation to verify identical route-selection receipts and generated source.
Reports publish only the seed digest, not the raw value. Without this variable,
the runner preserves its ordinary deterministic fallback behavior when Laya
is absent; seeded sampling does not change the default CI path.

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
