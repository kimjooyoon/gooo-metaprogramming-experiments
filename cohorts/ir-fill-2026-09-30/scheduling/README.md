# Scheduling and failure experiments (MOCK only)

Eight treatments exercise immediate and delayed replies, fixed binary versus `go run`, HTTP 503, two independent CLI processes, the eight-second provider budget, and repeatability. All calls use the pinned repaired compiler `ec4bf3e5f4119118b501c1b45862936eb46b95b7` and owned ephemeral loopback endpoints. No real Laya model was used.

- Successful MOCK responses propose `identity` in `mode=laya`; Gooo emits `zero` because it scores 9/9 instead of 5/9.
- A 450 ms mock delay yielded about 461 ms provider wait. Final code is emitted after the synchronous decision returns.
- Two distinct CLI processes overlapped at the threaded mock provider (maximum two active requests), both finishing in about 935 ms with a 900 ms mock delay.
- HTTP 503 produced `deterministic_fallback` with `PROVIDER_HTTP_ERROR`.
- An 8.35-second mock delay produced `PROVIDER_UNAVAILABLE` fallback; the CLI finished around 8.02 seconds. The mock's response attempt finished later, around 8.36 seconds. Client timeout does not stop provider computation.
- Fixed replies for the same plan reproduced non-null selected-candidate, generated-source, request and suite identities.

See `report.json`, `summary.json`, and `captures/` for complete request payloads, stdout/stderr, PIDs and timestamps. No deadlock was observed in these bounded trials; this is not a proof of deadlock freedom. The [installed real-server review](../laya-server-concurrency.md) shows that Laya itself serializes inference; mock overlap must not be presented as model throughput.

## Reproduce

Use a clean checkout and binary of the pinned source revision, then a fresh output directory:

```sh
python3 run_experiments.py \
  --fixed-binary /absolute/path/to/gooo \
  --worktree /absolute/path/to/meta-ontology-go \
  --fixture /absolute/path/to/this/directory/fixture.gooo \
  --plan /absolute/path/to/this/directory/plan.json \
  --out-dir /tmp/gooo-scheduling-new
```

The script starts and closes only its own ephemeral MOCK servers. It asserts complete receipt fields and expected modes before accepting measurements. A discarded first harness draft read the wrong JSON nesting and produced null fields; those draft figures are not part of this bundle. The published observations come from the corrected rerun with raw captures saved before reporting.
