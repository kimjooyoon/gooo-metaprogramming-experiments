#!/usr/bin/env python3
"""Adapt a frozen TDD v8 capture into the extra-domain source-manifest API.

This adapter reads captured artifacts only. It does not execute Go or call a
provider. A partial capture is preserved as a non-replayable draft with every
planned cell represented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from replay_extra_domain_probes import (
    PROBE_DIR,
    SOURCE_SCHEMA,
    plans_by_design,
    safe_name,
    sha256,
    validate_probe_freeze,
)
from replay_extra_domain_probes_v2 import validate_source_manifest


TDD_DESIGN_SHA256 = "ab691ac00f73abc1cef9648da58c20a1816d7ab16cda7e59536054bea9a66b52"
TDD_PHASE_PLANS_SHA256 = "e3ceeaa24d187e1a14c52e4c946b99751e305607491f4164f96e8b822e5b023e"
TDD_RUNNER_SHA256 = "0aabee1c485c9b0333c43dc3f7ce79c137e2e5b3651ca77483b2d2923a97cfee"
TDD_PREPARE_SHA256 = "f59e1132481bfcc81d84dfceb8e4e74601a31b265b252c18923014dac2df254b"
TDD_PROXY_SHA256 = "58b414b6dfa5070666514eae4bc044474c8ca19162a825fd2afc749023075dea"
TDD_SELECTION_SHA256 = "0c6ba54ded4c4cce5086945e74e25567aad23e492c7b3e45d05a7262e27771d6"
PROBE_FREEZE_SHA256 = "7c67f6d8faeccc79ef9a802cf31313d51b72288cfa4ce2d4c2dadfd933ac6061"
PROBE_ROWS_SHA256 = "8040a38fc43e6efa458d119c65d7ff6a6cb4518d8a8e1bbbcf4494068df917bd"
MODEL_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
COMPILER_REVISION = "f3e576ad55796c0d42b2af8b86f874b49baa61d8"
EXPECTED_ARMS = ("compact_multilingual_single", "compact_multilingual_local_feedback")
RUN_FILES = (
    "report.json", "summary.json", "run-metadata.json", "study-design.json",
    "study-design.sha256", "phase-plans.json", "preexecution.json",
    "proxy/events.json", "study-code/scripts/run_study_v8.py",
    "study-code/scripts/prepare_study.py",
    "study-code/dependencies/run_pinned_context_study.py",
    "study-code/dependencies/selection_support.py",
)
ARCHIVE_PINS = {
    "study-code/scripts/run_study_v8.py": TDD_RUNNER_SHA256,
    "study-code/scripts/prepare_study.py": TDD_PREPARE_SHA256,
    "study-code/dependencies/run_pinned_context_study.py": TDD_PROXY_SHA256,
    "study-code/dependencies/selection_support.py": TDD_SELECTION_SHA256,
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(raw: bytes, label: str) -> object:
    try:
        return json.loads(raw.decode("utf-8", errors="strict"),
                          object_pairs_hook=reject_duplicate_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValueError(f"non-finite JSON number: {value}")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON: {exc}") from exc


def read_json(path: Path, label: str) -> tuple[object, bytes]:
    raw = path.read_bytes()
    return parse_json(raw, label), raw


def strict_relative_file(root: Path, value: object, label: str,
                         expected_tree: tuple[str, ...] | None = None) -> tuple[Path, bytes]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{label} is not a safe relative path")
    relative = PurePosixPath(value)
    if (relative.is_absolute() or relative.as_posix() != value
            or any(part in ("", ".", "..") for part in relative.parts)):
        raise ValueError(f"{label} is not a normalized relative path")
    if expected_tree is not None and tuple(relative.parts[:len(expected_tree)]) != expected_tree:
        raise ValueError(f"{label} is outside its declared artifact tree")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} contains a symlink")
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError(f"{label} escapes its capture root") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} is not a file")
    return resolved, resolved.read_bytes()


def copy_bytes(root: Path, destination_root: Path, relative: str, label: str,
               expected_tree: tuple[str, ...] | None = None) -> tuple[Path, bytes]:
    source, raw = strict_relative_file(root, relative, label, expected_tree)
    target = destination_root / Path(*PurePosixPath(relative).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return source, raw


def recursive_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from recursive_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_keys(child)


def canonical_go_json(value: object) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return (raw.replace(b"&", b"\\u0026").replace(b"<", b"\\u003c")
            .replace(b">", b"\\u003e").replace("\u2028".encode(), b"\\u2028")
            .replace("\u2029".encode(), b"\\u2029"))


def typed_request_sha(outer: dict) -> str:
    state_wire = outer["state"]["request"]
    state = parse_json(state_wire.encode("utf-8"), "typed request state")
    questions = outer["questions"]
    if not isinstance(state, dict) or not isinstance(questions, dict) or len(questions) != 1:
        raise ValueError("raw provider request must contain one typed body-search question")
    candidates = state.get("remaining_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("raw provider request has no remaining candidates")
    question_id, question = next(iter(questions.items()))
    if not isinstance(question, dict) or not isinstance(question.get("instructions"), str):
        raise ValueError("raw provider question instructions are missing")
    criteria = question.get("criteria")
    expected_criteria = {item["id"]: "Try this exact expression: " + item["expression"]
                         for item in candidates}
    if (question_id != "body_ir_search" or question.get("type") != "choice"
            or criteria != expected_criteria):
        raise ValueError("raw provider question choices differ from their exact candidate expressions")
    request = {
        "schema": "gooo/typed-decision-request/v1",
        "state": state_wire,
        "question": {
            "id": question_id,
            "instructions": question["instructions"],
            "options": [{"id": item["id"],
                         "description": "Try this exact expression: " + item["expression"]}
                        for item in candidates],
        },
        "fallback": candidates[0]["id"],
        "provider_model": outer["model"],
    }
    return "sha256:" + digest(canonical_go_json(request))


def load_frozen_designs() -> tuple[dict, dict]:
    catalog, plans = plans_by_design()
    return catalog, plans


def verify_frozen_run_files(run_root: Path) -> tuple[dict, dict, dict, list[dict], list[str]]:
    issues: list[str] = []
    decoded = {}
    raw_by_path = {}
    for relative in RUN_FILES:
        try:
            _, raw = strict_relative_file(run_root, relative, relative)
            raw_by_path[relative] = raw
        except (OSError, ValueError) as exc:
            issues.append(f"missing or unsafe frozen capture artifact {relative}: {exc}")
    if issues:
        return {}, {}, {}, [], issues
    for name in ("report.json", "run-metadata.json", "study-design.json", "phase-plans.json",
                 "preexecution.json", "proxy/events.json"):
        decoded[name] = parse_json(raw_by_path[name], name)
    report, metadata = decoded["report.json"], decoded["run-metadata.json"]
    design, phase, preexecution = (decoded["study-design.json"], decoded["phase-plans.json"],
                                   decoded["preexecution.json"])
    events_doc = decoded["proxy/events.json"]
    if digest(raw_by_path["study-design.json"]) != TDD_DESIGN_SHA256:
        issues.append("TDD v8 study-design bytes differ from the adapter's frozen pin")
    if digest(raw_by_path["phase-plans.json"]) != TDD_PHASE_PLANS_SHA256:
        issues.append("TDD v8 phase-plan bytes differ from the adapter's frozen pin")
    if not isinstance(design, dict) or design.get("schema") != "gooo/ir-composition-tdd-study-design/v6":
        issues.append("TDD v8 study-design schema is invalid")
    design_arms = design.get("arms", []) if isinstance(design, dict) else []
    arm_specs = {row.get("id"): row for row in design_arms if isinstance(row, dict)}
    if set(arm_specs) != set(EXPECTED_ARMS):
        issues.append("TDD study design arm IDs differ from the frozen two-arm study")
    for arm_id, max_attempts in ((EXPECTED_ARMS[0], 1), (EXPECTED_ARMS[1], 3)):
        arm_spec = arm_specs.get(arm_id, {})
        if (arm_spec.get("provider_model") != "multilingual" or arm_spec.get("prompt_profile") != "compact"
                or arm_spec.get("external_training_feedback") is not False
                or arm_spec.get("max_attempts") != max_attempts):
            issues.append(f"TDD study arm does not match frozen prompt/model/attempt controls: {arm_id}")
    if not isinstance(phase, dict) or phase.get("planned_cells") != 64 or not isinstance(phase.get("plans"), list):
        issues.append("TDD v8 phase-plan schema is invalid")
    if not isinstance(preexecution, dict) or preexecution.get("schema") != "gooo/ir-composition-tdd-preexecution/v1":
        issues.append("TDD v8 preexecution receipt schema is invalid")
    if not isinstance(report, dict) or report.get("schema") != "gooo/ir-composition-tdd-capture-report/v1":
        issues.append("TDD v8 capture report schema is invalid")
    if not isinstance(metadata, dict) or metadata.get("schema") != "gooo/ir-composition-tdd-run-metadata/v1":
        issues.append("TDD v8 run-metadata schema is invalid")
    if not isinstance(events_doc, dict) or events_doc.get("schema") != "gooo/ir-composition-tdd-capture-events/v1":
        issues.append("TDD v8 proxy event index schema is invalid")
    if issues:
        return report if isinstance(report, dict) else {}, metadata if isinstance(metadata, dict) else {}, \
            phase if isinstance(phase, dict) else {}, [], issues
    expected_design_checksum = raw_by_path["study-design.sha256"].decode("ascii", errors="strict").split()[0]
    if expected_design_checksum != TDD_DESIGN_SHA256:
        issues.append("run-local study-design.sha256 does not bind the pinned design")
    if metadata.get("design_sha256") != TDD_DESIGN_SHA256:
        issues.append("run metadata does not bind the pinned study design")
    if metadata.get("preexecution_sha256") != digest(raw_by_path["preexecution.json"]):
        issues.append("run metadata does not bind the exact preexecution receipt")
    if metadata.get("provider_model") != "multilingual" or metadata.get("model_revision") != MODEL_REVISION:
        issues.append("run metadata provider model or revision differs from the frozen route pin")
    if metadata.get("planned_cells") != 64 or metadata.get("planned_intentions") != 32:
        issues.append("run metadata planned denominator differs from the frozen study")
    if metadata.get("measured_provider_post_cap") != 96 or metadata.get("warmup_calls") != 0:
        issues.append("run metadata provider POST cap or warmup count differs from the frozen study")
    if preexecution.get("design_sha256") != TDD_DESIGN_SHA256 or preexecution.get("planned_cells") != 64:
        issues.append("preexecution receipt does not bind the frozen 64-cell design")
    compiler = preexecution.get("compiler", {})
    if (compiler.get("sha256") != design.get("compiler", {}).get("sha256")
            or compiler.get("source_revision") != design.get("compiler", {}).get("source_revision")):
        issues.append("preexecution compiler pin differs from frozen study design")
    archive = {item.get("path"): item for item in preexecution.get("study_code_archive", [])
               if isinstance(item, dict)}
    for relative, expected in ARCHIVE_PINS.items():
        item = archive.get(relative, {})
        raw = raw_by_path.get(relative)
        if (raw is None or digest(raw) != expected or item.get("sha256") != expected
                or item.get("bytes") != len(raw)):
            issues.append(f"TDD capture source archive does not match frozen pin: {relative}")
    if preexecution.get("holdout_values_loaded") is not False:
        issues.append("preexecution receipt does not keep holdout values out of capture")
    if phase.get("new_intention_count") != 0 or len(phase.get("plans", [])) != 64:
        issues.append("phase plans do not preserve the 32-intent, 64-cell design")
    rows = phase.get("plans", [])
    if len({row.get("sequence") for row in rows if isinstance(row, dict)}) != 64:
        issues.append("phase plans contain duplicate or missing sequence numbers")
    if any(row.get("arm") not in EXPECTED_ARMS for row in rows if isinstance(row, dict)):
        issues.append("phase plans contain an unknown arm")
    counts = {arm: sum(row.get("arm") == arm for row in rows if isinstance(row, dict))
              for arm in EXPECTED_ARMS}
    if any(count != 32 for count in counts.values()):
        issues.append("phase plans do not contain 32 rows per frozen arm")
    event_rows = events_doc.get("events")
    if not isinstance(event_rows, list) or events_doc.get("raw_event_count") != len(event_rows):
        issues.append("proxy event index count differs from its raw events")
        event_rows = []
    return report, metadata, phase, event_rows, issues


def load_invocations(run_root: Path, phase_rows: list[dict], bundle_capture: Path) -> tuple[dict, dict, list[str]]:
    expected = {(row["sequence"], row["intent_id"], row["arm"]): row for row in phase_rows}
    found: dict[tuple[int, str, str], tuple[dict, str]] = {}
    artifact_index = {}
    inv_root = run_root / "invocations"
    if not inv_root.is_dir():
        return found, {"invocation_directory": "missing"}, ["invocation directory is missing"]
    issues = []
    for path in sorted(inv_root.rglob("*.json")):
        if path.name != "invocation.json" and not re.fullmatch(r"not-started-\d+\.json", path.name):
            continue
        try:
            relative = path.relative_to(run_root).as_posix()
            _, raw = strict_relative_file(run_root, relative, "invocation record", ("invocations",))
            record = parse_json(raw, relative)
            if not isinstance(record, dict):
                continue
            key = (record.get("sequence"), record.get("intent_id"), record.get("arm"))
            if key not in expected:
                issues.append(f"unplanned invocation record: {relative}")
                continue
            if key in found:
                issues.append(f"duplicate invocation record for planned cell {key}")
                continue
            found[key] = (record, relative)
            target = bundle_capture / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            artifact_index[relative] = {"sha256": digest(raw), "bytes": len(raw)}
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            issues.append(f"invocation record could not be independently parsed: {path.name}: {exc}")
    return found, artifact_index, issues


def plans_match_revision2(tdd_plan: object, frozen_plan: dict, row: dict) -> bool:
    if not isinstance(tdd_plan, dict):
        return False
    for key in ("intent", "hole_id", "candidates", "test_cases"):
        if tdd_plan.get(key) != frozen_plan.get(key):
            return False
    return (tdd_plan.get("schema") == "gooo/body-codegen-ir-search-plan/v1"
            and tdd_plan.get("provider_model") == "multilingual"
            and tdd_plan.get("prompt_profile") == "compact"
            and tdd_plan.get("max_attempts") == row.get("max_attempts"))


def event_bytes(run_root: Path, event: dict, bundle_capture: Path) -> tuple[bytes, bytes, dict]:
    request_path, request = strict_relative_file(run_root, event.get("request_file"),
                                                  "proxy request file", ("proxy", "requests"))
    response_path, response = strict_relative_file(run_root, event.get("response_file"),
                                                    "proxy response file", ("proxy", "responses"))
    stored = {}
    for value, raw in ((event["request_file"], request), (event["response_file"], response)):
        target = bundle_capture / Path(*PurePosixPath(value).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        stored[value] = {"sha256": digest(raw), "bytes": len(raw)}
    return request, response, {"stored_files": stored,
                               "source_paths_resolved": [str(request_path.name), str(response_path.name)]}


def verify_health_event(event: dict, run_root: Path, bundle_capture: Path) -> tuple[bool, list[str], dict]:
    issues = []
    info = {"sequence": event.get("seq"), "kind": event.get("kind")}
    try:
        request, response, copied = event_bytes(run_root, event, bundle_capture)
        health = parse_json(response, "health reply")
        if (digest(request) != event.get("request_sha256") or digest(response) != event.get("response_sha256")
                or request != b"" or event.get("status") != 200 or not isinstance(health, dict)
                or health.get("status") != "ok" or health.get("device") != "cpu"
                or "multilingual" not in health.get("loaded", [])
                or health.get("revisions", {}).get("multilingual") != MODEL_REVISION):
            issues.append("health request/reply raw digest or pinned model health did not match")
        info.update(copied)
        return not issues, issues, info
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, [f"health evidence could not be independently verified: {exc}"], info


def verify_post_event(event: dict, attempt: dict, run_root: Path, bundle_capture: Path,
                      plan: dict, model_revision: str) -> tuple[bool, list[str], dict]:
    issues = []
    info = {"sequence": event.get("seq"), "kind": event.get("kind")}
    try:
        req_raw, resp_raw, copied = event_bytes(run_root, event, bundle_capture)
        outer, reply = parse_json(req_raw, "provider request"), parse_json(resp_raw, "provider reply")
        if not isinstance(outer, dict) or not isinstance(reply, dict):
            raise ValueError("provider request and reply must be objects")
        if digest(req_raw) != event.get("request_sha256") or digest(resp_raw) != event.get("response_sha256"):
            issues.append("raw request or reply digest mismatch")
        if event.get("status") != 200 or event.get("method") != "POST" or event.get("path") != "/v1/systemone":
            issues.append("provider event endpoint or HTTP status mismatch")
        if event.get("kind") != "laya_choice":
            issues.append("provider event kind is not laya_choice")
        route_ok = outer.get("model") == "multilingual"
        if not route_ok:
            issues.append("raw request did not pin the multilingual provider model")
        state = parse_json(outer.get("state", {}).get("request", "").encode("utf-8"), "provider request state")
        if not isinstance(state, dict):
            raise ValueError("provider request state must be an object")
        if any("holdout" in key.lower() or "evaluation" in key.lower() for key in recursive_keys(state)):
            issues.append("provider request contains a holdout/evaluation key")
        declared = {item["id"]: item["expression"] for item in plan.get("candidates", [])}
        remaining = state.get("remaining_candidates")
        if not isinstance(remaining, list) or not remaining:
            issues.append("provider request has no declared remaining candidates")
        else:
            seen = set()
            for item in remaining:
                if not isinstance(item, dict) or item.get("id") in seen:
                    issues.append("provider request candidate list is malformed or duplicated")
                    continue
                seen.add(item.get("id"))
                if declared.get(item.get("id")) != item.get("expression"):
                    issues.append("provider request candidate expression differs from frozen plan")
        if typed_request_sha(outer) != (attempt.get("decision") or {}).get("request_sha256"):
            issues.append("native request digest does not bind exact captured request bytes")
        decision = attempt.get("decision") or {}
        route_ok = route_ok and decision.get("mode") == "laya"
        route_ok = route_ok and decision.get("provider") == "laya"
        route_ok = route_ok and decision.get("requested_provider_model") == "multilingual"
        route_ok = route_ok and decision.get("model_revision") == model_revision
        route_ok = route_ok and decision.get("routing", {}).get("model") == "multilingual"
        if not route_ok:
            issues.append("native provider decision receipt differs from the frozen route pin")
        choice = reply.get("answers", {}).get("body_ir_search", {}).get("choice")
        remaining_ids = {item.get("id") for item in state.get("remaining_candidates", [])
                         if isinstance(item, dict)}
        reply_ok = (reply.get("routing", {}).get("model") == "multilingual"
                    and choice == attempt.get("candidate_id") and choice in declared
                    and choice in remaining_ids
                    and event.get("selected_candidate_id") == choice)
        if not reply_ok:
            issues.append("provider reply choice or routing differs from native attempt and frozen plan")
        if attempt.get("expression") != declared.get(attempt.get("candidate_id")):
            issues.append("native attempt expression differs from the frozen candidate")
        info.update(copied)
        info.update({"choice": choice, "typed_request_sha256": typed_request_sha(outer),
                     "provider_route_pin_match": route_ok,
                     "reply_matches_native_attempt": reply_ok})
        return not issues, issues, info
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return False, [f"provider raw exchange could not be independently verified: {exc}"], info


def source_unit_status(receipt: object) -> tuple[bool | None, str | None]:
    if not isinstance(receipt, dict) or receipt.get("schema") != "gooo/metaprogramming-completeness-receipt/v2":
        return None, None
    dimensions = receipt.get("dimensions")
    if not isinstance(dimensions, list):
        return None, None
    rows = [row for row in dimensions if isinstance(row, dict) and row.get("id") == "source_ast_coverage"]
    if len(rows) != 1:
        return None, None
    row = rows[0]
    numerator, denominator, status = row.get("numerator"), row.get("denominator"), row.get("status")
    if (type(numerator) is not int or type(denominator) is not int or denominator <= 0
            or numerator < 0 or numerator > denominator):
        return None, None
    if status == "PASS" and numerator == denominator:
        return True, "source_ast_coverage is PASS with numerator equal to denominator"
    if status in ("FAIL", "FAIL_CLOSED") or numerator != denominator:
        return False, "source_ast_coverage reports a failure or incomplete unit ratio"
    return None, "source_ast_coverage remains unresolved"


def cell_id(row: dict) -> str:
    return f"{row['sequence']:02d}-{row['intent_id']}-{row['arm']}"


def cell_manifest_row(design_id: str, activity: str, status: str,
                      source_path: str | None = None, source_sha: str | None = None,
                      compiler_digest: str | None = None, selected: str | None = None,
                      expression: str | None = None, route_match: bool | None = None,
                      reply_match: bool | None = None, unit_complete: bool | None = None,
                      receipt_path: str | None = None, receipt_sha: str | None = None) -> dict:
    return {
        "design_id": design_id, "activity": activity, "capture_status": status,
        "source_path": source_path, "source_sha256": source_sha,
        "compiler_generated_digest": compiler_digest,
        "selected_candidate_id": selected, "selected_expression": expression,
        "provider_route_pin_match": route_match,
        "captured_reply_matches_compiler_choice": reply_match,
        "source_unit_complete": unit_complete,
        "source_unit_receipt_path": receipt_path,
        "source_unit_receipt_sha256": receipt_sha,
    }


def validate_cell(row: dict, record: dict | None, record_path: str | None, events: list[dict],
                  run_root: Path, bundle_capture: Path, bundle_root: Path,
                  catalog: dict, frozen_plans: dict, evidence_index: dict) -> tuple[dict, dict]:
    design_id = row["intent_id"]
    catalog_row = catalog.get(design_id)
    if not isinstance(catalog_row, dict):
        empty = cell_manifest_row(design_id, row.get("activity", ""), "FROZEN_DESIGN_MISSING")
        return empty, {"design_id": design_id, "arm": row["arm"], "status": "FROZEN_DESIGN_MISSING",
                       "issues": ["intent ID is absent from the frozen revision-2 catalog"]}
    activity = catalog_row["activity"]
    manifest = cell_manifest_row(design_id, activity, "MISSING_INVOCATION")
    audit = {"design_id": design_id, "intent_id": row["intent_id"], "arm": row["arm"],
             "sequence": row["sequence"], "invocation_id": cell_id(row), "issues": [],
             "evidence_files": {}, "raw_exchanges": []}
    plan = None
    planned_plan = frozen_plans.get(design_id)
    if (row.get("activity") != activity or row.get("provider_model") != "multilingual"
            or row.get("max_attempts") not in (1, 3) or row.get("plan_sha256") is None):
        audit["issues"].append("phase-plan row does not match the frozen catalog or route plan")
    if record is None:
        manifest["capture_status"] = "MISSING_INVOCATION"
        return manifest, audit
    audit["record_path"] = f"capture/{record_path}" if record_path else None
    audit["producer_claims"] = {"capture_validation_passed": record.get("capture_validation_passed"),
                                "exit_code": record.get("exit_code"),
                                "status": record.get("status"),
                                "not_started": record.get("not_started")}
    if record.get("schema") != "gooo/ir-composition-tdd-invocation/v2":
        audit["issues"].append("invocation record schema mismatch")
    for key, expected in (("sequence", row["sequence"]), ("intent_id", row["intent_id"]),
                          ("arm", row["arm"])):
        if record.get(key) != expected:
            audit["issues"].append(f"invocation record {key} differs from frozen plan")
    if record.get("not_started") is True or record.get("status") == "not_started_after_prior_failure":
        manifest["capture_status"] = "NOT_STARTED"
        return manifest, audit
    if (record.get("provider_model") != "multilingual" or record.get("max_attempts") != row.get("max_attempts")
            or record.get("activity") != row.get("activity")):
        audit["issues"].append("invocation route or attempt metadata differs from the frozen phase plan")
    if record.get("exit_code") is None:
        manifest["capture_status"] = "INVOCATION_INCOMPLETE"
        audit["issues"].append("invocation record has no completed CLI exit code")
        return manifest, audit
    inv_id = cell_id(row)
    inv_rel = f"invocations/{inv_id}"
    inv_files = {}
    for filename in ("stdout.raw", "stderr.raw", "plan.search.json", "fixture.gooo"):
        relative = f"{inv_rel}/{filename}"
        try:
            _, raw = copy_bytes(run_root, bundle_capture, relative, filename, ("invocations",))
            inv_files[filename] = raw
            evidence_index[f"capture/{relative}"] = {"sha256": digest(raw), "bytes": len(raw)}
        except (OSError, ValueError):
            inv_files[filename] = None
    for filename, field, expected in (("plan.search.json", "plan_sha256", row.get("plan_sha256")),
                                      ("fixture.gooo", "fixture_sha256", row.get("fixture_sha256"))):
        raw = inv_files.get(filename)
        if raw is None or digest(raw) != expected or record.get(field) != expected:
            audit["issues"].append(f"{filename} bytes do not match phase plan and invocation digests")
    if inv_files.get("plan.search.json") is not None:
        try:
            plan = parse_json(inv_files["plan.search.json"], "saved native search plan")
            if not plans_match_revision2(plan, planned_plan, row):
                audit["issues"].append("saved native search plan differs from frozen revision-2 candidates")
        except ValueError as exc:
            audit["issues"].append(str(exc))
    if record.get("capture_validation_passed") is not True:
        audit["producer_capture_claim"] = "false_or_absent; recomputed evidence is authoritative"
    if (type(record.get("raw_provider_post_count")) is not int
            or record.get("raw_provider_post_count") != sum(
                event.get("method") == "POST" and event.get("path") == "/v1/systemone" for event in events)):
        audit["issues"].append("invocation raw POST count differs from proxy event index")
    event_sequences = [event.get("seq") for event in events]
    if record.get("proxy_event_sequences") != event_sequences:
        audit["issues"].append("invocation proxy sequence list differs from raw proxy events")
    if any(event.get("kind") not in ("laya_choice", "health_check") for event in events):
        audit["issues"].append("invocation includes an unexpected proxy event kind")
    if type(row.get("max_attempts")) is not int or row["max_attempts"] not in (1, 3):
        audit["issues"].append("phase-plan maximum attempt count is not in the frozen arm design")
    post_events = sorted((event for event in events if event.get("method") == "POST"
                          and event.get("path") == "/v1/systemone"), key=lambda event: event.get("seq", -1))
    health_events = [event for event in events if event.get("method") == "GET" and event.get("path") == "/health"]
    if any(event.get("invocation_id") != inv_id for event in events):
        audit["issues"].append("proxy event is attributed to a different invocation")
    native_payload = None
    stdout = inv_files.get("stdout.raw")
    if stdout is not None:
        if record.get("stdout_sha256") != digest(stdout):
            audit["issues"].append("native stdout bytes differ from invocation SHA")
        try:
            native_payload = parse_json(stdout, "native CLI stdout")
        except ValueError as exc:
            audit["issues"].append(str(exc))
    stderr = inv_files.get("stderr.raw")
    if stderr is not None and record.get("stderr_sha256") != digest(stderr):
        audit["issues"].append("native stderr bytes differ from invocation SHA")
    native_report = native_payload.get("report", {}) if isinstance(native_payload, dict) else {}
    body = native_report.get("body_search", {}) if isinstance(native_report, dict) else {}
    attempts = body.get("attempts", []) if isinstance(body, dict) else []
    if not isinstance(attempts, list):
        attempts = []
        audit["issues"].append("native body-search attempts are not a list")
    provider_attempts = [attempt for attempt in attempts
                         if isinstance(attempt, dict) and (attempt.get("decision") or {}).get("mode") == "laya"]
    if len(provider_attempts) != len(post_events):
        audit["issues"].append("raw provider POST count differs from native Laya attempt count")
    if len(attempts) > row.get("max_attempts", 0):
        audit["issues"].append("native body-search exceeded the frozen attempt cap")
    route_ok = bool(post_events) and len(provider_attempts) == len(post_events)
    reply_ok = bool(post_events) and len(provider_attempts) == len(post_events)
    if plan is None and isinstance(planned_plan, dict):
        plan = planned_plan
    if isinstance(plan, dict):
        for index, event in enumerate(post_events):
            if event.get("invocation_id") != inv_id:
                route_ok = reply_ok = False
                continue
            attempt = provider_attempts[index] if index < len(provider_attempts) else {}
            ok, problems, info = verify_post_event(event, attempt, run_root, bundle_capture,
                                                   plan, MODEL_REVISION)
            audit["issues"].extend(f"POST {index + 1}: {problem}" for problem in problems)
            audit["raw_exchanges"].append(info)
            for relative, detail in info.get("stored_files", {}).items():
                evidence_index[f"capture/{relative}"] = detail
            route_ok = route_ok and info.get("provider_route_pin_match") is True
            reply_ok = reply_ok and info.get("reply_matches_native_attempt") is True
        for event in health_events:
            ok, problems, info = verify_health_event(event, run_root, bundle_capture)
            audit["issues"].extend(f"health: {problem}" for problem in problems)
            audit["raw_exchanges"].append(info)
            for relative, detail in info.get("stored_files", {}).items():
                evidence_index[f"capture/{relative}"] = detail
        if not health_events:
            audit["issues"].append("no per-invocation raw health exchange was captured")
    else:
        route_ok = reply_ok = False
        audit["issues"].append("frozen candidate plan could not be loaded")
    try:
        if len(post_events) > row.get("max_attempts", 0):
            audit["issues"].append("provider POST count exceeds the frozen cell attempt cap")
    except TypeError:
        audit["issues"].append("frozen maximum-attempt count is malformed")
    native_selected = body.get("selected_candidate_id") if isinstance(body, dict) else None
    native_expression = body.get("selected_expression") if isinstance(body, dict) else None
    declared = {item["id"]: item["expression"] for item in (plan or {}).get("candidates", [])}
    if native_selected not in declared or declared.get(native_selected) != native_expression:
        audit["issues"].append("native selected candidate/expression differs from frozen plan")
    if attempts and not any(attempt.get("candidate_id") == native_selected
                            and attempt.get("expression") == native_expression for attempt in attempts):
        audit["issues"].append("native selected candidate/expression is absent from the native attempt trace")
    source = native_payload.get("source") if isinstance(native_payload, dict) else None
    source_bytes = source.encode("utf-8") if isinstance(source, str) else None
    compiler_digest = native_report.get("generated_digest") if isinstance(native_report, dict) else None
    source_digest_ok = (source_bytes is not None and isinstance(compiler_digest, str)
                        and compiler_digest == "sha256:" + digest(source_bytes))
    if not source_digest_ok:
        audit["issues"].append("native source bytes do not match the generated-source digest")
    if record.get("selected_candidate_id") != native_selected:
        audit["issues"].append("invocation selected-candidate summary differs from native report")
    provider_ops = body.get("provider_operations") if isinstance(body, dict) else None
    if type(provider_ops) is not int or provider_ops != len(post_events):
        audit["issues"].append("native provider operation count differs from raw provider POSTs")
    native_ok = (record.get("exit_code") == 0 and isinstance(native_report, dict)
                 and native_report.get("decision") == "PASS"
                 and native_report.get("typecheck_passed") is True
                 and native_report.get("deterministic_replay") is True)
    if not native_ok:
        audit["issues"].append("native CLI did not report successful typecheck and deterministic replay")
    if record.get("holdout_read_before_capture_complete") is not False:
        audit["issues"].append("invocation does not attest that holdout stayed out of preselection")
    receipt = native_report.get("completeness_receipt") if isinstance(native_report, dict) else None
    unit_complete, unit_reason = source_unit_status(receipt)
    receipt_path = receipt_sha = None
    if isinstance(receipt, dict) and receipt.get("schema") == "gooo/metaprogramming-completeness-receipt/v2":
        receipt_raw = canonical_json(receipt)
        receipt_relative = f"receipts/{safe_name(row['arm'])}/{safe_name(design_id)}.json"
        (bundle_root / receipt_relative).parent.mkdir(parents=True, exist_ok=True)
        (bundle_root / receipt_relative).write_bytes(receipt_raw)
        receipt_path, receipt_sha = receipt_relative, digest(receipt_raw)
        evidence_index[receipt_relative] = {"sha256": receipt_sha, "bytes": len(receipt_raw),
                                            "derived_serialization": "canonical JSON from verified native stdout"}
        if unit_complete is None:
            receipt_path = receipt_sha = None
    audit["source_unit_receipt"] = {"status": unit_complete, "basis": unit_reason}
    row_ok = not audit["issues"] and native_ok and route_ok and reply_ok and source_digest_ok
    if record.get("exit_code") != 0:
        manifest["capture_status"] = "CLI_FAILED"
    elif row_ok:
        source_relative = f"sources/{safe_name(row['arm'])}/{safe_name(design_id)}.go"
        source_target = bundle_root / source_relative
        source_target.parent.mkdir(parents=True, exist_ok=True)
        source_target.write_bytes(source_bytes)
        evidence_index[source_relative] = {"sha256": digest(source_bytes), "bytes": len(source_bytes)}
        manifest = cell_manifest_row(design_id, activity, "CAPTURED_AND_COMPILED",
                                     source_relative, "sha256:" + digest(source_bytes), compiler_digest,
                                     native_selected, native_expression, True, True,
                                     unit_complete, receipt_path, receipt_sha)
    else:
        manifest["capture_status"] = "CAPTURE_EVIDENCE_INVALID"
    audit.update({"status": manifest["capture_status"], "provider_route_pin_match": route_ok,
                  "captured_reply_matches_compiler_choice": reply_ok,
                  "native_report_passed": native_report.get("decision") == "PASS"
                  if isinstance(native_report, dict) else False,
                  "source_digest_verified": source_digest_ok,
                  "native_compile_receipt": {"typecheck_passed": native_report.get("typecheck_passed"),
                                             "deterministic_replay": native_report.get("deterministic_replay")}
                  if isinstance(native_report, dict) else None})
    if audit["issues"]:
        audit["status"] = manifest["capture_status"]
    return manifest, audit


def build_bundle(run_root: Path, bundle_root: Path) -> tuple[dict, dict | None]:
    catalog, frozen_plans = load_frozen_designs()
    report, metadata, phase, all_events, global_issues = verify_frozen_run_files(run_root)
    if not phase:
        audit = {"schema": "gooo/ir-composition-extra-domain-capture-adapter/v1",
                 "adapter_status": "INVALID_CAPTURE_INPUT", "issues": global_issues,
                 "planned_cells": 64, "arms": []}
        return audit, None
    rows = phase["plans"]
    id_set = {row.get("intent_id") for row in rows if isinstance(row, dict)}
    if id_set != set(catalog):
        global_issues.append("TDD phase-plan intent IDs differ from frozen revision-2 catalog")
    rows_by_key = {}
    for row in rows:
        key = (row.get("sequence"), row.get("intent_id"), row.get("arm"))
        rows_by_key[key] = row
    invocation_map, index, invocation_issues = load_invocations(run_root, rows, bundle_root / "capture")
    global_issues.extend(invocation_issues)
    report_status = report.get("status")
    if report_status not in ("CAPTURED", "PARTIAL_CAPTURE"):
        global_issues.append("TDD capture report has an unknown lifecycle status")
    if report.get("scheduled_cells") != 64 or report.get("same_revision2_intents") != 32:
        global_issues.append("TDD report does not preserve the frozen 64-cell, 32-intent denominator")
    if report.get("new_intentions") != 0 or report.get("warmup_calls") != 0:
        global_issues.append("TDD report changed the zero-new-intent or zero-warmup design")
    if (report.get("measured_provider_post_cap") != 96
            or report.get("original_plan_failures_remain_in_denominator") is not True):
        global_issues.append("TDD report omits the fixed provider cap or original denominator policy")
    execution_records = sum(1 for key in rows_by_key if key in invocation_map
                            and invocation_map[key][0].get("exit_code") is not None
                            and invocation_map[key][0].get("not_started") is not True)
    if report.get("completed_cli_cells") != execution_records:
        global_issues.append("TDD report completed_cli_cells differs from independent invocation records")
    raw_posts = sum(event.get("kind") == "laya_choice" for event in all_events if isinstance(event, dict))
    if report.get("raw_provider_posts") != raw_posts or raw_posts > 96:
        global_issues.append("TDD report provider POST count differs from raw event index or exceeds cap")
    if metadata.get("status") != report_status:
        global_issues.append("run metadata and capture report lifecycle status differ")
    if (metadata.get("completed_cells") != execution_records
            or metadata.get("actual_provider_posts") != raw_posts):
        global_issues.append("run metadata cell or provider POST counts differ from independent artifacts")
    if report_status == "CAPTURED":
        if report.get("stop_reason") is not None:
            global_issues.append("CAPTURED report carries a stop reason")
        drains = report.get("provider_forward_drain", {})
        if (drains.get("pre_shutdown", {}).get("settled") is not True
                or drains.get("post_shutdown", {}).get("settled") is not True
                or report.get("owned_service_shutdown", {}).get("confirmed") is not True):
            global_issues.append("CAPTURED report lacks settled provider forwards or confirmed service shutdown")
        if execution_records != 64:
            global_issues.append("CAPTURED report does not have 64 completed invocation records")
    events_by_invocation = {}
    event_ids = {cell_id(row) for row in rows}
    for event in all_events:
        if not isinstance(event, dict):
            global_issues.append("proxy event index contains a non-object row")
            continue
        inv_id = event.get("invocation_id")
        if inv_id not in event_ids:
            global_issues.append(f"proxy event is not attributable to a planned cell: {inv_id!r}")
        events_by_invocation.setdefault(inv_id, []).append(event)
    for relative in RUN_FILES:
        try:
            _, raw = copy_bytes(run_root, bundle_root / "capture", relative, relative)
            index[f"capture/{relative}"] = {"sha256": digest(raw), "bytes": len(raw)}
        except (OSError, ValueError) as exc:
            global_issues.append(f"could not preserve {relative}: {exc}")
    for field, rel in (("summary", "summary.json"), ("run_metadata", "run-metadata.json"),
                       ("preexecution", "preexecution.json"), ("study_design", "study-design.json"),
                       ("phase_plans", "phase-plans.json"), ("proxy_events", "proxy/events.json")):
        copied = bundle_root / "capture" / rel
        if copied.is_file():
            index[f"capture/{rel}"] = {"sha256": digest(copied.read_bytes()), "bytes": copied.stat().st_size}
    manifest_arms, audit_arms = [], []
    all_rows_valid = True
    for arm in EXPECTED_ARMS:
        planned_rows = sorted((row for row in rows if row.get("arm") == arm), key=lambda row: row["sequence"])
        manifest_rows, audit_rows = [], []
        for row in planned_rows:
            key = (row["sequence"], row["intent_id"], row["arm"])
            entry = invocation_map.get(key)
            record, record_path = entry if entry else (None, None)
            cell_manifest, cell_audit = validate_cell(row, record, record_path,
                                                       events_by_invocation.get(cell_id(row), []),
                                                       run_root, bundle_root / "capture", bundle_root,
                                                       catalog, frozen_plans, index)
            manifest_rows.append(cell_manifest)
            audit_rows.append(cell_audit)
            all_rows_valid = all_rows_valid and cell_manifest["capture_status"] == "CAPTURED_AND_COMPILED"
        manifest_arms.append({"arm_id": arm, "designs": manifest_rows})
        audit_arms.append({"arm_id": arm, "planned_cells": len(planned_rows), "designs": audit_rows})
    capture_lifecycle_complete = (report_status == "CAPTURED" and not global_issues
                                  and execution_records == 64 and all_rows_valid)
    if capture_lifecycle_complete:
        _, rows, _ = validate_probe_freeze(PROBE_DIR.resolve())
        freeze_raw = (PROBE_DIR / "probe-freeze.json").read_bytes()
        if digest(freeze_raw) != PROBE_FREEZE_SHA256 or len(rows) != 128:
            raise ValueError("the frozen 128 extra-domain probe set changed")
    report_copy = bundle_root / "capture/report.json"
    if report_copy.is_file():
        report_digest = digest(report_copy.read_bytes())
    else:
        report_digest = ""
        global_issues.append("preserved capture report is missing")
        capture_lifecycle_complete = False
    manifest = {
        "schema": SOURCE_SCHEMA,
        "capture_complete": capture_lifecycle_complete,
        "probes_withheld_until_all_candidate_selection_complete": capture_lifecycle_complete,
        "capture_report_path": "capture/report.json",
        "capture_report_sha256": report_digest,
        "study_run_id": metadata.get("run_id"),
        "arms": manifest_arms,
    }
    manifest_file = "source-manifest.json" if capture_lifecycle_complete else "source-manifest.draft.json"
    manifest_raw = canonical_json(manifest)
    if manifest_file == "source-manifest.json":
        (bundle_root / manifest_file).write_bytes(manifest_raw)
    elif report_digest:
        (bundle_root / manifest_file).write_bytes(manifest_raw)
    index[manifest_file] = {"sha256": digest(manifest_raw), "bytes": len(manifest_raw),
                           "replayable": capture_lifecycle_complete}
    adapter_report = {
        "schema": "gooo/ir-composition-extra-domain-capture-adapter/v1",
        "adapter_status": "READY_FOR_POSTSELECTION_REPLAY" if capture_lifecycle_complete
        else ("PARTIAL_OR_INVALID_CAPTURE" if report_digest else "INVALID_CAPTURE_INPUT"),
        "source_manifest_path": manifest_file,
        "source_manifest_sha256": digest(manifest_raw),
        "source_manifest_replayable": capture_lifecycle_complete,
        "tdd_run_id": metadata.get("run_id"),
        "tdd_capture_status": report_status,
        "planned_cells": 64,
        "planned_cells_per_arm": 32,
        "completed_cli_cells_recomputed": execution_records,
        "validated_source_cells": sum(row["capture_status"] == "CAPTURED_AND_COMPILED"
                                       for arm in manifest_arms for row in arm["designs"]),
        "missing_or_invalid_cells": [
            {"arm_id": arm["arm_id"], "design_id": row["design_id"],
             "capture_status": row["capture_status"]}
            for arm in manifest_arms for row in arm["designs"]
            if row["capture_status"] != "CAPTURED_AND_COMPILED"],
        "raw_provider_posts_recomputed": raw_posts,
        "extra_probe_values_exposed": False,
        "probe_freeze_sha256": PROBE_FREEZE_SHA256,
        "probe_rows_sha256": PROBE_ROWS_SHA256,
        "capture_artifacts": index,
        "arms": audit_arms,
        "global_issues": sorted(set(global_issues)),
        "verification_note": "Validation is derived from frozen plan bytes, raw request/reply bytes, native receipts, exact source bytes, and source archive pins; producer booleans are recorded as claims only.",
    }
    (bundle_root / "adapter-report.json").write_bytes(canonical_json(adapter_report))
    return adapter_report, manifest


def copy_initial_capture(run_root: Path, target_root: Path) -> list[str]:
    issues = []
    for relative in RUN_FILES:
        try:
            copy_bytes(run_root, target_root, relative, relative)
        except (OSError, ValueError) as exc:
            issues.append(f"could not preserve {relative}: {exc}")
    return issues


def run_adapter(run_dir: Path, output: Path) -> dict:
    run_root = run_dir.resolve(strict=True)
    if not run_root.is_dir():
        raise ValueError("--run-dir must be an existing TDD v8 run directory")
    captures_root = (PROBE_DIR / "captures").resolve()
    output = output.resolve()
    if not output.is_relative_to(captures_root):
        raise ValueError("--output must be a new directory beneath the extra-domain probe captures/ directory")
    if output.exists():
        raise ValueError("adapter output is append-only; destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".tdd-v8-adapter-", dir=output.parent))
    try:
        copy_issues = copy_initial_capture(run_root, stage / "capture")
        report, _ = build_bundle(run_root, stage)
        if copy_issues:
            report["global_issues"] = sorted(set(report["global_issues"] + copy_issues))
            report["adapter_status"] = "PARTIAL_OR_INVALID_CAPTURE"
            report["source_manifest_replayable"] = False
            report["source_manifest_path"] = "source-manifest.draft.json"
            manifest_path = stage / "source-manifest.json"
            if manifest_path.exists():
                manifest_path.rename(stage / "source-manifest.draft.json")
                manifest = parse_json((stage / "source-manifest.draft.json").read_bytes(),
                                     "source manifest draft")
                manifest["capture_complete"] = False
                manifest["probes_withheld_until_all_candidate_selection_complete"] = False
                draft = canonical_json(manifest)
                (stage / "source-manifest.draft.json").write_bytes(draft)
                report["source_manifest_sha256"] = digest(draft)
        (stage / "adapter-report.json").write_bytes(canonical_json(report))
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return report


def verify_bundle(bundle: Path) -> dict:
    bundle_root = bundle.resolve(strict=True)
    if not bundle_root.is_dir():
        raise ValueError("--verify-bundle must name an existing adapter bundle")
    report_path = bundle_root / "adapter-report.json"
    expected_report, _ = read_json(report_path, "adapter report")
    with tempfile.TemporaryDirectory(prefix="gooo-tdd-v8-bundle-verify-") as temp_name:
        temp_bundle = Path(temp_name) / "bundle"
        shutil.copytree(bundle_root, temp_bundle, symlinks=True)
        derived, manifest = build_bundle(temp_bundle / "capture", temp_bundle)
        manifest_name = derived.get("source_manifest_path")
        manifest_path = bundle_root / manifest_name if manifest_name else None
        if manifest_path is None or not manifest_path.is_file():
            raise ValueError("adapter bundle is missing its declared source manifest or draft")
        existing_manifest = manifest_path.read_bytes()
        if manifest is None or canonical_json(manifest) != existing_manifest:
            raise ValueError("source manifest bytes differ from independently rederived capture evidence")
    if not isinstance(expected_report, dict):
        raise ValueError("adapter report must be an object")
    if canonical_json(expected_report) != canonical_json(derived):
        raise ValueError("adapter report does not match independently rederived capture evidence")
    return {"decision": "VERIFIED" if derived.get("source_manifest_replayable") else "PRESERVED_NON_REPLAYABLE",
            "bundle": str(bundle_root), "tdd_run_id": derived.get("tdd_run_id"),
            "source_manifest_path": derived.get("source_manifest_path"),
            "validated_source_cells": derived.get("validated_source_cells"),
            "planned_cells": derived.get("planned_cells"),
            "global_issues": derived.get("global_issues", [])}


def public_file(root: Path, relative: str) -> bytes:
    _, raw = strict_relative_file(root, relative, "public evidence file")
    if b"/Users/" in raw or b"/private/tmp/" in raw or b"/home/" in raw:
        raise ValueError(f"public evidence contains a private absolute path: {relative}")
    return raw


def verify_public_exchange(root: Path, exchange: dict, plan: dict,
                           attempts_by_request: dict[str, dict]) -> None:
    if not isinstance(exchange, dict) or exchange.get("kind") not in ("laya_choice", "health_check"):
        raise ValueError("public raw exchange has an unknown kind")
    files = exchange.get("stored_files")
    if not isinstance(files, dict) or len(files) != 2:
        raise ValueError("public raw exchange must bind request and response bytes")
    payloads = {}
    for relative, detail in files.items():
        bundle_relative = relative if relative.startswith("capture/") else "capture/" + relative
        raw = public_file(root, bundle_relative)
        if (not isinstance(detail, dict) or detail.get("sha256") != digest(raw)
                or detail.get("bytes") != len(raw)):
            raise ValueError(f"public raw exchange digest mismatch: {relative}")
        payloads[bundle_relative] = raw
    if exchange["kind"] == "health_check":
        return
    request_path = next((path for path in payloads if "/requests/" in path), None)
    response_path = next((path for path in payloads if "/responses/" in path), None)
    if not request_path or not response_path:
        raise ValueError("public Laya exchange lacks request or response bytes")
    outer = parse_json(payloads[request_path], "public raw provider request")
    response = parse_json(payloads[response_path], "public raw provider response")
    if not isinstance(outer, dict) or outer.get("model") != "multilingual":
        raise ValueError("public request provider model differs from frozen route")
    typed_sha = typed_request_sha(outer)
    if typed_sha != exchange.get("typed_request_sha256"):
        raise ValueError("public typed request digest differs from captured raw request")
    state = parse_json(outer["state"]["request"].encode("utf-8"), "public typed request state")
    if set(state) != {"schema", "stage", "activity", "activity_id", "body_ir", "intent",
                      "training_test_count", "remaining_candidates", "prior_attempts"}:
        raise ValueError("public raw request includes fields outside the preselection state schema")
    declared = plan.get("candidates")
    remaining = state.get("remaining_candidates")
    allowed = {row["id"]: row["expression"] for row in declared}
    if (not isinstance(remaining, list) or not remaining
            or any(not isinstance(row, dict) or row.get("id") not in allowed
                   or row.get("expression") != allowed[row.get("id")] for row in remaining)
            or len({row["id"] for row in remaining}) != len(remaining)
            or state.get("intent") != plan.get("intent")
            or state.get("training_test_count") != len(plan.get("test_cases", []))):
        raise ValueError("public raw request differs from frozen intent, candidates, or suite count")
    answer = response.get("answers", {}).get("body_ir_search", {})
    choice = answer.get("choice") if isinstance(answer, dict) else None
    if choice != exchange.get("choice") or choice not in {row["id"] for row in remaining}:
        raise ValueError("public raw response choice differs from adapter evidence or frozen candidates")
    routing = response.get("routing", {})
    if (not isinstance(routing, dict) or routing.get("model") != "multilingual"
            or routing.get("repo") != "convaiinnovations/laya/multilingual"):
        raise ValueError("public raw response route differs from frozen provider route")
    native_attempt = attempts_by_request.get(typed_sha)
    if (native_attempt is None or native_attempt.get("candidate_id") != choice
            or native_attempt.get("expression") != next(row["expression"] for row in declared
                                                           if row["id"] == choice)):
        raise ValueError("public raw choice does not match the native attempt trace")
    decision = native_attempt.get("decision", {})
    if (decision.get("requested_provider_model") != "multilingual"
            or decision.get("model_revision") != MODEL_REVISION
            or decision.get("routing", {}).get("model") != "multilingual"):
        raise ValueError("public native attempt provider route differs from frozen model pin")


def verify_public_bundle(bundle: Path) -> dict:
    root = bundle.resolve(strict=True)
    report_raw = public_file(root, "adapter-report.json")
    report = parse_json(report_raw, "public adapter report")
    if (not isinstance(report, dict)
            or report.get("schema") != "gooo/ir-composition-extra-domain-capture-adapter/v1"
            or report.get("adapter_status") != "READY_FOR_POSTSELECTION_REPLAY"
            or report.get("tdd_capture_status") != "CAPTURED"
            or report.get("planned_cells") != 64
            or report.get("planned_cells_per_arm") != 32
            or report.get("completed_cli_cells_recomputed") != 64
            or report.get("validated_source_cells") != 64
            or report.get("raw_provider_posts_recomputed") != 86
            or report.get("extra_probe_values_exposed") is not False
            or report.get("global_issues") != []):
        raise ValueError("public adapter report does not describe the frozen complete 64-cell capture")
    artifact_index = report.get("capture_artifacts")
    if not isinstance(artifact_index, dict):
        raise ValueError("public adapter report lacks the original artifact hash index")
    fixed_pins = {"capture/study-design.json": TDD_DESIGN_SHA256,
                  "capture/phase-plans.json": TDD_PHASE_PLANS_SHA256}
    for name, expected in ARCHIVE_PINS.items():
        fixed_pins["capture/" + name] = expected
    for relative, expected in fixed_pins.items():
        detail = artifact_index.get(relative, {})
        if not isinstance(detail, dict) or detail.get("sha256") != expected:
            raise ValueError(f"public adapter report does not preserve frozen source pin: {relative}")
    source_manifest_raw = public_file(root, "source-manifest.json")
    if digest(source_manifest_raw) != report.get("source_manifest_sha256"):
        raise ValueError("public source manifest digest differs from adapter report")
    source_manifest = parse_json(source_manifest_raw, "public source manifest")
    if not isinstance(source_manifest, dict):
        raise ValueError("public source manifest must be an object")
    capture_report = public_file(root, "capture/report.json")
    if digest(capture_report) != source_manifest.get("capture_report_sha256"):
        raise ValueError("public TDD report digest differs from source manifest")
    report_index = artifact_index.get("capture/report.json", {})
    if isinstance(report_index, dict) and report_index.get("sha256") != digest(capture_report):
        raise ValueError("public TDD report differs from adapter artifact index")
    tdd_report = parse_json(capture_report, "public TDD capture report")
    if (not isinstance(tdd_report, dict) or tdd_report.get("status") != "CAPTURED"
            or tdd_report.get("scheduled_cells") != 64
            or tdd_report.get("completed_cli_cells") != 64
            or tdd_report.get("same_revision2_intents") != 32
            or tdd_report.get("new_intentions") != 0
            or tdd_report.get("warmup_calls") != 0
            or tdd_report.get("raw_provider_posts") != 86
            or tdd_report.get("original_plan_failures_remain_in_denominator") is not True
            or tdd_report.get("provider_forward_drain", {}).get("pre_shutdown", {}).get("settled") is not True
            or tdd_report.get("provider_forward_drain", {}).get("post_shutdown", {}).get("settled") is not True
            or tdd_report.get("owned_service_shutdown", {}).get("confirmed") is not True):
        raise ValueError("public TDD report does not preserve complete capture and denominator controls")
    redaction_raw = public_file(root, "public-derivation.json")
    redaction = parse_json(redaction_raw, "public bundle derivation")
    if (not isinstance(redaction, dict)
            or redaction.get("schema") != "gooo/tdd-v8-public-evidence-derivative/v1"
            or redaction.get("source_adapter_report_sha256") != digest(report_raw)
            or redaction.get("source_manifest_sha256") != digest(source_manifest_raw)
            or redaction.get("source_run_id") != report.get("tdd_run_id")):
        raise ValueError("public derivative does not bind the frozen adapter report and source manifest")
    inventory = redaction.get("files")
    if not isinstance(inventory, dict):
        raise ValueError("public derivative lacks a closed file inventory")
    actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
                    and path.name != "public-derivation.json"}
    if actual_files != set(inventory):
        raise ValueError("public bundle files differ from the closed derivation inventory")
    for relative, expected in inventory.items():
        raw = public_file(root, relative)
        if expected != {"sha256": digest(raw), "bytes": len(raw)}:
            raise ValueError(f"public bundle inventory mismatch: {relative}")
    catalog, plans = load_frozen_designs()
    validated, _, _ = validate_source_manifest(root / "source-manifest.json", root, catalog, plans)
    manifest_cells = {(arm["arm_id"], cell["design_id"]): cell
                      for arm in validated["arms"] for cell in arm["designs"]}
    if len(manifest_cells) != 64:
        raise ValueError("public source manifest does not retain all 64 planned design rows")
    exchange_count = 0
    phase = parse_json(public_file(root, "capture/phase-plans.json"), "public phase plans")
    if (not isinstance(phase, dict) or phase.get("planned_cells") != 64
            or len(phase.get("plans", [])) != 64
            or len({row.get("sequence") for row in phase["plans"]}) != 64
            or digest(public_file(root, "capture/phase-plans.json")) != TDD_PHASE_PLANS_SHA256):
        raise ValueError("public phase plans differ from the frozen 64-cell artifact")
    for arm in report.get("arms", []):
        arm_id = arm.get("arm_id") if isinstance(arm, dict) else None
        designs = arm.get("designs") if isinstance(arm, dict) else None
        if not isinstance(arm_id, str) or not isinstance(designs, list) or len(designs) != 32:
            raise ValueError("public adapter report must contain 32 rows per frozen arm")
        for audit in designs:
            design_id = audit.get("design_id")
            cell = manifest_cells.get((arm_id, design_id))
            if (cell is None or audit.get("arm") != arm_id or audit.get("status") != "CAPTURED_AND_COMPILED"
                    or audit.get("issues") != [] or audit.get("provider_route_pin_match") is not True
                    or audit.get("captured_reply_matches_compiler_choice") is not True
                    or audit.get("native_report_passed") is not True
                    or audit.get("source_digest_verified") is not True
                    or audit.get("native_compile_receipt") != {"typecheck_passed": True,
                                                                  "deterministic_replay": True}):
                raise ValueError(f"public adapter evidence is incomplete for {arm_id}/{design_id}")
            invocation = audit.get("invocation_id")
            if not isinstance(invocation, str) or not re.fullmatch(r"\d{2}-[A-Za-z0-9_-]+", invocation):
                raise ValueError("public invocation ID is malformed")
            plan_raw = public_file(root, f"capture/invocations/{invocation}/plan.search.json")
            fixture_raw = public_file(root, f"capture/invocations/{invocation}/fixture.gooo")
            stdout_raw = public_file(root, f"capture/invocations/{invocation}/stdout.raw")
            stderr_raw = public_file(root, f"capture/invocations/{invocation}/stderr.raw")
            for relative, raw in ((f"capture/invocations/{invocation}/plan.search.json", plan_raw),
                                  (f"capture/invocations/{invocation}/fixture.gooo", fixture_raw),
                                  (f"capture/invocations/{invocation}/stdout.raw", stdout_raw),
                                  (f"capture/invocations/{invocation}/stderr.raw", stderr_raw)):
                detail = artifact_index.get(relative.removeprefix("capture/"),
                                            artifact_index.get(relative))
                if isinstance(detail, dict) and (detail.get("sha256") != digest(raw)
                                                  or detail.get("bytes") != len(raw)):
                    raise ValueError(f"public invocation artifact differs from original adapter index: {relative}")
            plan_doc = parse_json(plan_raw, "public saved native search plan")
            phase_row = next((row for row in phase["plans"]
                              if row.get("sequence") == audit.get("sequence")
                              and row.get("arm") == arm_id), None)
            if (phase_row is None or phase_row.get("intent_id") != design_id
                    or phase_row.get("activity") != catalog[design_id].get("activity")
                    or phase_row.get("plan_sha256") != digest(plan_raw)
                    or phase_row.get("fixture_sha256") != digest(fixture_raw)
                    or not plans_match_revision2(plan_doc, plans[design_id], phase_row)):
                raise ValueError(f"public saved plan differs from frozen plan for {arm_id}/{design_id}")
            frozen_fixture = (PROBE_DIR.parent / "revision-2" / catalog[design_id]["fixture"]).read_bytes()
            if fixture_raw != frozen_fixture:
                raise ValueError(f"public fixture differs from frozen revision-2 fixture for {design_id}")
            native = parse_json(stdout_raw, "public native Gooo output")
            native_report = native.get("report", {}) if isinstance(native, dict) else {}
            body = native_report.get("body_search", {}) if isinstance(native_report, dict) else {}
            source_raw = native.get("source", "").encode("utf-8") if isinstance(native, dict) else b""
            source_path = cell.get("source_path")
            saved_source = public_file(root, source_path)
            if (native_report.get("decision") != "PASS"
                    or native_report.get("compiler_source_sha") != COMPILER_REVISION
                    or native_report.get("typecheck_passed") is not True
                    or native_report.get("deterministic_replay") is not True
                    or native_report.get("generated_digest") != "sha256:" + digest(source_raw)
                    or source_raw != saved_source
                    or body.get("prompt_profile") != "compact"
                    or body.get("training_total") != len(plans[design_id].get("test_cases", []))
                    or body.get("selected_candidate_id") != cell.get("selected_candidate_id")
                    or body.get("selected_expression") != cell.get("selected_expression")):
                raise ValueError(f"native output does not bind selected expression and source for {design_id}")
            receipt = native_report.get("completeness_receipt")
            receipt_raw = canonical_json(receipt)
            unit_complete, _ = source_unit_status(receipt)
            if (cell.get("source_unit_receipt_sha256") != digest(receipt_raw)
                    or cell.get("source_unit_receipt_path") is None
                    or cell.get("source_unit_complete") is not unit_complete
                    or public_file(root, cell["source_unit_receipt_path"]) != receipt_raw):
                raise ValueError(f"public native completeness receipt does not match {design_id}")
            native_attempts = body.get("attempts", [])
            attempts_by_request = {}
            for attempt in native_attempts:
                decision = attempt.get("decision", {}) if isinstance(attempt, dict) else {}
                request_hash = decision.get("request_sha256")
                if isinstance(request_hash, str) and request_hash:
                    attempts_by_request[request_hash] = attempt
            exchanges = audit.get("raw_exchanges")
            if not isinstance(exchanges, list) or not exchanges:
                raise ValueError(f"public raw exchanges are missing for {arm_id}/{design_id}")
            if not any(item.get("kind") == "health_check" for item in exchanges if isinstance(item, dict)):
                raise ValueError(f"public health exchange is missing for {arm_id}/{design_id}")
            for exchange in exchanges:
                verify_public_exchange(root, exchange, plans[design_id], attempts_by_request)
                exchange_count += exchange.get("kind") == "laya_choice"
    if exchange_count != 86:
        raise ValueError(f"public provider POST count mismatch: expected 86, got {exchange_count}")
    return {"decision": "VERIFIED_PUBLIC_DERIVATIVE", "planned_cells": 64,
            "validated_source_cells": 64, "raw_provider_posts_recomputed": exchange_count,
            "probe_freeze_sha256": PROBE_FREEZE_SHA256, "probe_rows_sha256": PROBE_ROWS_SHA256,
            "prior_full_bundle_validation": "passed_before_export; path-bearing source files omitted"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path, help="completed or partial TDD v8 result directory")
    group.add_argument("--verify-bundle", type=Path, help="rederive a saved adapter bundle without mutation")
    group.add_argument("--verify-public-bundle", type=Path,
                       help="verify a path-redacted public evidence derivative")
    parser.add_argument("--output", type=Path, help="new append-only bundle directory under captures/")
    args = parser.parse_args()
    if args.verify_bundle:
        print(json.dumps(verify_bundle(args.verify_bundle), indent=2, sort_keys=True))
        return
    if args.verify_public_bundle:
        print(json.dumps(verify_public_bundle(args.verify_public_bundle), indent=2, sort_keys=True))
        return
    if args.output is None:
        parser.error("--output is required with --run-dir")
    report = run_adapter(args.run_dir, args.output)
    print(json.dumps({"adapter_status": report["adapter_status"],
                      "bundle": str(args.output.resolve()),
                      "source_manifest_path": report["source_manifest_path"],
                      "source_manifest_replayable": report["source_manifest_replayable"],
                      "planned_cells": report["planned_cells"],
                      "validated_source_cells": report["validated_source_cells"],
                      "global_issues": report["global_issues"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
