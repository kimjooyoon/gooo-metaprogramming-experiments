# Laya route-equivalence cohort — 2026-09-30

This local run used the exact Gooo `dev` source at commit
`453c7c8a27cd1a5fcb80e1383ade3829477b8a2c`, tree
`9b464b9d7bfb00fdebc252823781104bb9108e99`. The corresponding compiler change
is PR [#1082](https://github.com/kimjooyoon/meta-ontology-go/pull/1082); the
main promotion must preserve this tree. The Gooo binary and generated package
used Go 1.27.0 from the local toolchain cache.

## Cohort results

| Measure | Result |
| --- | ---: |
| Generated bodies | 100/100 |
| Finite-domain outputs | 2,500/2,500 matched |
| Body AST coverage | 100% |
| Route semantic-equivalence receipts | 100/100 PASS |
| Generated package compile and execution | passed |
| Seeded external replays | 100/100; zero mismatches |
| Completeness receipt | 13 PASS, 5 UNKNOWN; no aggregate score |

Fifty cases had multiple eligible routes and used Laya probabilities; the other
fifty had only `preserve` and used the deterministic route. Across all 100
cases the emitted routes were 97 `preserve`, one `guard-return`, and two
`merge-result`. The 50 Laya decisions had p50/p95 latency of 102.159/169.770 ms.
The run's seed digest is in `body-codegen-report.json`; the raw seed is not
stored.

`route_semantic_equivalence` passed 100/100 using the compiler's canonical
control-flow receipt. `route_quality` remains UNKNOWN because this experiment
has no independent readability or utility oracle. Other UNKNOWN dimensions are
resource-baseline comparison, real workflow coverage, reverse observation, and
full `int64`-domain semantics. The 25-point grid does not prove behavior at all
integer inputs.

## Resource observations

The Laya process ran on CPU with four configured threads and checkpoint
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. During the 13.348-second cohort it
used 22.62 CPU-seconds, averaging 169.46% of one core (16.95% of the 10-core
host). Its sampled peak RSS was 3,791,716,352 bytes (3.53 GiB). These values are
separate from the Gooo/Go children: those averaged 8.934% of one core, used
94,044,160 bytes peak child RSS, and completed the cohort in 13.036 seconds.

With lazy loading enabled, the first Laya request took 3,001.856 ms, hit
Gooo's three-second decision budget while the checkpoint was loading, and
deterministically fell back. The model was loaded by the time that request
returned; the next warm decision took 108.518 ms. Both raw receipts are retained as
`cold-load-timeout.json` and `laya-warmup.json`. A readiness or warm-up step
before routing requests should avoid that first-request fallback.

The Laya server warned that checkpoint value `choice:11+` had temperature
`0.10058280825614929`, outside the allowed `[0.5, 5]` range, and was clamped to
`0.5`. Confidence values for affected entries are uncalibrated; per-case
probability vectors remain visible in the local report.

## Reproduction

`observe_laya_server.py` samples the separate Laya PID using `ps` while it runs
`direct_body_codegen_cohort.py`. The checked-in GitHub Actions workflow remains
model-free and deterministic; it verifies the same receipt schema and finite
fixture behavior without downloading model weights.

An initial local attempt is retained at
[`../attempts/go1.26.5-local-only/`](../attempts/go1.26.5-local-only/). All 100
compiler receipts passed, but the generated package could not execute because
that attempt forced local Go 1.26.5 for a module requiring Go 1.27.0. The final
run selected the already-cached Go 1.27.0 toolchain and passed the generated
package check.
