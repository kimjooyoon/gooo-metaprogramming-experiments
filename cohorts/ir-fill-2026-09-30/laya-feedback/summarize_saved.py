#!/usr/bin/env python3
"""Summarize already-saved Laya trials. Does not call Laya or Gooo."""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import statistics

DEFAULT_ROOT = pathlib.Path(os.environ.get('GOOO_LAYA_EXPERIMENT_DIR', '/tmp/gooo-luna-laya-feedback-20260930'))
DEFAULT_GOOO = pathlib.Path(os.environ.get('GOOO_BINARY', '/tmp/gooo-luna-body-experiments-20260930/gooo'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', default=str(DEFAULT_ROOT))
parser.add_argument('--gooo-binary', default=str(DEFAULT_GOOO))
args = parser.parse_args()
ROOT = pathlib.Path(args.output_dir).expanduser().resolve()
GOOO = pathlib.Path(args.gooo_binary).expanduser().resolve()
rows = [json.loads(line) for line in (ROOT / 'trial_manifest.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]

def file_sha(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def group_summary(group):
    correct = sum(row['correct_by_finite_oracle'] for row in group)
    selected_positions = collections.Counter(int(row['selected_id'].split('_')[1]) for row in group if row['selected_id'])
    winners_by_position = collections.Counter(
        next(i for i in range(1, 4) if f'candidate_{i}' in row['best_candidate_ids'])
        for row in group
    )
    correct_by_winner_position = collections.Counter(
        next(i for i in range(1, 4) if f'candidate_{i}' in row['best_candidate_ids'])
        for row in group if row['correct_by_finite_oracle']
    )
    return {
        'calls': len(group),
        'valid_laya': sum(row['mode'] == 'laya' for row in group),
        'correct': correct,
        'accuracy_percent': round(100 * correct / max(1, len(group)), 1),
        'selected_candidate_position_counts': {str(i): selected_positions[i] for i in range(1, 4)},
        'best_candidate_position_counts': {str(i): winners_by_position[i] for i in range(1, 4)},
        'correct_by_best_position': {str(i): correct_by_winner_position[i] for i in range(1, 4)},
    }

latencies = sorted(row['latency_ms'] for row in rows if row['mode'] == 'laya' and row['latency_ms'] is not None)
nearest_rank_95 = latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None
by_context = {
    context: group_summary([row for row in rows if row['context'] == context])
    for context in ('intent_only', 'local_test_score_feedback')
}
by_task_context = []
for task in sorted({row['task'] for row in rows}):
    for context in ('intent_only', 'local_test_score_feedback'):
        group = sorted(
            (row for row in rows if row['task'] == task and row['context'] == context),
            key=lambda row: row['candidate_order_offset'],
        )
        summary = group_summary(group)
        by_task_context.append({
            'task': task,
            'context': context,
            **summary,
            'selected_candidates_by_order_offset': [row['selected_candidate'] for row in group],
        })

request_paths = sorted((ROOT / 'requests').glob('*.json'))
receipt_paths = sorted((ROOT / 'receipts').glob('*.stdout.json'))
request_file_hashes = {str(path.relative_to(ROOT)): file_sha(path) for path in request_paths}
receipt_file_hashes = {str(path.relative_to(ROOT)): file_sha(path) for path in receipt_paths}
manifest_rows = len(rows)
request_digests = [row['request_sha256'] for row in rows]
revision_set = sorted({row['model_revision'] for row in rows if row['model_revision']})
model_set = sorted({row['model'] for row in rows if row['model']})
health_record = json.loads((ROOT / 'service_health_observation.json').read_text(encoding='utf-8'))
health = health_record['health']
binary_sha = file_sha(GOOO)
manifest_completed_local = dt.datetime.fromtimestamp((ROOT / 'trial_manifest.jsonl').stat().st_mtime, dt.timezone.utc).isoformat()

# These two ps snapshots were captured from the owned server immediately
# before harness creation and after the harness completed. The first harness
# failed only while aggregating after all requests; its in-memory interval-only
# resource sample was therefore not persisted. Keep the observed interval and
# limitation explicit instead of labeling it trial-exclusive.
resource_observation = {
    'server_pid': 61962,
    'server_bind': '127.0.0.1:8787',
    'selection_trial_cpu_delta_seconds': None,
    'selection_trial_rss_before_mib': None,
    'selection_trial_peak_rss_mib': None,
    'selection_trial_rss_after_mib': None,
    'availability': 'Unavailable for the scored trial window. The run harness sampled process CPU/RSS in memory, but its post-run summary raised after all requests completed, before it persisted the resource snapshot. Later point-in-time ps observations are intentionally not attributed to the experiment.',
    'measurement_method_intended': 'macOS ps cumulative CPU time and RSS samples every 0.25 seconds.',
}
(ROOT / 'resource_observation.json').write_text(json.dumps(resource_observation, indent=2) + '\n', encoding='utf-8')

report = {
    'experiment': 'Gooo validated typed-decision selection trials through real loopback Laya requests',
    'manifest_completed_local_utc': manifest_completed_local,
    'calls': {
        'warmup': 1,
        'scored_trials': manifest_rows,
        'total_actual_laya_calls': manifest_rows + 1,
        'provider_valid_trials': sum(row['mode'] == 'laya' for row in rows),
        'design': '4 intentions x 2 context modes x 3 candidate-position rotations; one call per cell; shuffled with seed 20260930',
        'intentions': sorted({row['task'] for row in rows}),
    },
    'runtime': {
        'host': 'Apple Silicon macOS arm64, 10 logical CPUs',
        'laya_package': '0.3.21',
        'python': '3.11.15',
        'torch': '2.14.0',
        'transformers': '5.17.0',
        'device': 'cpu',
        'threads': 4,
        'models_loaded': health.get('loaded'),
        'model': model_set,
        'revision': revision_set,
        'hf_hub_offline': True,
        'transformers_offline': True,
        'service_health_observation': health, 'service_health_observation_file': str(ROOT / 'service_health_observation.json'),
    },
    'protocol': {
        'request_schema': 'gooo/typed-decision-request/v1',
        'receipt_schema': 'gooo/typed-decision-receipt/v1',
        'command': f'{GOOO} decide --json REQUEST.json',
        'binary': str(GOOO),
        'baseline_binary_sha256': binary_sha,
        'baseline_build': 'go1.27.0 darwin/arm64, vcs.revision=2fc19ea5b094f424f550e2b0a9ebe6477759d1a2, vcs.modified=false',
        'trial_type': 'Selection-only calls through the validated Gooo decide protocol; no end-to-end body-codegen or generated-Go execution.',
    },
    'latency': {
        'measurement': 'Wall time around each gooo decide process, including request, local revision health lookup and CLI process startup.',
        'n': len(latencies),
        'per_call_sum_ms': round(sum(latencies), 3),
        'p50_ms': round(statistics.median(latencies), 3) if latencies else None,
        'p95_ms_nearest_rank': round(nearest_rank_95, 3) if nearest_rank_95 is not None else None,
        'min_ms': round(min(latencies), 3) if latencies else None,
        'max_ms': round(max(latencies), 3) if latencies else None,
        'warmup_latency': 'excluded; the warm-up output is preserved but the harness did not persist its timing after the post-run report bug.',
    },
    'accuracy': {
        'correct_overall': sum(row['correct_by_finite_oracle'] for row in rows),
        'scored_trials': manifest_rows,
        'accuracy_percent': round(100 * sum(row['correct_by_finite_oracle'] for row in rows) / max(1, manifest_rows), 1),
        'by_context': by_context,
        'by_task_context': by_task_context,
        'candidate_position_effect': {
            'interpretation': 'Best-candidate position is balanced 8 times across each position when both contexts are combined. Raw selection was position 1 in 14/24 calls. Correct selections by best-candidate position were 6/8 at position 1, 3/8 at position 2, and 0/8 at position 3.',
            'selected_candidate_position_counts_overall': {
                str(i): sum(row['selected_id'] == f'candidate_{i}' for row in rows)
                for i in range(1, 4)
            },
            'correct_by_best_position_overall': {
                str(i): sum(row['correct_by_finite_oracle'] and f'candidate_{i}' in row['best_candidate_ids'] for row in rows)
                for i in range(1, 4)
            },
            'best_position_trials_overall': {
                str(i): sum(f'candidate_{i}' in row['best_candidate_ids'] for row in rows)
                for i in range(1, 4)
            },
        },
        'interpretation': 'A choice counts correct if it reaches the highest deterministic local finite-suite pass count. Score context yielded 4/12 versus 5/12 intent-only in this small run; this is descriptive, not statistical evidence. Do not trust raw Laya selections to beat the deterministic score gate.',
    },
    'resources': resource_observation,
    'provenance': {
        'warmup_request': str(ROOT / 'warmup_request.json'),
        'warmup_receipt': str(ROOT / 'warmup_stdout.json'),
        'trial_manifest': str(ROOT / 'trial_manifest.jsonl'),
        'oracle_file': str(ROOT / 'task_oracles.json'),
        'raw_requests': str(ROOT / 'requests'),
        'raw_receipts': str(ROOT / 'receipts'),
        'trial_manifest_rows': manifest_rows,
        'raw_request_files': len(request_paths),
        'raw_trial_receipts': len(receipt_paths),
        'all_trial_request_sha256_present': all(request_digests),
        'unique_gooo_request_digests': len(set(request_digests)),
        'model_revision_consistent': len(revision_set) == 1,
        'request_file_hashes_sha256': request_file_hashes,
        'receipt_file_hashes_sha256': receipt_file_hashes,
    },
    'setup_incident': {
        'summary': 'Before the measured experiment, an accidental `laya-serve --help` invocation started the default server on :8000 using MPS and opened an HTTPS connection to a model CDN. That owned process was terminated before the actual run.',
        'measured_run': 'The measured server was started separately with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1, bound only to 127.0.0.1:8787, CPU and 4 threads.',
        'cache_observation': 'Hugging Face hub cache remained 2.2G and no cache files had modification times within the 40-minute inspection window; no new weights or reinstall were observed. Transfer bytes from the accidental setup invocation were not instrumented, so the report does not claim that zero metadata bytes crossed the network.',
    },
    'limitations': [
        'Four hand-authored intentions and three candidates per intention; one call per context/order cell.',
        'Each correctness score is exact only for the listed finite test cases; candidate snippets were described to Laya but not emitted or executed as generated Go.',
        'The local oracle is not GitHub CI, generated-program runtime evidence, a full-domain proof, or a statistical benchmark.',
        'No Gooo deterministic score gate was applied in these direct decide trials; the raw model proposal is what was measured.',
        'The first harness completed all calls but hit a TypeError while aggregating its report. This summary was regenerated from saved exact requests, receipts, and manifest without repeating inference; the interval-only CPU sample and sampled RSS peak were not persisted.',
    ],
}
smoke_json_path = ROOT / 'fixed-compiler-smoke' / 'smoke_report.json'
fixed_smoke = json.loads(smoke_json_path.read_text(encoding='utf-8')) if smoke_json_path.exists() else None
if fixed_smoke:
    report['separate_fixed_compiler_smoke'] = {
        'report_file': str(ROOT / 'fixed-compiler-smoke' / 'smoke_report.md'),
        'calls': fixed_smoke['timing']['n'],
        'evaluator': fixed_smoke['runtime']['evaluator'],
        'raw_proposal': fixed_smoke['selection']['raw_laya_candidate_each_call'],
        'final_emitted_candidate': fixed_smoke['selection']['deterministic_final_emitted_candidate_each_call'],
        'command_wall_p50_and_range_ms': [fixed_smoke['timing']['command_wall_p50_ms'], *fixed_smoke['timing']['command_wall_range_ms']],
        'laya_decision_p50_and_range_ms': [fixed_smoke['timing']['laya_decision_p50_ms'], *fixed_smoke['timing']['laya_decision_range_ms']],
        'cpu_delta_seconds': fixed_smoke['resources']['cpu_delta_seconds'],
        'cpu_normalization': fixed_smoke['resources']['normalized_cpu_denominator'],
        'rss_start_and_peak_mib': [fixed_smoke['resources']['rss_start_mib'], fixed_smoke['resources']['max_rss_sampled_mib']],
        'external_go_compile_executed': fixed_smoke['selection']['external_go_compile_executed'],
        'generated_go_runtime_executed': fixed_smoke['selection']['generated_go_runtime_executed'],
    }
(ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

# Concise human-readable report for inspection without loading raw receipts.
intent = by_context['intent_only']
feedback = by_context['local_test_score_feedback']
md = f'''# Laya candidate-selection experiment (2026-09-30)

## Result

The warm CPU Laya service answered all **24 scored Gooo `decide` requests** (plus one excluded warm-up) with the English checkpoint at revision `{revision_set[0]}`. Raw selections matched the best candidate under the local finite test oracle in **9/24 (37.5%)** calls. Intent-only scored **{intent['correct']}/12 (41.7%)**; adding local deterministic score summaries scored **{feedback['correct']}/12 (33.3%)**. This four-intention sample does not establish a general effect, but it shows no benefit from score context in this run.

Candidate order mattered: the correct candidate was balanced across each of three positions. Laya selected position 1 in **14/24** calls. It selected the best candidate **6/8** times when that candidate was first, **3/8** when second, and **0/8** when third. Keep any Laya result advisory and let Gooo's deterministic finite-suite score gate choose the emitted candidate.

## Runtime and latency

- Runtime: Laya 0.3.21, Python 3.11.15, PyTorch 2.14.0, Transformers 5.17.0; CPU, four threads, English checkpoint only.
- Latency includes each `gooo decide` process, Laya round trip and model-revision health lookup: p50 **{statistics.median(latencies):.3f} ms**, p95 nearest-rank **{nearest_rank_95:.3f} ms**, range **{min(latencies):.3f}–{max(latencies):.3f} ms**.
- Selection-cohort process CPU delta and RSS values are **unavailable**: they were held in memory and lost when the post-run summary failed. I do not substitute later process snapshots for trial resource measurements.

## Scope and artifacts

These were **selection-protocol trials**, not end-to-end code-generation runs: four simple Go-like body intentions, three hand-authored candidate bodies each, and local finite test cases. The prompt showed either intent alone or pass-count summaries computed by this harness. Those summaries are not GitHub CI results. The model saw the candidate descriptions but did not emit code; no generated Go was compiled or executed.

Reproducible harness (paths, binary, endpoint, and PID are CLI/env configurable): [`run_experiment.py`](./run_experiment.py). Exact scored inputs and receipts: [`requests/`](./requests/) and [`receipts/`](./receipts/), indexed by [`trial_manifest.jsonl`](./trial_manifest.jsonl); local tests and candidate scores: [`task_oracles.json`](./task_oracles.json). The first run completed every request, then hit a summary-only Python `TypeError`; this report was rebuilt from saved outputs without rerunning Laya. See [`report.json`](./report.json), [`resource_observation.json`](./resource_observation.json), and [`service_health_observation.json`](./service_health_observation.json) for provenance and caveats. The selection cohort did not execute or externally compile generated Go. The separate fixed-compiler body-fill smoke is summarized in [`fixed-compiler-smoke/smoke_report.md`](./fixed-compiler-smoke/smoke_report.md).

## Fixed-compiler body-fill smoke (separate cohort)

Three calls with the clean compiler at commit `ec4bf3e5f4119118b501c1b45862936eb46b95b7` used evaluator `gooo/bodycodegen-int64-ast-interpreter/v2`. Laya proposed `negate` at 5/9 each time; deterministic arbitration emitted `zero` at 9/9, then passed internal typecheck and deterministic replay. Laya-decision latency p50/range was 367.162 / 366.456–381.632 ms; whole-command p50/range was 373.841 / 372.178–911.238 ms. Process CPU was 2.62 s over the n=3 warm invocation durations summed to 1.657 s (158.1% of one core); RSS started at 2017.9 MiB and peaked at 2077.2 MiB. This CPU denominator is the summed invocation durations, not total host CPU; other local work was excluded. No external `go build` or generated Go execution occurred. Exact evidence is in [`fixed-compiler-smoke/smoke_report.md`](./fixed-compiler-smoke/smoke_report.md), with raw receipts and resource samples in that directory.

## Setup note

An accidental pre-run `laya-serve --help` invocation started a default MPS service and opened an HTTPS connection to a model CDN. I terminated that process before the measured run. The actual measured server used `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` on loopback. The cache remained 2.2G with no newly modified cache files observed, but transfer bytes from the accidental invocation were not recorded, so zero network transfer is not claimed.
'''
(ROOT / 'report.md').write_text(md, encoding='utf-8')
print(json.dumps({
    'scored_trials': manifest_rows,
    'valid_laya': sum(row['mode'] == 'laya' for row in rows),
    'correct': sum(row['correct_by_finite_oracle'] for row in rows),
    'latency': {'p50_ms': round(statistics.median(latencies), 3), 'p95_nearest_rank_ms': round(nearest_rank_95, 3), 'min_ms': round(min(latencies), 3), 'max_ms': round(max(latencies), 3)},
    'by_context': by_context,
    'report': str(ROOT / 'report.md'),
    'report_json': str(ROOT / 'report.json'),
}, ensure_ascii=False, indent=2))
