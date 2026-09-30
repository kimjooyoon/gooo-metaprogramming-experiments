import argparse, json, os, pathlib, subprocess, time, hashlib, re, sys
from datetime import datetime, timezone

parser = argparse.ArgumentParser(description="Replay the bounded Gooo body-fill corpus and independent Go oracles.")
parser.add_argument("--binary", required=True, help="Path to the gooo binary under test.")
parser.add_argument("--output", required=True, help="Scratch/output directory; all generated fixtures and Go tests are written here.")
parser.add_argument("--source-repo", help="Optional repository checkout used only to record its HEAD and status.")
parser.add_argument("--expected-revision", help="Optional required embedded VCS revision; compared with go version -m output.")
args = parser.parse_args()
ROOT = pathlib.Path(args.output).resolve()
BIN = pathlib.Path(args.binary).resolve()
REPO = pathlib.Path(args.source_repo).resolve() if args.source_repo else None
OUT = ROOT / "corpus"
OUT.mkdir(parents=True, exist_ok=True)
MIN = -(2**63)
MAX = 2**63 - 1

# Each oracle is independently encoded as the cases below, not inferred from the CLI score.
def make_case(name, intent, body, candidates, seen, heldout):
    return {'name':name,'intent':intent,'body':body,'candidates':candidates,'seen':seen,'heldout':heldout}

cases = [
 make_case('nested_clamp', 'Clamp negative values to zero, preserving nonnegative values.',
  'let out = input; if input < 0 { if input < -100 { out = __GOOO_BODY_HOLE_expr__ } else { out = 0 } } else { out = input }; return out',
  [('zero','0'),('identity','input'),('negate','-input')],
  [(MIN,0),(-101,0),(-100,0),(-1,0),(0,0),(1,1),(MAX,MAX)],
  [(-999,0),(-2,0),(3,3),(200,200)]),
 make_case('nested_else_if', 'Take absolute value for negatives, double values from zero through nine, otherwise preserve the input.',
  'let out = input; if input < 0 { out = -input } else if input < 10 { out = __GOOO_BODY_HOLE_expr__ } else { out = input }; return out',
  [('double','input * 2'),('identity','input'),('add_two','input + 2')],
  [(-5,5),(-1,1),(0,0),(1,2),(5,10),(9,18),(10,10),(30,30)],
  [(-100,100),(2,4),(8,16),(11,11)]),
 make_case('sibling_locals_assignment', 'Return absolute value for negatives and add three for nonnegative values.',
  'let out = input; if input < 0 { let branchValue = -input; out = branchValue } else { let adjusted = input; adjusted = __GOOO_BODY_HOLE_expr__; out = adjusted }; return out',
  [('plus_three','input + 3'),('identity','input'),('times_two','input * 2')],
  [(-9,9),(-1,1),(0,3),(1,4),(5,8)],
  [(-100,100),(2,5),(77,80)]),
 make_case('composed_locals', 'Multiply the square plus two by three using the existing composed local.',
  'let square = input * input; let offset = square + 2; let out = offset; out = __GOOO_BODY_HOLE_expr__; return out',
  [('scale_out','out * 3'),('expanded','input * input * 3 + 6'),('wrong_order','input * input + 6')],
  [(-5,81),(-2,18),(0,6),(1,9),(4,54)],
  [(-7,153),(3,33),(10,306)]),
 make_case('short_circuit_and', 'If input is nonzero and below five, double it; otherwise return seven.',
  'let out = input; if input != 0 && input < 5 { out = __GOOO_BODY_HOLE_expr__ } else { out = 7 }; return out',
  [('double','input * 2'),('identity','input'),('seven','7')],
  [(-5,-10),(-1,-2),(0,7),(1,2),(4,8),(5,7)],
  [(-200,-400),(2,4),(6,7)]),
 make_case('short_circuit_or', 'Square values outside the inclusive range from negative three to three; return zero inside it.',
  'let out = input; if input < -3 || input > 3 { out = __GOOO_BODY_HOLE_expr__ } else { out = 0 }; return out',
  [('square','input * input'),('identity','input'),('zero','0')],
  [(-10,100),(-4,16),(-3,0),(0,0),(3,0),(4,16),(10,100)],
  [(-8,64),(-2,0),(5,25)]),
 make_case('constant_fold', 'Return six only for input two; otherwise increment the input.',
  'let out = input + 1; if input == 2 { out = __GOOO_BODY_HOLE_expr__ } else { out = input + 1 }; return out',
  [('folded_product','2 * 3'),('literal_six','6'),('wrong','input + 3')],
  [(-2,-1),(0,1),(1,2),(2,6),(3,4)],
  [(-100,-99),(4,5),(20,21)]),
 make_case('guarded_int64_increment', 'Increment every int64 value except the maximum, which remains unchanged.',
  'let out = input; if input == 9223372036854775807 { out = input } else { out = __GOOO_BODY_HOLE_expr__ }; return out',
  [('increment','input + 1'),('identity','input'),('skip_two','input + 2')],
  [(MIN,MIN+1),(MIN+1,MIN+2),(-1,0),(0,1),(MAX-1,MAX),(MAX,MAX)],
  [(-100,-99),(10,11),(MAX-5,MAX-4)]),
 make_case('seen_heldout_mismatch', 'Return the square of every integer.',
  'return __GOOO_BODY_HOLE_expr__',
  [('identity','input'),('square','input * input')],
  [(0,0),(1,1)],
  [(-2,4),(2,4),(-3,9),(3,9)]),
 make_case('compound_hole_precedence', 'Subtract the expression input plus one from input, then double the result; this is always negative two.',
  'return (input - __GOOO_BODY_HOLE_expr__) * 2',
  [('plus_one','input + 1'),('plus_two','input + 2')],
  [(-3,-2),(0,-2),(4,-2)],
  [(-100,-2),(2,-2),(50,-2)]),
 make_case('false_identifier_shadow', 'Bind false as an integer local and return that local value.',
  'let false = input; return __GOOO_BODY_HOLE_expr__',
  [('false_local','false'),('input','input')],
  [(5,5)],
  [(0,0),(9,9)]),
 make_case('int64_min_literal', 'Return the minimum int64 value, represented as a negated untyped integer literal.',
  'return __GOOO_BODY_HOLE_expr__',
  [('min_literal','-9223372036854775808'),('zero','0')],
  [(0,MIN)],
  [(1,MIN),(-99,MIN)]),
]

assert len(cases) == 12

def fixture_text(name, body):
    return ('package bodycodegen\nnamespace bodycodegen\n'
            'entity Integer id "bodycodegen://entity/integer"\n'
            f'activity {name}(Integer) -> Integer computes "{body}"\n')

def go_test(output_dir, generated_source, activity, tests, label):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'go.mod').write_text('module bodyfillcheck\n\ngo 1.23\n')
    (output_dir / 'generated.go').write_text(generated_source)
    rows = ',\n'.join('{%d, %d}' % (x, y) for x, y in tests)
    test_source = f'''package bodycodegen
import "testing"
func TestIndependent{label}(t *testing.T) {{
  cases := []struct{{in, want int64}}{{{rows}}}
  for _, tc := range cases {{
    if got := {activity}(tc.in); got != tc.want {{ t.Errorf("input %d: got %d, want %d", tc.in, got, tc.want) }}
  }}
}}
'''
    (output_dir / 'generated_test.go').write_text(test_source)
    started = time.monotonic()
    proc = subprocess.run(['go','test','-count=1','-v','./...'],cwd=output_dir,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    elapsed = (time.monotonic()-started)*1000
    failures = len(re.findall(r'input .*: got ', proc.stdout))
    return {'exit_code':proc.returncode,'elapsed_ms':round(elapsed,3),'output':proc.stdout.strip(),'cases_total':len(tests),'cases_passed':len(tests)-failures,'cases_failed':failures}

def run_cli(case, index):
    name = 'Exp%02d' % index
    case_dir = OUT / ('%02d_' % index + case['name'])
    case_dir.mkdir(parents=True, exist_ok=True)
    fx = case_dir / 'fixture.gooo.fixture'
    plan = case_dir / 'plan.json'
    fx.write_text(fixture_text(name, case['body']))
    plan_obj = {
      'schema':'gooo/body-codegen-ir-fill-plan/v1', 'intent':case['intent'], 'hole_id':'expr',
      'candidates':[{'id':i,'expression':e} for i,e in case['candidates']],
      'test_cases':[{'input':x,'expected':y} for x,y in case['seen']]
    }
    plan.write_text(json.dumps(plan_obj,ensure_ascii=False,indent=2)+'\n')
    env = os.environ.copy(); env.pop('GOOO_LAYA_URL',None); env.pop('GOOO_LAYA_API_KEY',None)
    cmd = [str(BIN),'body-codegen','--json','--fill-plan',str(plan),'--activity',name,str(fx)]
    started = time.monotonic()
    proc = subprocess.run(cmd,cwd=case_dir,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    elapsed = (time.monotonic()-started)*1000
    record = {'case':case['name'],'command_exit_code':proc.returncode,'cli_elapsed_ms':round(elapsed,3),'stdout':proc.stdout,'stderr':proc.stderr,'seen_cases':len(case['seen']),'heldout_cases':len(case['heldout'])}
    parsed = None
    try: parsed = json.loads(proc.stdout)
    except Exception as exc: record['json_parse_error'] = str(exc)
    if parsed is not None:
      record['decision'] = parsed.get('report',{}).get('decision')
      report = parsed.get('report',{})
      record['body_fill'] = report.get('body_fill')
      record['generated_source'] = parsed.get('source','')
      record['error'] = parsed.get('error')
      if parsed.get('source'):
        record['independent_go_seen'] = go_test(case_dir/'independent_seen', parsed['source'], name, case['seen'], 'Seen')
        record['independent_go_heldout'] = go_test(case_dir/'independent_heldout', parsed['source'], name, case['heldout'], 'Heldout')
    (case_dir/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return record

results=[]
for i, case in enumerate(cases,1):
    results.append(run_cli(case,i))

# Separate focused reproductions: same-name lexical shadow rejection, true-name evaluator resolution, and CLI error handling.
def run_probe(probe_name, body, candidate_list, tests, heldout, activity):
    probe_dir=OUT/'probes'/probe_name
    probe_dir.mkdir(parents=True,exist_ok=True)
    fx=probe_dir/'fixture.gooo.fixture'; plan=probe_dir/'plan.json'
    fx.write_text(fixture_text(activity,body))
    plan.write_text(json.dumps({'schema':'gooo/body-codegen-ir-fill-plan/v1','intent':probe_name,'hole_id':'expr','candidates':[{'id':i,'expression':e} for i,e in candidate_list],'test_cases':[{'input':x,'expected':y} for x,y in tests]},indent=2)+'\n')
    env=os.environ.copy(); env.pop('GOOO_LAYA_URL',None); env.pop('GOOO_LAYA_API_KEY',None)
    started=time.monotonic(); proc=subprocess.run([str(BIN),'body-codegen','--json','--fill-plan',str(plan),'--activity',activity,str(fx)],cwd=probe_dir,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE); elapsed=(time.monotonic()-started)*1000
    record={'probe':probe_name,'command_exit_code':proc.returncode,'cli_elapsed_ms':round(elapsed,3),'stdout':proc.stdout,'stderr':proc.stderr,'seen_cases':len(tests)}
    try:
      parsed=json.loads(proc.stdout); record['parsed']=parsed
      if parsed.get('source'):
        record['independent_go_seen']=go_test(probe_dir/'independent_seen',parsed['source'],activity,tests,'ProbeSeen')
        record['independent_go_heldout']=go_test(probe_dir/'independent_heldout',parsed['source'],activity,heldout,'ProbeHeldout')
    except Exception as exc: record['json_parse_error']=str(exc)
    (probe_dir/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return record

probes=[]
probes.append(run_probe('nested_same_name_shadow',
 'let value = input; if input > 0 { let value = __GOOO_BODY_HOLE_expr__; return value } else { return value }',
 [('one','1'),('input','input')],[(1,1),(-1,-1)],[(-3,-3),(2,2)],'ShadowValue'))
probes.append(run_probe('true_identifier_shadow',
 'let true = input; return __GOOO_BODY_HOLE_expr__',
 [('true_local','true'),('input','input')],[(5,5)],[(0,0),(9,9)],'ShadowTrue'))

# Revised plans keep the same local-binding intent but make every candidate use the local,
# avoiding an unused-declaration failure unrelated to lexical-value resolution.
revised_plans=[]
revised_plans.append(run_probe('false_identifier_shadow_revised',
 'let false = input; return __GOOO_BODY_HOLE_expr__',
 [('false_local','false'),('add_zero','false + 0')],[(5,5)],[(0,0),(9,9)],'FocusedFalse'))
revised_plans.append(run_probe('true_identifier_shadow_revised',
 'let true = input; return __GOOO_BODY_HOLE_expr__',
 [('true_local','true'),('add_zero','true + 0')],[(5,5)],[(0,0),(9,9)],'FocusedTrue'))

# Hand-authored Go confirms language-level semantics when the Gooo path exits before output.
manual_dir=OUT/'probes'/'manual_go_repros'; manual_dir.mkdir(parents=True,exist_ok=True)
manual_sources={
 'false_shadow.go': '''package bodycodegen\nfunc ManualFalseShadow(input int64) int64 { var false = input; return false }\n''',
 'true_shadow.go': '''package bodycodegen\nfunc ManualTrueShadow(input int64) int64 { var true = input; return true }\n''',
 'min_literal.go': '''package bodycodegen\nfunc ManualMinLiteral(input int64) int64 { return -9223372036854775808 }\n''',
}
(manual_dir/'go.mod').write_text('module bodyfillcheck\n\ngo 1.23\n')
for filename, source in manual_sources.items(): (manual_dir/filename).write_text(source)
(manual_dir/'manual_test.go').write_text('''package bodycodegen\nimport "testing"\nfunc TestManualLanguageRepros(t *testing.T) {\n if ManualFalseShadow(5)!=5 { t.Fatal("false local should resolve to integer local") }; if ManualTrueShadow(6)!=6 { t.Fatal("true local should resolve to integer local") }; if ManualMinLiteral(0)!=-9223372036854775808 { t.Fatal("minimum int64 literal should compile") }\n}\n''')
manual_started=time.monotonic(); manual_proc=subprocess.run(['go','test','-count=1','-v','./...'],cwd=manual_dir,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT); manual_ms=(time.monotonic()-manual_started)*1000

# Capture reproducible build/runtime provenance for the supplied fixed binary.
version=subprocess.run(['go','version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout.strip()
buildinfo=subprocess.run(['go','version','-m',str(BIN)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT).stdout.strip()
current_head=subprocess.run(['git','-C',str(REPO),'rev-parse','HEAD'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.strip() if REPO else None
current_status=subprocess.run(['git','-C',str(REPO),'status','--porcelain'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.strip() if REPO else None
revision_match=re.search(r'build\s+vcs.revision=(\S+)', buildinfo)
embedded_revision=revision_match.group(1) if revision_match else None

results_path=ROOT/'results.json'
metadata={
 'schema':'gooo/body-codegen-experiment-corpus/v1','created_utc':datetime.now(timezone.utc).isoformat(),
 'workspace':str(ROOT),'corpus_count':len(cases),'supplemental_probe_count':len(probes),'manual_go_repro_count':3,
 'laya_configured':False,'binary_path':str(BIN),'binary_sha256':subprocess.check_output(['shasum','-a','256',str(BIN)],text=True).split()[0],
 'binary_size_bytes':pathlib.Path(BIN).stat().st_size,'compiler_vcs_revision_embedded':embedded_revision,'expected_compiler_revision':args.expected_revision,
 'worktree_head_at_collection':current_head,'worktree_status_at_collection':current_status,
 'go_launcher_version':version,'go_build_metadata':buildinfo,
 'independent_verification':'Each emitted source was placed in its own temporary Go module and compiled/executed via go test with hand-specified seen and held-out input/output pairs. No test ran against repository files.',
 'experiments':results,'supplemental_probes':probes,'revised_boolean_plans':revised_plans,
 'manual_go_repros':{'exit_code':manual_proc.returncode,'elapsed_ms':round(manual_ms,3),'output':manual_proc.stdout.strip(), 'sources':list(manual_sources)},
}
results_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')

# Short, human-readable report derives only from the recorded experiment artifacts.
lines=['# Gooo body-codegen fixed corpus run', '',
       f'- Completed: {len(cases)} original cases, {len(probes)} original probes, {len(revised_plans)} revised boolean-binding plans, and {len(manual_sources)} standalone Go reproductions.',
       f'- Binary: `{BIN}`; embedded VCS revision `{metadata["compiler_vcs_revision_embedded"]}`; Laya disconnected.',
       f'- Current shared worktree at result capture: `{current_head}`; fixed binary is clean and commit-bound.',
       f'- Host launcher: `{version}`; binary toolchain metadata is recorded in `results.json`.',
       '- `functional_accuracy_percent` and candidate scores are Gooo’s finite declared-suite AST-interpreter results. Independent `go test` outcomes below compile and execute the emitted Go against the same suite and hand-selected held-out cases.', '',
       '| # | Case | Gooo result / suite | Selected | Independent seen | Held-out |', '|---:|---|---:|---|---:|---:|']
for i,r in enumerate(results,1):
    fill=r.get('body_fill') or {}
    seen=r.get('independent_go_seen')
    held=r.get('independent_go_heldout')
    seen_s=('pass' if seen and seen['exit_code']==0 else ('fail' if seen else 'not emitted'))
    held_s=('pass' if held and held['exit_code']==0 else ('fail' if held else 'not emitted'))
    lines.append(f"| {i} | {r['case']} | {r.get('decision','?')} / {fill.get('functional_accuracy_percent','n/a')}% | {fill.get('selected_candidate_id','n/a')} | {seen_s} | {held_s} |")
lines += ['', '## Exact findings', '']
for i,r in enumerate(results,1):
    name=r['case']; fill=r.get('body_fill') or {}
    if name=='seen_heldout_mismatch':
      lines.append(f"- `seen_heldout_mismatch`: Gooo reports {fill.get('functional_accuracy_percent')}% and retains `{fill.get('selected_candidate_id')}` on two seen cases; independently compiled Go fails the four held-out square checks. The selected identity produces only {r.get('independent_go_heldout',{}).get('cases_passed','?')}/4 held-out matches; the finite-suite limitation remains.")
    if name=='compound_hole_precedence':
      lines.append(f"- `compound_hole_precedence`: emitted `{r.get('generated_source','').split('return ')[-1].splitlines()[0] if r.get('generated_source') else 'none'}`. Gooo reports {fill.get('functional_accuracy_percent')}%; independent Go results are seen={r.get('independent_go_seen',{}).get('exit_code')} and held-out={r.get('independent_go_heldout',{}).get('exit_code')}.")
    if name in ('false_identifier_shadow','int64_min_literal'):
      lines.append(f"- `{name}`: CLI exit {r['command_exit_code']}; decision={r.get('decision')!r}; selected={((r.get('body_fill') or {}).get('selected_candidate_id'))!r}; error={r.get('error')!r}.")
for p in probes:
    parsed=p.get('parsed') or {}
    lines.append(f"- Supplemental `{p['probe']}`: exit {p['command_exit_code']}; output `{p['stdout'].strip()}`; parsed decision/error `{parsed.get('decision')!r}` / `{parsed.get('error')!r}`.")
lines.append(f"- Independent manual Go semantics checks: exit {manual_proc.returncode}; {manual_proc.stdout.strip().replace(chr(10), ' ')}")
lines += ['', '## Most useful language extension', '',
          'Make the body hole a typed expression node in the Go AST (or guarantee parenthesized substitution), then resolve lexical bindings with scoped environments and Go constant semantics in the evaluator. Add a compile-and-run oracle boundary for emitted functions so the reported candidate score cannot be mistaken for independent execution. The highest leverage user-facing extension is multiple typed holes or typed parameter/result profiles only after these semantic boundaries are exact.', '',
          'Full per-case JSON, emitted source, fixture, plans, timings, independent test output, and failure reproductions are in `results.json` and `corpus/`.', '']
(ROOT/'report.md').write_text('\n'.join(lines))
# Machine assertions: exact expected limitations remain visible; every other outcome must pass.
issues=[]
if args.expected_revision and embedded_revision != args.expected_revision: issues.append(f'compiler revision mismatch: embedded {embedded_revision!r}, expected {args.expected_revision!r}')
if 'build\tvcs.modified=false' not in buildinfo: issues.append('compiler binary does not report vcs.modified=false')
by_name={r['case']:r for r in results}
if len(results)!=12 or set(by_name)!={c['name'] for c in cases}: issues.append('corpus must contain the exact 12 named cases')
for r in results:
    name=r['case']
    if name=='false_identifier_shadow':
        if r['command_exit_code']!=1 or not (r.get('error') and 'declared and not used: false' in r['error']): issues.append('false_identifier_shadow must fail closed on the unused input candidate')
        continue
    if r.get('decision')!='PASS': issues.append(f'{name} did not emit PASS')
    if (r.get('body_fill') or {}).get('functional_accuracy_percent')!=100: issues.append(f'{name} did not score 100% on its declared suite')
    for suite in ('independent_go_seen','independent_go_heldout'):
        check=r.get(suite)
        if check:
            intentional=(name=='seen_heldout_mismatch' and suite=='independent_go_heldout')
            if intentional:
                if check['cases_total']!=4 or check['cases_failed']!=4: issues.append('seen_heldout_mismatch must fail exactly four held-out outputs')
            elif check['exit_code']!=0 or check['cases_failed']!=0: issues.append(f'{name} {suite} must compile and pass')
        elif suite=='independent_go_seen': issues.append(f'{name} has no emitted-Go seen oracle')
if sum(bool(r.get('independent_go_seen')) for r in results)!=11: issues.append('expected 11 emitted core functions with seen Go checks')
heldout_pass=sum(bool(r.get('independent_go_heldout')) and r['independent_go_heldout']['cases_failed']==0 for r in results)
if heldout_pass!=10: issues.append('expected 10 passing held-out suites plus the one intentional mismatch')
by_probe={r['probe']:r for r in probes}
shadow=by_probe.get('nested_same_name_shadow',{}).get('parsed') or {}
if by_probe.get('nested_same_name_shadow',{}).get('command_exit_code')!=1 or shadow.get('decision')!='FAIL_CLOSED': issues.append('nested same-name shadow must be rejected with nonzero FAIL_CLOSED')
true_original=by_probe.get('true_identifier_shadow',{}).get('parsed') or {}
if by_probe.get('true_identifier_shadow',{}).get('command_exit_code')!=1 or true_original.get('decision')!='FAIL_CLOSED': issues.append('original true-local candidate set must be rejected because its alternate leaves true unused')
by_revised={r['probe']:r for r in revised_plans}
for label in ('false_identifier_shadow_revised','true_identifier_shadow_revised'):
    item=by_revised.get(label,{})
    parsed=item.get('parsed') or {}
    check=item.get('independent_go_heldout')
    seen_check=item.get('independent_go_seen')
    if item.get('command_exit_code')!=0 or parsed.get('report',{}).get('decision')!='PASS' or parsed.get('report',{}).get('body_fill',{}).get('functional_accuracy_percent')!=100: issues.append(f'{label} must score 100% and emit PASS')
    if not check or check['exit_code']!=0 or check['cases_total']!=2 or check['cases_passed']!=2: issues.append(f'{label} must pass both independent held-out Go cases')
    if not seen_check or seen_check['exit_code']!=0 or seen_check['cases_total']!=1 or seen_check['cases_passed']!=1: issues.append(f'{label} must pass its one independent seen Go case')
if manual_proc.returncode!=0: issues.append('manual Go language reproductions must pass')
metadata['assertion_failures']=issues
results_path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
if issues:
    print(json.dumps({'assertion_failures':issues},indent=2),file=sys.stderr)
    sys.exit(1)
print(json.dumps({'results':str(results_path),'report':str(ROOT/'report.md'),'corpus_count':len(results),'probes':len(probes),'manual_go_exit':manual_proc.returncode,'summary':[{'case':r['case'],'exit':r['command_exit_code'],'decision':r.get('decision'),'accuracy':(r.get('body_fill') or {}).get('functional_accuracy_percent'),'ind_seen':(r.get('independent_go_seen') or {}).get('exit_code'),'ind_held':(r.get('independent_go_heldout') or {}).get('exit_code')} for r in results]},indent=2))
