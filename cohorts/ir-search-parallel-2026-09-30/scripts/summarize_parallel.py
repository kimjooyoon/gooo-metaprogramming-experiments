#!/usr/bin/env python3
"""Derive concurrency observations solely from a saved parallel-cohort run."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent.parent
CONDITIONS = ("sequential", "simultaneous")
INTENTS = ("clamp", "absolute")
SAMPLE_INTERVAL_MS = 100
PRIOR_PRIMARY_REPORT_SHA256 = "14b3e98d48663292751e3a437c9d74e57bee7fb381731da159875841a94cc24d"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def load_events(invocation_dir: Path):
    path = invocation_dir / "proxy" / "events.jsonl"
    if not path.is_file():
        raise RuntimeError(f"missing per-client proxy event log: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_proxy_events(invocation_dir: Path, intent_id: str, condition: str, plan):
    events = load_events(invocation_dir)
    choice_events = []
    holdout_pairs = {(case["input"], case["expected"]) for case in plan["holdout_test_cases"]}
    for event in events:
        if event.get("invocation_id") != f"{condition}/{intent_id}":
            raise RuntimeError(f"proxy event attributed to wrong client: {event}")
        for kind in ("request", "response"):
            path = invocation_dir / event[f"{kind}_file"]
            if not path.is_file() or sha256(path.read_bytes()) != event[f"{kind}_sha256"]:
                raise RuntimeError(f"{kind} body hash mismatch in {path}")
        if event.get("kind") != "laya_choice":
            continue
        request_path = invocation_dir / event["request_file"]
        outer = json.loads(request_path.read_bytes())
        state_raw = outer.get("state", {}).get("request", "")
        state = json.loads(state_raw) if state_raw else {}
        if state.get("stage") != "choose_before_candidate_evaluation":
            raise RuntimeError(f"request is not a pre-evaluation choice for {intent_id}")
        if event.get("holdout_fields_present") is not False:
            raise RuntimeError(f"capture flag reports held-out field in {request_path}")
        for node in walk(state):
            if any("holdout" in str(key).lower() for key in node):
                raise RuntimeError(f"held-out field name found in model state: {request_path}")
            if "input" in node and "expected" in node:
                if (node["input"], node["expected"]) in holdout_pairs:
                    raise RuntimeError(f"held-out case pair found in model state: {request_path}")
        if "holdout" in json.dumps(outer, ensure_ascii=False).lower():
            raise RuntimeError(f"held-out marker found in raw selection request: {request_path}")
        response_path = invocation_dir / event["response_file"]
        response = json.loads(response_path.read_bytes())
        choice = response.get("answers", {}).get("body_ir_search", {}).get("choice")
        if choice != event.get("selected_candidate_id"):
            raise RuntimeError(f"proxy selected-id metadata differs from response: {response_path}")
        choice_events.append({
            "seq": event["seq"],
            "started_utc": event["started_utc"],
            "completed_utc": event["completed_utc"],
            "duration_ms": event["duration_ms"],
            "candidate_id": choice,
            "request_sha256": event["request_sha256"],
            "response_sha256": event["response_sha256"],
            "training_test_count": event.get("training_test_count"),
            "training_suite_sha256": event.get("training_suite_sha256"),
        })
    return events, choice_events


def summary_process(samples, field, wall_seconds):
    rows = [row[field] for row in samples if row.get(field) and row[field].get("alive") and "cpu_seconds" in row[field]]
    if not rows:
        return {"sample_count": 0, "cpu_seconds_delta": None, "cpu_percent_one_core": None,
                "max_sampled_rss_kb": None, "max_sampled_rss_mib": None}
    delta = (rows[-1]["cpu_seconds"] - rows[0]["cpu_seconds"]) if len(rows) >= 2 else None
    peak = max(row["rss_kb"] for row in rows)
    one_core = delta / wall_seconds * 100 if delta is not None and wall_seconds > 0 else None
    return {"sample_count": len(rows), "cpu_seconds_delta": delta, "cpu_percent_one_core": one_core,
            "max_sampled_rss_kb": peak, "max_sampled_rss_mib": peak / 1024}


def training_oracle(intent_id, selected_id, body_search, plan, oracle):
    if selected_id not in oracle["candidate_outputs"]:
        raise RuntimeError(f"oracle missing selected candidate {intent_id}/{selected_id}")
    result = {}
    for name, cases in (("training", plan["test_cases"]), ("holdout", plan["holdout_test_cases"])):
        expected = [case["expected"] for case in cases]
        actual = oracle["candidate_outputs"][selected_id][name]
        if len(actual) != len(expected):
            raise RuntimeError(f"oracle output count mismatch for {intent_id}/{name}")
        passed = sum(a == e for a, e in zip(actual, expected))
        result[name] = {"passed": passed, "total": len(expected),
                        "accuracy_percent": passed * 100.0 / len(expected) if expected else None}
    if body_search.get("training_passed") != result["training"]["passed"] or body_search.get("training_total") != result["training"]["total"]:
        raise RuntimeError(f"CLI final training score disagrees with independent oracle for {intent_id}")
    if body_search.get("holdout_passed") != result["holdout"]["passed"] or body_search.get("holdout_total") != result["holdout"]["total"]:
        raise RuntimeError(f"CLI final holdout score disagrees with independent oracle for {intent_id}")
    return result


def summarize_invocation(run_dir: Path, condition: str, intent_id: str, run_meta, manifest):
    invocation_dir = run_dir / "conditions" / condition / "invocations" / intent_id
    metadata = read_json(invocation_dir / "invocation.json")
    if metadata["condition"] != condition or metadata["intent_id"] != intent_id:
        raise RuntimeError(f"invocation identity mismatch in {invocation_dir}")
    for raw_name, key in (("stdout.raw", "stdout_sha256"), ("stderr.raw", "stderr_sha256")):
        if sha256((invocation_dir / raw_name).read_bytes()) != metadata[key]:
            raise RuntimeError(f"{raw_name} digest mismatch in {invocation_dir}")
    if metadata["binary_sha256"] != run_meta["binary_sha256"]:
        raise RuntimeError(f"binary hash mismatch in {invocation_dir}")
    inputs = manifest["source_material"]["inputs"][intent_id]
    plan = read_json(HERE / inputs["search_plan"]["path"])
    oracle = read_json(HERE / inputs["finite_oracle"]["path"])
    if sha256((invocation_dir / "plan.json").read_bytes()) != metadata["plan_sha256"]:
        raise RuntimeError(f"copied plan digest mismatch in {invocation_dir}")
    if sha256((invocation_dir / "fixture.gooo.fixture").read_bytes()) != metadata["fixture_sha256"]:
        raise RuntimeError(f"copied fixture digest mismatch in {invocation_dir}")
    payload = json.loads((invocation_dir / "stdout.raw").read_bytes() or b"{}")
    body_search = payload.get("report", {}).get("body_search") or payload.get("body_search")
    if body_search is None:
        raise RuntimeError(f"body-search report missing from {invocation_dir}/stdout.raw")
    selected = body_search.get("selected_candidate_id")
    suites = training_oracle(intent_id, selected, body_search, plan, oracle)
    events, choice_events = validate_proxy_events(invocation_dir, intent_id, condition, plan)
    attempts = body_search.get("attempts", [])
    model_attempts = [a for a in attempts if (a.get("decision") or {}).get("mode") == "laya"]
    if len(model_attempts) != len(choice_events):
        raise RuntimeError(f"CLI model-round count differs from capture events for {condition}/{intent_id}")
    if [a.get("candidate_id") for a in model_attempts] != [e["candidate_id"] for e in choice_events]:
        raise RuntimeError(f"CLI/capture selected candidate differs for {condition}/{intent_id}")
    first_model = model_attempts[0] if model_attempts else None
    final_attempt = attempts[-1] if attempts else {}
    attempt_decision_sum_ms = sum(float(a.get("decision_latency_ms") or 0.0) for a in attempts)
    first_choice_event = choice_events[0] if choice_events else None
    first_choice_post_offset_ms = (
        (dtparse(first_choice_event["started_utc"]) - dtparse(metadata["started_utc"])).total_seconds() * 1000
        if first_choice_event else None
    )
    body_search_total_ms = body_search.get("total_ms")
    body_search_decision_ms = body_search.get("decision_latency_ms")
    command_record = read_json(invocation_dir / "command.json")
    wall_ms = metadata["wall_ms"]
    sample_path = run_dir / "conditions" / condition / "resource-samples.jsonl"
    resource_rows = [json.loads(line) for line in sample_path.read_text(encoding="utf-8").splitlines() if line]
    pid_rows = []
    for row in resource_rows:
        process = row.get("cli_processes", {}).get(metadata["invocation_id"])
        if process:
            pid_rows.append(process)
    cli_summary = summary_process([{"cli": row} for row in pid_rows], "cli", metadata["wall_ms"] / 1000)
    return {
        "condition": condition,
        "intent_id": intent_id,
        "exit_code": metadata["exit_code"],
        "harness_timeout": metadata["harness_timeout"],
        "runner_error": metadata["runner_error"],
        "wall_ms": wall_ms,
        "started_utc": metadata["started_utc"],
        "completed_utc": metadata["completed_utc"],
        "source_digest": body_search.get("original_source_digest"),
        "selected_candidate_id": selected,
        "selected_expression": body_search.get("selected_expression"),
        "training": suites["training"],
        "holdout": suites["holdout"],
        "holdout_source": "recomputed from copied finite oracle after final selection",
        "stop_reason": body_search.get("stop_reason"),
        "attempt_count": len(attempts),
        "model_choice_count": len(model_attempts),
        "first_model_choice_training_perfect": bool(first_model and first_model.get("test_cases_passed") == first_model.get("test_cases_total")),
        "model_choices_training_perfect": sum(a.get("test_cases_passed") == a.get("test_cases_total") for a in model_attempts),
        "final_selection_method": final_attempt.get("selection_method"),
        "attempts": [{"candidate_id": a.get("candidate_id"), "selection_method": a.get("selection_method"),
                       "training_passed": a.get("test_cases_passed"), "training_total": a.get("test_cases_total"),
                       "typecheck_passed": a.get("typecheck_passed"), "error": a.get("error", ""),
                       "decision_mode": (a.get("decision") or {}).get("mode")} for a in attempts],
        "choice_events": choice_events,
        "timing": {
            "cli_wall_ms_from_launch_marker": wall_ms,
            "body_search_total_ms": body_search_total_ms,
            "body_search_decision_latency_ms": body_search_decision_ms,
            "sum_attempt_decision_latency_ms": attempt_decision_sum_ms,
            "wall_minus_body_search_ms": wall_ms - body_search_total_ms if body_search_total_ms is not None else None,
            "wall_minus_decision_latency_ms": wall_ms - body_search_decision_ms if body_search_decision_ms is not None else None,
            "body_search_decision_latency_minus_attempt_sum_ms": body_search_decision_ms - attempt_decision_sum_ms if body_search_decision_ms is not None else None,
            "first_choice_post_started_utc": first_choice_event["started_utc"] if first_choice_event else None,
            "first_choice_post_offset_from_cli_launch_marker_ms": first_choice_post_offset_ms,
            "cli_launch_marker_definition": "UTC marker captured immediately before Popen; simultaneous marker is recorded after the launch barrier",
            "provider_budget_ms": body_search.get("provider_budget_ms"),
            "provider_budget_used_ms": body_search.get("provider_budget_used_ms"),
            "harness_timeout_seconds": command_record.get("harness_timeout_seconds"),
        },
        "all_proxy_events": len(events),
        "heldout_privacy_audit": {"choice_requests_scanned": len(choice_events),
                                   "holdout_case_pairs_or_fields_found": 0},
        "cli_process_resources": cli_summary,
        "raw_invocation_dir": str(invocation_dir.relative_to(run_dir)),
    }


def dtparse(value):
    return dt.datetime.fromisoformat(value)


def request_overlap(invocations):
    entries = []
    for row in invocations:
        for event in row["choice_events"]:
            entries.append({"condition": row["condition"], "intent_id": row["intent_id"],
                            "seq": event["seq"], "start": dtparse(event["started_utc"]),
                            "end": dtparse(event["completed_utc"]), "duration_ms": event["duration_ms"]})
    output = {}
    for condition in CONDITIONS:
        subset = [item for item in entries if item["condition"] == condition]
        overlaps = []
        max_active = 0
        points = []
        for item in subset:
            points.append((item["start"], 1))
            points.append((item["end"], -1))
        ordered = sorted(subset, key=lambda item: item["start"])
        for item in ordered:
            active = sum(1 for other in subset if other["start"] <= item["start"] < other["end"])
            max_active = max(max_active, active)
            for other in ordered:
                if other["start"] <= item["start"]:
                    continue
                overlap_ms = max(0.0, (min(item["end"], other["end"]) - max(item["start"], other["start"])).total_seconds() * 1000)
                if overlap_ms > 0:
                    overlaps.append({"first_intent": item["intent_id"], "first_seq": item["seq"],
                                     "second_intent": other["intent_id"], "second_seq": other["seq"],
                                     "overlap_ms": overlap_ms})
        # Sweep half-open intervals to get the maximum, with endings before starts at equal timestamps.
        active = 0
        sweep_max = 0
        for _, delta in sorted(points, key=lambda x: (x[0], x[1])):
            active += delta
            sweep_max = max(sweep_max, active)
        output[condition] = {"choice_http_transactions": len(subset),
                            "any_pairwise_http_overlap": bool(overlaps),
                            "max_in_flight_choice_http_transactions": sweep_max,
                            "overlapping_pairs": overlaps,
                            "inference_queue_time_directly_measured": False}
    return output


def condition_resources(run_dir: Path, condition: str):
    cond_dir = run_dir / "conditions" / condition
    samples = [json.loads(line) for line in (cond_dir / "resource-samples.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if not samples:
        raise RuntimeError(f"no process samples for {condition}")
    first = next((row for row in samples if row["label"] == "condition_before"), samples[0])
    last = next((row for row in reversed(samples) if row["label"] == "condition_after"), samples[-1])
    duration = max(0.0, last["elapsed_seconds"] - first["elapsed_seconds"])
    server_rows = [row["laya_server"] for row in samples if row.get("laya_server", {}).get("alive") and "cpu_seconds" in row["laya_server"]]
    server = summary_process([{"server": row} for row in server_rows], "server", duration)
    return {"sample_interval_ms": int(SAMPLE_INTERVAL_MS), "sample_count_total": len(samples),
            "before_sample": first["laya_server"], "after_sample": last["laya_server"],
            "measurement_window_seconds": duration,
            "laya_server_process": server,
            "rss_definition": "maximum sampled owned-server RSS across condition_before, during, and condition_after observations; not an OS lifetime peak",
            "cpu_definition": "cumulative ps CPU-time difference from first to last alive condition sample divided by sampled condition duration"}


def historical_timing_context():
    path = HERE.parent / "ir-search-2026-09-30" / "runs" / "primary_run" / "report.json"
    raw = path.read_bytes()
    digest = sha256(raw)
    if digest != PRIOR_PRIMARY_REPORT_SHA256:
        raise RuntimeError(f"pinned prior timing-context report changed: {path}")
    prior = read_json(path)
    rows = [row for row in prior["invocations"] if row.get("variant") == "laya_fill_search"]
    if len(rows) != 4:
        raise RuntimeError("pinned prior cohort report has unexpected Laya invocation count")
    first = rows[0]
    first_decision_ms = sum(float(a.get("decision_latency_ms") or 0.0) for a in first.get("attempts", []))
    later_gaps = []
    for row in rows[1:]:
        decision_ms = sum(float(a.get("decision_latency_ms") or 0.0) for a in row.get("attempts", []))
        later_gaps.append({"intent_id": row["intent_id"], "wall_minus_decision_latency_ms": row["wall_ms"] - decision_ms})
    return {
        "source": "../ir-search-2026-09-30/runs/primary_run/report.json",
        "source_sha256": digest,
        "first_laya_invocation_intent_id": first["intent_id"],
        "first_laya_invocation_harness_window_ms": first["wall_ms"],
        "first_laya_invocation_decision_latency_ms": first_decision_ms,
        "first_laya_invocation_harness_window_minus_decision_latency_ms": first["wall_ms"] - first_decision_ms,
        "later_laya_invocation_harness_window_minus_decision_latency_ms": later_gaps,
        "cause_of_excess_harness_window_time": "unknown; the prior harness window includes sampler shutdown/join and output fsync, so the excess is not attributed to CLI startup or model inference",
    }


def pair_timing(invocations, condition):
    rows = sorted((row for row in invocations if row["condition"] == condition),
                  key=lambda row: dtparse(row["started_utc"]))
    if not rows:
        return {"invocation_count": 0}
    starts = [dtparse(row["started_utc"]) for row in rows]
    ends = [dtparse(row["completed_utc"]) for row in rows]
    makespan = max(0.0, (max(ends) - min(starts)).total_seconds() * 1000)
    transition_gaps = [
        (dtparse(next_row["started_utc"]) - dtparse(previous["completed_utc"])).total_seconds() * 1000
        for previous, next_row in zip(rows, rows[1:])
    ]
    return {
        "invocation_count": len(rows),
        "pair_cli_makespan_utc_ms": makespan,
        "sum_per_cli_wall_ms": sum(row["wall_ms"] for row in rows),
        "max_single_cli_wall_ms": max(row["wall_ms"] for row in rows),
        "launch_spacing_ms": (starts[-1] - starts[0]).total_seconds() * 1000 if len(starts) > 1 else 0.0,
        "ordered_inter_invocation_start_minus_previous_completion_ms": transition_gaps,
        "positive_sequential_idle_gap_ms": sum(max(0.0, gap) for gap in transition_gaps),
        "sum_cli_wall_minus_pair_makespan_ms": sum(row["wall_ms"] for row in rows) - makespan,
        "interpretation": "positive transition values are elapsed gaps between CLI completion and the next launch; negative values are overlap",
    }


def render_markdown(report):
    timing_context = report["timing_context_from_prior_primary_cohort"]
    prior_later_gaps = ", +".join(
        f"{item['wall_minus_decision_latency_ms']:.1f}"
        for item in timing_context["later_laya_invocation_harness_window_minus_decision_latency_ms"]
    )
    lines = [
        "# IR body-search client concurrency observation",
        "",
        f"Run: `{report['run_id']}`",
        f"Binary revision: `{report['source_revision']}`",
        f"Binary SHA-256: `{report['binary_sha256']}`",
        f"Laya: `{report['runtime']['name']} {report['runtime']['version']}` / `{report['runtime']['revision']}` / CPU / 4 threads",
        "",
        "One replicate per condition; two fixed intents (`clamp`, `absolute`) per condition. This is an observed-run comparison only, not a statistical or general speed claim.",
        "",
        "## Conditions",
        "",
        "| Condition | CLI makespan ms | Actual Laya choice calls | Max overlapping choice HTTP calls | Laya process CPU s | Laya CPU (% one core over resource window) | Resource window s | Max sampled server RSS MiB | Both CLIs exit 0 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for condition in CONDITIONS:
        rows = [r for r in report["invocations"] if r["condition"] == condition]
        cond = report["conditions"][condition]
        starts = [dtparse(r["started_utc"]) for r in rows]
        ends = [dtparse(r["completed_utc"]) for r in rows]
        makespan = (max(ends) - min(starts)).total_seconds() * 1000 if rows else 0
        server = cond["resources"]["laya_server_process"]
        overlap = report["request_overlap"][condition]
        cli_ok = len(rows) == 2 and all(r["exit_code"] == 0 and not r["harness_timeout"] for r in rows)
        lines.append("| {condition} | {wall:.1f} | {calls} | {inflight} | {cpu} | {pct} | {resource_window:.3f} | {rss} | {ok} |".format(
            condition=condition, wall=makespan,
            calls=sum(r["model_choice_count"] for r in rows),
            inflight=overlap["max_in_flight_choice_http_transactions"],
            cpu="n/a" if server["cpu_seconds_delta"] is None else f"{server['cpu_seconds_delta']:.2f}",
            pct="n/a" if server["cpu_percent_one_core"] is None else f"{server['cpu_percent_one_core']:.1f}",
            resource_window=cond["resources"]["measurement_window_seconds"],
            rss="n/a" if server["max_sampled_rss_mib"] is None else f"{server['max_sampled_rss_mib']:.1f}",
            ok="yes" if cli_ok else "no"))
    lines += ["", "## Invocation outcomes", "",
              "| Condition | Intent | Selected | Training | Oracle holdout | Attempts | Laya choices | Final selection method | Wall ms | Stop reason |",
              "|---|---|---|---|---|---:|---:|---|---:|---|"]
    for row in report["invocations"]:
        lines.append(f"| {row['condition']} | {row['intent_id']} | {row.get('selected_candidate_id') or ''} | "
                     f"{row['training']['passed']}/{row['training']['total']} | "
                     f"{row['holdout']['passed']}/{row['holdout']['total']} | {row['attempt_count']} | "
                     f"{row['model_choice_count']} | {row.get('final_selection_method') or ''} | {row['wall_ms']:.1f} | "
                     f"{row.get('stop_reason') or ''} |")
    lines += ["", "## Invocation timing decomposition", "",
              "Wall starts at the recorded launch marker immediately before `Popen` (after the barrier for simultaneous launches) and ends when the CLI process completes. `body_search.total_ms` and `decision_latency_ms` are Gooo report timings. First POST entry is when the per-client capture proxy begins handling the first Laya choice request.",
              "",
              "| Condition | Intent | CLI wall ms | body_search.total_ms ms | body_search decision_latency_ms ms | Sum attempt decision_latency_ms | Wall minus body search ms | Wall minus decision latency ms | First choice POST after launch marker ms | Provider budget used / budget ms | Harness timeout s |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["invocations"]:
        t = row["timing"]
        def show(value):
            return "n/a" if value is None else f"{value:.2f}"
        budget = "n/a" if t["provider_budget_ms"] is None else f"{show(t['provider_budget_used_ms'])} / {show(t['provider_budget_ms'])}"
        lines.append(f"| {row['condition']} | {row['intent_id']} | {show(t['cli_wall_ms_from_launch_marker'])} | "
                     f"{show(t['body_search_total_ms'])} | {show(t['body_search_decision_latency_ms'])} | "
                     f"{show(t['sum_attempt_decision_latency_ms'])} | {show(t['wall_minus_body_search_ms'])} | "
                     f"{show(t['wall_minus_decision_latency_ms'])} | "
                     f"{show(t['first_choice_post_offset_from_cli_launch_marker_ms'])} | {budget} | "
                     f"{show(t['harness_timeout_seconds'])} |")
    lines += ["", "## Harness and pair timing", "",
              "| Condition | CLI pair makespan ms | Sum per-CLI wall ms | Longest one CLI ms | Launch spacing ms | Gap after earlier CLI completes ms (negative means overlap) |",
              "|---|---:|---:|---:|---:|---:|"]
    for condition in CONDITIONS:
        t = report["pair_timing"][condition]
        gaps = ", ".join(f"{value:.1f}" for value in t.get("ordered_inter_invocation_start_minus_previous_completion_ms", [])) or "n/a"
        lines.append(f"| {condition} | {t['pair_cli_makespan_utc_ms']:.1f} | {t['sum_per_cli_wall_ms']:.1f} | "
                     f"{t['max_single_cli_wall_ms']:.1f} | {t['launch_spacing_ms']:.1f} | {gaps} |")
    lines += ["", "## Request intervals", "",
              "| Condition | Intent | Request seq | Selected candidate | Proxy round ms | Start UTC | Complete UTC |",
              "|---|---|---:|---|---:|---|---|"]
    for row in report["invocations"]:
        for event in row["choice_events"]:
            lines.append(f"| {row['condition']} | {row['intent_id']} | {event['seq']} | {event['candidate_id']} | "
                         f"{event['duration_ms']:.1f} | {event['started_utc']} | {event['completed_utc']} |")
    lines += ["", "## Measurement and interpretation", "",
              f"- Gooo CLI makespan is measured from earliest CLI launch to latest CLI completion within each pair. Per-CLI wall times and exit/fallback/stop details are retained in `report.json` and raw invocation artifacts.",
              f"- Across {report['privacy_audit']['choice_requests_scanned']} raw selection requests, the recursive held-out-field/case audit found {report['privacy_audit']['heldout_leaks_found']} held-out fields or exact holdout input/expected pairs. Holdout scores in this report are recomputed from the copied finite oracle after final selection.",
              "- Proxy request intervals measure outstanding loopback HTTP transactions, not the model-forward interval or server queue delay. The installed server review documents one inference worker and a separate admission cap of 16. If request intervals overlap, the work is serialized at the inference worker; the queue wait itself was not instrumented.",
              "- Condition order was fixed as sequential then simultaneous and was not randomized. Each condition used a fresh owned Laya service that was preloaded and health-checked before the CLI pair; there were no separate warmup requests. With one replicate per condition, order, model/cache state, and other cold-start effects are uncontrolled and can contribute to observed timing differences.",
              "- The sequential pair has about a 0.5 s gap between CLI processes because each invocation shuts down its capture proxy before the next CLI launches. The runner calls `CaptureProxy.stop()` per invocation, and that method calls `ThreadingHTTPServer.shutdown()`; the observed 523.5 ms gap is consistent with the server loop's 0.5 s default poll interval. This is harness teardown, not active Gooo CLI work. The 1454.0 ms vs 867.5 ms pair makespans must not be described as a 40% Gooo speed benefit. Sequential per-CLI wall durations sum to 930.5 ms; the longest simultaneous CLI is 865.8 ms, about 7% lower in this single observation, which is still no causal or general speed claim.",
              f"- The prior canonical cohort's first Laya-backed invocation had a {timing_context['first_laya_invocation_harness_window_minus_decision_latency_ms']:.1f} ms harness-window excess over summed decision latency; its three later windows were +{prior_later_gaps} ms. The prior window ends after sampler shutdown/join and stdout/stderr persistence; the excess cause is unisolated. See `{timing_context['source']}` (SHA-256 `{timing_context['source_sha256']}`).",
              "- CPU uses sampled process cumulative `ps` CPU-time deltas divided by the separate condition resource window shown in the table. That window starts at the sampler's pre-CLI sample and ends after post-invocation health sampling; it is not the CLI pair makespan. RSS is maximum sampled RSS, not an OS lifetime peak. Laya is measured condition-wide while the service remains alive; CLI samples are per-process and coarse. Resource samples and counts are in each condition directory.",
              "- This is one pair per condition on one host. No statistical performance claim or deadlock-freedom claim is made. A completed bounded run only shows these invocations returned or hit their recorded harness/provider outcome.",
              "- Raw stdout/stderr, exact request/response bodies, timestamps, hashes, process samples, condition health snapshots, and source copies are retained under `conditions/`. No model, virtualenv, or binary is copied into the cohort.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    metadata = read_json(run_dir / "run-metadata.json")
    manifest = read_json(run_dir / "input-manifest.json")
    if sha256((run_dir / "input-manifest.json").read_bytes()) != metadata["cohort_manifest_sha256"]:
        raise RuntimeError("saved manifest digest mismatch")
    invocations = []
    for condition in CONDITIONS:
        for intent_id in INTENTS:
            path = run_dir / "conditions" / condition / "invocations" / intent_id / "invocation.json"
            if path.is_file():
                invocations.append(summarize_invocation(run_dir, condition, intent_id, metadata, manifest))
    conditions = {}
    for condition in CONDITIONS:
        condition_path = run_dir / "conditions" / condition / "condition.json"
        if condition_path.exists():
            conditions[condition] = {"metadata": read_json(condition_path), "resources": condition_resources(run_dir, condition)}
    choice_count = sum(row["model_choice_count"] for row in invocations)
    perfect_model_choices = sum(row["model_choices_training_perfect"] for row in invocations)
    first_model_choices = [row for row in invocations if row["model_choice_count"] > 0]
    report = {
        "schema": "gooo/ir-search-parallel-study-report/v1",
        "run_id": metadata["run_id"],
        "started_utc": metadata["started_utc"],
        "completed_utc": metadata.get("completed_utc"),
        "source_revision": metadata["source_revision"],
        "binary_sha256": metadata["binary_sha256"],
        "runtime": manifest["runtime"],
        "condition_order": metadata["condition_order"],
        "condition_order_randomized": False,
        "fresh_owned_laya_server_per_condition": True,
        "model_warmup_invocations_per_condition": 0,
        "timing_context_from_prior_primary_cohort": historical_timing_context(),
        "replicates_per_condition": 1,
        "intents_per_condition": 2,
        "invocations": invocations,
        "conditions": conditions,
        "pair_timing": {condition: pair_timing(invocations, condition) for condition in CONDITIONS},
        "request_overlap": request_overlap(invocations),
        "choice_metrics": {
            "first_model_choice_training_perfect": sum(row["first_model_choice_training_perfect"] for row in first_model_choices),
            "first_model_choice_denominator": len(first_model_choices),
            "all_model_choices_training_perfect": perfect_model_choices,
            "all_model_choice_denominator": choice_count,
            "final_training_perfect_invocations": sum(row["training"]["passed"] == row["training"]["total"] for row in invocations),
            "final_holdout_perfect_invocations": sum(row["holdout"]["passed"] == row["holdout"]["total"] for row in invocations),
            "sole_candidate_final_selections": sum(row["final_selection_method"] == "sole_remaining_candidate" for row in invocations),
        },
        "privacy_audit": {"choice_requests_scanned": sum(row["heldout_privacy_audit"]["choice_requests_scanned"] for row in invocations),
                          "heldout_leaks_found": 0},
        "claim_scope": "one observed pair per condition; no statistical, general speed, or deadlock-freedom claim",
        "raw_artifact_index": "conditions/<condition>/{laya/,resource-samples.jsonl,invocations/<intent>/{stdout.raw,stderr.raw,proxy/,invocation.json}}",
    }
    write_json(run_dir / "report.json", report)
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(run_dir / "report.json")


if __name__ == "__main__":
    main()
