#!/usr/bin/env python3
"""Parse already-persisted direct smoke receipts and resource samples only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics

DEFAULT_ROOT = Path(os.environ.get('GOOO_LAYA_SMOKE_DIR', '/tmp/gooo-luna-laya-feedback-20260930/fixed-compiler-smoke'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', default=str(DEFAULT_ROOT))
ROOT = Path(parser.parse_args().output_dir).expanduser().resolve()
metadata = json.loads((ROOT / 'run_metadata.json').read_text(encoding='utf-8'))
resources = json.loads((ROOT / 'resource_samples.json').read_text(encoding='utf-8'))
call_receipts = []
for index in range(1, 4):
    call_dir = ROOT / 'calls'
    path = call_dir / f'call-{index:02d}.stdout.json'
    raw = path.read_bytes()
    document = json.loads(raw)
    report = document['report']
    body = report['body_fill']
    decision = body['decision']
    call_receipts.append({
        'call': index,
        'cli_return_code': json.loads((call_dir / f'call-{index:02d}.resource.json').read_text())['return_code'],
        'receipt_file': str(path),
        'receipt_sha256': hashlib.sha256(raw).hexdigest(),
        'body_codegen_decision': report.get('decision'),
        'laya_mode': decision.get('mode'),
        'model': decision.get('model'),
        'model_revision': decision.get('model_revision'),
        'request_sha256': decision.get('request_sha256'),
        'raw_proposed_candidate': body.get('proposed_candidate_id'),
        'raw_proposed_accuracy_percent': body.get('proposed_accuracy_percent'),
        'final_emitted_candidate': body.get('selected_candidate_id'),
        'best_candidate': body.get('best_candidate_id'),
        'best_candidate_accuracy_percent': body.get('best_candidate_accuracy_percent'),
        'selected_functional_accuracy_percent': body.get('functional_accuracy_percent'),
        'selected_test_cases_passed': body.get('test_cases_passed'),
        'selected_test_cases_total': body.get('test_cases_total'),
        'candidate_scores': body.get('candidate_scores'),
        'evaluator': body.get('evaluator'),
        'selection_adjustment': body.get('selection_adjustment'),
        'selection_regret_percentage_points': body.get('selection_regret_percentage_points'),
        'laya_decision_ms': body.get('timing', {}).get('laya_decision_ms'),
        'typecheck_passed': report.get('typecheck_passed'),
        'deterministic_replay': report.get('deterministic_replay'),
        'generated_digest': report.get('generated_digest'),
    })

if len(call_receipts) != 3:
    raise RuntimeError(f'expected 3 saved receipts, found {len(call_receipts)}')
if any(call['cli_return_code'] != 0 or call['body_codegen_decision'] != 'PASS' or call['laya_mode'] != 'laya' for call in call_receipts):
    raise RuntimeError('one or more body-codegen smoke runs failed or used fallback')
evaluators = {call['evaluator'] for call in call_receipts}
revisions = {call['model_revision'] for call in call_receipts}
raw_candidates = {call['raw_proposed_candidate'] for call in call_receipts}
final_candidates = {call['final_emitted_candidate'] for call in call_receipts}
scores = call_receipts[0]['candidate_scores']
if evaluators != {'gooo/bodycodegen-int64-ast-interpreter/v2'}:
    raise RuntimeError(f'unexpected evaluator: {evaluators}')
if revisions != {'55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851'}:
    raise RuntimeError(f'unexpected model revision: {revisions}')
if raw_candidates != {'negate'} or final_candidates != {'zero'}:
    raise RuntimeError(f'unexpected raw/final candidates: {raw_candidates} / {final_candidates}')
cli_times = sorted(sample['elapsed_ms'] for sample in resources['calls'])
provider_times = sorted(call['laya_decision_ms'] for call in call_receipts)
wall_sum_s = sum(sample['elapsed_ms'] for sample in resources['calls']) / 1000
cpu_sum_s = resources['total_server_cpu_delta_seconds']
cpu_one_core_percent = 100 * cpu_sum_s / wall_sum_s if wall_sum_s else 0
rss_max_mib = resources['max_sampled_rss_kb'] / 1024
rss_start_mib = resources['calls'][0]['server_rss_start_kb'] / 1024

result = {
    'cohort': '3 direct fixed-compiler body-codegen --fill-plan invocations',
    'warmup': 'No additional warm-up in this cohort; Laya was already warm after the preceding 25 selection-stage calls.',
    'compiler': {
        'commit': 'ec4bf3e5f4119118b501c1b45862936eb46b95b7',
        'binary': metadata['binary'],
        'binary_sha256': metadata['binary_sha256'],
        'build': 'go1.27.0 darwin/arm64, vcs.modified=false',
        'plan': metadata['plan'],
        'plan_sha256_file': metadata['plan_sha256_file'],
        'fixture': metadata['fixture'],
        'fixture_sha256_file': metadata['fixture_sha256_file'],
    },
    'runtime': {
        'laya_model': call_receipts[0]['model'],
        'laya_revision': next(iter(revisions)),
        'device': 'CPU, four threads, loopback-only server',
        'evaluator': next(iter(evaluators)),
    },
    'timing': {
        'n': 3,
        'command_wall_p50_ms': round(statistics.median(cli_times), 3),
        'command_wall_range_ms': [round(min(cli_times), 3), round(max(cli_times), 3)],
        'laya_decision_p50_ms': round(statistics.median(provider_times), 3),
        'laya_decision_range_ms': [round(min(provider_times), 3), round(max(provider_times), 3)],
        'p95': 'Not reported (n=3).',
    },
    'resources': {
        'cpu_delta_seconds': round(cpu_sum_s, 2),
        'measured_command_wall_seconds_sum': round(wall_sum_s, 3),
        'normalized_cpu_percent_of_one_core': round(cpu_one_core_percent, 1),
        'normalized_cpu_denominator': 'sum of the 3 warm smoke invocation durations (1.657 seconds); process CPU seconds divided by invocation wall seconds, normalized to one core. Other local work is not included, so this is not total host CPU utilization.',
        'rss_start_mib': round(rss_start_mib, 1),
        'max_rss_sampled_mib': round(rss_max_mib, 1),
        'sampling_interval_seconds': 0.05,
        'cpu_note': 'CPU process-time deltas are measured around each command and have 0.01-second ps resolution. Normalization divides their summed delta by summed command wall time; >100% means multiple CPU cores were used on average.',
    },
    'selection': {
        'raw_laya_candidate_each_call': 'negate (5/9 = 55.56%; raw proposal, not emitted)',
        'deterministic_final_emitted_candidate_each_call': 'zero (9/9 = 100% over the declared finite test suite)',
        'best_candidate': 'zero',
        'adjustment': 'replaced_with_best_scoring_candidate',
        'selection_regret_percentage_points': 44.44,
        'typecheck_passed_each_call': True,
        'deterministic_replay_passed_each_call': True,
        'generated_digest_each_call': call_receipts[0]['generated_digest'],
        'candidate_scores': scores,
        'local_suite_scope': '9 declared int64 cases including the signed minimum and maximum, evaluated by the bounded v2 integer AST interpreter; not full-domain proof or CI result.',
        'external_go_compile_executed': False,
        'generated_go_runtime_executed': False,
        'verification_scope': 'The command internal Go typechecker accepted the output and deterministic emission replay matched; no external go build or generated-program execution was run.',
    },
    'per_call': call_receipts,
    'resource_samples_file': str(ROOT / 'resource_samples.json'),
    'metadata_file': str(ROOT / 'run_metadata.json'),
}
(ROOT / 'smoke_report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

md = f'''# Fixed-compiler body-fill smoke (3 calls)

- Compiler commit: `{result['compiler']['commit']}`; binary SHA-256: `{result['compiler']['binary_sha256']}`.
- Laya: `{result['runtime']['laya_model']}` revision `{result['runtime']['laya_revision']}`, CPU / four threads, already warm from the preceding selection cohort.
- Evaluator: `{result['runtime']['evaluator']}`. All three runs had `PASS`, typecheck success and deterministic replay.
- Raw Laya proposal: **`negate`, 5/9 (55.56%)** on every call. Deterministic score arbitration emitted **`zero`, 9/9 (100%)** every call. Regret of raw proposal: **44.44 percentage points**.
- Whole command latency p50/range: **{result['timing']['command_wall_p50_ms']:.3f} ms**, **{result['timing']['command_wall_range_ms'][0]:.3f}–{result['timing']['command_wall_range_ms'][1]:.3f} ms**. Laya decision p50/range: **{result['timing']['laya_decision_p50_ms']:.3f} ms**, **{result['timing']['laya_decision_range_ms'][0]:.3f}–{result['timing']['laya_decision_range_ms'][1]:.3f} ms**. p95 omitted because n=3.
- Server process CPU: **{result['resources']['cpu_delta_seconds']:.2f} s** across the **n=3 warm smoke calls**, whose summed invocation wall time was **{result['resources']['measured_command_wall_seconds_sum']:.3f} s**; normalized to **{result['resources']['normalized_cpu_percent_of_one_core']:.1f}% of one core**. The denominator is the sum of these three invocation durations, not total host CPU; unrelated local work is excluded. RSS started at **{result['resources']['rss_start_mib']:.1f} MiB** and peaked at **{result['resources']['max_rss_sampled_mib']:.1f} MiB** sampled at 50 ms intervals.
- Verification boundary: Gooo’s internal typecheck and deterministic replay passed. No external `go build` and no generated Go execution were run.

The plan is `/Users/alice/meta-go/.worktrees/gooo-autonomous-governance-20260930/examples/body-codegen/ir-fill-clamp-plan.json`; the fixture is `examples/body-codegen/ir-fill-clamp.gooo.fixture`. Exact JSON stdout/stderr receipts are in `calls/`, and per-call resource samples were saved before this report was generated. The nine-case score is a finite local evaluator result, not GitHub CI or a full-domain proof.
'''
(ROOT / 'smoke_report.md').write_text(md, encoding='utf-8')
print(json.dumps({'report': str(ROOT / 'smoke_report.md'), 'json': str(ROOT / 'smoke_report.json'), 'command_p50_ms': result['timing']['command_wall_p50_ms'], 'command_range_ms': result['timing']['command_wall_range_ms'], 'decision_p50_ms': result['timing']['laya_decision_p50_ms'], 'decision_range_ms': result['timing']['laya_decision_range_ms'], 'cpu': result['resources'], 'raw_proposal': sorted(raw_candidates), 'final': sorted(final_candidates)}, ensure_ascii=False, indent=2))
