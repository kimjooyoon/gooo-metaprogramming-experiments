# IR body-search client concurrency observation

This cohort compares one `--fill-search` invocation for `clamp` plus one for `absolute` in two conditions: run the CLIs sequentially against an owned Laya server, then launch two independent CLIs simultaneously against a fresh owned Laya server. Each condition has one replicate. This is a small operational observation, not a general throughput or speed claim and not a new functional-intent cohort.

Condition order is fixed (sequential first) and not randomized. Each fresh Laya service is model-preloaded and health-checked before its pair, with no separate warmup requests. There is one replicate per condition, so startup and cache effects are uncontrolled. The sequential harness shuts down one capture proxy before starting the next CLI; its measured inter-CLI gap is approximately the Python server loop's default 0.5-second shutdown poll. Pair makespan therefore includes harness idle time and must not be treated as a Gooo speed benefit.

The task fixtures, search plans, and finite oracles are byte-for-byte copies from the canonical `ir-search-2026-09-30` cohort. The fixed Gooo executable is source revision `29d44bc778d85aee03b9af500bd83dc98f368189`, SHA-256 `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9`. The owned Laya process uses the already-installed `laya==0.3.21` CPU `english` model at revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, four threads, offline flags, loopback-only bindings, and the default 16-request admission cap. The existing shared model cache is reused; no model download or duplicate cache is created.

Each client gets its own capture proxy and artifact directory, even in the simultaneous condition; raw requests and responses cannot be attributed through a shared mutable invocation label. The run records per-client choice-call start/completion times, condition-level in-flight request overlap, CLI exits and stop reasons, and condition-level Laya CPU/RSS samples before, during, and after both CLI calls. RSS is reported as a sampled maximum, not a hardware peak. Per-CLI CPU is sampled and coarse. The server review in `../ir-fill-2026-09-30/laya-server-concurrency.md` found a single inference worker: overlapping HTTP transactions do not mean overlapping model forwards. Any queue interpretation will be labeled as inference from that source review plus observed request intervals, not as directly timed server queue duration.

The raw run is created only by explicit `--execute`, with exact binary SHA supplied. It starts and stops only its own loopback Laya process group. It retains raw process outputs and capture bytes before generating the report. A harness timeout is a safety stop distinct from Gooo's provider fallback. Do not interpret one bounded run as proof that Laya cannot deadlock. No binary, model, virtualenv, or cache belongs in this cohort.

Validate the saved raw hashes, pinned inputs, invocation/event counts, health snapshots, and resource endpoints without launching Gooo or Laya:

```sh
python3 scripts/validate_run.py --run-dir runs/primary_run
```

The validator independently scans all six captured choice POST bodies, recursively decoding nested objects, arrays, and JSON documents embedded in string fields. It rejects holdout field names and exact finite-oracle input/expected pairs in case-shaped objects while allowing unrelated numeric constants. The CI workflow runs regression probes for question, option, and nested-state leaks plus benign candidate constants.

Compile and execute each captured emitted Go source against its copied independent training and holdout oracle vectors (standard library only; no Gooo CLI, provider, Laya process, model, or model download):

```sh
python3 scripts/validate_emitted_go.py --run-dir runs/primary_run
```

The `ir-search-parallel-replay` workflow runs both validations and pins the Go toolchain to `go1.27.0`; generated-source validation uses `GOTOOLCHAIN=local`, `GOPROXY=off`, and `GOSUMDB=off`. The validation is finite-suite evidence, not a full `int64` proof.

Run after the local validator workload is quiet:

```sh
python3 scripts/run_parallel.py --execute \
  --binary /tmp/gooo-ir-search-20260930 \
  --sha256 f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9
```
