# IR body filling: semantics, selection, and scheduling

These experiments extend the earlier 100-case matrices. They keep their denominators separate: 12 original composition cases, focused binding probes, 24 real-Laya selection trials, three real-Laya body-fill calls, eight MOCK scheduling treatments, and four no-model scaling treatments with five repeats each. Repeated calls are not counted as new intentions.

## Findings

| Question | Evidence | Result |
| --- | --- | --- |
| Does a reported body score agree with generated Go? | Original 12-case before/after composition corpus; independently compiled seen/held-out tests | Fixed precedence and minimum-int64 behavior. One original candidate set correctly rejects an unused local; its revised valid binding plans are separate probes. |
| Does a 100% supplied-suite score imply complete intent? | Square intention, identity vs square candidates, supplied inputs 0 and 1 | Both tie on 2/2 supplied cases. Identity fails all four held-out inputs. This limitation remains visible after the compiler repair. |
| Does Laya pick the best candidate? | 24 calls: 4 intentions × 2 context treatments × 3 candidate rotations | 9/24 correct raw selections; intent-only 5/12, local-score context 4/12. No general statistical effect is established by this small sample. |
| Does Gooo correct an inferior Laya choice? | Three direct calls through repaired body-fill compiler | Raw proposal 5/9; emitted candidate 9/9 in all three calls. These are bounded evaluator scores; this smoke did not independently execute generated Go. |
| Is provider waiting bounded? | Controlled MOCK service | Delayed provider falls back around 8.02 seconds. This bounds the provider wait, not the whole compilation operation. |
| Can Gooo clients overlap? | Two independent CLI processes and a concurrent MOCK provider | Two requests overlap. This does not establish concurrent inference inside real Laya. |
| What does deterministic scoring cost? | Candidate counts 2/16 × case counts 9/4096, five repeats each | Whole CLI medians 4.75–27.09 ms; largest plan scoring median 17.45 ms. One intention, no model. |

The compiler repair is [meta-ontology-go PR #1093](https://github.com/kimjooyoon/meta-ontology-go/pull/1093), clean source commit `ec4bf3e5f4119118b501c1b45862936eb46b95b7`. Historical baseline artifacts identify `2fc19ea5b094f424f550e2b0a9ebe6477759d1a2`. The baseline is retained as evidence of discovered defects, not offered as correct behavior.

## Artifacts

- [Composition corpus and replay](composition/README.md): original before/after outcomes, exact fixtures, compiled Go checks, and separate revised binding probes.
- [Real Laya study](laya-feedback/README.md): configurable runners, exact requests/receipts, model identity, and reporting incident.
- [Fixed compiler smoke](laya-feedback/fixed-compiler-smoke/smoke_report.md): three calls, v2 evaluator, CPU/RSS samples and raw/final selections.
- [MOCK scheduling experiments](scheduling/README.md): delays, fallback, repeatability and process overlap; no model quality claims.
- [Installed Laya server review](laya-server-concurrency.md): inference uses one worker; admission defaults to 16 requests, and client cancellation does not guarantee that inference stops.
- [Deterministic scaling](scaling/README.md): candidate/test-count costs and compressed complete stdout receipts.

The actual model was `laya-rl-agent`, revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, CPU with four threads. The selection cohort's p50/p95 was 169.274/184.862 ms including the CLI. The three-call body-fill smoke's model-decision median/range was 367.162 ms / 366.456–381.632 ms. These request shapes and timings must not be pooled.

Only the three-call smoke retained CPU/RSS samples: 2.62 server CPU-seconds over 1.657 summed invocation wall-seconds, about 158.1% of one core, sampled peak 2077.2 MiB. This is server-process utilization, not the increase in total host utilization. The 24-call cohort's resource samples were lost during its first report failure and remain unavailable. No inference was rerun to manufacture missing observations.

## Development direction

Current body filling scores every finite candidate before asking Laya. The correct candidate is already known when the model is consulted, and this cohort establishes neither an accuracy improvement nor a speedup. Keep raw model choice, deterministic correction, candidate-set adequacy, and held-out behavior as distinct measurements.

A useful next experiment would let Laya rank typed candidate families *before* exhaustive testing, then test one candidate at a time with a fixed search budget. Compare against deterministic ordering on identical intentions, candidate sets and budgets. Measure candidates tested until success, total generation latency, CPU time, invalid typed choices, supplied-suite success, and independently executed held-out success. Retain failed traces for the next TDD round; keep final held-out tests out of model feedback. A CI result can inform a later revision only when its tested source/plan digest is retained. The local score feedback in this bundle is not a CI observation.

Expand to multiple typed holes only after the scorer/emitter agreement remains stable. Conditions, assignments, and return expressions can be separate typed choices, with scope dependencies supplied explicitly. Measure how many declared behaviors the assembled function implements; do not infer the percentage of unstated human intent from AST coverage or one passing test suite.

For scheduling, bound outstanding model requests to the measured server capacity and retain a deterministic path when its budget expires. Parallel Gooo compilation can proceed independently, but the installed Laya server's single inference worker makes a burst of model requests a queue. A cancellation/queue-load experiment on the real service remains to be measured before claiming that more client parallelism improves throughput.

## Reproduction and storage

The new CI workflow replays the fixed composition corpus with a pinned compiler and checks the evidence manifest. Real-model runs remain optional local experiments. Existing 100-case workflows retain their previous pins and denominators.

No compiler executables, model weights, virtual environments, or caches are included. Exact raw records retain original local paths as provenance; runnable scripts accept replacement paths. Timing fields describe the recorded host, not expected CI performance.
