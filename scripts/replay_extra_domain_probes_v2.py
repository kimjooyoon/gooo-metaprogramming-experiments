#!/usr/bin/env python3
"""Post-selection replay of frozen extra-domain probes against captured Go sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

from prepare_extra_domain_probes import (
    INT64_MAX, INT64_MIN, OUTPUT as PROBE_DIR, REVISION,
    REVISION_FREEZE_SHA256, REVISION_MANIFEST_SHA256, canonical_json, read_json, sha256,
    verify_revision2,
)

GO_BIN_DEFAULT = Path("go")
GO_BINARY_SHA256 = "a19a71df81715c12d9a7e81bab036c12696fec1ddbd4258b48a2131a9080b267"
GO_LINUX_AMD64_DIST_SHA256 = "675c26c449cbb18fc24b74650de1eabbae6e16f64326fd85a283fb3b58280685"
SOURCE_SCHEMA = "gooo/ir-composition-extra-domain-source-manifest/v1"
REFERENCE_MARKER = "EXTRA_DOMAIN_REFERENCE_RESULT:"
CANDIDATE_MARKER = "EXTRA_DOMAIN_CANDIDATE_RESULT:"


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path: Path, value: object) -> bytes:
    raw = canonical_json(value)
    write_bytes(path, raw)
    return raw


def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def check_fields(value: object, required: set[str], allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a JSON object")
    missing = required - value.keys()
    extra = value.keys() - allowed
    if missing or extra:
        raise ValueError(f"{where} fields invalid: missing={sorted(missing)}, unknown={sorted(extra)}")
    return value


def safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    if not safe:
        raise ValueError("empty or unsafe path label")
    return safe[:80]


def digest_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a SHA-256 string")
    match = re.fullmatch(r"(?:sha256:)?([0-9a-f]{64})", value)
    if not match:
        raise ValueError(f"{label} must contain a lowercase SHA-256 digest")
    return match.group(1)


def validate_probe_freeze(probe_dir: Path) -> tuple[dict, list[dict], bytes]:
    freeze_path = probe_dir / "probe-freeze.json"
    rows_path = probe_dir / "probe-rows.json"
    index_path = probe_dir / "freeze-files.json"
    freeze_raw, rows_raw = freeze_path.read_bytes(), rows_path.read_bytes()
    if sha256(freeze_raw) != "7c67f6d8faeccc79ef9a802cf31313d51b72288cfa4ce2d4c2dadfd933ac6061":
        raise ValueError("extra-domain probe freeze digest mismatch")
    freeze, rows_doc, index = read_json(freeze_path), read_json(rows_path), read_json(index_path)
    if (freeze.get("rows_sha256") != sha256(rows_raw)
            or index.get("files", {}).get("probe-freeze.json") != sha256(freeze_raw)
            or index.get("files", {}).get("probe-rows.json") != sha256(rows_raw)):
        raise ValueError("extra-domain probe file index mismatch")
    for name, expected in index.get("files", {}).items():
        path = probe_dir / name
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise ValueError(f"extra-domain probe artifact changed: {name}")
    if freeze.get("revision2_design_freeze_sha256") != REVISION_FREEZE_SHA256:
        raise ValueError("probe freeze binds another revision-2 design freeze")
    if freeze.get("revision2_manifest_sha256") != REVISION_MANIFEST_SHA256:
        raise ValueError("probe freeze binds another revision-2 manifest")
    if rows_doc.get("probe_count") != 128 or len(rows_doc.get("rows", [])) != 128:
        raise ValueError("expected exactly 128 frozen probe rows")
    verify_revision2()
    declared = freeze.get("bound_revision2_files", {})
    for name, expected in declared.items():
        if sha256((REVISION / name).read_bytes()) != expected:
            raise ValueError(f"probe-bound revision-2 source changed: {name}")
    rows = rows_doc["rows"]
    seen = set()
    for row in rows:
        key = (row.get("design_id"), row.get("input"))
        if key in seen or type(key[1]) is not int or not INT64_MIN <= key[1] <= INT64_MAX:
            raise ValueError("duplicate or out-of-range frozen probe input")
        seen.add(key)
    if len({row["design_id"] for row in rows}) != 32:
        raise ValueError("probes do not cover the same 32 revision-2 designs")
    return freeze, rows, rows_raw


def plans_by_design() -> tuple[dict[str, dict], dict[str, dict]]:
    catalog = read_json(REVISION / "catalog.json")["designs"]
    plans = {row["id"]: read_json(REVISION / row["body_fill_plan"]) for row in catalog}
    return {row["id"]: row for row in catalog}, plans


def validate_source_manifest(path: Path, source_root: Path, catalog: dict, plans: dict) -> tuple[dict, bytes, dict]:
    source_root = source_root.resolve()
    raw = path.read_bytes()
    manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs)
    manifest = check_fields(
        manifest,
        {"schema", "capture_complete", "probes_withheld_until_all_candidate_selection_complete",
         "capture_report_path", "capture_report_sha256", "arms"},
        {"schema", "capture_complete", "probes_withheld_until_all_candidate_selection_complete",
         "capture_report_path", "capture_report_sha256", "arms", "study_run_id"},
        "source manifest",
    )
    if manifest.get("schema") != SOURCE_SCHEMA:
        raise ValueError(f"source manifest schema must be {SOURCE_SCHEMA}")
    if manifest.get("capture_complete") is not True:
        raise ValueError("source manifest must attest that provider capture is complete")
    if manifest.get("probes_withheld_until_all_candidate_selection_complete") is not True:
        raise ValueError("source manifest must attest probes were withheld until all choices were captured")
    report_digest = digest_text(manifest.get("capture_report_sha256"), "capture_report_sha256")
    report_path_value = manifest.get("capture_report_path")
    if not isinstance(report_path_value, str) or not report_path_value:
        raise ValueError("capture_report_path is required to bind the source manifest to the completed study report")
    report_relative = Path(report_path_value)
    if report_relative.is_absolute() or ".." in report_relative.parts:
        raise ValueError("capture_report_path must be relative to source_root")
    report_path = (source_root / report_relative).resolve()
    if not report_path.is_relative_to(source_root) or not report_path.is_file():
        raise ValueError("capture report is missing or outside source_root")
    if sha256(report_path.read_bytes()) != report_digest:
        raise ValueError("capture report bytes do not match capture_report_sha256")
    arms = manifest.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("source manifest must have at least one arm")
    ids = set(catalog)
    arm_ids = set()
    for arm in arms:
        arm = check_fields(arm, {"arm_id", "designs"}, {"arm_id", "designs"}, "arm")
        arm_id = arm.get("arm_id")
        if not isinstance(arm_id, str) or not arm_id or arm_id in arm_ids:
            raise ValueError("arm_id values must be nonempty and unique")
        arm_ids.add(arm_id)
        cells = arm.get("designs")
        if not isinstance(cells, list) or len(cells) != 32:
            raise ValueError(f"arm {arm_id} must contain 32 planned design rows, including failures")
        cell_ids = [cell.get("design_id") for cell in cells]
        if set(cell_ids) != ids or len(cell_ids) != len(set(cell_ids)):
            raise ValueError(f"arm {arm_id} must contain each frozen design ID exactly once")
        for cell in cells:
            cell_fields = {
                "design_id", "activity", "capture_status", "source_path", "source_sha256",
                "compiler_generated_digest", "selected_candidate_id", "selected_expression",
                "provider_route_pin_match", "captured_reply_matches_compiler_choice", "source_unit_complete",
                "source_unit_receipt_path", "source_unit_receipt_sha256",
            }
            cell = check_fields(cell, cell_fields, cell_fields, f"{arm_id} design row")
            case_id = cell["design_id"]
            if cell.get("activity") != catalog[case_id].get("activity"):
                raise ValueError(f"{arm_id}/{case_id}: activity differs from frozen catalog")
            if cell.get("source_unit_complete") not in (True, False, None):
                raise ValueError(f"{arm_id}/{case_id}: source_unit_complete must be boolean or null")
            receipt_digest_value = cell.get("source_unit_receipt_sha256")
            receipt_path_value = cell.get("source_unit_receipt_path")
            if cell.get("source_unit_complete") is not None:
                if not isinstance(receipt_path_value, str) or not receipt_path_value:
                    raise ValueError(f"{arm_id}/{case_id}: source-unit status must bind a receipt path")
                receipt_digest = digest_text(receipt_digest_value, "source_unit_receipt_sha256")
                receipt_relative = Path(receipt_path_value)
                if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
                    raise ValueError(f"{arm_id}/{case_id}: receipt path must be relative to source_root")
                receipt_path = (source_root / receipt_relative).resolve()
                if not receipt_path.is_relative_to(source_root) or not receipt_path.is_file():
                    raise ValueError(f"{arm_id}/{case_id}: source-unit receipt is missing or outside source_root")
                if sha256(receipt_path.read_bytes()) != receipt_digest:
                    raise ValueError(f"{arm_id}/{case_id}: source-unit receipt digest mismatch")
            elif receipt_path_value is not None or receipt_digest_value is not None:
                raise ValueError(f"{arm_id}/{case_id}: unknown source-unit completeness must not carry receipt bytes")
            state = cell.get("capture_status")
            if not isinstance(state, str) or not state:
                raise ValueError(f"{arm_id}/{case_id}: capture_status is required")
            if state != "CAPTURED_AND_COMPILED":
                continue
            source_path = cell.get("source_path")
            if not isinstance(source_path, str) or not source_path:
                raise ValueError(f"{arm_id}/{case_id}: captured source path is missing")
            relative = Path(source_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"{arm_id}/{case_id}: source path must be relative to source_root")
            source = (source_root / relative).resolve()
            if not source.is_relative_to(source_root) or not source.is_file():
                raise ValueError(f"{arm_id}/{case_id}: source path is missing or outside source_root")
            expected_digest = digest_text(cell.get("source_sha256"), "source_sha256")
            compiler_digest = digest_text(cell.get("compiler_generated_digest"), "compiler_generated_digest")
            if expected_digest != compiler_digest or sha256(source.read_bytes()) != expected_digest:
                raise ValueError(f"{arm_id}/{case_id}: source bytes do not match compiler digest")
            chosen = cell.get("selected_candidate_id")
            chosen_expression = cell.get("selected_expression")
            declared = {candidate["id"]: candidate["expression"] for candidate in plans[case_id]["candidates"]}
            if chosen not in declared or chosen_expression != declared[chosen]:
                raise ValueError(f"{arm_id}/{case_id}: selected candidate/expression differs from frozen plan")
            if cell.get("provider_route_pin_match") is not True:
                raise ValueError(f"{arm_id}/{case_id}: captured row does not attest provider route pin match")
            if cell.get("captured_reply_matches_compiler_choice") is not True:
                raise ValueError(f"{arm_id}/{case_id}: provider reply and compiler choice do not match")
    return manifest, raw, {"arms": arm_ids, "catalog": catalog, "plans": plans}


def go_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update({"GO111MODULE": "on", "GOTOOLCHAIN": "local", "GOPROXY": "off",
                "GOSUMDB": "off", "GOWORK": "off", "GOENV": "off", "CGO_ENABLED": "1"})
    for key in ("GOFLAGS", "GOROOT", "GOOS", "GOARCH"):
        env.pop(key, None)
    return env


def verify_go(go_bin: Path, output: Path, official_dist_sha256: str | None = None) -> dict:
    go_bin = resolve_go_binary(go_bin)
    if not go_bin.is_file() or not os.access(go_bin, os.X_OK):
        raise ValueError(f"direct Go 1.27 binary is missing or non-executable: {go_bin}")
    binary_sha = sha256(go_bin.read_bytes())
    if official_dist_sha256 is None and binary_sha != GO_BINARY_SHA256:
        raise ValueError("Go binary differs from the pinned Go 1.27.0 toolchain")
    if official_dist_sha256 is not None and official_dist_sha256 != GO_LINUX_AMD64_DIST_SHA256:
        raise ValueError("official Go distribution digest is not the pinned Go 1.27.0 linux-amd64 archive")
    version = subprocess.run([str(go_bin), "version"], capture_output=True, text=True, check=False, timeout=10)
    write_bytes(output / "toolchain-version.stdout.raw", version.stdout.encode())
    write_bytes(output / "toolchain-version.stderr.raw", version.stderr.encode())
    if version.returncode or not re.search(r"\bgo1\.27(?:\.0)?\b", version.stdout):
        raise ValueError(f"required direct Go 1.27 binary; got {version.stdout.strip()!r}")
    receipt = {"binary": go_bin.name, "version": version.stdout.strip(), "sha256": binary_sha,
               "path_disclosure": "omitted from public receipt"}
    if official_dist_sha256 is not None:
        receipt["official_distribution_sha256"] = official_dist_sha256
        receipt["distribution_verification"] = "workflow-verified official Go 1.27.0 linux-amd64 archive"
    return receipt


def resolve_go_binary(go_bin: Path) -> Path:
    candidate = str(go_bin)
    if not go_bin.is_absolute() and len(go_bin.parts) == 1:
        found = shutil.which(candidate)
        if found is None:
            raise ValueError(f"Go executable is not on PATH: {candidate}")
        return Path(found).resolve(strict=True)
    return go_bin.resolve(strict=True)


def literal(value: int) -> str:
    if not INT64_MIN <= value <= INT64_MAX:
        raise ValueError("probe value is outside signed int64")
    return str(value)


def reference_test_source(rows: list[dict]) -> bytes:
    cases = ",\n".join(
        f'{{DesignID:{json.dumps(row["design_id"])}, ProbeID:{json.dumps(row["probe_id"])}, Index:{index}, Input:{literal(row["input"])}}}'
        for index, row in enumerate(rows)
    )
    source = f'''package oracle

import (
    "encoding/json"
    "testing"
)

type extraReferenceCase struct {{ DesignID string; ProbeID string; Index int; Input int64 }}
type extraReferenceResult struct {{ DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Expected int64 `json:"expected"` }}

func TestExtraDomainProbeReference(t *testing.T) {{
    cases := []extraReferenceCase{{{cases}}}
    results := make([]extraReferenceResult, 0, len(cases))
    for _, item := range cases {{
        results = append(results, extraReferenceResult{{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Expected:Reference(item.DesignID, item.Input)}})
    }}
    encoded, err := json.Marshal(results)
    if err != nil {{ t.Fatal(err) }}
    t.Logf("{REFERENCE_MARKER}%s", encoded)
}}

'''
    return source.encode()


def candidate_test_source(rows: list[dict], activity: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", activity):
        raise ValueError("unsafe activity identifier")
    cases = ",\n".join(
        f'{{DesignID:{json.dumps(row["design_id"])}, ProbeID:{json.dumps(row["probe_id"])}, Index:{index}, Input:{literal(row["input"])}}}'
        for index, row in enumerate(rows)
    )
    source = f'''package bodycodegen

import (
    "encoding/json"
    "testing"
)

type extraCandidateCase struct {{ DesignID string; ProbeID string; Index int; Input int64 }}
type extraCandidateResult struct {{ DesignID string `json:"design_id"`; ProbeID string `json:"probe_id"`; Index int `json:"index"`; Input int64 `json:"input"`; Actual int64 `json:"actual"` }}

func TestExtraDomainProbeCandidate(t *testing.T) {{
    cases := []extraCandidateCase{{{cases}}}
    results := make([]extraCandidateResult, 0, len(cases))
    for _, item := range cases {{
        results = append(results, extraCandidateResult{{DesignID:item.DesignID, ProbeID:item.ProbeID, Index:item.Index, Input:item.Input, Actual:{activity}(item.Input)}})
    }}
    encoded, err := json.Marshal(results)
    if err != nil {{ t.Fatal(err) }}
    t.Logf("{CANDIDATE_MARKER}%s", encoded)
}}
'''
    return source.encode()


def go_run(go_bin: Path, cwd: Path, args: list[str], timeout: int, env: dict[str, str]):
    started = time.time_ns()
    try:
        result = subprocess.run([str(go_bin), *args], cwd=cwd, env=env, capture_output=True,
                                timeout=timeout, check=False)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        result = subprocess.CompletedProcess([str(go_bin), *args], 124, exc.stdout or b"", exc.stderr or b"")
        timed_out = True
    finished = time.time_ns()
    return result, started, finished, timed_out


def marker_payload(raw: bytes, marker: str):
    found = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if marker in line:
            payload = line.split(marker, 1)[1].strip()
            found.append(json.loads(payload))
    return found


def run_reference(go_bin: Path, temp: Path, rows: list[dict], run_dir: Path, env: dict[str, str]) -> dict:
    package = temp / "reference"
    package.mkdir()
    go_mod = b"module extra-domain-reference\n\ngo 1.27.0\n"
    oracle_source = (REVISION / "oracle/oracle.go").read_bytes()
    test_source = reference_test_source(rows)
    write_bytes(package / "go.mod", go_mod)
    write_bytes(package / "oracle.go", oracle_source)
    write_bytes(package / "probe_test.go", test_source)
    write_bytes(run_dir / "reference" / "go.mod", go_mod)
    write_bytes(run_dir / "reference" / "oracle.go", oracle_source)
    write_bytes(run_dir / "reference" / "probe_test.go", test_source)
    source_sha = sha256(oracle_source)
    compile, compile_start, compile_finish, compile_timeout = go_run(go_bin, package, ["test", "-count=1", "-run", "^$", "./..."], 120, env)
    write_bytes(run_dir / "reference" / "compile.stdout.raw", compile.stdout)
    write_bytes(run_dir / "reference" / "compile.stderr.raw", compile.stderr)
    if compile.returncode:
        return {"status": "compile_failed", "timed_out": compile_timeout, "exit_code": compile.returncode, "source_sha256": source_sha,
                "compile_started_unix_ns": compile_start, "compile_finished_unix_ns": compile_finish}
    test, test_start, test_finish, test_timeout = go_run(go_bin, package, ["test", "-count=1", "-run", "^TestExtraDomainProbeReference$", "-v", "./..."], 120, env)
    write_bytes(run_dir / "reference" / "test.stdout.raw", test.stdout)
    write_bytes(run_dir / "reference" / "test.stderr.raw", test.stderr)
    payloads = marker_payload(test.stdout, REFERENCE_MARKER)
    if test.returncode or len(payloads) != 1 or not isinstance(payloads[0], list) or len(payloads[0]) != 128:
        return {"status": "execution_failed", "timed_out": test_timeout, "exit_code": test.returncode, "source_sha256": source_sha,
                "test_started_unix_ns": test_start, "test_finished_unix_ns": test_finish}
    refs = {item["probe_id"]: item for item in payloads[0]}
    if len(refs) != 128:
        return {"status": "invalid_reference_observation", "source_sha256": source_sha}
    for row in rows:
        result = refs.get(row["probe_id"])
        if not result or result.get("input") != row["input"] or result.get("design_id") != row["design_id"]:
            return {"status": "invalid_reference_observation", "source_sha256": source_sha}
    write_json(run_dir / "reference" / "expected-results.json", {"rows": payloads[0]})
    return {"status": "compiled_and_executed", "exit_code": test.returncode, "source_sha256": source_sha,
            "probe_count": len(refs), "compile_started_unix_ns": compile_start,
            "compile_finished_unix_ns": compile_finish, "test_started_unix_ns": test_start,
            "test_finished_unix_ns": test_finish, "results": refs}


def capture_binding_ready(cell: dict) -> tuple[bool, str]:
    if cell.get("capture_status") != "CAPTURED_AND_COMPILED":
        return False, "capture_status_not_accepted"
    for key in ("provider_route_pin_match", "captured_reply_matches_compiler_choice"):
        if cell.get(key) is not True:
            return False, key + "_missing_or_false"
    return True, "verified"


def run_candidate(go_bin: Path, temp_root: Path, arm_id: str, cell: dict, rows: list[dict],
                  run_dir: Path, source_root: Path, catalog: dict, env: dict[str, str]) -> dict:
    ready, reason = capture_binding_ready(cell)
    base = {"design_id": cell["design_id"], "selected_candidate_id": cell.get("selected_candidate_id"),
            "source_unit_complete": cell.get("source_unit_complete"),
            "source_unit_receipt_sha256": cell.get("source_unit_receipt_sha256"),
            "planned_probe_count": len(rows)}
    if not ready:
        return {**base, "status": "unknown", "reason": reason, "observed_probe_count": 0}
    source_path = (source_root / cell["source_path"]).resolve()
    source = source_path.read_bytes()
    if sha256(source) != digest_text(cell.get("source_sha256"), "source_sha256"):
        return {**base, "status": "unknown", "reason": "source_digest_changed_after_manifest_validation",
                "observed_probe_count": 0}
    case_dir = temp_root / safe_name(arm_id) / safe_name(cell["design_id"])
    case_dir.mkdir(parents=True)
    go_mod = b"module extra-domain-candidate\n\ngo 1.27.0\n"
    probe_source = candidate_test_source(rows, catalog[cell["design_id"]]["activity"])
    raw_dir = run_dir / "arms" / safe_name(arm_id) / safe_name(cell["design_id"])
    write_bytes(case_dir / "go.mod", go_mod)
    write_bytes(case_dir / "emitted.go", source)
    write_bytes(case_dir / "probe_test.go", probe_source)
    write_bytes(raw_dir / "go.mod", go_mod)
    write_bytes(raw_dir / "emitted.go", source)
    write_bytes(raw_dir / "probe_test.go", probe_source)
    compile, compile_start, compile_finish, compile_timeout = go_run(go_bin, case_dir,
        ["test", "-count=1", "-run", "^$", "./..."], 120, env)
    write_bytes(raw_dir / "compile.stdout.raw", compile.stdout)
    write_bytes(raw_dir / "compile.stderr.raw", compile.stderr)
    if compile.returncode:
        return {**base, "status": "compile_failed", "timed_out": compile_timeout, "observed_probe_count": 0,
                "source_sha256": sha256(source), "compile_exit_code": compile.returncode,
                "compile_started_unix_ns": compile_start, "compile_finished_unix_ns": compile_finish}
    test, test_start, test_finish, test_timeout = go_run(go_bin, case_dir,
        ["test", "-count=1", "-run", "^TestExtraDomainProbeCandidate$", "-v", "./..."], 120, env)
    write_bytes(raw_dir / "test.stdout.raw", test.stdout)
    write_bytes(raw_dir / "test.stderr.raw", test.stderr)
    payloads = marker_payload(test.stdout, CANDIDATE_MARKER)
    if test.returncode or len(payloads) != 1 or not isinstance(payloads[0], list) or len(payloads[0]) != len(rows):
        return {**base, "status": "execution_failed", "timed_out": test_timeout, "observed_probe_count": 0,
                "source_sha256": sha256(source), "test_exit_code": test.returncode,
                "test_started_unix_ns": test_start, "test_finished_unix_ns": test_finish}
    observations = {item.get("probe_id"): item for item in payloads[0]}
    if len(observations) != len(rows):
        return {**base, "status": "invalid_candidate_observation", "observed_probe_count": 0,
                "source_sha256": sha256(source)}
    details = []
    for row in rows:
        actual = observations.get(row["probe_id"])
        if not actual or actual.get("input") != row["input"] or actual.get("design_id") != row["design_id"]:
            return {**base, "status": "invalid_candidate_observation", "observed_probe_count": 0,
                    "source_sha256": sha256(source)}
        details.append({"probe_id": row["probe_id"], "input": row["input"],
                        "expected": None, "actual": actual["actual"]})
    write_json(raw_dir / "actual-results.json", {"rows": details})
    return {**base, "status": "compiled_and_executed", "source_sha256": sha256(source),
            "observed_probe_count": len(details), "compile_exit_code": compile.returncode,
            "test_exit_code": test.returncode, "compile_started_unix_ns": compile_start,
            "compile_finished_unix_ns": compile_finish, "test_started_unix_ns": test_start,
            "test_finished_unix_ns": test_finish, "actuals": {item["probe_id"]: item["actual"] for item in details}}


def copy_source_unit_receipt(run_dir: Path, source_root: Path, arm_id: str, cell: dict) -> None:
    receipt_path = cell.get("source_unit_receipt_path")
    if not receipt_path:
        return
    receipt_bytes = (source_root / receipt_path).resolve().read_bytes()
    expected = digest_text(cell.get("source_unit_receipt_sha256"), "source_unit_receipt_sha256")
    if sha256(receipt_bytes) != expected:
        raise ValueError(f"{arm_id}/{cell['design_id']}: source-unit receipt changed after manifest validation")
    write_bytes(run_dir / "arms" / safe_name(arm_id) / safe_name(cell["design_id"])
                / "source-unit-receipt.json", receipt_bytes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="new, append-only attempt directory under extra-domain-probes-128/execution")
    parser.add_argument("--go-bin", type=Path, default=GO_BIN_DEFAULT)
    parser.add_argument("--official-go-dist-sha256", help="CI-only: verified official go1.27.0 linux-amd64 archive SHA-256")
    parser.add_argument("--after-root-measurement-gate", action="store_true",
                        help="required explicit gate; do not run during Laya measurement")
    args = parser.parse_args()
    if not args.after_root_measurement_gate:
        raise SystemExit("refusing to run Go; pass --after-root-measurement-gate only after root confirms capture is complete")

    probe_dir = PROBE_DIR.resolve()
    freeze, all_rows, _ = validate_probe_freeze(probe_dir)
    catalog, plans = plans_by_design()
    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise ValueError("source-root must be an existing capture directory")
    manifest, source_manifest_raw, _ = validate_source_manifest(args.source_manifest.resolve(), source_root, catalog, plans)
    safe_arm_ids = [safe_name(arm["arm_id"]) for arm in manifest["arms"]]
    if len(safe_arm_ids) != len(set(safe_arm_ids)):
        raise ValueError("arm IDs collide after safe output-path normalization")
    output = args.output.resolve()
    execution_root = (probe_dir / "execution").resolve()
    if not output.is_relative_to(execution_root):
        raise ValueError("output must be a new directory beneath the frozen probe cohort's execution/")
    output.mkdir(parents=True, exist_ok=False)
    write_bytes(output / "source-manifest.json", source_manifest_raw)
    write_json(output / "run-start.json", {
        "schema": "gooo/ir-composition-extra-domain-probe-run-start/v1",
        "probe_freeze_sha256": sha256((probe_dir / "probe-freeze.json").read_bytes()),
        "probe_rows_sha256": sha256((probe_dir / "probe-rows.json").read_bytes()),
        "source_manifest_sha256": sha256(source_manifest_raw),
        "source_capture_report_sha256": manifest["capture_report_sha256"],
        "arms": [arm["arm_id"] for arm in manifest["arms"]],
        "model_calls": 0,
        "postselection_only": True,
    })
    go_bin = resolve_go_binary(args.go_bin)
    go_receipt = verify_go(go_bin, output, args.official_go_dist_sha256)
    env = go_environment()
    with tempfile.TemporaryDirectory(prefix="gooo-extra-domain-replay-") as temp_name:
        temp = Path(temp_name)
        ref = run_reference(go_bin, temp, all_rows, output, env)
        if ref["status"] != "compiled_and_executed":
            write_json(output / "incomplete-run.json", {"decision": "REFERENCE_FAILED", "reference": {k: v for k, v in ref.items() if k != "results"}})
            raise SystemExit("frozen handwritten Go reference did not complete; raw output is preserved")
        reference_results = ref.pop("results")
        results_by_design = {}
        for row in all_rows:
            results_by_design.setdefault(row["design_id"], []).append(row)
        arm_reports = []
        for arm in manifest["arms"]:
            arm_id = arm["arm_id"]
            cells = {cell["design_id"]: cell for cell in arm["designs"]}
            per_design = []
            capture_status_counts: Counter[str] = Counter(cell["capture_status"] for cell in arm["designs"])
            replay_status_counts: Counter[str] = Counter()
            total_planned = total_observed = total_match = total_mismatch = total_unknown = 0
            planned_regions = set()
            observed_regions = set()
            planned_areas: Counter[str] = Counter()
            observed_areas: Counter[str] = Counter()
            output_diversities = []
            source_unit = Counter()
            for case_id in catalog:
                cell = cells[case_id]
                probes = results_by_design[case_id]
                copy_source_unit_receipt(output, source_root, arm_id, cell)
                for probe in probes:
                    planned_regions.add(probe["region_target"])
                    planned_areas[probe["semantic_area"]] += 1
                source_unit[str(cell.get("source_unit_complete", "unknown"))] += 1
                result = run_candidate(go_bin, temp, arm_id, cell, probes, output,
                                       source_root, catalog, env)
                replay_status_counts[result["status"]] += 1
                total_planned += len(probes)
                actuals = result.pop("actuals", {})
                observed_count = result.get("observed_probe_count", 0)
                total_observed += observed_count
                design_rows = []
                for probe in probes:
                    expected = reference_results[probe["probe_id"]]["expected"]
                    actual = actuals.get(probe["probe_id"])
                    if actual is None:
                        total_unknown += 1
                        continue
                    passed = actual == expected
                    total_match += int(passed)
                    total_mismatch += int(not passed)
                    observed_regions.add(probe["region_target"])
                    observed_areas[probe["semantic_area"]] += 1
                    design_rows.append({"probe_id": probe["probe_id"], "input": probe["input"],
                                        "region_target": probe["region_target"], "expected": expected,
                                        "actual": actual, "passed": passed})
                expected_values = {reference_results[probe["probe_id"]]["expected"] for probe in probes}
                output_diversities.append(len(expected_values))
                per_design.append({**result, "planned_probe_count": len(probes),
                                   "observed_probe_count": len(design_rows), "matched": sum(item["passed"] for item in design_rows),
                                   "mismatched": sum(not item["passed"] for item in design_rows),
                                   "unknown": len(probes) - len(design_rows), "rows": design_rows,
                                   "reference_distinct_output_count": len(expected_values)})
            report = {
                "schema": "gooo/ir-composition-extra-domain-probe-arm-result/v1",
                "arm_id": arm_id,
                "planned_designs": 32,
                "planned_probe_rows": total_planned,
                "executed_probe_rows": total_observed,
                "matched_probe_rows": total_match,
                "mismatched_probe_rows": total_mismatch,
                "unknown_probe_rows": total_unknown,
                "finite_match_rate_observed_only": (total_match / total_observed) if total_observed else None,
                "capture_status_counts": dict(capture_status_counts),
                "replay_status_counts": dict(replay_status_counts),
                "source_unit_completeness": {"complete": source_unit["True"], "incomplete": source_unit["False"],
                                             "unknown": source_unit["None"] + source_unit["unknown"]},
                "planned_region_targets": len(planned_regions),
                "observed_region_targets": len(observed_regions),
                "probe_purpose_coverage": len(observed_regions) / len(planned_regions) if planned_regions else None,
                "probe_rows_by_semantic_area": {
                    area: {"observed": observed_areas[area], "planned": planned_areas[area]}
                    for area in sorted(planned_areas)
                },
                "dynamic_branch_coverage": "UNMEASURED",
                "branch_test_adequacy": "UNMEASURED",
                "reference_output_diversity_by_design": {"designs": len(output_diversities),
                                                         "distinct_outputs_min": min(output_diversities),
                                                         "distinct_outputs_max": max(output_diversities)},
                "designs": per_design,
                "coverage_limit": "probe-purpose coverage is static; no dynamic branch instrumentation or branch-test adequacy measurement was collected",
                "scope": "128 new unseen finite int64 inputs across the same 32 intents; passing is not full-domain proof",
            }
            write_json(output / "arms" / f"{safe_name(arm_id)}" / "results.json", report)
            arm_reports.append({key: value for key, value in report.items() if key != "designs"})

    full_report = {
        "schema": "gooo/ir-composition-extra-domain-probe-replay/v1",
        "decision": "COMPLETE",
        "probe_freeze_sha256": sha256((probe_dir / "probe-freeze.json").read_bytes()),
        "probe_rows_sha256": sha256((probe_dir / "probe-rows.json").read_bytes()),
        "source_manifest_sha256": sha256(source_manifest_raw),
        "source_capture_report_sha256": manifest["capture_report_sha256"],
        "go_toolchain": go_receipt,
        "model_calls": 0,
        "candidate_selection_calls": 0,
        "probe_inputs_in_prompts": False,
        "reference": {key: value for key, value in ref.items() if key != "results"},
        "arm_summaries": arm_reports,
        "oracle_limitation": freeze["reference"]["limitation"],
        "scope": "Each arm's captured emitted source is independently compiled and run against 128 post-selection probe inputs, compared with the separately compiled frozen handwritten Go reference.",
    }
    report_raw = write_json(output / "replay-report.json", full_report)
    (output / "replay-report.md").write_text(render_report(full_report), encoding="utf-8")
    write_json(output / "artifact-index.json", {
        "schema": "gooo/ir-composition-extra-domain-probe-run-index/v1",
        "files": {str(path.relative_to(output)): sha256(path.read_bytes())
                  for path in sorted(output.rglob("*")) if path.is_file() and path.name != "artifact-index.json"},
        "replay_report_sha256": sha256(report_raw),
    })
    print(json.dumps({"decision": "COMPLETE", "output": str(output),
                      "arms": len(arm_reports), "probe_rows_per_arm": 128,
                      "model_calls": 0, "replay_report_sha256": sha256(report_raw)}))


def render_report(report: dict) -> str:
    lines = [
        "# Extra-domain probe replay", "",
        "The frozen 128 probes were evaluated only after capture and candidate choice. They cover four new inputs for each of the same 32 revision-2 designs.", "",
        "| Arm | Executed / planned | Matched | Mismatched | Unknown | Region targets observed / planned | Source units complete / incomplete / unknown |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in report["arm_summaries"]:
        source_units = arm["source_unit_completeness"]
        lines.append(
            f"| {arm['arm_id']} | {arm['executed_probe_rows']}/{arm['planned_probe_rows']} | "
            f"{arm['matched_probe_rows']} | {arm['mismatched_probe_rows']} | {arm['unknown_probe_rows']} | "
            f"{arm['observed_region_targets']}/{arm['planned_region_targets']} | "
            f"{source_units['complete']}/{source_units['incomplete']}/{source_units['unknown']} |"
        )
    lines.extend([
        "", "These scores describe only the 128 frozen values. Probe-purpose coverage uses static region tags. Dynamic branch coverage and branch-test adequacy are unmeasured.",
        "The expected outputs come from the revision-2 handwritten Go reference, which shares source lineage with the prior finite oracle. Agreement is a correlated-oracle diagnostic, not independent ground truth.",
        "Passing these new values does not prove full-domain correctness. Missing captures, invalid route/choice bindings, compile failures, and incomplete executions remain unknown rows.", "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
