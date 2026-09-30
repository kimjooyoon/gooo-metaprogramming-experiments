#!/usr/bin/env python3
"""Run bounded Gooo IR-search robustness treatments against a loopback MOCK provider."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, http.server, json, os, re, signal, socket, subprocess, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PRIMARY = HERE.parent / "ir-search-2026-09-30"
EXPECTED_SHA = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"
EXPECTED_REVISION = "29d44bc778d85aee03b9af500bd83dc98f368189"
HOLDOUT_SENTINELS = [-9223372036854775808, 1, 4]

TREATMENTS = [
    {"id":"unconfigured_fallback", "kind":"no_provider", "expected":"deterministic"},
    {"id":"http_503_fallback", "kind":"response", "steps":[{"status":503,"body":{"error":"MOCK unavailable"}}], "expected":"deterministic"},
    {"id":"malformed_json_fallback", "kind":"response", "steps":[{"status":200,"raw":"{MOCK malformed"}], "expected":"deterministic"},
    {"id":"missing_choice_fallback", "kind":"response", "steps":[{"status":200,"body":{"model":"MOCK","answers":{},"usage":{}}}], "expected":"deterministic"},
    {"id":"unknown_choice_fallback", "kind":"response", "steps":[{"status":200,"choice":"not-in-options"}], "expected":"deterministic"},
    {"id":"failure_feedback_privacy", "kind":"response", "steps":[{"choice":"identity"},{"choice":"zero"}], "expected":"train_perfect_after_failure"},
    {"id":"repeated_tried_choice", "kind":"response", "steps":[{"choice":"identity"},{"choice":"identity"},{"choice":"zero"}], "expected":"no_reselection"},
    {"id":"invalid_expression_then_valid", "kind":"response", "steps":[{"choice":"broken"},{"choice":"zero"}], "expected":"parse_rejection_then_success", "candidate_override":[{"id":"broken","expression":"input +"},{"id":"negate","expression":"-input"},{"id":"zero","expression":"0"}]},
    {"id":"type_mismatch_then_valid", "kind":"response", "steps":[{"choice":"boolean"},{"choice":"zero"}], "expected":"type_rejection_then_success", "candidate_override":[{"id":"boolean","expression":"true"},{"id":"negate","expression":"-input"},{"id":"zero","expression":"0"}]},
    {"id":"training_perfect_holdout_failure", "kind":"response", "steps":[{"choice":"identity"}], "expected":"holdout_failure",
     "training_override":[{"input":0,"expected":0},{"input":1,"expected":1},{"input":4,"expected":4}],
     "holdout_override":[{"input":-1,"expected":0},{"input":-2,"expected":0},{"input":-17,"expected":0},{"input":-9223372036854775808,"expected":0}]},
    {"id":"provider_budget_timeout", "kind":"delay", "delay_ms":9000, "steps":[{"choice":"zero"}], "expected":"timeout_or_fallback", "process_timeout_ms":9800},
    {"id":"cancel_inflight_provider", "kind":"delay", "delay_ms":5000, "steps":[{"choice":"zero"}], "expected":"runner_cancelled", "cancel_after_ms":350},
]


def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(b: bytes): return hashlib.sha256(b).hexdigest()
def dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
def write_raw(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    with path.open("rb") as f: os.fsync(f.fileno())

class MockProvider:
    """Local-only /v1/systemone responder; every request and response is raw-captured."""
    def __init__(self, out_dir: Path, treatment):
        self.out_dir, self.treatment = out_dir, treatment
        self.lock = threading.Lock(); self.seq = 0; self.steps = list(treatment.get("steps", []))
        self.events = []; self.released = threading.Event()
        outer = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_): pass
            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0")); body = self.rfile.read(min(n, 2*1024*1024))
                request_started_utc = now()
                with outer.lock:
                    outer.seq += 1; seq = outer.seq
                    step = outer.steps.pop(0) if outer.steps else {"choice":"zero"}
                req_path = outer.out_dir / "requests" / f"{seq:02d}.request.raw"
                res_path = outer.out_dir / "responses" / f"{seq:02d}.response.raw"
                write_raw(req_path, body)
                wait_ms = step.get("delay_ms", outer.treatment.get("delay_ms", 0)) if outer.treatment.get("kind") == "delay" else 0
                if wait_ms:
                    outer.released.wait(wait_ms / 1000)
                if "raw" in step:
                    response = step["raw"].encode("utf-8"); status = step.get("status", 200)
                elif "body" in step:
                    response = json.dumps(step["body"], separators=(",", ":")).encode(); status = step.get("status", 200)
                else:
                    try:
                        req = json.loads(body); question = req.get("questions", {}).get("body_ir_search", {})
                        options = question.get("criteria", {})
                        probs = {k: round(1 / max(1, len(options)), 4) for k in options}
                    except Exception:
                        options, probs = {}, {}
                    answer = {"type":"choice", "choice":step.get("choice", "zero"), "probabilities":probs,
                              "confidence":0.5, "answer_confidence":0.5, "action":{"act_probability":1.0}}
                    response = json.dumps({"model":"MOCK local fixture", "answers":{"body_ir_search":answer},
                        "usage":{"input_tokens":0,"output_tokens":0}, "routing":{"model":"MOCK","repo":"local-only","reason":"MOCK treatment"}}, separators=(",", ":")).encode()
                    status = step.get("status", 200)
                write_raw(res_path, response)
                event = {"seq":seq,"label":"MOCK","started_utc":request_started_utc,"completed_utc":now(),"method":"POST","path":self.path,
                         "status":status,"request_file":str(req_path.relative_to(outer.out_dir)),"response_file":str(res_path.relative_to(outer.out_dir)),
                         "request_sha256":sha(body),"response_sha256":sha(response),"delay_ms":wait_ms}
                with outer.lock:
                    outer.events.append(event)
                    with (outer.out_dir / "events.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(event,sort_keys=True)+"\n"); f.flush(); os.fsync(f.fileno())
                try:
                    self.send_response(status); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(response))); self.send_header("Connection","close"); self.end_headers(); self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                self.close_connection = True
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/systemone"
    def stop(self):
        self.released.set(); self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)


def check_binary(binary, supplied_sha):
    if sha(binary.read_bytes()) != supplied_sha or supplied_sha != EXPECTED_SHA:
        raise RuntimeError("canonical frozen compiler SHA-256 mismatch")
    m = subprocess.run(["go","version","-m",str(binary)],capture_output=True,text=True,check=True).stdout
    rev = re.search(r"vcs\.revision=(\S+)",m); mod = re.search(r"vcs\.modified=(\S+)",m)
    if not rev or rev.group(1) != EXPECTED_REVISION or not mod or mod.group(1) != "false":
        raise RuntimeError("compiler revision/clean-tree build metadata mismatch")


def activity_from(fixture):
    m = re.search(r"^activity\s+(\w+)\(", fixture, re.M)
    if not m: raise RuntimeError("could not determine fixture activity")
    return m.group(1)


def run_one(binary, treatment, run_dir):
    tid = treatment["id"]; out = run_dir / "treatments" / tid
    out.mkdir(parents=True, exist_ok=False)
    fixture_raw = (PRIMARY / "fixtures" / "clamp.gooo.fixture").read_bytes()
    plan = json.loads((PRIMARY / "plans" / "clamp.search-plan.json").read_text())
    if "candidate_override" in treatment: plan["candidates"] = treatment["candidate_override"]
    if "training_override" in treatment: plan["test_cases"] = treatment["training_override"]
    if "holdout_override" in treatment: plan["holdout_test_cases"] = treatment["holdout_override"]
    plan["max_attempts"] = 3
    # Preserve a disjoint finite holdout; inputs 1, 4, and MinInt64 are sentinels for request privacy assertions.
    write_raw(out / "fixture.gooo.fixture", fixture_raw)
    dump(out / "plan.json", plan)
    steps = treatment.get("steps", [])
    mock = None
    if treatment["kind"] != "no_provider":
        mock = MockProvider(out / "mock_provider", treatment)
    command = [str(binary),"body-codegen","--json","--fill-search",str(out / "plan.json"),"--activity",activity_from(fixture_raw.decode()),str(out / "fixture.gooo.fixture")]
    env = os.environ.copy(); env.pop("GOOO_LAYA_API_KEY", None); env.pop("GOOO_LAYA_URL", None)
    if mock: env["GOOO_LAYA_URL"] = mock.url
    started = time.monotonic(); started_utc = now(); p = subprocess.Popen(command,cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    canceled = False; timeout_ms = treatment.get("process_timeout_ms",4000)
    try:
        if "cancel_after_ms" in treatment:
            time.sleep(treatment["cancel_after_ms"]/1000)
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM); canceled=True
        try: stdout,stderr = p.communicate(timeout=max(0.1,(timeout_ms-(time.monotonic()-started)*1000)/1000))
        except subprocess.TimeoutExpired:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM); canceled=True
            try: stdout,stderr = p.communicate(timeout=0.75)
            except subprocess.TimeoutExpired:
                if p.poll() is None: os.killpg(p.pid,signal.SIGKILL)
                stdout,stderr = p.communicate(timeout=1)
    finally:
        if mock: mock.stop()
    elapsed = time.monotonic()-started
    write_raw(out/"stdout.raw",stdout); write_raw(out/"stderr.raw",stderr)
    stdout_json = None
    try: stdout_json=json.loads(stdout).get("report",{})
    except Exception: pass
    body = stdout_json.get("body_search",{}) if stdout_json else {}
    receipt = {"schema":"gooo/ir-search-fault-invocation/v1","label":"MOCK_PROVIDER_TREATMENT" if mock else "NO_PROVIDER_CONTROL",
        "treatment_id":tid,"expected_probe":treatment["expected"],"started_utc":started_utc,"completed_utc":now(),"wall_ms":elapsed*1000,
        "argv":command,"exit_code":p.returncode,"runner_cancelled":canceled,"binary_sha256":sha(binary.read_bytes()),
        "fixture_sha256":sha(fixture_raw),"plan_sha256":sha((out/"plan.json").read_bytes()),"stdout_sha256":sha(stdout),"stderr_sha256":sha(stderr),
        "stdout_file":"stdout.raw","stderr_file":"stderr.raw","provider_request_count":len(mock.events) if mock else 0,
        "provider_events":mock.events if mock else [], "selected_candidate_id":body.get("selected_candidate_id"),
        "stop_reason":body.get("stop_reason"),"training_passed":body.get("training_passed"),"training_total":body.get("training_total"),
        "holdout_passed":body.get("holdout_passed"),"holdout_total":body.get("holdout_total"),"attempts":body.get("attempts",[]),
        "provider_budget_used_ms":body.get("provider_budget_used_ms")}
    dump(out/"invocation.json",receipt)
    return receipt


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--execute",action="store_true"); ap.add_argument("--binary",type=Path,required=True); ap.add_argument("--sha256",required=True); ap.add_argument("--run-id",default="mock-provider-run-2026-09-30")
    args=ap.parse_args()
    if not args.execute: raise SystemExit("refusing to run; pass --execute explicitly")
    binary=args.binary.resolve(); check_binary(binary,args.sha256)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",args.run_id): raise SystemExit("unsafe run id")
    run_dir=HERE/"runs"/args.run_id
    if run_dir.exists(): raise SystemExit(f"refusing to overwrite saved evidence: {run_dir}")
    run_dir.mkdir(parents=True)
    manifest={"schema":"gooo/ir-search-mock-fault-cohort/v1","label":"MOCK_PROVIDER_ONLY_NOT_LAYA","created_utc":now(),"binary":{"sha256":sha(binary.read_bytes()),"source_revision":EXPECTED_REVISION},
        "scope":"Finite IR-search robustness treatments on the clamp fixture; provider exchanges are synthetic loopback fixtures and do not measure Laya or GPT-6 behavior.",
        "treatment_count":len(TREATMENTS),"treatments":[{k:v for k,v in t.items() if k not in ("steps",)} for t in TREATMENTS],"holdout_privacy_sentinels":HOLDOUT_SENTINELS}
    dump(run_dir/"run-manifest.json",manifest)
    results=[]
    for t in TREATMENTS:
        print(f"[MOCK cohort] {t['id']}",flush=True)
        results.append(run_one(binary,t,run_dir))
    dump(run_dir/"invocations.json",results)
    print(json.dumps({"run_dir":str(run_dir),"invocations":len(results),"wall_ms":sum(r["wall_ms"] for r in results),"requests":sum(r["provider_request_count"] for r in results)},indent=2))

if __name__=="__main__": main()
