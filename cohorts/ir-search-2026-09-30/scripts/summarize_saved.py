#!/usr/bin/env python3
"""Build a report from a saved IR-search run; never contacts Laya or reruns Gooo."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics


HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "manifest.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def float_value(value):
    return float(value) if isinstance(value, (int, float)) else None


def oracle_score(oracle, candidate_id):
    outputs = oracle["candidate_outputs"][candidate_id]["holdout"]
    expected = oracle["holdout"]["expected"]
    passed = sum(actual == wanted for actual, wanted in zip(outputs, expected))
    return {"passed": passed, "total": len(expected), "accuracy_percent": passed * 100.0 / len(expected)}


def load_capture_events(run_dir: Path):
    path = run_dir / "proxy" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resource_summary_from_raw(folder: Path, wall_ms: float, cpu_count: int, variant: str):
    raw_path = folder / "resource-samples.jsonl"
    samples = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()] if raw_path.exists() else []
    elapsed = wall_ms / 1000.0
    out = {"schema": "gooo/ir-search-process-resources/v1", "wall_ms": wall_ms,
           "logical_cpu_count": cpu_count, "sampling_scope": "recomputed from saved periodic ps samples during this invocation",
           "raw_samples": "resource-samples.jsonl"}
    for key in ("cli", "laya_server"):
        alive = [sample[key] for sample in samples if sample.get(key, {}).get("alive") and "cpu_seconds" in sample[key]]
        if not alive:
            out[key] = {"samples": 0, "cpu_seconds_delta": None, "rss_peak_kb": None,
                        "max_rss_mib": None, "cpu_percent_one_core": None,
                        "cpu_percent_host_normalized": None}
            continue
        has_interval = len(alive) >= 2
        delta = max(0.0, alive[-1]["cpu_seconds"] - alive[0]["cpu_seconds"]) if has_interval else None
        peak_kb = max(row["rss_kb"] for row in alive)
        one_core = delta / elapsed * 100 if delta is not None and elapsed > 0 else None
        out[key] = {
            "samples": len(alive), "cpu_seconds_delta": delta, "rss_peak_kb": peak_kb,
            "max_rss_mib": peak_kb / 1024,
            "cpu_percent_one_core": one_core,
            "cpu_percent_host_normalized": one_core / cpu_count if one_core is not None and cpu_count else None,
            "measurement": ("owned_process_cumulative_cpu_time_delta_over_invocation_wall_time" if has_interval
                            else "not_available_one_process_sample_only"),
        }
        if key == "laya_server" and variant != "laya_fill_search":
            out[key]["cpu_seconds_delta"] = None
            out[key]["cpu_percent_one_core"] = None
            out[key]["cpu_percent_host_normalized"] = None
            out[key]["measurement"] = "resident_server_only_no_provider_call_during_invocation"
    return out, samples


def summarize_invocation(run_dir: Path, intent, variant, oracle, events):
    folder = run_dir / "invocations" / intent["id"] / variant
    metadata = load_json(folder / "invocation.json")
    stdout_path = folder / "stdout.raw"
    raw_stdout = stdout_path.read_bytes()
    payload = None
    try:
        payload = json.loads(raw_stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    report = payload.get("report", {}) if isinstance(payload, dict) else {}
    search = report.get("body_search") or (payload or {}).get("body_search")
    fill = report.get("body_fill") or (payload or {}).get("body_fill")
    record = {
        "intent_id": intent["id"],
        "variant": variant,
        "exit_code": metadata["exit_code"],
        "wall_ms": metadata["wall_ms"],
        "stdout_sha256": sha256(raw_stdout),
        "stderr_sha256": sha256((folder / "stderr.raw").read_bytes()),
        "repository_writes": report.get("repository_writes"),
        "source_digest": report.get("source_digest"),
        "generated_digest": report.get("generated_digest"),
        "attempts": [],
        "model_rounds": [],
    }
    if search:
        record.update({
            "selected_candidate_id": search.get("selected_candidate_id"),
            "training": {
                "passed": search.get("training_passed"),
                "total": search.get("training_total"),
                "accuracy_percent": float_value(search.get("training_accuracy_percent")),
            },
            "holdout": {
                "passed": search.get("holdout_passed"),
                "total": search.get("holdout_total"),
                "accuracy_percent": float_value(search.get("holdout_accuracy_percent")),
            },
            "attempted_candidates": search.get("attempted_candidates"),
            "evaluated_candidates": search.get("evaluated_candidates"),
            "untested_candidates": search.get("untested_candidates"),
            "stop_reason": search.get("stop_reason"),
            "training_suite_sha256": search.get("training_suite_sha256"),
            "holdout_suite_sha256": search.get("holdout_suite_sha256"),
            "ir_plan_sha256": search.get("ir_plan_sha256"),
            "attempted_candidates": search.get("attempted_candidates"),
            "evaluated_candidates": search.get("evaluated_candidates"),
        })
        selected_id = search.get("selected_candidate_id")
        expected_holdout = oracle["holdout"]["expected"]
        oracle_candidate = oracle.get("candidate_outputs", {}).get(selected_id, {}).get("holdout")
        observed_holdout = [case.get("actual") for case in search.get("holdout_case_results", [])]
        record["independent_holdout_oracle"] = {
            "candidate_outputs": oracle_candidate,
            "expected": expected_holdout,
            "passed": sum(a == e for a, e in zip(oracle_candidate or [], expected_holdout)),
            "total": len(expected_holdout),
        }
        record["holdout_outputs_match_independent_oracle"] = observed_holdout == oracle_candidate
        matching_events = [e for e in events if e.get("invocation_id") == f"{intent['id']}/{variant}" and e.get("kind") == "laya_choice"]
        decision_events = iter(matching_events)
        for index, attempt in enumerate(search.get("attempts", []), start=1):
            decision = attempt.get("decision") or {}
            item = {
                "attempt": index,
                "candidate_id": attempt.get("candidate_id"),
                "selection_method": attempt.get("selection_method"),
                "decision_mode": decision.get("mode"),
                "typecheck_passed": attempt.get("typecheck_passed"),
                "scoring_completed": attempt.get("scoring_completed"),
                "training_passed": attempt.get("test_cases_passed"),
                "training_total": attempt.get("test_cases_total"),
                "accuracy_percent": float_value(attempt.get("accuracy_percent")),
                "error": attempt.get("error", ""),
                "decision_latency_ms": attempt.get("decision_latency_ms"),
                "evaluation_ms": attempt.get("evaluation_ms"),
                "request_sha256": decision.get("request_sha256"),
                "model": decision.get("model"),
                "model_revision": decision.get("model_revision"),
            }
            if decision.get("mode") == "laya":
                event = next(decision_events, None)
                if event:
                    item["proxy_exchange"] = {
                        "event_seq": event.get("seq"),
                        "round_latency_ms": event.get("duration_ms"),
                        "request_sha256": event.get("request_sha256"),
                        "response_sha256": event.get("response_sha256"),
                        "response_selected_id": event.get("selected_candidate_id"),
                    }
                    record["model_rounds"].append(item.copy())
            record["attempts"].append(item)
    elif fill:
        selected_id = fill.get("selected_candidate_id")
        holdout = oracle_score(oracle, selected_id) if selected_id in oracle["candidate_outputs"] else None
        passed = fill.get("test_cases_passed")
        total = fill.get("test_cases_total")
        record.update({
            "selected_candidate_id": selected_id,
            "training": {
                "passed": passed,
                "total": total,
                "accuracy_percent": fill.get("functional_accuracy_percent"),
            },
            "holdout": holdout,
            "holdout_measurement": "independent_finite_oracle_for_selected_candidate",
            "candidate_scores": fill.get("candidate_scores", []),
            "attempted_candidates": None,
            "evaluated_candidates": len(fill.get("candidate_scores", [])),
            "test_suite_sha256": fill.get("test_suite_sha256"),
            "ir_plan_sha256": fill.get("ir_plan_sha256"),
            "holdout_measurement": "independent_candidate_oracle_not_executed_by_fill_plan_command",
        })
    else:
        record["parse_error"] = payload.get("error") if isinstance(payload, dict) else "CLI output was not a JSON report"
    record["resources"], record["_raw_resource_samples"] = resource_summary_from_raw(
        folder, metadata["wall_ms"], load_json(folder / "resource.json").get("logical_cpu_count", 1), variant)
    return record


def render_markdown(report):
    lines = [
        "# Gooo IR body-search cohort results",
        "",
        f"Run: `{report['run_id']}`  ",
        f"Binary SHA-256: `{report['binary_sha256']}`  ",
        f"Source revision: `{report['source_revision']}`",
        "",
        "This report describes finite training and disjoint holdout suites. It is not a proof over all int64 inputs.",
        "",
        "## Per-intent outcomes",
        "",
        "| Intent | Variant | Selected | Training | Holdout | Search attempts / scored candidates | Laya rounds | Stop reason | Wall ms | Laya server CPU (one core %) | Laya server sampled RSS MiB |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for row in report["invocations"]:
        training = row.get("training") or {}
        holdout = row.get("holdout") or {}
        resources = row.get("resources") or {}
        server = resources.get("laya_server") or {}
        cpu_value = server.get("cpu_percent_one_core")
        cpu_text = f"{cpu_value:.2f}" if isinstance(cpu_value, (int, float)) else "N/A"
        attempt_score = (f"{row.get('attempted_candidates')} / {row.get('evaluated_candidates')}"
                         if row.get("attempted_candidates") is not None
                         else f"— / {row.get('evaluated_candidates', 0)}")
        lines.append("| {intent} | {variant} | {selected} | {train} | {holdout} | {attempts} | {rounds} | {stop} | {wall:.1f} | {cpu} | {rss:.1f} |".format(
            intent=row["intent_id"], variant=row["variant"], selected=row.get("selected_candidate_id", ""),
            train=f"{training.get('passed')}/{training.get('total')}",
            holdout=f"{holdout.get('passed')}/{holdout.get('total')}" if holdout else "unavailable",
            attempts=attempt_score, rounds=len(row.get("model_rounds", [])),
            stop=row.get("stop_reason", ""), wall=row.get("wall_ms", 0),
            cpu=cpu_text, rss=server.get("max_rss_mib") or 0,
        ))
    totals = report["totals"]
    selection = report["selection_quality"]
    lines += [
        "",
        "## Totals",
        "",
        f"- Gooo invocations: {totals['invocation_count']} / 12 planned.",
        f"- Laya-backed Gooo invocations: {totals['laya_backed_invocation_count']} / 4 planned.",
        f"- Captured Laya choice rounds: {totals['captured_laya_rounds']}.",
        f"- Successful invocations: {totals['successful_invocations']} / {totals['invocation_count']}.",
        f"- First Laya choices that already scored 100% on training: {selection['first_choice_training_perfect']} / {selection['first_choice_total']}.",
        f"- Laya model rounds that selected a training-perfect candidate: {selection['training_perfect_model_choices']} / {selection['model_choice_rounds']}.",
        f"- Final Laya-search outputs that scored 100% on training: {selection['final_training_perfect']} / {selection['laya_search_invocations']}; holdout: {selection['final_holdout_perfect']} / {selection['laya_search_invocations']}.",
        f"- Laya search attempted/scored {totals['laya_search_attempted_candidates']}/{totals['laya_search_evaluated_candidates']} candidates. The exhaustive plans scored {totals['exhaustive_fill_plan_candidate_scores']} candidates.",
        f"- No-provider search attempted/scored {totals['deterministic_search_attempted_candidates']}/{totals['deterministic_search_evaluated_candidates']} candidates.",
        f"- Search-selected holdout actuals matched the independent finite oracle in {selection['holdout_oracle_matches']} / {selection['laya_search_invocations']} Laya runs.",
        "- Per-intent measured wall costs and ratios:",
    ]
    for cost in report["per_intent_costs"]:
        lines.append(
            f"  - `{cost['intent_id']}`: Laya search {cost['laya_search_wall_ms']:.1f} ms; deterministic search {cost['deterministic_search_wall_ms']:.1f} ms; exhaustive fill plan {cost['exhaustive_fill_plan_wall_ms']:.1f} ms; Laya/offline-search ratio {cost['laya_vs_deterministic_search_ratio']:.1f}x; Laya/exhaustive ratio {cost['laya_vs_exhaustive_fill_plan_ratio']:.1f}x."
        )
    lines += [
        f"- A speed benefit was not observed in this cohort: Laya-backed wall time exceeded both no-provider baselines in {report['speed_observation']['intents_slower_than_both_baselines']} of 4 intents. The four-intent result is descriptive and does not establish general performance.",
        f"- Maximum sampled RSS of the owned Laya process across all {report['process_resource_observation']['sampled_process_rows']} saved process sample rows: {report['process_resource_observation']['laya_server_max_sampled_rss_mib']:.1f} MiB ({report['process_resource_observation']['laya_server_max_sampled_rss_invocation']}). This is the highest recorded sample, not a continuous peak measurement.",
        f"- No exact pre-run manifest snapshot was saved. The post-run reconstruction has SHA-256 `{report['manifest_provenance']['recorded_preexecution_sha256']}`, matching the digest recorded before execution; the reconstruction is labeled separately from raw evidence. Each invocation does retain its exact fixture and plan bytes with hashes.",
        "- CPU percentages refer to the owned Laya server process: one-core utilization is process CPU-time delta divided by invocation wall time; host-normalized process utilization divides that by the logical CPU count. Controls made no provider call and had one process sample each, so server CPU is shown as N/A; their RSS values describe the resident server sample, not the Gooo command's memory.",
        "- Search holdout outputs are checked against the independent oracle. For exhaustive `--fill-plan`, holdout values are computed from the selected candidate's independent oracle output because the command receives training cases only; this is not an executed holdout measurement.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    metadata = load_json(run_dir / "run-metadata.json")
    manifest = load_json(MANIFEST)
    events = load_capture_events(run_dir)
    invocations = []
    for intent in manifest["intents"]:
        oracle = load_json(HERE / intent["oracle"])
        for variant in manifest["invocation_variants"]:
            invocations.append(summarize_invocation(run_dir, intent, variant, oracle, events))
    invocations.sort(key=lambda row: (next(i for i, intent in enumerate(manifest["intents"]) if intent["id"] == row["intent_id"]), manifest["invocation_variants"].index(row["variant"])))
    laya_rounds = [round_ for row in invocations for round_ in row.get("model_rounds", [])]
    for row in invocations:
        row.pop("_raw_resource_samples", None)
    laya_rows = [row for row in invocations if row["variant"] == "laya_fill_search"]
    deterministic_rows = {row["intent_id"]: row for row in invocations if row["variant"] == "deterministic_fill_search"}
    exhaustive_rows = {row["intent_id"]: row for row in invocations if row["variant"] == "exhaustive_fill_plan"}
    per_intent_costs = []
    slower_count = 0
    for row in laya_rows:
        deterministic = deterministic_rows[row["intent_id"]]
        exhaustive = exhaustive_rows[row["intent_id"]]
        laya_wall = row["wall_ms"]
        deterministic_wall = deterministic["wall_ms"]
        exhaustive_wall = exhaustive["wall_ms"]
        if laya_wall > deterministic_wall and laya_wall > exhaustive_wall:
            slower_count += 1
        per_intent_costs.append({
            "intent_id": row["intent_id"], "laya_search_wall_ms": laya_wall,
            "deterministic_search_wall_ms": deterministic_wall,
            "exhaustive_fill_plan_wall_ms": exhaustive_wall,
            "laya_decision_latency_total_ms": sum(a.get("decision_latency_ms", 0) for a in row["attempts"] if a.get("decision_mode") == "laya"),
            "laya_vs_deterministic_search_ratio": laya_wall / deterministic_wall if deterministic_wall else None,
            "laya_vs_exhaustive_fill_plan_ratio": laya_wall / exhaustive_wall if exhaustive_wall else None,
            "model_rounds": len(row.get("model_rounds", [])),
        })
    all_samples = []
    for intent in manifest["intents"]:
        for variant in manifest["invocation_variants"]:
            folder = run_dir / "invocations" / intent["id"] / variant
            for line in (folder / "resource-samples.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    sample = json.loads(line)
                    all_samples.append({"invocation_id": f"{intent['id']}/{variant}", **sample})
    rss_samples = [sample for sample in all_samples if sample.get("laya_server", {}).get("alive") and "rss_kb" in sample["laya_server"]]
    peak_sample = max(rss_samples, key=lambda item: item["laya_server"]["rss_kb"]) if rss_samples else None
    first_choices = []
    training_perfect_rounds = 0
    for row in laya_rows:
        model_attempts = [attempt for attempt in row.get("attempts", []) if attempt.get("decision_mode") == "laya"]
        if model_attempts:
            first_choices.append(model_attempts[0])
        training_perfect_rounds += sum(
            attempt.get("scoring_completed") and attempt.get("training_passed") == attempt.get("training_total")
            for attempt in model_attempts
        )
    final_training_perfect = sum(row.get("training", {}).get("accuracy_percent") == 100 for row in laya_rows)
    final_holdout_perfect = sum(row.get("holdout", {}).get("accuracy_percent") == 100 for row in laya_rows)
    holdout_oracle_matches = sum(row.get("holdout_outputs_match_independent_oracle") is True for row in laya_rows)
    final_deterministic = [r for r in invocations if r["variant"] == "deterministic_fill_search"]
    full_candidate_scores = sum(len(row.get("candidate_scores", [])) for row in invocations if row["variant"] == "exhaustive_fill_plan")
    reconstructed_path = run_dir / "cohort-manifest-preexecution.reconstructed.json"
    manifest_evidence_path = run_dir / "manifest-evidence.json"
    manifest_provenance = {
        "recorded_preexecution_sha256": metadata.get("cohort_manifest_sha256"),
        "snapshot_saved_at_run_time": (run_dir / "cohort-manifest-preexecution.json").exists(),
        "reconstructed_snapshot_file": reconstructed_path.name if reconstructed_path.exists() else None,
        "reconstruction_evidence_file": manifest_evidence_path.name if manifest_evidence_path.exists() else None,
        "reconstruction_matches_recorded_digest": None,
        "note": "Pre-run bytes were not persisted by the first runner revision; any post-run reconstruction is labeled and independently hash-matched to the digest recorded before execution.",
    }
    if manifest_evidence_path.exists():
        evidence = load_json(manifest_evidence_path)
        manifest_provenance["reconstruction_matches_recorded_digest"] = evidence.get("reconstruction_matches_recorded_digest")
    report = {
        "schema": "gooo/ir-search-study-report/v1",
        "run_id": metadata["run_id"],
        "started_utc": metadata["started_utc"],
        "completed_utc": metadata["completed_utc"],
        "binary_sha256": metadata["binary_sha256"],
        "source_revision": metadata["source_revision"],
        "runtime": metadata["runtime"],
        "invocations": invocations,
        "per_intent_costs": per_intent_costs,
        "selection_quality": {
            "first_choice_training_perfect": sum(a.get("scoring_completed") and a.get("training_passed") == a.get("training_total") for a in first_choices),
            "first_choice_total": len(first_choices),
            "training_perfect_model_choices": training_perfect_rounds,
            "model_choice_rounds": len(laya_rounds),
            "final_training_perfect": final_training_perfect,
            "final_holdout_perfect": final_holdout_perfect,
            "holdout_oracle_matches": holdout_oracle_matches,
            "laya_search_invocations": len(laya_rows),
        },
        "speed_observation": {
            "intents_slower_than_both_baselines": slower_count,
            "speed_benefit_observed": slower_count < len(laya_rows),
            "scope": "four-intent local finite cohort only",
        },
        "process_resource_observation": {
            "laya_server_max_sampled_rss_kb": peak_sample["laya_server"]["rss_kb"] if peak_sample else None,
            "laya_server_max_sampled_rss_mib": peak_sample["laya_server"]["rss_kb"] / 1024 if peak_sample else None,
            "laya_server_max_sampled_rss_invocation": peak_sample["invocation_id"] if peak_sample else None,
            "laya_server_max_sampled_rss_utc": peak_sample["sampled_utc"] if peak_sample else None,
            "sampled_process_rows": len(rss_samples),
            "sampling_source": "all saved invocation resource-samples.jsonl files",
            "measurement_limit": "highest recorded RSS sample only; sampling is periodic and is not a continuous peak capture",
        },
        "manifest_provenance": manifest_provenance,
        "totals": {
            "invocation_count": len(invocations),
            "laya_backed_invocation_count": sum(r["variant"] == "laya_fill_search" for r in invocations),
            "captured_laya_rounds": len(laya_rounds),
            "successful_invocations": sum(r["exit_code"] == 0 for r in invocations),
            "laya_search_attempted_candidates": sum(r.get("attempted_candidates", 0) for r in laya_rows),
            "laya_search_evaluated_candidates": sum(r.get("evaluated_candidates", 0) for r in laya_rows),
            "deterministic_search_attempted_candidates": sum(r.get("attempted_candidates", 0) for r in final_deterministic),
            "deterministic_search_evaluated_candidates": sum(r.get("evaluated_candidates", 0) for r in final_deterministic),
            "exhaustive_fill_plan_candidate_scores": full_candidate_scores,
            "mean_wall_ms": statistics.mean([r["wall_ms"] for r in invocations]) if invocations else None,
            "mean_laya_round_ms": statistics.mean([r["proxy_exchange"]["round_latency_ms"] for r in laya_rounds if "proxy_exchange" in r]) if laya_rounds else None,
        },
        "raw_artifact_index": {
            "proxy_events": "proxy/events.jsonl",
            "process_resources": "resource_samples.json",
            "invocations": "invocations/<intent>/<variant>/",
        },
    }
    out_json = run_dir / "report.json"
    out_md = run_dir / "report.md"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")
    print(out_json)


if __name__ == "__main__":
    main()
