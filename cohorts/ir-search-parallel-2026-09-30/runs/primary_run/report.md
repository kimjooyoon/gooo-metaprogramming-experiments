# IR body-search client concurrency observation

Run: `primary_run`
Binary revision: `29d44bc778d85aee03b9af500bd83dc98f368189`
Binary SHA-256: `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9`
Laya: `Laya 0.3.21` / `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` / CPU / 4 threads

One replicate per condition; two fixed intents (`clamp`, `absolute`) per condition. This is an observed-run comparison only, not a statistical or general speed claim.

## Conditions

| Condition | CLI makespan ms | Actual Laya choice calls | Max overlapping choice HTTP calls | Laya process CPU s | Laya CPU (% one core over resource window) | Resource window s | Max sampled server RSS MiB | Both CLIs exit 0 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| sequential | 1454.0 | 3 | 1 | 1.92 | 95.9 | 2.001 | 2096.7 | yes |
| simultaneous | 867.5 | 3 | 2 | 1.86 | 131.4 | 1.415 | 2076.9 | yes |

## Invocation outcomes

| Condition | Intent | Selected | Training | Oracle holdout | Attempts | Laya choices | Final selection method | Wall ms | Stop reason |
|---|---|---|---|---|---:|---:|---|---:|---|
| sequential | clamp | zero | 3/3 | 4/4 | 1 | 1 | laya | 335.0 | TRAINING_SUITE_PASSED |
| sequential | absolute | negate | 3/3 | 4/4 | 3 | 2 | sole_remaining_candidate | 595.5 | TRAINING_SUITE_PASSED |
| simultaneous | clamp | zero | 3/3 | 4/4 | 1 | 1 | laya | 540.2 | TRAINING_SUITE_PASSED |
| simultaneous | absolute | negate | 3/3 | 4/4 | 3 | 2 | sole_remaining_candidate | 865.8 | TRAINING_SUITE_PASSED |

## Invocation timing decomposition

Wall starts at the recorded launch marker immediately before `Popen` (after the barrier for simultaneous launches) and ends when the CLI process completes. `body_search.total_ms` and `decision_latency_ms` are Gooo report timings. First POST entry is when the per-client capture proxy begins handling the first Laya choice request.

| Condition | Intent | CLI wall ms | body_search.total_ms ms | body_search decision_latency_ms ms | Sum attempt decision_latency_ms | Wall minus body search ms | Wall minus decision latency ms | First choice POST after launch marker ms | Provider budget used / budget ms | Harness timeout s |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sequential | clamp | 335.01 | 323.98 | 323.51 | 323.51 | 11.03 | 11.50 | 11.14 | 323.51 / 8000.00 | 60.00 |
| sequential | absolute | 595.49 | 584.67 | 584.00 | 584.00 | 10.81 | 11.49 | 11.94 | 584.00 / 8000.00 | 60.00 |
| simultaneous | clamp | 540.16 | 529.32 | 528.79 | 528.79 | 10.84 | 11.37 | 12.03 | 528.78 / 8000.00 | 60.00 |
| simultaneous | absolute | 865.80 | 856.25 | 855.54 | 855.54 | 9.55 | 10.26 | 10.69 | 855.53 / 8000.00 | 60.00 |

## Harness and pair timing

| Condition | CLI pair makespan ms | Sum per-CLI wall ms | Longest one CLI ms | Launch spacing ms | Gap after earlier CLI completes ms (negative means overlap) |
|---|---:|---:|---:|---:|---:|
| sequential | 1454.0 | 930.5 | 595.5 | 858.5 | 523.5 |
| simultaneous | 867.5 | 1406.0 | 865.8 | 1.7 | -538.5 |

## Request intervals

| Condition | Intent | Request seq | Selected candidate | Proxy round ms | Start UTC | Complete UTC |
|---|---|---:|---|---:|---|---|
| sequential | clamp | 1 | zero | 317.9 | 2026-09-30T04:38:14.444968+00:00 | 2026-09-30T04:38:14.762869+00:00 |
| sequential | absolute | 1 | zero | 248.6 | 2026-09-30T04:38:15.304265+00:00 | 2026-09-30T04:38:15.552837+00:00 |
| sequential | absolute | 3 | identity | 329.7 | 2026-09-30T04:38:15.555124+00:00 | 2026-09-30T04:38:15.884822+00:00 |
| simultaneous | clamp | 1 | zero | 524.5 | 2026-09-30T04:38:18.873092+00:00 | 2026-09-30T04:38:19.397583+00:00 |
| simultaneous | absolute | 1 | zero | 278.6 | 2026-09-30T04:38:18.873416+00:00 | 2026-09-30T04:38:19.152043+00:00 |
| simultaneous | absolute | 3 | identity | 570.5 | 2026-09-30T04:38:19.154946+00:00 | 2026-09-30T04:38:19.725399+00:00 |

## Measurement and interpretation

- Gooo CLI makespan is measured from earliest CLI launch to latest CLI completion within each pair. Per-CLI wall times and exit/fallback/stop details are retained in `report.json` and raw invocation artifacts.
- Across 6 raw selection requests, the recursive held-out-field/case audit found 0 held-out fields or exact holdout input/expected pairs. Holdout scores in this report are recomputed from the copied finite oracle after final selection.
- Proxy request intervals measure outstanding loopback HTTP transactions, not the model-forward interval or server queue delay. The installed server review documents one inference worker and a separate admission cap of 16. If request intervals overlap, the work is serialized at the inference worker; the queue wait itself was not instrumented.
- Condition order was fixed as sequential then simultaneous and was not randomized. Each condition used a fresh owned Laya service that was preloaded and health-checked before the CLI pair; there were no separate warmup requests. With one replicate per condition, order, model/cache state, and other cold-start effects are uncontrolled and can contribute to observed timing differences.
- The sequential pair has about a 0.5 s gap between CLI processes because each invocation shuts down its capture proxy before the next CLI launches. The runner calls `CaptureProxy.stop()` per invocation, and that method calls `ThreadingHTTPServer.shutdown()`; the observed 523.5 ms gap is consistent with the server loop's 0.5 s default poll interval. This is harness teardown, not active Gooo CLI work. The 1454.0 ms vs 867.5 ms pair makespans must not be described as a 40% Gooo speed benefit. Sequential per-CLI wall durations sum to 930.5 ms; the longest simultaneous CLI is 865.8 ms, about 7% lower in this single observation, which is still no causal or general speed claim.
- The prior canonical cohort's first Laya-backed invocation had a 534.5 ms harness-window excess over summed decision latency; its three later windows were +6.7, +6.3, +6.7 ms. The prior window ends after sampler shutdown/join and stdout/stderr persistence; the excess cause is unisolated. See `../ir-search-2026-09-30/runs/primary_run/report.json` (SHA-256 `14b3e98d48663292751e3a437c9d74e57bee7fb381731da159875841a94cc24d`).
- CPU uses sampled process cumulative `ps` CPU-time deltas divided by the separate condition resource window shown in the table. That window starts at the sampler's pre-CLI sample and ends after post-invocation health sampling; it is not the CLI pair makespan. RSS is maximum sampled RSS, not an OS lifetime peak. Laya is measured condition-wide while the service remains alive; CLI samples are per-process and coarse. Resource samples and counts are in each condition directory.
- This is one pair per condition on one host. No statistical performance claim or deadlock-freedom claim is made. A completed bounded run only shows these invocations returned or hit their recorded harness/provider outcome.
- Raw stdout/stderr, exact request/response bodies, timestamps, hashes, process samples, condition health snapshots, and source copies are retained under `conditions/`. No model, virtualenv, or binary is copied into the cohort.
