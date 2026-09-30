#!/usr/bin/env python3
"""Run bounded, local Gooo typed-decision trials against offline Laya."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

DEFAULT_ROOT = Path(os.environ.get('GOOO_LAYA_EXPERIMENT_DIR', '/tmp/gooo-luna-laya-feedback-20260930'))
DEFAULT_GOOO = Path(os.environ.get('GOOO_BINARY', '/tmp/gooo-luna-body-experiments-20260930/gooo'))
DEFAULT_ENDPOINT = os.environ.get('GOOO_LAYA_URL', 'http://127.0.0.1:8787/v1/systemone')
DEFAULT_SERVER_PID = int(os.environ.get('LAYA_SERVER_PID', '61962'))
ROOT = DEFAULT_ROOT
GOOO = DEFAULT_GOOO
ENDPOINT = DEFAULT_ENDPOINT
HEALTH = ''
SERVER_PID = DEFAULT_SERVER_PID
SCHEMA = 'gooo/typed-decision-request/v1'


def configure():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default=str(DEFAULT_ROOT), help='where to save requests, receipts, and reports')
    parser.add_argument('--gooo-binary', default=str(DEFAULT_GOOO), help='prebuilt Gooo binary')
    parser.add_argument('--endpoint', default=DEFAULT_ENDPOINT, help='Laya /v1/systemone URL')
    parser.add_argument('--server-pid', type=int, default=DEFAULT_SERVER_PID, help='Laya server PID for process CPU/RSS sampling')
    args = parser.parse_args()
    global ROOT, GOOO, ENDPOINT, HEALTH, SERVER_PID
    ROOT = Path(args.output_dir).expanduser().resolve()
    GOOO = Path(args.gooo_binary).expanduser().resolve()
    ENDPOINT = args.endpoint.rstrip('/')
    parsed = urlsplit(ENDPOINT)
    base_path = parsed.path[:-len('/v1/systemone')] if parsed.path.endswith('/v1/systemone') else parsed.path
    HEALTH = urlunsplit((parsed.scheme, parsed.netloc, base_path.rstrip('/') + '/health', '', ''))
    SERVER_PID = args.server_pid
    ROOT.mkdir(parents=True, exist_ok=True)
    return args

# Candidate functions below are a local, deterministic, finite-suite oracle.
# The snippets passed to Laya are not emitted or executed as generated code.
TASKS = [
    {
        'slug': 'clamp_negative_to_zero',
        'intent': 'For an int64 input, return zero when the input is negative; otherwise return the input unchanged.',
        'signature': 'func(input int64) int64',
        'inputs': [-2, -1, 0, 1, 2],
        'expected': [0, 0, 0, 1, 2],
        'candidates': [
            ('clamp', 'if input < 0 { return 0 }; return input', lambda x: 0 if x < 0 else x),
            ('identity', 'return input', lambda x: x),
            ('zero', 'return 0', lambda x: 0),
        ],
    },
    {
        'slug': 'negate_negative_preserve_nonnegative',
        'intent': 'For an int64 input, negate it if negative; preserve zero and positive inputs unchanged.',
        'signature': 'func(input int64) int64',
        'inputs': [-4, -1, 0, 1, 4],
        'expected': [4, 1, 0, 1, 4],
        'candidates': [
            ('conditional_negate', 'if input < 0 { return -input }; return input', lambda x: -x if x < 0 else x),
            ('negate_all', 'return -input', lambda x: -x),
            ('identity', 'return input', lambda x: x),
        ],
    },
    {
        'slug': 'integer_sign',
        'intent': 'For an int64 input, return -1 for a negative value, zero for zero, and 1 for a positive value.',
        'signature': 'func(input int64) int64',
        'inputs': [-4, -1, 0, 1, 4],
        'expected': [-1, -1, 0, 1, 1],
        'candidates': [
            ('sign', 'if input < 0 { return -1 }; if input > 0 { return 1 }; return 0', lambda x: -1 if x < 0 else (1 if x > 0 else 0)),
            ('negative_one', 'return -1', lambda x: -1),
            ('identity', 'return input', lambda x: x),
        ],
    },
    {
        'slug': 'is_even',
        'intent': 'For an int64 input, return true exactly when it is evenly divisible by 2; return false otherwise.',
        'signature': 'func(input int64) bool',
        'inputs': [-2, -1, 0, 1, 2, 3],
        'expected': [True, False, True, False, True, False],
        'candidates': [
            ('even', 'return input % 2 == 0', lambda x: x % 2 == 0),
            ('positive', 'return input > 0', lambda x: x > 0),
            ('nonzero', 'return input != 0', lambda x: x != 0),
        ],
    },
]


def ps_sample():
    raw = subprocess.check_output(['ps', '-p', str(SERVER_PID), '-o', 'time=,rss='], text=True).strip()
    parts = raw.split()
    if len(parts) != 2:
        raise RuntimeError(f'unexpected ps sample: {raw!r}')
    clock = parts[0]
    colon = clock.split(':')
    if len(colon) == 3:
        cpu_seconds = int(colon[0]) * 3600 + int(colon[1]) * 60 + float(colon[2])
    elif len(colon) == 2:
        cpu_seconds = int(colon[0]) * 60 + float(colon[1])
    else:
        cpu_seconds = float(clock)
    return {'cpu_seconds': cpu_seconds, 'rss_kb': int(parts[1])}


def health():
    with urllib.request.urlopen(HEALTH, timeout=3) as response:
        return json.load(response)


def oracle_scores(task):
    scores = {}
    for candidate_id, _code, evaluator in task['candidates']:
        passed = sum(evaluator(x) == expected for x, expected in zip(task['inputs'], task['expected']))
        scores[candidate_id] = {'passed': passed, 'total': len(task['inputs'])}
    return scores


def candidate_json(task, order):
    return [
        {
            'position': i + 1,
            'canonical_id': cid,
            'code': code,
            'evaluator': evaluator,
        }
        for i, (cid, code, evaluator) in enumerate(order)
    ]


def make_request(task, order, context_mode):
    scores = oracle_scores(task)
    ordered = candidate_json(task, order)
    id_by_canonical = {item['canonical_id']: f"candidate_{item['position']}" for item in ordered}
    state = (
        f"Intent: {task['intent']}\n"
        f"Signature: {task['signature']}\n"
        "Choose among the listed complete Go-like body candidates."
    )
    if context_mode == 'local_test_score_feedback':
        summaries = [
            f"{id_by_canonical[cid]}: {scores[cid]['passed']}/{scores[cid]['total']} passed"
            for cid, _code, _eval in order
        ]
        state += (
            "\n\nLocal deterministic test-score feedback (finite reference cases only; "
            "not GitHub Actions or CI): " + '; '.join(summaries) + "."
        )
    options = []
    for item in ordered:
        cid = id_by_canonical[item['canonical_id']]
        options.append({
            'id': cid,
            'description': f"Complete body for {task['signature']}: `{item['code']}`.",
        })
    request = {
        'schema': SCHEMA,
        'state': state,
        'question': {
            'id': 'body_candidate',
            'instructions': (
                'Choose the one listed complete Go-like body that best matches the stated intent. '
                'When local test-score feedback is present, use it as finite-suite evidence. '
                'Return one listed candidate ID.'
            ),
            'options': options,
        },
        'fallback': options[0]['id'],
    }
    score_by_position = {
        id_by_canonical[cid]: scores[cid] for cid, _code, _eval in order
    }
    canonical_by_position = {id_by_canonical[cid]: cid for cid, _code, _eval in order}
    return request, score_by_position, canonical_by_position, id_by_canonical


def run_one(path, timeout=15):
    started = time.perf_counter()
    proc = subprocess.run(
        [str(GOOO), 'decide', '--json', str(path)],
        env={**os.environ, 'GOOO_LAYA_URL': ENDPOINT},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        receipt = json.loads(proc.stdout)
    except Exception:
        receipt = None
    return proc, receipt, elapsed_ms


def dump_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    configure()
    run_started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    if not GOOO.is_file():
        raise RuntimeError(f'gooo binary missing: {GOOO}')
    before_health = health()
    if before_health.get('device') != 'cpu' or before_health.get('loaded') != ['english']:
        raise RuntimeError(f'wrong Laya configuration: {before_health!r}')
    revision_values = list(before_health.get('revisions', {}).values())
    if not revision_values:
        raise RuntimeError('model revision unavailable')

    # One warm-up call, not included in the 24 scored factorial trials.
    warm_task = TASKS[0]
    warm_order = warm_task['candidates']
    warm_request, _, _, _ = make_request(warm_task, warm_order, 'intent_only')
    warm_path = ROOT / 'warmup_request.json'
    dump_json(warm_path, warm_request)
    warm_proc, warm_receipt, warm_ms = run_one(warm_path)
    (ROOT / 'warmup_stdout.json').write_text(warm_proc.stdout, encoding='utf-8')
    (ROOT / 'warmup_stderr.txt').write_text(warm_proc.stderr, encoding='utf-8')
    if warm_proc.returncode != 0 or not warm_receipt or warm_receipt.get('mode') != 'laya':
        raise RuntimeError(f'warm-up failed: rc={warm_proc.returncode} receipt={warm_receipt!r} stderr={warm_proc.stderr!r}')

    # Measure a short idle baseline after warm-up, then sample the Laya process
    # throughout the actual candidate-selection batch.
    idle_start = ps_sample()
    time.sleep(3.0)
    idle_end = ps_sample()
    trial_cpu_start = ps_sample()
    max_rss_kb = trial_cpu_start['rss_kb']
    sample_stop = threading.Event()

    def sample_resources():
        nonlocal max_rss_kb
        while not sample_stop.wait(0.25):
            try:
                sample = ps_sample()
                max_rss_kb = max(max_rss_kb, sample['rss_kb'])
            except Exception:
                pass

    sampler = threading.Thread(target=sample_resources, daemon=True)
    sampler.start()

    trials = []
    for task in TASKS:
        for context_mode in ['intent_only', 'local_test_score_feedback']:
            for offset in range(3):
                order = task['candidates'][offset:] + task['candidates'][:offset]
                trials.append((task, context_mode, offset, order))
    random.Random(20260930).shuffle(trials)

    rows = []
    batch_started = time.perf_counter()
    for serial, (task, context_mode, offset, order) in enumerate(trials, start=1):
        request, score_by_position, canonical_by_position, id_by_canonical = make_request(task, order, context_mode)
        order_tokens = ''.join(canonical_by_position[f'candidate_{i}'][0] for i in range(1, 4))
        stem = f'{serial:02d}_{task["slug"]}_{context_mode}_{order_tokens}'
        request_path = ROOT / 'requests' / f'{stem}.json'
        dump_json(request_path, request)
        proc, receipt, elapsed_ms = run_one(request_path)
        (ROOT / 'receipts' / f'{stem}.stdout.json').write_text(proc.stdout, encoding='utf-8')
        (ROOT / 'receipts' / f'{stem}.stderr.txt').write_text(proc.stderr, encoding='utf-8')
        selected = receipt.get('selected') if receipt else None
        selected_score = score_by_position.get(selected)
        best_score = max((value['passed'] for value in score_by_position.values()), default=0)
        best_ids = sorted(k for k, value in score_by_position.items() if value['passed'] == best_score)
        canonical_by_position_for_trial = canonical_by_position
        row = {
            'serial': serial,
            'task': task['slug'],
            'context': context_mode,
            'candidate_order_offset': offset,
            'candidate_order': [canonical_by_position_for_trial[f'candidate_{i}'] for i in range(1, 4)],
            'position_order': [f'candidate_{i}' for i in range(1, 4)],
            'request_file': str(request_path),
            'receipt_file': str(ROOT / 'receipts' / f'{stem}.stdout.json'),
            'stderr_file': str(ROOT / 'receipts' / f'{stem}.stderr.txt'),
            'cli_return_code': proc.returncode,
            'latency_ms': round(elapsed_ms, 3),
            'mode': receipt.get('mode') if receipt else None,
            'provider': receipt.get('provider') if receipt else None,
            'selected_id': selected,
            'selected_candidate': canonical_by_position.get(selected),
            'selected_test_score': selected_score,
            'best_test_score': best_score,
            'best_candidate_ids': best_ids,
            'correct_by_finite_oracle': bool(selected_score and selected_score['passed'] == best_score and receipt and receipt.get('mode') == 'laya'),
            'request_sha256': receipt.get('request_sha256') if receipt else None,
            'model': receipt.get('model') if receipt else None,
            'model_revision': receipt.get('model_revision') if receipt else None,
            'confidence': receipt.get('confidence') if receipt else None,
            'answer_confidence': receipt.get('answer_confidence') if receipt else None,
            'local_score_by_position': score_by_position,
            'canonical_by_position': canonical_by_position,
            'stdout_parseable': receipt is not None,
            'stderr': proc.stderr,
        }
        rows.append(row)
        if proc.returncode != 0 or not receipt or receipt.get('mode') != 'laya':
            # Continue to preserve exact observations for a bounded batch, but
            # service/provider faults will be reported rather than hidden.
            pass
    batch_seconds = time.perf_counter() - batch_started
    sample_stop.set()
    sampler.join(timeout=2)
    trial_cpu_end = ps_sample()
    after_health = health()
    resource_snapshot = {
        'server_pid': SERVER_PID,
        'idle_baseline_start': idle_start,
        'idle_baseline_end': idle_end,
        'trial_start': trial_cpu_start,
        'trial_end': trial_cpu_end,
        'sampled_peak_rss_kb': max_rss_kb,
        'sample_interval_seconds': 0.25,
        'batch_wall_seconds': batch_seconds,
    }
    dump_json(ROOT / 'resource_snapshot.json', resource_snapshot)

    dump_json(ROOT / 'task_oracles.json', [
        {
            'slug': t['slug'],
            'intent': t['intent'],
            'signature': t['signature'],
            'test_inputs': t['inputs'],
            'expected_outputs': t['expected'],
            'candidates': [
                {'id': cid, 'code': code, 'passed': oracle_scores(t)[cid]['passed'], 'total': oracle_scores(t)[cid]['total']}
                for cid, code, _eval in t['candidates']
            ],
            'oracle_scope': 'Locally computed exact score over the listed finite test cases; candidate snippets are described to the model but not emitted or executed as generated Go.',
        }
        for t in TASKS
    ])
    with (ROOT / 'trial_manifest.jsonl').open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')

    latencies = sorted(row['latency_ms'] for row in rows if row['mode'] == 'laya' and row['latency_ms'] is not None)
    def nearest_rank(p):
        return latencies[max(0, math.ceil(p * len(latencies)) - 1)] if latencies else None
    correct_count = sum(row['correct_by_finite_oracle'] for row in rows)
    valid_count = sum(row['mode'] == 'laya' for row in rows)
    by_context = {}
    for context_mode in ['intent_only', 'local_test_score_feedback']:
        group = [row for row in rows if row['context'] == context_mode]
        good = sum(row['correct_by_finite_oracle'] for row in group)
        by_context[context_mode] = {'calls': len(group), 'valid_laya': sum(row['mode'] == 'laya' for row in group), 'correct': good, 'accuracy_percent': round(100 * good / max(1, len(group)), 1)}
    # Count selected IDs by task/context to avoid ambiguous same-name IDs.
    by_task_context = []
    for task in TASKS:
        for context_mode in ['intent_only', 'local_test_score_feedback']:
            group = [row for row in rows if row['task'] == task['slug'] and row['context'] == context_mode]
            by_task_context.append({
                'task': task['slug'], 'context': context_mode, 'calls': len(group),
                'selected': [row['selected_candidate'] for row in sorted(group, key=lambda r: r['candidate_order_offset'])],
                'correct': sum(row['correct_by_finite_oracle'] for row in group),
                'finite_oracle_accuracy_percent': round(100 * sum(row['correct_by_finite_oracle'] for row in group) / max(1, len(group)), 1),
            })
    model_revisions = sorted(set(row['model_revision'] for row in rows if row['model_revision']))
    models = sorted(set(row['model'] for row in rows if row['model']))
    report = {
        'experiment': 'Gooo validated typed-decision selection trials through real loopback Laya requests',
        'started_utc': run_started_utc,
        'calls': {'warmup_excluded': 1, 'scored_trials': len(rows), 'total_laya_invocations_including_warmup': len(rows) + 1, 'provider_valid': valid_count, 'factorial_design': '4 intentions x 2 context modes x 3 candidate-position rotations; one call per cell; shuffled with seed 20260930'},
        'host': 'Apple Silicon macOS, arm64; process-local CPU accounting from ps; no repository writes',
        'runtime': {'laya': '0.3.21', 'python': '3.11.15', 'device': 'cpu', 'threads': 4, 'models_loaded': before_health.get('loaded'), 'model': models, 'revision': model_revisions, 'hf_hub_offline': True, 'transformers_offline': True, 'endpoint': ENDPOINT},
        'protocol': {'request_schema': SCHEMA, 'provider_receipts': 'gooo/typed-decision-receipt/v1', 'path': 'gooo decide --json; request validated by the selected binary; each receipt records request SHA-256 and model revision', 'binary': str(GOOO), 'trial_type': 'selection only; not end-to-end body-codegen; no generated Go is emitted, compiled, or run'},
        'latency': {'measurement': 'wall time around each gooo decide process, including Laya decision request and health revision lookup, plus CLI startup', 'n': len(latencies), 'p50_ms': round(statistics.median(latencies), 3) if latencies else None, 'p95_ms_nearest_rank': round(nearest_rank(0.95), 3) if latencies else None, 'min_ms': round(min(latencies), 3) if latencies else None, 'max_ms': round(max(latencies), 3) if latencies else None, 'batch_wall_seconds': round(batch_seconds, 3), 'warmup_ms_excluded': round(warm_ms, 3)},
        'resources': {'server_pid_owned_by_this_run': SERVER_PID, 'baseline_idle_observation_seconds': 3.0, 'idle_cpu_delta_seconds_ps_resolution_0.01s': round(idle_end['cpu_seconds'] - idle_start['cpu_seconds'], 2), 'trial_server_cpu_delta_seconds_ps_resolution_0.01s': round(trial_cpu_end['cpu_seconds'] - trial_cpu_start['cpu_seconds'], 2), 'rss_before_trials_mib': round(trial_cpu_start['rss_kb'] / 1024, 1), 'peak_rss_sampled_during_trials_mib': round(max_rss_kb / 1024, 1), 'rss_after_trials_mib': round(trial_cpu_end['rss_kb'] / 1024, 1), 'sample_interval_seconds': 0.25},
        'accuracy': {'finite_oracle_correct': correct_count, 'scored_trials': len(rows), 'valid_laya_accuracy_percent': round(100 * correct_count / max(1, valid_count), 1), 'intent_only_vs_score_feedback': by_context, 'per_task_context': by_task_context, 'interpretation': 'A selected candidate is counted correct only if its locally evaluated pass count equals the highest pass count in that candidate set. Finite suites are limited evidence and are not CI or full-domain proof.'},
        'provenance': {'warmup_receipt': str(ROOT / 'warmup_stdout.json'), 'trial_manifest': str(ROOT / 'trial_manifest.jsonl'), 'raw_requests_dir': str(ROOT / 'requests'), 'raw_receipts_dir': str(ROOT / 'receipts'), 'oracle_file': str(ROOT / 'task_oracles.json'), 'all_trial_request_sha256_present': all(row['request_sha256'] for row in rows if row['mode'] == 'laya'), 'revision_consistent': len(model_revisions) <= 1, 'health_after': after_health},
        'limitations': ['Only 4 hand-authored body intentions and 3 candidates per intention.', 'One trial per context/order factorial cell; no repeated stochastic sampling.', 'The score oracle covers only the listed finite inputs; it is not generated-Go execution, a formal proof, or GitHub CI.', 'Raw Laya choices are measured; no Gooo score gate is applied in these direct decide trials.'],
    }
    dump_json(ROOT / 'report.json', report)
    print(json.dumps({'scored_trials': len(rows), 'valid_laya': valid_count, 'correct': correct_count, 'latency': report['latency'], 'resources': report['resources'], 'revision': model_revisions, 'by_context': by_context, 'report': str(ROOT / 'report.json')}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
