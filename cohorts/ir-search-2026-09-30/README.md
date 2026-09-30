# Gooo IR search cohort

This cohort compares bounded IR body search with and without Laya, alongside the exhaustive finite-plan baseline. It uses four hand-authored `Integer -> Integer` tasks, three expression candidates per task, a training suite, and a disjoint holdout suite. The finite tests measure observed behavior only; they do not establish correctness over all int64 inputs.

The absolute-value intent explicitly uses signed two's-complement int64 wrapping. In particular, negating `MinInt64` wraps to `MinInt64`; it does not use arbitrary-precision absolute value.

## Study design

Each intent has three invocations:

1. Laya-backed `gooo body-codegen --fill-search` through a local capture proxy.
2. Deterministic no-provider `--fill-search` with identical fixture and search plan.
3. Deterministic no-provider exhaustive `--fill-plan` with identical candidates and training cases.

The cohort therefore has 12 Gooo invocations and four Laya-backed invocations. A search may make fewer than two model requests: it stops after the first training-perfect candidate, and the last remaining option is selected without a provider request. Model rounds are recorded from both the raw proxy exchange and the CLI's attempt receipt.

`plans/*.search-plan.json` and `plans/*.fill-plan.json` are the exact CLI inputs. `oracles/*.oracle.json` independently records expected values and each candidate's finite output on both suites. The holdout cases never appear in `--fill-plan` or the model's search request.

## Safety and run gate

`scripts/run_cohort.py` is inert unless invoked with `--execute`, `--binary`, and `--sha256`. It verifies the supplied binary digest before any process is started. It uses the already-installed Laya environment at `/tmp/meta-ontology-go-laya-venv-20260930` by default, forces offline CPU execution with four threads, binds the service and capture proxy to loopback, and stops only the process group it created. It does not download models or retain binary/model artifacts.

Do not run `laya-serve --help`: this entry point starts a server. The runner starts it without flags and records its own PID/process group. Do not point the runner at an externally managed server.

The runner writes a pre-execution manifest snapshot, exact CLI stdout/stderr, exact HTTP request/response bodies, event metadata, and process CPU/RSS samples to a fresh `runs/primary_run/`. These raw inputs are persisted before report derivation. `scripts/summarize_saved.py` derives results only from saved artifacts and does not contact Laya or rerun Gooo.

The committed `primary_run` reference is set only after a successful complete run. This directory must never contain a Gooo binary, virtualenv, or model cache.

## Reproduction

After the binary revision and SHA-256 are added to `manifest.json`:

```sh
python3 scripts/run_cohort.py --execute \
  --binary /path/to/clean/gooo \
  --sha256 <expected-sha256>
```

The four real Laya calls are an offline local CPU replay against the pinned installed model. No external endpoint or model download is used.

## Recorded primary run

`runs/primary_run/report.md` and `report.json` contain the twelve invocation records, six captured Laya request/response rounds, per-round choices and latency, finite training/holdout scores, and measured process resources. The run used the clean Gooo binary from revision `29d44bc778d85aee03b9af500bd83dc98f368189` and SHA-256 `f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9`; Laya health reported the pinned `english` model revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851` on CPU.

All four Laya-search outputs passed their training and holdout suites. The model's first choice was already training-perfect in two of four tasks; across six model choice rounds, two selected a training-perfect candidate. The other searches reached a training-perfect result after the candidate loop continued, including sole-candidate selection. Laya search scored eight candidates in eight attempts; deterministic no-provider search scored twelve in twelve attempts; exhaustive fill-plan scored twelve candidates.

Laya-backed CLI wall time exceeded both local no-provider baselines in each task. Per-intent ratios and times are in the report. This cohort shows no speed benefit from Laya-backed search; it is a four-task local result and does not establish general performance. CPU percentages use the owned Laya process's cumulative CPU-time samples. The eight no-provider controls each have one process sample, so their Laya-server CPU is reported as unavailable; their RSS records the resident server. The maximum RSS value is the highest periodic sample across the run, not a continuous process peak.

Search holdout results come from the emitted result receipts and match the independent finite candidate oracle. The exhaustive fill-plan command receives training cases only, so its holdout value is computed from the selected candidate's saved oracle output, not executed by that command. An exact pre-run manifest snapshot was not captured in this first run; `manifest-evidence.json` records a separately labeled post-run reconstruction whose digest matches the pre-run digest stored in run metadata. Exact fixture and plan copies plus hashes are saved for every invocation. The runner now saves the manifest bytes before future runs.
