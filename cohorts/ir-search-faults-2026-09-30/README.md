# Gooo IR-search fault and coverage cohort

This cohort measures how a pinned Gooo `body-codegen --fill-search` binary responds to controlled provider faults and finite-suite edge cases. Every configured provider is a tiny loopback **MOCK** responder. This is not a Laya or GPT-6 evaluation; no model server, model download, or model call is used.

The binary is `/tmp/gooo-ir-search-20260930`, clean revision `29d44bc778d85aee03b9af500bd83dc98f368189`, SHA-256 `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9`. The inputs are copied from the neighboring `ir-search-2026-09-30` cohort; the final holdout-trap treatment changes only its declared finite training and holdout cases. All generated artifacts are stored within this cohort.

## Final recorded run

[Final report](runs/final-mock-provider-run-2026-09-30/report.md) and [machine-readable report](runs/final-mock-provider-run-2026-09-30/report.json) summarize 12 treatments and 19 captured mock HTTP requests. The machine-readable report includes hashes for the saved inputs, raw exchanges, stdout/stderr, events, and invocation receipts. Exact plans, fixtures, compiler stdout/stderr, raw request and response bodies, request events, and per-invocation receipts are under the same run directory.

Highlights:

- Missing provider, HTTP 503, malformed JSON, missing answer, and unknown choice exercised deterministic fallback paths.
- A second request included only prior failed training-case feedback. The holdout suite and holdout-only inputs did not appear in provider state.
- Repeated selection of a consumed candidate was rejected; the saved attempt trace contains no duplicate candidate.
- Malformed syntax and a `bool` expression for an `int64` output were rejected before finite scoring; each search continued.
- A candidate with 3/3 training matches scored 0/4 on its disjoint holdout, while the search stopped on `TRAINING_SUITE_PASSED`.
- One stalled provider call reached the compiler's 8,000 ms provider budget. The runner was configured to send SIGTERM after 350 ms; the CLI exited with -15 and one MOCK request was captured. Saved timing does not prove the request was still in flight at the signal instant.

These are finite observations from one hand-authored `int64` clamp fixture. They do not establish general domain coverage, correctness outside the listed values, generated-package runtime behavior, Laya performance, or model quality.

## Superseded pilot

[runs/mock-provider-run-2026-09-30](runs/mock-provider-run-2026-09-30/PILOT-SUPERSEDED.md) is retained and clearly labeled. It also contains 12 invocations and 19 mock requests, but its intended holdout-failure case was incorrectly configured: the chosen zero expression scored 4/4. The pilot is excluded from final report claims. The corrected run uses identity on nonnegative training inputs and negative holdout inputs.

## Reproduction and saved-artifact validation

`run_fault_cohort.py` requires the explicit `--execute` switch, the exact frozen compiler digest, and a new run ID if preserving existing evidence. It does not contact a Laya server; provider treatments bind only a loopback mock. The timeout treatment has one intentional 8-second wait, not repeated slow trials.

```sh
python3 scripts/run_fault_cohort.py --execute \
  --binary /tmp/gooo-ir-search-20260930 \
  --sha256 f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9 \
  --run-id <fresh-run-id>
```

`scripts/validate_saved.py` is the short offline validation target for CI: it checks exact source-revision and compiler-digest pins, binds `invocations.json` and per-treatment receipts to decoded `stdout.raw` reports, binds provider receipts to `events.jsonl` and request/response hashes, and scans each complete raw request for holdout field names and exact input/expected pairs (recursively decoding JSON strings). It performs no compiler run, provider call, or network request. Three in-memory probes cover summary tampering, JSON hidden in another field, and legitimate unrelated constants. Add `--write-report` only when intentionally regenerating derived reports.

```sh
python3 scripts/validate_saved.py --run-dir runs/final-mock-provider-run-2026-09-30
python3 -m unittest discover -s scripts -p 'test_validate_saved.py' -v
```

The source pin is fixed at revision `29d44bc778d85aee03b9af500bd83dc98f368189`; this cohort does not test later provider-operation changes.
