#!/usr/bin/env python3
"""Check published evidence identities and recompute its separate denominators."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'cohorts/ir-fill-2026-09-30'
FIXED = 'ec4bf3e5f4119118b501c1b45862936eb46b95b7'
MODEL = '55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851'

def read(path):
    return json.loads(path.read_text())

def validate():
    manifest = read(ROOT / 'manifest.json')
    files = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    assert files == set(manifest['files']), 'evidence file set changed'
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name

    composition = read(ROOT / 'composition/fixed.json')
    baseline = read(ROOT / 'composition/baseline.json')
    assert composition['binary']['vcs_revision'] == FIXED
    cases = composition['original_12_cases']
    assert len(cases) == 12
    assert [c['name'] for c in cases] == [c['name'] for c in baseline['original_12_cases']]
    emitted = [c for c in cases if c['command_exit_code'] == 0]
    assert len(emitted) == 11
    seen = [c['independent_go_seen'] for c in emitted]
    held = [c['independent_go_heldout'] for c in emitted]
    assert all(c['exit_code'] == 0 for c in seen)
    assert sum(c['cases_total'] for c in seen) == 55
    assert sum(c['cases_total'] for c in held) == 35
    assert sum(c['exit_code'] == 0 for c in held) == 10
    overfit = next(c for c in cases if c['name'] == 'seen_heldout_mismatch')
    assert overfit['body_fill_accuracy_percent'] == 100
    assert overfit['independent_go_heldout']['cases_passed'] == 0
    assert overfit['independent_go_heldout']['cases_total'] == 4
    assert composition['counts']['original_go_individual_checks'] == 55 + 35
    replay = json.loads(gzip.decompress((ROOT / 'composition/publication-replay.json.gz').read_bytes()))
    assert replay['compiler_vcs_revision_embedded'] == FIXED
    assert replay['assertion_failures'] == []
    assert len(replay['experiments']) == 12
    assert len(replay['revised_boolean_plans']) == 2

    folder = ROOT / 'laya-feedback'
    rows = [json.loads(line) for line in (folder / 'trial_manifest.jsonl').read_text().splitlines()]
    assert len(rows) == 24
    correct = 0
    for row in rows:
        receipt = read(folder / 'receipts' / Path(row['receipt_file']).name)
        assert receipt['mode'] == row['mode'] == 'laya'
        assert receipt['model_revision'] == MODEL
        assert receipt['request_sha256'] == row['request_sha256']
        assert receipt['selected'] == row['selected_id']
        best = max(score['passed'] for score in row['local_score_by_position'].values())
        match = row['local_score_by_position'][receipt['selected']]['passed'] == best
        assert match == row['correct_by_finite_oracle']
        correct += match
    assert correct == 9
    assert read(folder / 'report.json')['accuracy']['correct_overall'] == correct
    smoke = folder / 'fixed-compiler-smoke'
    receipts = sorted((smoke / 'calls').glob('*.stdout.json'))
    assert len(receipts) == 3
    for path in receipts:
        report = read(path)['report']
        body = report['body_fill']
        assert report['compiler_source_sha'] == FIXED
        assert body['evaluator'] == 'gooo/bodycodegen-int64-ast-interpreter/v2'
        assert body['decision']['mode'] == 'laya'
        assert body['proposed_candidate_id'] == 'negate'
        assert body['selected_candidate_id'] == 'zero'
        assert body['test_cases_passed'] == body['test_cases_total'] == 9
    for row in read(smoke / 'resource_samples.json')['calls']:
        path = smoke / 'calls' / Path(row['stdout_file']).name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['stdout_sha256']

    scaling = ROOT / 'scaling/replay'
    rows = read(scaling / 'calls.json')
    assert len(rows) == 20
    for row in rows:
        stdout = gzip.decompress((scaling / row['receipt_path']).read_bytes())
        assert hashlib.sha256(stdout).hexdigest() == row['receipt_sha256']
        report = json.loads(stdout)['report']
        body = report['body_fill']
        assert report['compiler_source_sha'] == FIXED
        assert body['decision']['mode'] == 'deterministic_fallback'
        assert len(body['candidate_scores']) == row['candidate_count']
        assert body['test_cases_passed'] == body['test_cases_total'] == row['test_case_count']
    summary = read(ROOT / 'scheduling/summary.json')
    assert summary['trial_count'] == len(summary['trials']) == 8
    for trial in summary['trials']:
        assert all(code == 0 for code in trial['exit_codes'])
        assert all(choice == 'zero' for choice in trial['emitted_candidate'])
    assert summary['trials'][5]['provider_overlap'] is True
    assert summary['trials'][6]['fallback_reasons'] == ['PROVIDER_UNAVAILABLE']
    print(f'PASS: {len(files)} evidence files; composition, selection, smoke, scheduling, and scaling denominators remain separate')

if __name__ == '__main__':
    validate()
