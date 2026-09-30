#!/usr/bin/env python3
"""Offline assertions over already-saved MOCK cohort artifacts; never runs Gooo or a provider."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DEFAULT_RUN = HERE / "runs" / "final-mock-provider-run-2026-09-30"
EXPECTED = {
    "unconfigured_fallback", "http_503_fallback", "malformed_json_fallback", "missing_choice_fallback",
    "unknown_choice_fallback", "failure_feedback_privacy", "repeated_tried_choice",
    "invalid_expression_then_valid", "type_mismatch_then_valid", "training_perfect_holdout_failure",
    "provider_budget_timeout", "cancel_inflight_provider",
}
EXPECTED_BINARY_SHA256 = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"
EXPECTED_SOURCE_REVISION = "29d44bc778d85aee03b9af500bd83dc98f368189"
BODY_SEARCH_FIELDS = ("selected_candidate_id", "stop_reason", "training_passed", "training_total",
                      "holdout_passed", "holdout_total", "attempts", "provider_budget_used_ms")

def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def read_json(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def require(condition, message):
    if not condition: raise AssertionError(message)
def deep_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).lower(); yield from deep_keys(item)
    elif isinstance(value, list):
        for item in value: yield from deep_keys(item)

def decoded_dicts(value, depth=0):
    """Yield every object after recursively parsing full or embedded JSON strings."""
    if depth > 40:
        raise AssertionError("request JSON-string nesting exceeded validator limit")
    if isinstance(value, dict):
        yield value
        for key, item in value.items():
            yield from decoded_dicts(key, depth + 1)
            yield from decoded_dicts(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from decoded_dicts(item, depth + 1)
    elif isinstance(value, str):
        variants = [value]
        unescaped_quotes = value.replace('\\"', '"')
        if unescaped_quotes != value:
            variants.append(unescaped_quotes)
        decoder = json.JSONDecoder()
        for text in variants:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, RecursionError):
                parsed = None
                found_full_json = False
            else:
                found_full_json = True
                yield from decoded_dicts(parsed, depth + 1)
            if found_full_json:
                continue
            index = 0
            while index < len(text):
                if text[index] not in "[{":
                    index += 1
                    continue
                try:
                    parsed, end = decoder.raw_decode(text, index)
                except (json.JSONDecodeError, RecursionError):
                    index += 1
                    continue
                yield from decoded_dicts(parsed, depth + 1)
                index = end

def assert_no_holdout_leak(raw_request, holdout_cases, context="request"):
    """Reject holdout keys anywhere and exact input/expected holdout pairs in case objects."""
    if isinstance(raw_request, bytes):
        raw_request = json.loads(raw_request)
    pairs = {(case["input"], case["expected"]) for case in holdout_cases}
    for obj in decoded_dicts(raw_request):
        keys = {str(key).lower() for key in obj}
        if any("holdout" in key for key in keys):
            raise AssertionError(f"{context}: holdout field leaked into raw provider request")
        if "input" in keys and "expected" in keys:
            fields = {str(key).lower(): value for key, value in obj.items()}
            if (fields.get("input"), fields.get("expected")) in pairs:
                raise AssertionError(f"{context}: exact holdout input/expected pair leaked into raw provider request")

def assert_summary_matches_body(summary, body_search, context="summary"):
    """Bind every reported candidate-search summary field to stdout.raw report.body_search."""
    for field in BODY_SEARCH_FIELDS:
        if summary.get(field) != body_search.get(field):
            raise AssertionError(f"{context}: {field} disagrees with raw report.body_search")

def decode_body_search(stdout_raw):
    report = json.loads(stdout_raw).get("report", {})
    body_search = report.get("body_search")
    if not isinstance(body_search, dict):
        raise AssertionError("successful stdout.raw lacks report.body_search")
    return body_search

def validate(run: Path, write_report=False):
    manifest=read_json(run/"run-manifest.json")
    rows=read_json(run/"invocations.json")
    cohort_manifest=read_json(HERE/"manifest.json")
    require(manifest["label"] == "MOCK_PROVIDER_ONLY_NOT_LAYA", "run is not explicitly labeled mock-only")
    require(manifest["treatment_count"] == 12 and len(rows) == 12, "expected twelve treatments and result rows")
    require({r["treatment_id"] for r in rows} == EXPECTED, "treatment set differs from frozen expected set")
    require(manifest["binary"]["sha256"] == EXPECTED_BINARY_SHA256, "run-manifest compiler SHA-256 differs from canonical pin")
    require(manifest["binary"]["source_revision"] == EXPECTED_SOURCE_REVISION, "run-manifest source revision differs from canonical pin")
    require(cohort_manifest["binary"]["sha256"] == EXPECTED_BINARY_SHA256, "cohort-manifest compiler SHA-256 differs from canonical pin")
    require(cohort_manifest["binary"]["source_revision"] == EXPECTED_SOURCE_REVISION, "cohort-manifest source revision differs from canonical pin")
    require(all(r["binary_sha256"] == EXPECTED_BINARY_SHA256 for r in rows), "invocation compiler SHA-256 differs from canonical pin")
    require(all(r["label"] in {"MOCK_PROVIDER_TREATMENT", "NO_PROVIDER_CONTROL"} for r in rows), "unexpected provider label")
    by_id={r["treatment_id"]:r for r in rows}
    ordered_ids=[item["id"] for item in manifest["treatments"]]
    require([r["treatment_id"] for r in rows] == ordered_ids, "invocation index order differs from run manifest")
    for row in rows:
        folder=run/"treatments"/row["treatment_id"]
        receipt=read_json(folder/"invocation.json")
        require(receipt == row, f"{row['treatment_id']} invocation index differs from local receipt")
        require(sha((folder/"stdout.raw").read_bytes()) == row["stdout_sha256"], f"{row['treatment_id']} stdout hash mismatch")
        require(sha((folder/"stderr.raw").read_bytes()) == row["stderr_sha256"], f"{row['treatment_id']} stderr hash mismatch")
        require(sha((folder/"fixture.gooo.fixture").read_bytes()) == row["fixture_sha256"], f"{row['treatment_id']} fixture hash mismatch")
        require(sha((folder/"plan.json").read_bytes()) == row["plan_sha256"], f"{row['treatment_id']} plan hash mismatch")
        plan=read_json(folder/"plan.json")
        raw_stdout=(folder/"stdout.raw").read_bytes()
        if row["exit_code"] == 0:
            body_search=decode_body_search(raw_stdout)
            assert_summary_matches_body(row,body_search,row["treatment_id"])
        else:
            require(row["treatment_id"] == "cancel_inflight_provider" and row["exit_code"] == -15 and row["runner_cancelled"],
                    f"{row['treatment_id']} failed without the declared runner-cancellation treatment")
            require(row["attempts"] == [] and all(row.get(field) is None for field in BODY_SEARCH_FIELDS if field != "attempts"),
                    "canceled invocation claims a Gooo body-search result without a stdout report")
            require(not raw_stdout.strip(), "canceled invocation unexpectedly contains a partial stdout report")
        require(len(row["provider_events"]) == row["provider_request_count"], f"{row['treatment_id']} provider event count mismatch")
        event_path=folder/"mock_provider"/"events.jsonl"
        if event_path.exists():
            event_rows=[json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line]
        else:
            event_rows=[]
        require(event_rows == row["provider_events"], f"{row['treatment_id']} provider receipt differs from events.jsonl")
        for event in row["provider_events"]:
            req=(folder/"mock_provider"/event["request_file"]).read_bytes()
            res=(folder/"mock_provider"/event["response_file"]).read_bytes()
            require(event["label"] == "MOCK" and event["method"] == "POST" and event["path"] == "/v1/systemone"
                    and sha(req) == event["request_sha256"] and sha(res) == event["response_sha256"],
                    f"{row['treatment_id']} saved provider exchange hash/label mismatch")
            assert_no_holdout_leak(req,plan["holdout_test_cases"],context=f"{row['treatment_id']} {event['request_file']}")
    require(by_id["unconfigured_fallback"]["provider_request_count"] == 0, "no-provider control unexpectedly contacted a provider")
    require(by_id["unconfigured_fallback"]["selected_candidate_id"] == "zero", "control did not finish on finite-training winner")
    require(by_id["unconfigured_fallback"]["attempts"][0]["decision"]["fallback_reason"] == "NOT_CONFIGURED", "missing-provider fallback receipt differs")

    for tid, reason in [("http_503_fallback","PROVIDER_HTTP_ERROR"),("malformed_json_fallback","PROVIDER_RESULT_INVALID"),
                        ("missing_choice_fallback","PROVIDER_RESULT_INVALID"),("unknown_choice_fallback","PROVIDER_RESULT_INVALID")]:
        row=by_id[tid]
        require(row["exit_code"] == 0 and row["attempts"], f"{tid} did not return a compiler report")
        first=row["attempts"][0]
        require(first["decision"]["mode"] == "deterministic_fallback" and first["decision"]["fallback_reason"] == reason,
                f"{tid} fallback receipt mismatch")

    feedback=by_id["failure_feedback_privacy"]
    reqdir=run/"treatments"/"failure_feedback_privacy"/"mock_provider"/"requests"
    req1,req2=(read_json(reqdir/f"{i:02d}.request.raw") for i in (1,2))
    state1=json.loads(req1["state"]["request"]); state2=json.loads(req2["state"]["request"])
    require(len(state2["prior_attempts"]) == 1 and state2["prior_attempts"][0]["candidate_id"] == "identity", "second request omits prior failure feedback")
    prior=state2["prior_attempts"][0]
    require(prior["test_cases_total"] == 3 and [x["input"] for x in prior["failed_cases"]] == [-3,-2,-1], "feedback did not report only the training failures")
    require("identity" not in req2["questions"]["body_ir_search"]["criteria"], "consumed choice was not removed from remaining options")
    require(not any("holdout" in key for key in deep_keys(state1)) and not any("holdout" in key for key in deep_keys(state2)), "holdout field leaked into provider state")
    require(feedback["selected_candidate_id"] == "zero" and feedback["training_passed"] == 3 and feedback["holdout_passed"] == 4, "feedback/privacy treatment result differs")

    repeat=by_id["repeated_tried_choice"]
    repeat_resp=read_json(run/"treatments"/"repeated_tried_choice"/"mock_provider"/"responses"/"02.response.raw")
    repeat_req=read_json(run/"treatments"/"repeated_tried_choice"/"mock_provider"/"requests"/"02.request.raw")
    require(repeat_resp["answers"]["body_ir_search"]["choice"] == "identity", "repeat-choice fixture did not return a consumed candidate")
    require("identity" not in repeat_req["questions"]["body_ir_search"]["criteria"], "second request still offered consumed candidate")
    ids=[a.get("candidate_id") for a in repeat["attempts"]]
    require(len(ids) == len(set(ids)), "compiler retried a previously attempted candidate")

    for tid, cid in [("invalid_expression_then_valid","broken"),("type_mismatch_then_valid","boolean")]:
        row=by_id[tid]; attempt=row["attempts"][0]
        require(attempt["candidate_id"] == cid and attempt["typecheck_passed"] is False and attempt["scoring_completed"] is False,
                f"{tid} did not reject candidate before finite scoring")
        require(row["selected_candidate_id"] == "zero" and row["training_passed"] == 3, f"{tid} did not continue to the valid candidate")
        req=read_json(run/"treatments"/tid/"mock_provider"/"requests"/"02.request.raw")
        state=json.loads(req["state"]["request"])
        require(state["prior_attempts"][0]["candidate_id"] == cid and bool(state["prior_attempts"][0].get("error")), f"{tid} rejection feedback is missing")

    trap=by_id["training_perfect_holdout_failure"]
    require(trap["selected_candidate_id"] == "identity" and trap["training_passed"] == 3 and trap["training_total"] == 3,
            "holdout trap did not produce a training-perfect selection")
    require(trap["holdout_passed"] == 0 and trap["holdout_total"] == 4 and trap["stop_reason"] == "TRAINING_SUITE_PASSED",
            "holdout trap did not preserve finite holdout failure after training stop")

    budget=by_id["provider_budget_timeout"]
    require(budget["exit_code"] == 0 and 7900 <= budget["provider_budget_used_ms"] <= 8150, "single stalled provider request did not hit the 8s provider budget")
    require(budget["attempts"][0]["decision"]["fallback_reason"] == "SEARCH_PROVIDER_BUDGET_EXHAUSTED", "timeout fallback reason differs")
    require(budget["provider_request_count"] == 1, "timeout treatment unexpectedly repeated slow provider requests")
    canceled=by_id["cancel_inflight_provider"]
    require(canceled["runner_cancelled"] is True and canceled["exit_code"] == -15 and canceled["provider_request_count"] == 1,
            "in-flight cancellation did not stop only the compiler process as expected")

    files=[]
    for p in sorted(run.rglob("*")):
        if p.is_file() and p.name not in {"report.md", "report.json"}:
            raw=p.read_bytes(); files.append({"path":str(p.relative_to(run)),"bytes":len(raw),"sha256":sha(raw)})
    total_req=sum(r["provider_request_count"] for r in rows)
    mock_treatments=sum(r["label"] == "MOCK_PROVIDER_TREATMENT" for r in rows)
    result={"schema":"gooo/ir-search-mock-fault-report/v1","label":"MOCK_PROVIDER_ONLY_NOT_LAYA","run_dir":str(run),
        "compiler":manifest["binary"],"treatments":len(rows),"mock_provider_treatments":mock_treatments,"mock_requests":total_req,
        "pilot":{"run_id":"mock-provider-run-2026-09-30","invocations":12,"mock_requests":19,
                 "status":"SUPERSEDED_HOLDOUT_FIXTURE_MISCONFIGURED","detail":"The first pilot used a zero-expression treatment that also passed its original holdout. It is retained as raw evidence and excluded from final claims."},
        "assertions_passed":["12 treatment inventory and exact source-revision/compiler-digest pin","invocation summary fields bind to decoded stdout.raw report.body_search and local receipt",
            "provider events bind to events.jsonl and exact raw request/response hashes","recursive request decoding rejects holdout fields and exact holdout case pairs while allowing unrelated constants",
            "deterministic fallback for absent, HTTP-error, malformed, missing, and unknown choices",
            "provider state carries failed training-case feedback but excludes disjoint holdout cases","consumed candidates disappear from options and are never attempted twice",
            "invalid syntax and int64 type mismatch are rejected before scoring, then search proceeds","training-perfect identity candidate scores 0/4 on its disjoint finite holdout while stopping on training",
            "one stalled provider call reaches the 8s budget and falls back","runner SIGTERM yields CLI exit -15 and one captured MOCK request without a Gooo report"],
        "limitations":["All provider exchanges are local synthetic MOCK fixtures; no Laya or GPT-6 behavior was measured.",
            "One hand-authored int64 clamp fixture and small finite suites do not establish domain coverage or full-domain correctness.",
            "The holdout result is finite behavioral evidence from the bounded interpreter; generated package code was not executed.",
            "The 8s timeout treatment is singular by design; the cancellation runner is configured to send SIGTERM after 350ms, but saved timing does not prove the request was still in flight at that exact instant."],
        "invocation_index":[{"treatment_id":r["treatment_id"],"exit_code":r["exit_code"],"requests":r["provider_request_count"],
            "selected_candidate_id":r["selected_candidate_id"],"training_passed":r["training_passed"],"training_total":r["training_total"],
            "holdout_passed":r["holdout_passed"],"holdout_total":r["holdout_total"],"stop_reason":r["stop_reason"],"wall_ms":round(r["wall_ms"],3)} for r in rows],
        "saved_files":files}
    md=["# Gooo IR-search fault and coverage experiment", "", "**Label: MOCK provider only. This is not Laya output and not a GPT-6 measurement.**", "",
        f"Final run: `{run.name}` — {len(rows)} treatments, {mock_treatments} MOCK-provider treatments, {total_req} captured HTTP requests. Compiler SHA-256 `{manifest['binary']['sha256']}` (source revision `{manifest['binary']['source_revision']}`).", "",
        "## Observed results", "", "| Treatment | Requests | Selection | Training | Holdout | Observation |", "|---|---:|---|---:|---:|---|"]
    notes={"unconfigured_fallback":"No provider requests; deterministic fallback reaches the training-perfect candidate.",
      "http_503_fallback":"503 produces PROVIDER_HTTP_ERROR fallback, then a later valid choice can continue.",
      "malformed_json_fallback":"Malformed JSON produces PROVIDER_RESULT_INVALID fallback.",
      "missing_choice_fallback":"Missing answer produces PROVIDER_RESULT_INVALID fallback.",
      "unknown_choice_fallback":"Unknown candidate ID produces PROVIDER_RESULT_INVALID fallback.",
      "failure_feedback_privacy":"Second request includes failed training inputs only; holdout fields/inputs absent.",
      "repeated_tried_choice":"Repeated ID is invalid because it was removed; attempt trace contains no duplicate candidate.",
      "invalid_expression_then_valid":"Malformed Go expression is rejected before scoring; search continues.",
      "type_mismatch_then_valid":"Bool expression is rejected for int64 before scoring; search continues.",
      "training_perfect_holdout_failure":"Identity is 3/3 on nonnegative training, then 0/4 on negative holdout; stop reason remains training-perfect.",
      "provider_budget_timeout":"One stalled request reaches the 8,000 ms budget and search falls back.",
      "cancel_inflight_provider":"Runner SIGTERM is configured after 350 ms; the CLI exits -15 and one MOCK request is captured. Saved timing does not prove the request remained in flight at the signal instant."}
    for r in rows:
        training=f"{r['training_passed']}/{r['training_total']}" if r["training_total"] is not None else "—"
        holdout=f"{r['holdout_passed']}/{r['holdout_total']}" if r["holdout_total"] is not None else "—"
        md.append(f"| `{r['treatment_id']}` | {r['provider_request_count']} | {r['selected_candidate_id'] or '—'} | {training} | {holdout} | {notes[r['treatment_id']]} |")
    md += ["", "## Pilot retained but superseded", "", "The first raw run at `runs/mock-provider-run-2026-09-30/` is retained (12 invocations, 19 requests, about 13.2 seconds). Its training-perfect/holdout-failure probe was incorrectly configured: the zero-expression candidate remained correct on that holdout. The corrected final probe uses identity with nonnegative training inputs and negative disjoint holdout inputs. Pilot outputs are excluded from the result table and claims.", "", "## Interpretation and limits", "", "The frozen compiler handled these injected failure modes as recorded, and training success did not imply holdout success. The deterministic finite search and its receipts support only the twelve synthetic treatments against one int64 fixture. They do not establish Laya quality, model success rates, domain accuracy, or correctness beyond the finite cases. The HTTP mock binds loopback only; the no-provider case unsets the Laya URL and API key. No model server or model call was used. The cancellation treatment records runner-configured SIGTERM, process exit -15, and one mock request; timing does not establish that the request was still in flight at the signal instant.", "", "## Reproduction and validation", "", "Runner: `scripts/run_fault_cohort.py`. It requires explicit `--execute`, the pinned binary, and the exact SHA-256. Use a fresh `--run-id` to preserve existing evidence. `scripts/validate_saved.py` checks saved output only and performs no compiler invocation, model call, or network request.", ""]
    markdown="\n".join(md)
    if write_report:
        (run/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        (run/"report.md").write_text(markdown,encoding="utf-8")
    else:
        report_json=run/"report.json"; report_md=run/"report.md"
        if report_json.exists():
            require(read_json(report_json) == result, "saved report.json disagrees with independently re-derived raw-evidence report")
        if report_md.exists():
            require(report_md.read_text(encoding="utf-8") == markdown, "saved report.md disagrees with independently re-derived raw-evidence report")
    print(f"PASS: {len(result['assertions_passed'])} independent assertion groups; {len(rows)} treatments; {total_req} MOCK requests")
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--run-dir",type=Path,default=DEFAULT_RUN); ap.add_argument("--write-report",action="store_true",help="derive report.md and report.json from saved artifacts")
    args=ap.parse_args(); validate(args.run_dir.resolve(),write_report=args.write_report)
if __name__=="__main__": main()
