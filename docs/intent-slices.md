# Public intent-slice repositories

The 100-case corpus is published as ten focused public repositories. Each slice contains one declared intent, all ten lowering routes, its Laya and deterministic-fallback decision records, per-route completeness evidence, a pinned source lineage, and a CI evidence verifier.

CI validates the archived receipts and repository data. It does not call Laya or regenerate Go source in these small slices; the umbrella repository contains the compiled, replayable 100-case harness.

| Intent | Public repository | CI evidence |
| --- | --- | --- |
| Sign classification | [gooo-codegen-exp-sign-classification](https://github.com/kimjooyoon/gooo-codegen-exp-sign-classification) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-sign-classification/actions/runs/36644535090) |
| Threshold gate | [gooo-codegen-exp-threshold-gate](https://github.com/kimjooyoon/gooo-codegen-exp-threshold-gate) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-threshold-gate/actions/runs/36644569049) |
| Inclusive range | [gooo-codegen-exp-inclusive-range](https://github.com/kimjooyoon/gooo-codegen-exp-inclusive-range) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-inclusive-range/actions/runs/36644594403) |
| Parity filter | [gooo-codegen-exp-parity-filter](https://github.com/kimjooyoon/gooo-codegen-exp-parity-filter) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-parity-filter/actions/runs/36644561573) |
| Status mapping | [gooo-codegen-exp-status-mapping](https://github.com/kimjooyoon/gooo-codegen-exp-status-mapping) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-status-mapping/actions/runs/36644552591) |
| Compound gate | [gooo-codegen-exp-compound-gate](https://github.com/kimjooyoon/gooo-codegen-exp-compound-gate) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-compound-gate/actions/runs/36644586991) |
| Priority rules | [gooo-codegen-exp-priority-rules](https://github.com/kimjooyoon/gooo-codegen-exp-priority-rules) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-priority-rules/actions/runs/36644544524) |
| Clamp value | [gooo-codegen-exp-clamp-value](https://github.com/kimjooyoon/gooo-codegen-exp-clamp-value) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-clamp-value/actions/runs/36644521721) |
| Retry state | [gooo-codegen-exp-retry-state](https://github.com/kimjooyoon/gooo-codegen-exp-retry-state) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-retry-state/actions/runs/36644527503) |
| Explicit allowlist | [gooo-codegen-exp-explicit-allowlist](https://github.com/kimjooyoon/gooo-codegen-exp-explicit-allowlist) | [passed](https://github.com/kimjooyoon/gooo-codegen-exp-explicit-allowlist/actions/runs/36644580227) |

Each slice records ten code assembly patterns for one intent. Completeness in those reports refers to the recorded 25-point integer fixture domain and reachable rule clauses only; it does not claim full-domain or real-workflow coverage.
