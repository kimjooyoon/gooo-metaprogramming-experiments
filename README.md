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
