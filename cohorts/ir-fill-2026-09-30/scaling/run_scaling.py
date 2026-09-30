#!/usr/bin/env python3
"""Four deterministic candidate/test-count treatments, five repeats each; no model."""
import gzip, hashlib, json, os, pathlib, platform, resource, statistics, subprocess, time
from datetime import datetime, timezone
ROOT = pathlib.Path(os.environ.get('GOOO_SCALING_OUT', '/tmp/gooo-ir-fill-scaling-measurements-20260930/replay'))
BIN = pathlib.Path(os.environ['GOOO_BIN']).resolve()
EXPRESSIONS = ['0','input','-input','1','-1','input + 1','input - 1','input * 2','input * 3','input + 2','input - 2','2','-2','3','-3','input * 4']
def digest(data): return hashlib.sha256(data).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2)+'\n')
def main():
    ROOT.mkdir(parents=True, exist_ok=False)
    fixture = ROOT/'clamp.gooo.fixture'
    fixture.write_text('package bodycodegen\nnamespace bodycodegen\nentity Integer id "bodycodegen://entity/integer"\nactivity Clamp(Integer) -> Integer computes "let out = input; if input < 0 { out = __GOOO_BODY_HOLE_expr__ } else { out = input }; return out"\n')
    env = dict(os.environ); env.pop('GOOO_LAYA_URL', None); env.pop('GOOO_LAYA_API_KEY', None)
    metadata = {'schema':'gooo/local-body-fill-scaling/v1', 'started_utc':datetime.now(timezone.utc).isoformat(), 'platform':platform.platform(), 'logical_cpu_count':os.cpu_count(), 'binary_sha256':digest(BIN.read_bytes()), 'build_metadata':subprocess.check_output(['go','version','-m',str(BIN)],text=True), 'fixture_sha256':digest(fixture.read_bytes()), 'laya_configured':False, 'distinct_intents':1, 'treatments':4, 'repeats_per_treatment':5, 'scope':'No Laya. CPU is child CLI CPU time per invocation; Go output is typechecked and scored by v2 but not independently executed in this scaling study. Other local agents ran concurrently, so no isolated-machine throughput claim.'}
    save(ROOT/'metadata.json',metadata)
    records=[]
    for n in [2,16]:
      for t in [9,4096]:
        values=[-2**63,-100,-2,-1,0,1,2,100,2**63-1] if t==9 else list(range(-2048,2048))
        folder=ROOT/f'candidates-{n}-tests-{t}';folder.mkdir()
        plan={'schema':'gooo/body-codegen-ir-fill-plan/v1','intent':'Clamp negative inputs to zero, preserve other inputs.','hole_id':'expr','candidates':[{'id':f'candidate_{i}','expression':e} for i,e in enumerate(EXPRESSIONS[:n])],'test_cases':[{'input':x,'expected':max(0,x)} for x in values]}
        save(folder/'plan.json',plan)
        for repetition in range(1,6):
          before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.perf_counter()
          p=subprocess.run([str(BIN),'body-codegen','--json','--fill-plan',str(folder/'plan.json'),'--activity','Clamp',str(fixture)],env=env,capture_output=True,timeout=30)
          elapsed=time.perf_counter()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
          (folder/f'call-{repetition}.json.gz').write_bytes(gzip.compress(p.stdout,mtime=0))
          (folder/f'call-{repetition}.stderr.txt').write_bytes(p.stderr)
          body=json.loads(p.stdout)['report']['body_fill']
          assert p.returncode==0 and body['evaluator'].endswith('/v2') and body['decision']['mode']=='deterministic_fallback'
          assert body['test_cases_passed']==t and body['selected_candidate_id']=='candidate_0'
          record={'candidate_count':n,'test_case_count':t,'repetition':repetition,'return_code':p.returncode,'cli_wall_ms':elapsed*1000,'child_cpu_ms':((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime))*1000,'receipt_sha256':digest(p.stdout),'receipt_path':str((folder/f'call-{repetition}.json.gz').relative_to(ROOT)),'timing':body['timing'],'test_cases_passed':body['test_cases_passed'],'evaluator':body['evaluator'],'mode':body['decision']['mode']}
          records.append(record);save(ROOT/'calls.json',records)
    summaries=[]
    for n in [2,16]:
      for t in [9,4096]:
        rows=[r for r in records if r['candidate_count']==n and r['test_case_count']==t]
        summary={'candidate_count':n,'test_case_count':t,'calls':len(rows)}
        for key in ['cli_wall_ms','child_cpu_ms']:
          a=[r[key] for r in rows];summary[key]={'median':statistics.median(a),'min':min(a),'max':max(a)}
        for key in ['ir_plan_build_ms','laya_decision_ms','final_emission_ms','total_ms']:
          a=[r['timing'][key] for r in rows];summary[key]={'median':statistics.median(a),'min':min(a),'max':max(a)}
        summaries.append(summary)
    save(ROOT/'report.json',{'metadata':metadata,'treatments':summaries,'calls':records})
    print(json.dumps(summaries,indent=2))
if __name__=='__main__':main()
