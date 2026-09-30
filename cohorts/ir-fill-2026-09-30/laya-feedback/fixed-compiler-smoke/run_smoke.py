#!/usr/bin/env python3
"""Three direct body-codegen fill-plan calls; persist measurements before analysis."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit, urlunsplit

DEFAULT_ROOT = Path(os.environ.get('GOOO_LAYA_SMOKE_DIR', '/tmp/gooo-luna-laya-feedback-20260930/fixed-compiler-smoke'))
DEFAULT_BIN = Path(os.environ.get('GOOO_BINARY', '/tmp/gooo-ir-fill-fixed-20260930'))
DEFAULT_REPO = Path(os.environ.get('GOOO_REPO_ROOT', '/Users/alice/meta-go/.worktrees/gooo-autonomous-governance-20260930'))
DEFAULT_PLAN = Path(os.environ.get('GOOO_LAYA_FILL_PLAN', str(DEFAULT_REPO / 'examples/body-codegen/ir-fill-clamp-plan.json')))
DEFAULT_FIXTURE = Path(os.environ.get('GOOO_LAYA_FILL_FIXTURE', str(DEFAULT_REPO / 'examples/body-codegen/ir-fill-clamp.gooo.fixture')))
DEFAULT_ENDPOINT = os.environ.get('GOOO_LAYA_URL', 'http://127.0.0.1:8787/v1/systemone')
DEFAULT_SERVER_PID = int(os.environ.get('LAYA_SERVER_PID', '61962'))
DEFAULT_REVISION = os.environ.get('LAYA_EXPECTED_REVISION', '55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851')
DEFAULT_TIMEOUT = int(os.environ.get('GOOO_LAYA_CALL_TIMEOUT_SECONDS', '15'))
ROOT, BIN, PLAN, FIXTURE = DEFAULT_ROOT, DEFAULT_BIN, DEFAULT_PLAN, DEFAULT_FIXTURE
ENDPOINT, HEALTH, SERVER_PID = DEFAULT_ENDPOINT, '', DEFAULT_SERVER_PID
EXPECTED_REVISION, TIMEOUT_SECONDS = DEFAULT_REVISION, DEFAULT_TIMEOUT


def configure():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default=str(DEFAULT_ROOT))
    parser.add_argument('--binary', default=str(DEFAULT_BIN), help='fixed prebuilt Gooo binary')
    parser.add_argument('--plan', default=str(DEFAULT_PLAN))
    parser.add_argument('--fixture', default=str(DEFAULT_FIXTURE))
    parser.add_argument('--endpoint', default=DEFAULT_ENDPOINT, help='Laya /v1/systemone URL')
    parser.add_argument('--server-pid', type=int, default=DEFAULT_SERVER_PID, help='Laya server PID for CPU/RSS sampling')
    parser.add_argument('--expected-revision', default=DEFAULT_REVISION)
    parser.add_argument('--timeout-seconds', type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    global ROOT, BIN, PLAN, FIXTURE, ENDPOINT, HEALTH, SERVER_PID, EXPECTED_REVISION, TIMEOUT_SECONDS
    ROOT = Path(args.output_dir).expanduser().resolve()
    BIN = Path(args.binary).expanduser().resolve()
    PLAN = Path(args.plan).expanduser().resolve()
    FIXTURE = Path(args.fixture).expanduser().resolve()
    ENDPOINT = args.endpoint.rstrip('/')
    parsed = urlsplit(ENDPOINT)
    base_path = parsed.path[:-len('/v1/systemone')] if parsed.path.endswith('/v1/systemone') else parsed.path
    HEALTH = urlunsplit((parsed.scheme, parsed.netloc, base_path.rstrip('/') + '/health', '', ''))
    SERVER_PID = args.server_pid
    EXPECTED_REVISION = args.expected_revision
    TIMEOUT_SECONDS = args.timeout_seconds
    return args


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ps_sample():
    raw = subprocess.check_output(['ps', '-p', str(SERVER_PID), '-o', 'time=,rss='], text=True).strip()
    fields = raw.split()
    if len(fields) != 2:
        raise RuntimeError(f'unexpected ps output {raw!r}')
    clock = fields[0]
    components = clock.split(':')
    if len(components) == 3:
        cpu_seconds = int(components[0]) * 3600 + int(components[1]) * 60 + float(components[2])
    elif len(components) == 2:
        cpu_seconds = int(components[0]) * 60 + float(components[1])
    else:
        cpu_seconds = float(clock)
    return {'cpu_seconds': cpu_seconds, 'rss_kb': int(fields[1])}


def save(path, value):
    path = Path(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    configure()
    ROOT.mkdir(parents=True, exist_ok=True)
    calls_dir = ROOT / 'calls'
    calls_dir.mkdir(parents=True, exist_ok=True)
    if any(calls_dir.iterdir()):
        raise RuntimeError(f'refusing to overwrite existing smoke artifacts in {calls_dir}')
    with urllib.request.urlopen(HEALTH, timeout=3) as response:
        health = json.load(response)
    if health.get('device') != 'cpu' or health.get('revisions', {}).get('english') != EXPECTED_REVISION:
        raise RuntimeError(f'unexpected existing server: {health!r}')

    metadata = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'server_pid': SERVER_PID,
        'endpoint': ENDPOINT,
        'health_before': health,
        'binary': str(BIN),
        'binary_sha256': sha(BIN),
        'binary_go_version_m': subprocess.check_output(['go', 'version', '-m', str(BIN)], text=True),
        'plan': str(PLAN),
        'plan_sha256_file': sha(PLAN),
        'fixture': str(FIXTURE),
        'fixture_sha256_file': sha(FIXTURE),
        'run_type': 'three direct body-codegen --fill-plan commands; service pre-warmed by earlier selection trials; no extra model warm-up request',
        'expected_revision': EXPECTED_REVISION,
        'timeout_seconds_per_call': TIMEOUT_SECONDS,
    }
    save(ROOT / 'run_metadata.json', metadata)

    measures = []
    for index in range(1, 4):
        stem = f'call-{index:02d}'
        stdout_path = calls_dir / f'{stem}.stdout.json'
        stderr_path = calls_dir / f'{stem}.stderr.txt'
        resource_path = calls_dir / f'{stem}.resource.json'
        started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
        before = ps_sample()
        max_rss_kb = before['rss_kb']
        stop = threading.Event()
        def sample_loop():
            nonlocal max_rss_kb
            while not stop.wait(0.05):
                try:
                    max_rss_kb = max(max_rss_kb, ps_sample()['rss_kb'])
                except Exception:
                    pass
        sampler = threading.Thread(target=sample_loop, daemon=True)
        sampler.start()
        start = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                [str(BIN), 'body-codegen', '--json', '--fill-plan', str(PLAN), '--activity', 'ClampNegativeToZero', str(FIXTURE)],
                env={**os.environ, 'GOOO_LAYA_URL': ENDPOINT},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            rc = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            rc = None
            stdout = exc.stdout or b''
            stderr = exc.stderr or b''
        elapsed_ms = (time.perf_counter() - start) * 1000
        stop.set()
        sampler.join(timeout=2)
        after = ps_sample()
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        measurement = {
            'call': index,
            'started_utc': started_utc,
            'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'timeout': timed_out,
            'return_code': rc,
            'elapsed_ms': round(elapsed_ms, 3),
            'server_cpu_start_seconds': before['cpu_seconds'],
            'server_cpu_end_seconds': after['cpu_seconds'],
            'server_cpu_delta_seconds_ps_resolution_0.01s': round(after['cpu_seconds'] - before['cpu_seconds'], 2),
            'server_rss_start_kb': before['rss_kb'],
            'server_rss_max_sampled_kb': max_rss_kb,
            'server_rss_end_kb': after['rss_kb'],
            'rss_sample_interval_seconds': 0.05,
            'stdout_file': str(stdout_path),
            'stderr_file': str(stderr_path),
            'stdout_sha256': sha(stdout_path),
            'stderr_sha256': sha(stderr_path),
        }
        # Persist raw resource/time observations before parsing or summarizing
        # this call's potentially large body-codegen receipt.
        save(resource_path, measurement)
        measures.append(measurement)
    aggregate = {
        'calls': measures,
        'total_elapsed_ms': round(sum(m['elapsed_ms'] for m in measures), 3),
        'total_server_cpu_delta_seconds': round(sum(m['server_cpu_delta_seconds_ps_resolution_0.01s'] for m in measures), 2),
        'max_sampled_rss_kb': max(m['server_rss_max_sampled_kb'] for m in measures),
        'resource_note': 'Process CPU is a server-wide delta measured per command, rounded by macOS ps to 0.01 seconds. RSS maxima are sampled every 0.05 seconds. This cohort is separate from the 24 selection trials.',
    }
    # Persist the complete raw per-call measurements as soon as the call cohort
    # completes and before report formatting or receipt interpretation.
    save(ROOT / 'resource_samples.json', aggregate)
    print(json.dumps({'cohort': 'fixed_compiler_smoke', 'calls': len(measures), 'resource_file': str(ROOT / 'resource_samples.json'), 'raw_receipt_dir': str(calls_dir)}, indent=2))

if __name__ == '__main__':
    main()
