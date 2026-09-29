# Gooo Metaprogramming Experiments

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

## Latest compiler-integrated run — 2026-09-30

The merged [GitHub Actions run](https://github.com/kimjooyoon/gooo-metaprogramming-experiments/actions/runs/36606448269)
processed 100 `.gooo` activity bodies, compiled the generated package, and
matched all 2,500 declared finite-domain outputs. The 1,370 accepted body AST
units were all represented in generated code. These results describe the
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

The current Gooo grammar does not yet express executable activity bodies.
This lab asks Gooo to generate the semantic declaration projection, then a
typed rule IR deterministically lowers to Go helpers containing `if`, Boolean
conditions, `switch`, and assignments. The helpers are an experimental
sidecar; they are not represented as stable `.gooo` statements yet.

Completeness is measured over a finite fixture domain and over reachable
decision clauses. It does not prove behavior for every integer or for domain
types beyond the small prototype. The intentionally partial route demonstrates
that the score detects omitted branches: its candidate agreement ranges from
48% to 96%, depending on the intent.

The separate experimental [`gooo body-codegen` path](https://github.com/kimjooyoon/meta-ontology-go/blob/dev/docs/language/body-codegen.md)
emits a small subset of `.gooo` `computes` programs as deterministic,
typechecked Go functions. [PR #1074](https://github.com/kimjooyoon/meta-ontology-go/pull/1074)
adds a bounded Laya choice among three equivalent conditional-lowering shapes,
with deterministic `preserve` fallback and route/latency/completeness receipts;
it is on `main` via [PR #1079](https://github.com/kimjooyoon/meta-ontology-go/pull/1079),
which promoted the exact `dev` tree. Main CI and the promotion proof passed.
The deployed commit is `0299ba548f15ac9550d1c7f742749d5e42948a4a`. A warm
30-call smoke on one fixture measured 108.48 ms p50 / 123.10 ms p95, with `preserve` selected on
every call. This is a latency/resource observation, not an accuracy result.

The 100-case corpus reported above remains the sidecar-based baseline. A
separate [direct body-codegen cohort](cohorts/body-codegen-100/README.md)
routes 100 generated `.gooo` bodies through the pinned Gooo CLI and checks 2,500
finite-domain outputs after compiling the generated Go package. It keeps
behavioral agreement separate from body-AST coverage and records replay,
latency, child CPU, peak child RSS, and average core-normalized CPU use. Its
machine-readable completeness receipt reports independent PASS/PROGRESS/UNKNOWN
dimensions without a single aggregate score, keeping real-use-case coverage,
reverse observation, full-domain behavior, and route quality UNKNOWN until
those claims have their own evidence. Resource figures cover Gooo and generated
Go child processes; a separately running Laya server is excluded. CI runs
without a model service and uses the deterministic fallback; Laya route choice
remains an optional local measurement, with request digest, model revision,
probabilities, and confidence preserved when available. The two cohorts have
different input construction and evidence boundaries, so their percentages are
not averaged together.
