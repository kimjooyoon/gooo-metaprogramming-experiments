# Gooo IR body-search cohort results

Run: `primary_run`  
Binary SHA-256: `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9`  
Source revision: `29d44bc778d85aee03b9af500bd83dc98f368189`

This report describes finite training and disjoint holdout suites. It is not a proof over all int64 inputs.

## Per-intent outcomes

| Intent | Variant | Selected | Training | Holdout | Search attempts / scored candidates | Laya rounds | Stop reason | Wall ms | Laya server CPU (one core %) | Laya server sampled RSS MiB |
|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| clamp | laya_fill_search | zero | 3/3 | 4/4 | 1 / 1 | 1 | TRAINING_SUITE_PASSED | 967.3 | 52.72 | 1673.4 |
| clamp | deterministic_fill_search | zero | 3/3 | 4/4 | 3 / 3 | 0 | TRAINING_SUITE_PASSED | 7.0 | N/A | 1688.8 |
| clamp | exhaustive_fill_plan | zero | 3/3 | 4/4 | — / 3 | 0 |  | 6.7 | N/A | 1688.8 |
| absolute | laya_fill_search | negate | 3/3 | 4/4 | 3 / 3 | 2 | TRAINING_SUITE_PASSED | 588.1 | 187.06 | 1727.7 |
| absolute | deterministic_fill_search | negate | 3/3 | 4/4 | 3 / 3 | 0 | TRAINING_SUITE_PASSED | 6.6 | N/A | 1753.5 |
| absolute | exhaustive_fill_plan | negate | 3/3 | 4/4 | — / 3 | 0 |  | 6.3 | N/A | 1753.5 |
| piecewise | laya_fill_search | seven | 3/3 | 4/4 | 1 / 1 | 1 | TRAINING_SUITE_PASSED | 240.4 | 145.58 | 1754.0 |
| piecewise | deterministic_fill_search | seven | 3/3 | 4/4 | 3 / 3 | 0 | TRAINING_SUITE_PASSED | 6.3 | N/A | 1754.0 |
| piecewise | exhaustive_fill_plan | seven | 3/3 | 4/4 | — / 3 | 0 |  | 7.4 | N/A | 1754.0 |
| compound-precedence | laya_fill_search | hundred | 4/4 | 4/4 | 3 / 3 | 2 | TRAINING_SUITE_PASSED | 616.2 | 181.76 | 1754.9 |
| compound-precedence | deterministic_fill_search | hundred | 4/4 | 4/4 | 3 / 3 | 0 | TRAINING_SUITE_PASSED | 6.5 | N/A | 1785.0 |
| compound-precedence | exhaustive_fill_plan | hundred | 4/4 | 4/4 | — / 3 | 0 |  | 6.1 | N/A | 1785.0 |

## Totals

- Gooo invocations: 12 / 12 planned.
- Laya-backed Gooo invocations: 4 / 4 planned.
- Captured Laya choice rounds: 6.
- Successful invocations: 12 / 12.
- First Laya choices that already scored 100% on training: 2 / 4.
- Laya model rounds that selected a training-perfect candidate: 2 / 6.
- Final Laya-search outputs that scored 100% on training: 4 / 4; holdout: 4 / 4.
- Laya search attempted/scored 8/8 candidates. The exhaustive plans scored 12 candidates.
- No-provider search attempted/scored 12/12 candidates.
- Search-selected holdout actuals matched the independent finite oracle in 4 / 4 Laya runs.
- Per-intent measured wall costs and ratios:
  - `clamp`: Laya search 967.3 ms; deterministic search 7.0 ms; exhaustive fill plan 6.7 ms; Laya/offline-search ratio 137.4x; Laya/exhaustive ratio 143.3x.
  - `absolute`: Laya search 588.1 ms; deterministic search 6.6 ms; exhaustive fill plan 6.3 ms; Laya/offline-search ratio 89.6x; Laya/exhaustive ratio 93.5x.
  - `piecewise`: Laya search 240.4 ms; deterministic search 6.3 ms; exhaustive fill plan 7.4 ms; Laya/offline-search ratio 38.0x; Laya/exhaustive ratio 32.4x.
  - `compound-precedence`: Laya search 616.2 ms; deterministic search 6.5 ms; exhaustive fill plan 6.1 ms; Laya/offline-search ratio 94.4x; Laya/exhaustive ratio 100.5x.
- A speed benefit was not observed in this cohort: Laya-backed wall time exceeded both no-provider baselines in 4 of 4 intents. The four-intent result is descriptive and does not establish general performance.
- Maximum sampled RSS of the owned Laya process across all 24 saved process sample rows: 1785.0 MiB (compound-precedence/deterministic_fill_search). This is the highest recorded sample, not a continuous peak measurement.
- No exact pre-run manifest snapshot was saved. The post-run reconstruction has SHA-256 `626b6122ed597fe64066a9b4a0dc366e8f9795c6fae126ea2d206fe51bbff22c`, matching the digest recorded before execution; the reconstruction is labeled separately from raw evidence. Each invocation does retain its exact fixture and plan bytes with hashes.
- CPU percentages refer to the owned Laya server process: one-core utilization is process CPU-time delta divided by invocation wall time; host-normalized process utilization divides that by the logical CPU count. Controls made no provider call and had one process sample each, so server CPU is shown as N/A; their RSS values describe the resident server sample, not the Gooo command's memory.
- Search holdout outputs are checked against the independent oracle. For exhaustive `--fill-plan`, holdout values are computed from the selected candidate's independent oracle output because the command receives training cases only; this is not an executed holdout measurement.
