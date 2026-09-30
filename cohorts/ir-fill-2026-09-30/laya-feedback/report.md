# Laya candidate-selection experiment (2026-09-30)

## Result

The warm CPU Laya service answered all **24 scored Gooo `decide` requests** (plus one excluded warm-up) with the English checkpoint at revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. Raw selections matched the best candidate under the local finite test oracle in **9/24 (37.5%)** calls. Intent-only scored **5/12 (41.7%)**; adding local deterministic score summaries scored **4/12 (33.3%)**. This four-intention sample does not establish a general effect, but it shows no benefit from score context in this run.

Candidate order mattered: the correct candidate was balanced across each of three positions. Laya selected position 1 in **14/24** calls. It selected the best candidate **6/8** times when that candidate was first, **3/8** when second, and **0/8** when third. Keep any Laya result advisory and let Gooo's deterministic finite-suite score gate choose the emitted candidate.

## Runtime and latency

- Runtime: Laya 0.3.21, Python 3.11.15, PyTorch 2.14.0, Transformers 5.17.0; CPU, four threads, English checkpoint only.
- Latency includes each `gooo decide` process, Laya round trip and model-revision health lookup: p50 **169.274 ms**, p95 nearest-rank **184.862 ms**, range **149.655–185.983 ms**.
- Selection-cohort process CPU delta and RSS values are **unavailable**: they were held in memory and lost when the post-run summary failed. I do not substitute later process snapshots for trial resource measurements.

## Scope and artifacts

These were **selection-protocol trials**, not end-to-end code-generation runs: four simple Go-like body intentions, three hand-authored candidate bodies each, and local finite test cases. The prompt showed either intent alone or pass-count summaries computed by this harness. Those summaries are not GitHub CI results. The model saw the candidate descriptions but did not emit code; no generated Go was compiled or executed.

Reproducible harness (paths, binary, endpoint, and PID are CLI/env configurable): [`run_experiment.py`](./run_experiment.py). Exact scored inputs and receipts: [`requests/`](./requests/) and [`receipts/`](./receipts/), indexed by [`trial_manifest.jsonl`](./trial_manifest.jsonl); local tests and candidate scores: [`task_oracles.json`](./task_oracles.json). The first run completed every request, then hit a summary-only Python `TypeError`; this report was rebuilt from saved outputs without rerunning Laya. See [`report.json`](./report.json), [`resource_observation.json`](./resource_observation.json), and [`service_health_observation.json`](./service_health_observation.json) for provenance and caveats. The selection cohort did not execute or externally compile generated Go. The separate fixed-compiler body-fill smoke is summarized in [`fixed-compiler-smoke/smoke_report.md`](./fixed-compiler-smoke/smoke_report.md).

## Fixed-compiler body-fill smoke (separate cohort)

Three calls with the clean compiler at commit `ec4bf3e5f4119118b501c1b45862936eb46b95b7` used evaluator `gooo/bodycodegen-int64-ast-interpreter/v2`. Laya proposed `negate` at 5/9 each time; deterministic arbitration emitted `zero` at 9/9, then passed internal typecheck and deterministic replay. Laya-decision latency p50/range was 367.162 / 366.456–381.632 ms; whole-command p50/range was 373.841 / 372.178–911.238 ms. Process CPU was 2.62 s over the n=3 warm invocation durations summed to 1.657 s (158.1% of one core); RSS started at 2017.9 MiB and peaked at 2077.2 MiB. This CPU denominator is the summed invocation durations, not total host CPU; other local work was excluded. No external `go build` or generated Go execution occurred. Exact evidence is in [`fixed-compiler-smoke/smoke_report.md`](./fixed-compiler-smoke/smoke_report.md), with raw receipts and resource samples in that directory.

## Setup note

An accidental pre-run `laya-serve --help` invocation started a default MPS service and opened an HTTPS connection to a model CDN. I terminated that process before the measured run. The actual measured server used `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` on loopback. The cache remained 2.2G with no newly modified cache files observed, but transfer bytes from the accidental invocation were not recorded, so zero network transfer is not claimed.
