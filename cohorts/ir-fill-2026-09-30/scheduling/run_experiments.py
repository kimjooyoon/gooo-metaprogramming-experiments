#!/usr/bin/env python3
"""Exercise Gooo body-codegen scheduling with an owned, explicit local MOCK."""
import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path('/tmp/gooo-luna-scheduling-experiments-20260930')
BIN = Path('/tmp/gooo-ir-fill-fixed-20260930')
WORKTREE = Path('/Users/alice/meta-go/.worktrees/gooo-autonomous-governance-20260930')
FIXTURE = OUT / 'fixture.gooo'
PLAN = OUT / 'plan.json'
CAPTURES = OUT / 'captures'
ACTIVITY = 'ClampNegativeToZero'
SUCCESS = json.dumps({'model': 'MOCK-only', 'answers': {'body_ir_fill': {'choice': 'identity'}}}).encode()

class MockState:
    def __init__(self, delay, status, response, capture_dir, trial):
        self.delay, self.status, self.response = delay, status, response
        self.capture_dir, self.trial = capture_dir, trial
        self.lock = threading.Lock()
        self.events, self.active, self.max_active = [], 0, 0
    def persist_line(self, kind, value):
        path = self.capture_dir / f'{self.trial}.http.jsonl'
        with self.lock, path.open('a') as handle:
            handle.write(json.dumps({'event': kind, **value}, sort_keys=True) + '\n')

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, fmt, *args):
        pass
    def handle_error(self, request, client_address):
        pass
    def do_POST(self):
        state = self.server.state
        start = time.monotonic_ns()
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        try:
            payload = json.loads(raw)
            decoded = json.loads(payload['state']['request'])
        except Exception as exc:
            payload, decoded = {'parse_error': str(exc)}, {'parse_error': str(exc)}
        event = {
            'method': 'POST', 'path': self.path, 'start_monotonic_ns': start,
            'question_ids': list(payload.get('questions', {}).keys()),
            'stage': decoded.get('stage'),
            'candidate_ids': [item.get('id') for item in decoded.get('candidate_scores', [])],
            'process_label': self.path.split('trial=')[-1] if 'trial=' in self.path else None,
            'request_payload': payload,
        }
        with state.lock:
            state.active += 1
            state.max_active = max(state.max_active, state.active)
            state.events.append(event)
        state.persist_line('request_received', event)
        if state.delay:
            time.sleep(state.delay)
        client_error = None
        try:
            self.send_response(state.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(state.response)))
            self.end_headers()
            self.wfile.write(state.response)
        except (BrokenPipeError, ConnectionResetError) as exc:
            client_error = type(exc).__name__
        finally:
            end = time.monotonic_ns()
            event.update({'response_status': state.status, 'response_attempt_monotonic_ns': end,
                          'client_closed_before_response': client_error})
            with state.lock:
                state.active -= 1
            state.persist_line('response_attempt', event)

class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass

class MockServer:
    def __init__(self, delay, status, response, trial):
        self.state = MockState(delay, status, response, CAPTURES, trial)
        self.server = QuietThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.state = self.state
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    def __enter__(self):
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/v1/systemone'
        return self
    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')

def cmd_for(kind):
    if kind == 'fixed_binary':
        return [str(BIN), 'body-codegen', '--json', '--fill-plan', str(PLAN), '--activity', ACTIVITY, str(FIXTURE)]
    if kind == 'working_tree_go_run':
        return ['go', 'run', './cmd/gooo', 'body-codegen', '--json', '--fill-plan', str(PLAN), '--activity', ACTIVITY, str(FIXTURE)]
    raise ValueError(kind)

def run_process(kind, url, label, timeout=25, expected_mode='laya', expected_fallback=None):
    env = os.environ.copy()
    env['GOOO_LAYA_URL'], env['GOOO_LAYA_API_KEY'] = url, ''
    started = time.monotonic_ns()
    proc = subprocess.Popen(cmd_for(kind), cwd=WORKTREE if kind == 'working_tree_go_run' else OUT,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f'{kind} subprocess exceeded experiment cap of {timeout}s')
    finished = time.monotonic_ns()
    stem = re.sub(r'[^a-zA-Z0-9_.-]+', '_', f'{label}-{pid}')
    stdout_path, stderr_path = CAPTURES / f'{stem}.stdout.json', CAPTURES / f'{stem}.stderr.txt'
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)
    parsed, parse_error = None, None
    try:
        parsed = json.loads(stdout)
    except Exception as exc:
        parse_error = str(exc)
    report = parsed.get('report') if parsed else None
    body = report.get('body_fill') if report else None
    decision = body.get('decision') if body else None
    result = {
        'kind': kind, 'pid': pid,
        'pid_scope': 'go run driver; executed Go child PID not separately measured' if kind == 'working_tree_go_run' else 'direct clean-binary CLI process',
        'exit_code': proc.returncode, 'wall_ms': (finished-started)/1e6,
        'stdout_json': bool(parsed), 'stdout_file': str(stdout_path), 'stderr_file': str(stderr_path),
        'stderr_nonempty': bool(stderr), 'parse_error': parse_error,
        'selected_candidate_id': body.get('selected_candidate_id') if body else None,
        'proposed_candidate_id': body.get('proposed_candidate_id') if body else None,
        'provider_selected_candidate_id': decision.get('selected') if decision else None,
        'functional_accuracy_percent': body.get('functional_accuracy_percent') if body else None,
        'generated_digest': report.get('generated_digest') if report else None,
        'decision_mode': decision.get('mode') if decision else None,
        'fallback_reason': decision.get('fallback_reason') if decision else None,
        'request_sha256': decision.get('request_sha256') if decision else None,
        'test_suite_sha256': body.get('test_suite_sha256') if body else None,
        'evaluator': body.get('evaluator') if body else None,
    }
    required = ('selected_candidate_id', 'proposed_candidate_id', 'provider_selected_candidate_id', 'functional_accuracy_percent', 'generated_digest', 'decision_mode', 'request_sha256', 'test_suite_sha256', 'evaluator')
    missing = [field for field in required if result[field] is None]
    if proc.returncode != 0 or parse_error or missing:
        raise RuntimeError(f'{label}: invalid CLI evidence; exit={proc.returncode}, missing={missing}, parse={parse_error}, stderr={stderr[-600:]}')
    if result['decision_mode'] != expected_mode:
        raise RuntimeError(f'{label}: decision mode {result["decision_mode"]!r}, wanted {expected_mode!r}')
    if expected_fallback is not None and result['fallback_reason'] != expected_fallback:
        raise RuntimeError(f'{label}: fallback reason {result["fallback_reason"]!r}, wanted {expected_fallback!r}')
    if expected_mode == 'laya' and (result['provider_selected_candidate_id'] != 'identity' or result['proposed_candidate_id'] != 'identity'):
        raise RuntimeError(f'{label}: valid success mock was not accepted as the identity proposal')
    return result

def persist_requests(name, events):
    path = CAPTURES / f'{name}.requests.json'
    write_json(path, events)
    return path

def one(name, kind, delay=0, status=200, response=SUCCESS, timeout=25, expected_mode='laya', expected_fallback=None):
    with MockServer(delay, status, response, name) as mock:
        result = run_process(kind, mock.url, name, timeout, expected_mode, expected_fallback)
        if delay >= 8:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                with mock.state.lock:
                    active = mock.state.active
                if not active:
                    break
                time.sleep(0.02)
        events = list(mock.state.events)
        if len(events) != 1:
            raise RuntimeError(f'{name}: expected exactly one POST, got {len(events)}')
        event = events[0]
        elapsed = None if not event.get('response_attempt_monotonic_ns') else (event['response_attempt_monotonic_ns']-event['start_monotonic_ns'])/1e6
        request_path = persist_requests(name, events)
        result.update({'mock_provider': {'explicit_mock': True, 'host': '127.0.0.1', 'ephemeral_port': mock.server.server_address[1], 'path': '/v1/systemone', 'delay_ms': delay*1000, 'status': status},
                       'request_count': 1, 'request_file': str(request_path), 'request_to_response_attempt_ms': elapsed,
                       'provider_max_active_requests': mock.state.max_active})
        return {'name': name, 'result': result}

def concurrency_trial():
    name = '06_two_process_concurrency'
    with MockServer(0.9, 200, SUCCESS, name) as mock:
        barrier, results, failures = threading.Barrier(3), [None, None], []
        def worker(index):
            try:
                barrier.wait()
                results[index] = run_process('fixed_binary', mock.url+f'?trial=concurrent-{index}', f'{name}-p{index}')
                results[index]['worker_index'] = index
            except Exception as exc:
                failures.append(repr(exc))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(timeout=30)
        if any(thread.is_alive() for thread in threads) or failures:
            raise RuntimeError(f'concurrency worker failure: {failures}')
        pid_by_trial = {f'concurrent-{item["worker_index"]}': item['pid'] for item in results}
        events = list(mock.state.events)
        for event in events:
            event['pid'] = pid_by_trial.get(event['process_label'])
        if len(events) != 2 or mock.state.max_active < 2 or len({item['pid'] for item in results}) != 2:
            raise RuntimeError('two independent provider requests did not overlap')
        path = persist_requests(name, events)
        return {'name': name, 'results': results,
                'mock_provider': {'explicit_mock': True, 'host': '127.0.0.1', 'ephemeral_port': mock.server.server_address[1], 'delay_ms': 900, 'server': 'threaded Python HTTPServer'},
                'request_file': str(path), 'request_count': 2,
                'provider_max_active_requests': mock.state.max_active, 'provider_overlap_observed': True,
                'request_start_spread_ms': (max(e['start_monotonic_ns'] for e in events)-min(e['start_monotonic_ns'] for e in events))/1e6}

def repeat_trial():
    name = '08_same_plan_repeatability'
    with MockServer(0.03, 200, SUCCESS, name) as mock:
        first = run_process('fixed_binary', mock.url, name+'-first')
        second = run_process('fixed_binary', mock.url, name+'-second')
        events = list(mock.state.events)
        if len(events) != 2:
            raise RuntimeError(f'{name}: expected two requests, got {len(events)}')
        path = persist_requests(name, events)
        fields = ('selected_candidate_id', 'generated_digest', 'request_sha256', 'test_suite_sha256', 'functional_accuracy_percent')
        values = {field: [first[field], second[field]] for field in fields}
        if not all(pair[0] is not None and pair[0] == pair[1] for pair in values.values()):
            raise RuntimeError(f'{name}: repeated non-null outputs differ: {values}')
        return {'name': name, 'results': [first, second], 'mock_provider': {'explicit_mock': True, 'host': '127.0.0.1', 'ephemeral_port': mock.server.server_address[1], 'delay_ms': 30},
                'request_count': 2, 'request_file': str(path), 'deterministic_fields_equal': True, 'compared_fields': values}

def git_info(path):
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path, text=True).strip()
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=path, text=True).strip()
    return {'path': str(path), 'head': head, 'clean_worktree': not bool(status), 'status_porcelain': status}

def binary_info(path):
    version = subprocess.check_output(['go', 'version', str(path)], text=True).strip()
    text = subprocess.check_output(['go', 'version', '-m', str(path)], text=True)
    settings = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0] == 'build' and '=' in parts[1]:
            key, value = parts[1].split('=', 1)
            if key in ('vcs.revision', 'vcs.modified', 'vcs.time', 'GOARCH', 'GOOS'):
                settings[key] = value
    expected = 'ec4bf3e5f4119118b501c1b45862936eb46b95b7'
    if settings.get('vcs.revision') != expected or settings.get('vcs.modified') != 'false':
        raise RuntimeError(f'clean binary metadata mismatch: {settings}')
    return {'path': str(path), 'go_version': version, 'settings': settings, 'copied': False}

def main():
    global OUT, BIN, WORKTREE, FIXTURE, PLAN, CAPTURES
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', default=os.environ.get('GOOO_EXPERIMENT_OUT', str(OUT)))
    parser.add_argument('--fixed-binary', default=os.environ.get('GOOO_FIXED_BIN', str(BIN)))
    parser.add_argument('--worktree', default=os.environ.get('GOOO_WORKTREE', str(WORKTREE)))
    parser.add_argument('--fixture', default=os.environ.get('GOOO_FIXTURE', str(FIXTURE)))
    parser.add_argument('--plan', default=os.environ.get('GOOO_FILL_PLAN', str(PLAN)))
    args = parser.parse_args()
    OUT, BIN, WORKTREE = Path(args.out_dir), Path(args.fixed_binary), Path(args.worktree)
    FIXTURE, PLAN, CAPTURES = Path(args.fixture), Path(args.plan), Path(args.out_dir)/'captures'
    CAPTURES.mkdir(parents=True, exist_ok=True)
    for path in (BIN, WORKTREE, FIXTURE, PLAN):
        if not path.exists():
            raise RuntimeError(f'required path does not exist: {path}')
    clean_binary, worktree = binary_info(BIN), git_info(WORKTREE)
    revision = clean_binary['settings']['vcs.revision']
    if worktree['head'] != revision or not worktree['clean_worktree']:
        raise RuntimeError(f'worktree must be clean at fixed revision {revision}: {worktree}')
    trials = [
        one('01_fixed_binary_immediate_mock', 'fixed_binary'),
        one('02_worktree_go_run_immediate_mock', 'working_tree_go_run'),
        one('03_fixed_binary_delayed_mock_450ms', 'fixed_binary', delay=.45),
        one('04_worktree_go_run_delayed_mock_450ms', 'working_tree_go_run', delay=.45),
        one('05_http_503_deterministic_fallback', 'fixed_binary', status=503, response=b'{"error":"MOCK provider unavailable"}', expected_mode='deterministic_fallback', expected_fallback='PROVIDER_HTTP_ERROR'),
        concurrency_trial(),
        one('07_provider_exceeds_eight_second_context_budget', 'fixed_binary', delay=8.35, timeout=20, expected_mode='deterministic_fallback', expected_fallback='PROVIDER_UNAVAILABLE'),
        repeat_trial(),
    ]
    report = {
      'title': 'Gooo body-codegen IR-fill scheduling experiments (explicit MOCK provider only)',
      'created_utc': datetime.now(timezone.utc).isoformat(), 'date_local': '2026-09-30', 'timezone': 'Asia/Seoul',
      'clean_binary': clean_binary, 'working_tree': worktree,
      'fixture_and_plan': {'fixture': str(FIXTURE), 'plan': str(PLAN), 'example_data_only': True},
      'provider_scope': 'Every request went to an owned ephemeral 127.0.0.1 endpoint with a Python MOCK handler. Port 8787 was neither contacted nor bound. No real Laya service/model was used.',
      'measurement_notes': [
        'Wall time includes process startup; provider timestamps isolate the mock wait.',
        'Concurrent trial launches two independent clean-binary CLI processes; unique mock query markers map each request to the recorded PID.',
        'Working-tree runs use go run; the recorded PID is the go run driver, not its short-lived executed Go child.',
        'The body-fill provider context budget is eight seconds. Timeout trial held the mock response 8.35 seconds and captured client fallback.',
        'The mock returns fixed identity only to exercise scheduling/protocol. This is not model-performance evidence.',
        'Raw stdout, stderr, parsed request payloads, and response-attempt events are persisted under captures/ before report/summary writes.'
      ],
      'trials': trials,
    }
    write_json(OUT/'report.json', report)
    summary=[]
    for trial in trials:
        results=trial.get('results') or [trial.get('result', {})]
        summary.append({'name': trial['name'], 'request_count': trial.get('request_count', trial.get('result', {}).get('request_count')),
                        'provider_overlap': trial.get('provider_overlap_observed'), 'wall_ms': [x.get('wall_ms') for x in results],
                        'pids': [x.get('pid') for x in results], 'exit_codes': [x.get('exit_code') for x in results],
                        'provider_proposal': [x.get('provider_selected_candidate_id') for x in results],
                        'emitted_candidate': [x.get('selected_candidate_id') for x in results], 'decision_modes': [x.get('decision_mode') for x in results],
                        'fallback_reasons': [x.get('fallback_reason') for x in results]})
    write_json(OUT/'summary.json', {'report': str(OUT/'report.json'), 'trial_count': len(trials), 'trials': summary})
    print(json.dumps({'report': str(OUT/'report.json'), 'summary': str(OUT/'summary.json'), 'trial_count': len(trials), 'trials': summary}, indent=2))

if __name__ == '__main__':
    main()
