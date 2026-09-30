# Gooo IR-search fault and coverage experiment

**Label: MOCK provider only. This is not Laya output and not a GPT-6 measurement.**

Final run: `final-mock-provider-run-2026-09-30` — 12 treatments, 11 MOCK-provider treatments, 19 captured HTTP requests. Compiler SHA-256 `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9` (source revision `29d44bc778d85aee03b9af500bd83dc98f368189`).

## Observed results

| Treatment | Requests | Selection | Training | Holdout | Observation |
|---|---:|---|---:|---:|---|
| `unconfigured_fallback` | 0 | zero | 3/3 | 4/4 | No provider requests; deterministic fallback reaches the training-perfect candidate. |
| `http_503_fallback` | 2 | zero | 3/3 | 4/4 | 503 produces PROVIDER_HTTP_ERROR fallback, then a later valid choice can continue. |
| `malformed_json_fallback` | 2 | zero | 3/3 | 4/4 | Malformed JSON produces PROVIDER_RESULT_INVALID fallback. |
| `missing_choice_fallback` | 2 | zero | 3/3 | 4/4 | Missing answer produces PROVIDER_RESULT_INVALID fallback. |
| `unknown_choice_fallback` | 2 | zero | 3/3 | 4/4 | Unknown candidate ID produces PROVIDER_RESULT_INVALID fallback. |
| `failure_feedback_privacy` | 2 | zero | 3/3 | 4/4 | Second request includes failed training inputs only; holdout fields/inputs absent. |
| `repeated_tried_choice` | 2 | zero | 3/3 | 4/4 | Repeated ID is invalid because it was removed; attempt trace contains no duplicate candidate. |
| `invalid_expression_then_valid` | 2 | zero | 3/3 | 4/4 | Malformed Go expression is rejected before scoring; search continues. |
| `type_mismatch_then_valid` | 2 | zero | 3/3 | 4/4 | Bool expression is rejected for int64 before scoring; search continues. |
| `training_perfect_holdout_failure` | 1 | identity | 3/3 | 0/4 | Identity is 3/3 on nonnegative training, then 0/4 on negative holdout; stop reason remains training-perfect. |
| `provider_budget_timeout` | 1 | zero | 3/3 | 4/4 | One stalled request reaches the 8,000 ms budget and search falls back. |
| `cancel_inflight_provider` | 1 | — | — | — | Runner SIGTERM is configured after 350 ms; the CLI exits -15 and one MOCK request is captured. Saved timing does not prove the request remained in flight at the signal instant. |

## Pilot retained but superseded

The first raw run at `runs/mock-provider-run-2026-09-30/` is retained (12 invocations, 19 requests, about 13.2 seconds). Its training-perfect/holdout-failure probe was incorrectly configured: the zero-expression candidate remained correct on that holdout. The corrected final probe uses identity with nonnegative training inputs and negative disjoint holdout inputs. Pilot outputs are excluded from the result table and claims.

## Interpretation and limits

The frozen compiler handled these injected failure modes as recorded, and training success did not imply holdout success. The deterministic finite search and its receipts support only the twelve synthetic treatments against one int64 fixture. They do not establish Laya quality, model success rates, domain accuracy, or correctness beyond the finite cases. The HTTP mock binds loopback only; the no-provider case unsets the Laya URL and API key. No model server or model call was used. The cancellation treatment records runner-configured SIGTERM, process exit -15, and one mock request; timing does not establish that the request was still in flight at the signal instant.

## Reproduction and validation

Runner: `scripts/run_fault_cohort.py`. It requires explicit `--execute`, the pinned binary, and the exact SHA-256. Use a fresh `--run-id` to preserve existing evidence. `scripts/validate_saved.py` checks saved output only and performs no compiler invocation, model call, or network request.
