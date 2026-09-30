# Gooo + Laya local experiment bundle

This directory contains a bounded selection study and a separate fixed-compiler body-fill smoke. It contains scripts, exact JSON requests/receipts, reports, and resource samples; it does not contain a Go binary or model weights. All experiment outputs were kept outside the repository.

The selection cohort used 24 `gooo decide` calls over four hand-authored body intentions, with and without local deterministic pass-count context and three balanced candidate positions, plus one excluded warm-up. The later compiler smoke used three direct `gooo body-codegen --fill-plan` invocations with commit `ec4bf3e5f4119118b501c1b45862936eb46b95b7`. These are separate cohorts. Local finite-suite scores are not GitHub Actions/CI outcomes.

## Start a cached CPU Laya service

Point `LAYA_VENV` to an already-installed environment containing `laya[serve]==0.3.21`. The required checkpoint must already be cached. Start the service in a separate terminal:

```sh
: "${LAYA_VENV:?Set LAYA_VENV to the installed Laya virtual environment}"
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  LAYA_HOST=127.0.0.1 LAYA_PORT=8787 LAYA_MODELS=english \
  LAYA_DEVICE=cpu LAYA_THREADS=4 LAYA_PRELOAD=1 \
  "$LAYA_VENV/bin/laya-serve"
```

Keep the service running while each runner is active. In another terminal, resolve its PID without terminating unrelated processes:

```sh
LAYA_SERVER_PID="$(lsof -tiTCP:8787 -sTCP:LISTEN)"
```

Do not pass `--help` or other flags to `laya-serve`; that entry point treats them as server invocations.

## Run the selection cohort

Supply the prebuilt Gooo binary and a fresh output directory. Paths can be set with CLI flags or environment variables (`GOOO_LAYA_EXPERIMENT_DIR`, `GOOO_BINARY`, `GOOO_LAYA_URL`, `LAYA_SERVER_PID`).

```sh
python3 run_experiment.py \
  --output-dir /tmp/gooo-laya-selection-results \
  --gooo-binary /path/to/gooo \
  --endpoint http://127.0.0.1:8787/v1/systemone \
  --server-pid "$LAYA_SERVER_PID"
python3 summarize_saved.py \
  --output-dir /tmp/gooo-laya-selection-results \
  --gooo-binary /path/to/gooo
```

The runner writes the resource snapshot before assembling the report. The summarizer works from saved artifacts and a saved health observation; it does not need the server to remain running.

## Run the fixed-compiler smoke

Provide a clean compiler binary, repository/worktree paths, and a fresh smoke output directory. The default plan and fixture are under `examples/body-codegen/`; `GOOO_REPO_ROOT`, `GOOO_BINARY`, `GOOO_LAYA_FILL_PLAN`, `GOOO_LAYA_FILL_FIXTURE`, `GOOO_LAYA_SMOKE_DIR`, `GOOO_LAYA_URL`, and `LAYA_SERVER_PID` are configurable via environment, with matching CLI arguments for the run-specific values.

```sh
python3 fixed-compiler-smoke/run_smoke.py \
  --output-dir /tmp/gooo-laya-fixed-smoke \
  --binary /path/to/fixed-gooo \
  --plan /path/to/repo/examples/body-codegen/ir-fill-clamp-plan.json \
  --fixture /path/to/repo/examples/body-codegen/ir-fill-clamp.gooo.fixture \
  --endpoint http://127.0.0.1:8787/v1/systemone \
  --server-pid "$LAYA_SERVER_PID"
python3 fixed-compiler-smoke/summarize_smoke.py \
  --output-dir /tmp/gooo-laya-fixed-smoke
```

The runner saves each exact stdout/stderr receipt and each per-call CPU/RSS/time sample before formatting the report. The report distinguishes Laya's raw proposal from Gooo's deterministic score-gated emitted candidate. The command's internal Go typecheck and deterministic replay are recorded; no external `go build` or generated-Go execution is implied.

## Recorded result files

- `report.md` / `report.json`: selection cohort summary.
- `trial_manifest.jsonl`, `requests/`, `receipts/`, and `task_oracles.json`: exact selection inputs, outputs, model/request provenance, and finite local oracle.
- `fixed-compiler-smoke/smoke_report.md` / `smoke_report.json`: three-call fixed-compiler result.
- `fixed-compiler-smoke/resource_samples.json` and per-call `.resource.json`: smoke process resource observations captured before report generation.
- `run_experiment.py`, `summarize_saved.py`, `fixed-compiler-smoke/run_smoke.py`, and `fixed-compiler-smoke/summarize_smoke.py`: configurable runners and offline summarizers.

The original selection runner completed all 24 calls but its first report aggregation raised after the calls. That cohort's interval-only CPU/RSS sample was lost and is reported as unavailable. The runner now persists those measurements before summary construction; its input-specific measurements were not rerun. The exact model caches remained outside this artifact directory.
