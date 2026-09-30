# Gooo Metaprogramming Experiments

The 100 cases are also published as ten public, one-intent repositories. See the [intent-slice index](docs/intent-slices.md); [CI validates the catalog](catalog/intent-repositories.json) against the source plan.

New [IR body-fill experiments](cohorts/ir-fill-2026-09-30/README.md) compare
12 composition cases before/after a compiler repair, 24 real-Laya choices,
three direct body-fill calls, eight mock scheduling treatments, and four
candidate/test-count scaling treatments. The model's raw choices, corrected
emission, held-out behavior, and runtime costs have separate denominators.

This public corpus runs 100 distinct intent/lowering combinations:

- 10 intents: sign, threshold, range, parity, status mapping, compound
  condition, priority, clamping, retry transition, and allowlist;
- 10 code assembly routes: guard returns, if/else ladder, boolean switch,
  assigned ladder, predicate helpers, predicate table, closure, assigned
  switch, finite-domain lookup, and intentionally partial assignment.

The cross product produces 100 compiled and executed candidates. Each is
evaluated on 25 explicit integer inputs (`-12` through `12`). This means 100
codegen treatments but only 10 unique Laya decision requests; it is not a claim
of 100 independent natural-language tasks.

## Result snapshot — 2026-09-29

| Measure | Laya top-1 | Seeded probability sample | Deterministic fallback |
| --- | ---: | ---: | ---: |
| Mean finite-domain agreement | 100% | 97.6% | 100% |
| Compile success | 100/100 | 100/100 | 100/100 |
| Deterministic replays | 100/100 | 100/100 | 100/100 |

Laya selected a complete route for all ten intent descriptions, matching the
fallback's completeness rather than improving it. The seeded probabilistic
selection chose one incomplete partial-assignment route, lowering its mean by
2.4 percentage points. This is evidence to keep probability sampling behind
compile and completeness gates; it is not evidence that Laya should author code.

On the final local CPU run, the ten Laya decisions averaged 119.6 ms each
(p95 151.0 ms). A separate run of the same batch observed about 82% of one CPU
core on the Laya process (8.2% of the 10-core host) and 603 MiB resident
memory. The compiler matrix itself generated a 138,705-byte combined Go source
file. Model weights were not copied into this repository.

Full decision probabilities, checkpoint revision, and per-candidate results:
[Laya report](results/2026-09-29/laya-report.json) and
[fallback report](results/2026-09-29/fallback-report.json). Individual records
are in [`experiments/`](experiments/). See the [measurement details](docs/measurement-method.md)
and [full result interpretation](docs/results-2026-09-29.md).

## Previous compiler-integrated baseline — 2026-09-30

The merged [GitHub Actions run](https://github.com/kimjooyoon/gooo-metaprogramming-experiments/actions/runs/36606448269)
processed 100 `.gooo` activity bodies on the pre-edge plan, compiled the
generated package, and matched all 2,500 declared finite-domain outputs. All
1,370 accepted body AST units were represented in generated code. These results describe the
declared fixtures and finite input domain; they do not measure coverage of
unstated user intent or prove behavior over the full integer domain.

This CI run had no Laya service configured. All 100 decisions therefore used
the deterministic `preserve` fallback, including 50 cases where multiple
routes were eligible. It is fallback and compiler evidence, not evidence about
Laya route quality. The separate [local Laya smoke](https://github.com/kimjooyoon/meta-ontology-go/blob/main/docs/language/laya-local-evaluation-2026-09-29.md)
records 30 real service calls on one fixture.

| Measurement | Result |
| --- | ---: |
| Gooo CLI invocation p50 / p95 | 3.402 / 3.775 ms |
| Cohort wall time | 2.157 s |
| Child-process CPU time | 5.566 CPU-s |
| Average CPU use | 258.08% of one core; 64.52% of four logical CPUs |
| Peak child-process RSS | 106,479,616 bytes (about 101.5 MiB) |
| Completeness receipt | 11 PASS, 6 UNKNOWN, no aggregate score |

Resource figures include the Gooo CLI and generated Go compile/run children;
they exclude an independently running Laya service. Laya route observation,
real-use-case coverage, reverse observation, full-domain behavior, route
quality, and a comparable resource baseline remain UNKNOWN pending their own
evidence.

## Scoped wrapping-affine int64 partition experiment — 2026-09-30

The direct body-codegen cohort now covers Boolean combinations of bounded
wrapping-affine conditions such as `input + 3 > 5`, `input * 2 == 0`, and
`input * 3 + 5 >= 10`. Its proof profile accepts signed `int64` constants and
limits the absolute input coefficient to 8. It derives transition inputs at
modular wraps, signed-order seams, and comparison boundaries, then adds those
representatives to generated-package execution alongside the separate 29-point
finite fixture domain. The independent oracle models Go `int64` wraparound.

The [PR CI run](https://github.com/kimjooyoon/gooo-metaprogramming-experiments/actions/runs/36626379233)
passed with 100 generated bodies, 2,900/2,900 finite-domain matches, and
2,500/2,500 partition-representative matches across 25 cells. All 100 route
equivalence receipts and the generated Go package test passed. The receipt has
14 PASS and 6 UNKNOWN dimensions with no aggregate score.

This claim is limited to the declared affine condition profile with constant
result pairs and the two tested body shapes. Other supported body expressions,
unrestricted Gooo body semantics, Laya route quality, and real-workflow coverage
remain outside this proof. The CI receipt keeps those dimensions UNKNOWN and
does not collapse completeness into one score.

## Reproduce

Install/build the Gooo CLI and lab runner, then run:

```sh
GOOO_BIN=/path/to/gooo go run github.com/kimjooyoon/gooo-metaprogramming-lab/cmd/lab matrix \
  --plan plan-v1.json --out /tmp/gooo-matrix
```

For local Laya routing, set `GOOO_LAYA_URL` to the running loopback service.
The checked-in GitHub Actions workflow uses the deterministic fallback and
compiles/runs all 100 candidates without downloading model weights.

## Scope and limits

The original sidecar cohort predates Gooo's executable activity-body profile.
That cohort asks Gooo to generate the semantic declaration projection, then a
typed rule IR deterministically lowers to Go helpers containing `if`, Boolean
conditions, `switch`, and assignments. The helpers are an experimental
sidecar; they are not represented as stable `.gooo` statements yet.

Completeness is measured over a finite fixture domain and over reachable
decision clauses. It does not prove behavior for every integer or for domain
types beyond the small prototype. The intentionally partial route demonstrates
that the score detects omitted branches: its candidate agreement ranges from
48% to 96%, depending on the intent.

The separate experimental [`gooo body-codegen` path](https://github.com/kimjooyoon/meta-ontology-go/blob/main/docs/language/body-codegen.md)
emits a small subset of `.gooo` `computes` programs as deterministic,
typechecked Go functions. [PR #1074](https://github.com/kimjooyoon/meta-ontology-go/pull/1074)
adds a bounded Laya choice among three equivalent conditional-lowering shapes,
with deterministic `preserve` fallback and route/latency/completeness receipts;
it is on `main` via [PR #1080](https://github.com/kimjooyoon/meta-ontology-go/pull/1080)
and exact-tree promotion [PR #1081](https://github.com/kimjooyoon/meta-ontology-go/pull/1081).
The initial seeded-sampler deployment was commit
`6414da939c5d7e55425cdb3a4ed220121ab49c16`. A warm
30-call smoke on one fixture measured 108.48 ms p50 / 123.10 ms p95, with `preserve` selected on
every call. This is a latency/resource observation, not an accuracy result.

The compiler-derived route-equivalence receipt was added by
[PR #1082](https://github.com/kimjooyoon/meta-ontology-go/pull/1082) and
promoted by exact-tree [PR #1083](https://github.com/kimjooyoon/meta-ontology-go/pull/1083).
At that deployment, `main` was `3e31f92f529a8cff013b933d04fb8bbdc8fec72b`, with
the same tree as `dev`. See the workflow's pinned compiler revision for the
current CI baseline; historical measurements retain their original revisions.

The 100-case corpus reported above remains the sidecar-based baseline. A
separate [direct body-codegen cohort](cohorts/body-codegen-100/README.md)
routes 100 generated `.gooo` bodies through the pinned Gooo CLI and checks 2,900
finite-domain outputs after compiling the generated Go package, including 400
observations at signed `int64` extrema and adjacent values. It keeps
behavioral agreement separate from body-AST coverage and records replay,
latency, child CPU, peak child RSS, and average core-normalized CPU use. Its
machine-readable completeness receipt reports independent PASS/PROGRESS/UNKNOWN
dimensions without a single aggregate score, keeping real-use-case coverage,
reverse observation, unrestricted full-domain behavior, and route quality
UNKNOWN until those claims have their own evidence. The current direct cohort
also derives exact transition points for bounded wrapping-affine conditions
and executes one representative from each resulting int64 cell; CI records
this as a separate 100/100 scoped partition proof. It does not extend that proof
to other Gooo body expressions. Resource figures cover Gooo
and generated-Go child processes; a separately running Laya server is excluded. CI runs
without a model service and uses the deterministic fallback; Laya route choice
remains an optional local measurement, with request digest, model revision,
probabilities, and confidence preserved when available. The cohorts have
different input construction and evidence boundaries, so their percentages are
not averaged together.

The separate [exhaustive Boolean-domain cohort](cohorts/body-codegen-boolean-100/README.md)
crosses 100 generated bodies with both possible Boolean inputs, checks 200
compiled outputs, and exercises five condition forms plus five local/body
shapes. It reports full-domain completeness only for Boolean input and leaves
real-use-case and Laya route-quality dimensions UNKNOWN. The sidecar matrix,
affine `int64` proof, and Boolean proof retain separate denominators and are
never averaged into a single score.

Its [PR CI run](https://github.com/kimjooyoon/gooo-metaprogramming-experiments/actions/runs/36627399107)
matched 200/200 outputs, 100/100 route-equivalence receipts, and 100/100
external repeats. Gooo CLI invocation p50 was 2.77 ms on the GitHub runner with
Laya disabled; that timing is only the deterministic fallback path.

## Shared completeness receipt contract — 2026-09-30

The direct affine and exhaustive Boolean cohorts now emit the same
`gooo/metaprogramming-completeness-receipt/v2` contract. Each dimension carries
its evidence unit, numerator and denominator, reason, and evidence references.
Every `PROGRESS`, `UNKNOWN`, or `FAIL_CLOSED` item is retained in receipt order
with a concrete next operation; `first_unresolved` identifies the earliest
remaining item. Scope binds the hashed plan, compiler source revision,
toolchain, execution environment, allowed investment, and explicit exclusions.

The receipt keeps its aggregate completeness score null. A cohort can pass its
declared fixture core while real workflows, reverse observation, host
permissions, route quality, or a compatible before/after semantic baseline
remain UNKNOWN. Baseline comparison is a separate dimension so experiments
can show per-dimension regressions without turning unrelated coverage into a
single percentage. GitHub Actions checks both cohort reports against the
shared schema and their report identities.

## Seeded Laya route experiment — 2026-09-30

Two local runs used the compiler's seeded weighted sampler with live Laya route
probabilities. Each run processed the same 100 generated bodies (50 had three
eligible routes; 50 had only the source-preserving route), compiled and ran the
generated package, and repeated every seeded CLI invocation. Both runs passed:
2,500/2,500 pre-edge-plan finite-domain outputs, 100% body-AST coverage, and 100/100 exact
external replays, with no replay mismatches. Across the 50 Laya-routed cases,
changing only the seed changed four selected routes. That demonstrates
reproducible variation in this fixture, not better route quality or broader
intent coverage.

| Measurement | Seed 1 | Seed 2 |
| --- | ---: | ---: |
| Laya route choices | 50 | 50 |
| `preserve` / `guard-return` / `merge-result` among those choices | 47 / 1 / 2 | 48 / 1 / 1 |
| Laya decision latency p50 / p95 | 104.3 / 328.2 ms | 104.8 / 239.5 ms |
| Laya process CPU, one core / 10-core host | 140.7% / 14.1% | 169.6% / 17.0% |
| Laya sampled peak resident memory | 3.82 GiB | 3.15 GiB |
| Generated package | passed | passed |

The latency percentiles use linear interpolation over 50 Laya decisions per
run; one seed-1 request took 2.52 seconds. The separate Laya server ran pinned to revision
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, on CPU with four configured
threads. Its CPU and memory are measured separately from Gooo and generated-Go
child-process costs. The checkpoint emitted a warning that some temperature
values were clamped; confidence values for affected entries are therefore
uncalibrated. Probability sampling remains behind compiler type-checking,
deterministic replay, generated-package compilation, and declared-domain
behavior checks.

The complete per-case reports, generated package, and separate Laya process
telemetry are in
[`results/2026-09-30/laya-seeded-route-sampling/`](results/2026-09-30/laya-seeded-route-sampling/)
and
[`results/2026-09-30/laya-seeded-route-sampling-seed-2/`](results/2026-09-30/laya-seeded-route-sampling-seed-2/).
These are local observations from one machine, not CI timings. The machine
readable receipts retain 12 PASS and 5 UNKNOWN dimensions with no aggregate
score; real-use-case coverage, reverse observation, full-domain semantics,
route quality, and comparable resource baseline remain UNKNOWN.

## Route-equivalence receipt with Laya — 2026-09-30

A third seeded local run on the pre-edge plan used Gooo dev commit
`453c7c8a27cd1a5fcb80e1383ade3829477b8a2c` (tree
`9b464b9d7bfb00fdebc252823781104bb9108e99`), containing the compiler change
from PR #1082. It generated and ran all 100 bodies, matched 2,500/2,500 finite
domain outputs, passed 100/100 semantic-equivalence receipts, and replayed all
100 seeded CLI calls without mismatch. The 50 Laya-selected cases chose 47
`preserve`, one `guard-return`, and two `merge-result` routes; the other 50
cases had only the deterministic `preserve` route. The receipt now reports 13
PASS and 5 UNKNOWN dimensions, with no aggregate score. Route quality remains
UNKNOWN because semantic equality does not rank clarity or usefulness.

| Measurement | Result |
| --- | ---: |
| Laya decision p50 / p95 | 102.159 / 169.770 ms |
| Laya CPU use, one core / 10-core host | 169.46% / 16.95% |
| Laya sampled peak RSS | 3,791,716,352 bytes (3.53 GiB) |
| Gooo and generated-Go children | 13.036 s; 8.934% of one core; 94,044,160 bytes peak RSS |

The model ran on CPU with four configured threads at revision
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. With lazy model loading, the first
request took 3,001.856 ms and reached the decision budget during lazy loading,
so it used deterministic fallback; the next warm request took 108.518 ms. A checkpoint temperature was
clamped to 0.5, so affected confidence values are uncalibrated. Full case
reports, warm/cold receipts, generated package, and sampled process metrics are
in [`results/2026-09-30/laya-route-equivalence-seed-3/`](results/2026-09-30/laya-route-equivalence-seed-3/).
The compiler change was promoted by PR #1083 at commit
`3e31f92f529a8cff013b933d04fb8bbdc8fec72b`; its tree matches the source tree
used by this measurement. The report retains the pre-promotion `dev` SHA as its
source identity because that is the exact revision used to build the local
compiler binary.

## Compiler-owned completeness receipts — 2026-09-30

The direct 100-case cohort now embeds the compiler's own
`gooo/metaprogramming-completeness-receipt/v2` in every case record. CI
validates each receipt, binds its plan digest and compiler revision to the
exact body-codegen report, verifies a canonical receipt SHA-256, and compares
that digest during deterministic replay. The cohort reports compiler receipt
coverage separately from the number of cases whose declared compiler core
dimensions all pass. The Python cohort receipt remains a separate outer
measurement, and both aggregate completeness scores stay null.

A clean local run against candidate Gooo commit
`b44e288e2c9aed7001cc1f14b0b9d97f3be271d3` validated 100/100 compiler
receipts and 100/100 core receipts. Its source tree was promoted to protected
`main` by [meta-ontology-go PR #1085](https://github.com/kimjooyoon/meta-ontology-go/pull/1085)
at deployed commit `3086deb0892329fe10a38f2ee2882a5375be2fa6`. The compiler
reported 1,000 PASS and 1,000 UNKNOWN dimension observations across the 100
cases; UNKNOWNs remain visible for execution, permissions, Laya observation,
real workflows, reverse observation, broad-domain behavior, route quality,
resources, and comparable baselines. The outer cohort passed 2,900/2,900
finite-domain outputs and 2,500/2,500 affine partition representatives.

| Measurement | Result |
| --- | ---: |
| Cohort wall time | 1,715.934 ms |
| Gooo invocation p50 / p95 | 5.174 / 5.778 ms |
| Child CPU, one core / 10-core host | 71.270% / 7.127% |
| Child peak RSS | 94,093,312 bytes |
| Compiler receipts / core passes | 100/100 / 100/100 |
| Laya decisions | 0; deterministic fallback used |

These resource figures are one local macOS arm64 run using Go 1.27.0. They
include Gooo and generated-package child processes, exclude a Laya server, and
are not yet a same-profile before/after comparison. The public experiment PR
now pins deployed `main` commit `3086deb0892329fe10a38f2ee2882a5375be2fa6`;
its CI run is the cross-platform reproduction against that protected revision.
