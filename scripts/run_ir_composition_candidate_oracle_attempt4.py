#!/usr/bin/env python3
"""Separate original candidate validity from counterfactual attempt-3 outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "cohorts/ir-composition-curriculum-2026-09-30"
GO_VERSION = "go1.27.1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_design_freeze() -> dict:
    manifest = json.loads((COHORT / "design-freeze.json").read_text(encoding="utf-8"))
    changed = []
    for relative, expected in manifest["files"].items():
        path = ROOT / relative
        if not path.is_file() or sha(path.read_bytes()) != expected:
            changed.append(relative)
    if changed:
        raise SystemExit("design freeze changed: " + ", ".join(changed[:8]))
    return manifest


def add_unused_local_uses(source: str) -> tuple[str, list[dict[str, str]]]:
    lines = source.splitlines()
    output = []
    repairs = []
    index = 0
    while index < len(lines):
        if not re.match(r"^func candidate\d+[abc]\(input int64\) int64 \{$", lines[index]):
            output.append(lines[index])
            index += 1
            continue
        function_lines = [lines[index]]
        depth = lines[index].count("{") - lines[index].count("}")
        index += 1
        while index < len(lines) and depth > 0:
            function_lines.append(lines[index])
            depth += lines[index].count("{") - lines[index].count("}")
            index += 1
        if depth != 0:
            raise ValueError("unbalanced candidate function while preparing derived oracle")
        body = "\n".join(function_lines)
        declared = re.findall(r"\bvar\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", body)
        unused = [name for name in declared if len(re.findall(rf"\b{re.escape(name)}\b", body)) == 1]
        if unused:
            inserted = []
            for line in function_lines:
                inserted.append(line)
                for name in unused:
                    if re.search(rf"\bvar\s+{re.escape(name)}\s*=", line):
                        inserted.append(f"\t_ = {name}")
                        repairs.append({"function": function_lines[0].split("(", 1)[0][5:], "local": name})
            function_lines = inserted
        output.extend(function_lines)
    return "\n".join(output) + "\n", repairs


def candidate_function_blocks(source: str) -> dict[str, str]:
    lines = source.splitlines()
    blocks = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^func (candidate\d+[abc])\(input int64\) int64 \{$", lines[index])
        if not match:
            index += 1
            continue
        function_lines = [lines[index]]
        depth = lines[index].count("{") - lines[index].count("}")
        index += 1
        while index < len(lines) and depth > 0:
            function_lines.append(lines[index])
            depth += lines[index].count("{") - lines[index].count("}")
            index += 1
        if depth != 0:
            raise ValueError("unbalanced candidate function in frozen Go source")
        blocks[match.group(1)] = "\n".join(function_lines)
    return blocks


def compile_original_candidates(module: Path, go_bin: Path, original: str, attempt_dir: Path) -> dict:
    package_root = module.parent / "original-candidate-validity"
    if package_root.exists():
        raise SystemExit("original candidate validity attempt already exists")
    package_root.mkdir(parents=True)
    (package_root / "go.mod").write_text(
        "module example.invalid/gooo/ir-composition-original-candidate-validity\n\ngo 1.27.1\n",
        encoding="utf-8",
    )
    catalog = json.loads((COHORT / "catalog.json").read_text(encoding="utf-8"))
    functions = candidate_function_blocks(original)
    by_function = {}
    for index, design in enumerate(catalog["designs"], start=1):
        options = json.loads((COHORT / design["body_fill_plan"]).read_text(encoding="utf-8"))["candidates"]
        for option in options:
            function = f"candidate{index:02d}{option['id'][-1]}"
            by_function[function] = {"case_id": design["id"], "candidate_id": option["id"]}
            package = f"case{index:02d}_{design['id']}_{option['id']}"
            target = package_root / package
            target.mkdir()
            (target / "candidate.go").write_text(
                "package candidatevalidity\n\n" + functions[function] + "\n", encoding="utf-8",
            )
            (target / "candidate_test.go").write_text(
                'package candidatevalidity\nimport "testing"\n'
                f'func TestCandidateCompiles(t *testing.T) {{ _ = {function}(0) }}\n',
                encoding="utf-8",
            )
    env = go_environment(go_bin)
    result = subprocess.run(
        [str(go_bin), "test", "-json", "-count=1", "./..."], cwd=package_root,
        env=env, capture_output=True, text=True, timeout=180, check=False,
    )
    module_path = "example.invalid/gooo/ir-composition-original-candidate-validity/"
    statuses = {}
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        package = event.get("Package", "")
        if package.startswith(module_path) and event.get("Action") in {"pass", "fail"} and "Test" not in event:
            statuses[package.rsplit("/", 1)[-1]] = "valid" if event["Action"] == "pass" else "compile_or_test_failed"
    rows = []
    for package, status in statuses.items():
        identity = next((value for value in by_function.values() if f"_{value['case_id']}_" in package), None)
        option = package.rsplit("_", 1)[-1]
        if identity:
            rows.append({"case_id": identity["case_id"], "candidate_id": f"option_{option}", "original_source_status": status})
    expected = {(value["case_id"], value["candidate_id"]) for value in by_function.values()}
    seen = {(row["case_id"], row["candidate_id"]) for row in rows}
    if expected != seen:
        raise SystemExit(f"candidate validity report incomplete: {len(seen)}/96 packages reported")
    rows.sort(key=lambda row: (row["case_id"], row["candidate_id"]))
    counts = {status: sum(row["original_source_status"] == status for row in rows) for status in ("valid", "compile_or_test_failed")}
    report = {
        "schema": "gooo/ir-composition-original-candidate-validity/v1",
        "scope": "original frozen candidate Go bodies compiled one by one without repair",
        "candidate_count": len(rows),
        "valid_count": counts["valid"],
        "compile_or_test_failed_count": counts["compile_or_test_failed"],
        "unknown_count": 96 - len(rows),
        "go_test_exit_code": result.returncode,
        "go_test_stderr": result.stderr[-4000:],
        "rows": rows,
    }
    target = attempt_dir / "original-candidate-validity.json"
    write_result(target, report)
    return report


def go_environment(go_bin: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off", "GOWORK": "off"})
    env.pop("GOOO_LAYA_URL", None)
    env.pop("GOOO_LAYA_API_KEY", None)
    env["PATH"] = str(go_bin.parent) + os.pathsep + env.get("PATH", "")
    return env


def write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--go-bin", type=Path, required=True)
    args = parser.parse_args()
    design_freeze = verify_design_freeze()
    execution = COHORT / "execution"
    attempt1 = execution / "candidate-oracle-attempt-1.json"
    if not attempt1.is_file():
        raise SystemExit("record the failed original candidate compile as attempt 1 before retrying")
    attempt2_runner = execution / "candidate-oracle-attempt-2/runner-attempt-2.py"
    if not attempt2_runner.is_file():
        raise SystemExit("attempt 2 source was not preserved")
    destination = execution / "candidate-oracle-attempt-4"
    if destination.exists():
        raise SystemExit("attempt 4 already exists; preserve it and use a new attempt directory")

    version = subprocess.run([str(args.go_bin), "version"], capture_output=True, text=True, check=False)
    if version.returncode != 0 or GO_VERSION not in version.stdout:
        raise SystemExit(f"attempt 4 requires physical Go {GO_VERSION}; got {version.stdout.strip()!r}")
    original_candidates = (COHORT / "oracle/candidates.go").read_text(encoding="utf-8")
    validity = compile_original_candidates(destination / "unused", args.go_bin, original_candidates, destination)
    if validity["candidate_count"] != 96:
        raise SystemExit("original candidate validity must preserve a 96-candidate denominator")
    module = destination / "module"
    for relative in ("go.mod", "oracle.go", "oracle_test.go", "testdata/vectors.json", "cmd/oracle-report/main.go"):
        source = COHORT / "oracle" / relative
        target = module / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    derived_candidates, repairs = add_unused_local_uses(original_candidates)
    if not repairs:
        raise SystemExit("attempt 4 expected to identify unused locals without changing candidate semantics")
    derived_candidates = re.sub(
        r"\bfunc candidate(\d+[abc])", r"func Candidate\1", derived_candidates,
    )
    (module / "candidates.go").write_text(derived_candidates, encoding="utf-8")
    report_source_path = module / "cmd/oracle-report/main.go"
    derived_report = report_source_path.read_text(encoding="utf-8")
    derived_report = re.sub(r"\bcandidate(\d+[abc])", r"oracle.Candidate\1", derived_report)
    derived_report = derived_report.replace(
        "gold := optionIDs[index%3]", "gold := optionIDs[(3-(index%3))%3]",
    )
    report_source_path.write_text(derived_report, encoding="utf-8")

    env = go_environment(args.go_bin)
    test = subprocess.run(
        [str(args.go_bin), "test", "-count=1", "./..."], cwd=module, env=env,
        capture_output=True, text=True, timeout=180, check=False,
    )
    result = {
        "schema": "gooo/ir-composition-candidate-oracle-attempt/v1",
        "attempt": 4,
        "status": "counterfactual_go_test_failed" if test.returncode else "counterfactual_go_test_passed",
        "original_candidate_validity": {
            "candidate_count": validity["candidate_count"],
            "valid_count": validity["valid_count"],
            "compile_or_test_failed_count": validity["compile_or_test_failed_count"],
            "validity_artifact": "original-candidate-validity.json",
        },
        "source_design_freeze_sha256": sha((COHORT / "design-freeze.json").read_bytes()),
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "go_version": version.stdout.strip(),
        "original_candidates_sha256": sha(original_candidates.encode("utf-8")),
        "derived_candidates_sha256": sha(derived_candidates.encode("utf-8")),
        "derived_reporter_sha256": sha(derived_report.encode("utf-8")),
        "repair": "counterfactual diagnostic only: mark original unused locals, export candidate functions for the separate reporter package, and correct reporter gold indexing; none of these changes are treated as original source validity",
        "counterfactual_outputs_accepted_as_actual": False,
        "counterfactual_outputs_usable_for_external_feedback": False,
        "repairs": repairs,
        "go_test_exit_code": test.returncode,
        "go_test_stdout": test.stdout[-4000:],
        "go_test_stderr": test.stderr[-4000:],
        "model_calls": 0,
    }
    write_result(destination / "result.json", result)
    if test.returncode:
        write_result(destination / "result.json", result)
        raise SystemExit("attempt 4 counterfactual Go tests failed; see execution/candidate-oracle-attempt-4/result.json")

    report = subprocess.run(
        [str(args.go_bin), "run", "./cmd/oracle-report"], cwd=module, env=env,
        capture_output=True, text=True, timeout=180, check=False,
    )
    result.update({
        "status": "counterfactual_report_failed" if report.returncode else "counterfactual_candidate_outputs_validated",
        "go_report_exit_code": report.returncode,
        "go_report_stderr": report.stderr[-4000:],
    })
    if report.returncode == 0:
        payload = json.loads(report.stdout)
        valid = payload.get("model_calls") == 0 and len(payload.get("designs", [])) == 32
        valid = valid and all(
            len(row.get("training", [])) > 0
            and all(case.get("passed") for case in row["training"] + row["evaluation"])
            and set(row.get("candidate_outputs_by_training_input", {})) == {"option_a", "option_b", "option_c"}
            and set(row.get("candidate_outputs_by_evaluation_input", {})) == {"option_a", "option_b", "option_c"}
            for row in payload["designs"]
        )
        valid = valid and all(repairs)
        result["counterfactual_go_oracle_crosscheck_passed"] = valid
        if valid:
            output = destination / "counterfactual-candidate-outputs.json"
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result["counterfactual_outputs_sha256"] = sha(output.read_bytes())
            result["counterfactual_outputs_path"] = output.relative_to(ROOT).as_posix()
        else:
            result["status"] = "counterfactual_report_validation_failed"
    else:
        result["counterfactual_go_oracle_crosscheck_passed"] = False
    write_result(destination / "result.json", result)
    if not result.get("counterfactual_go_oracle_crosscheck_passed"):
        raise SystemExit("attempt 4 candidate report failed; see execution/candidate-oracle-attempt-4/result.json")
    print(json.dumps({
        "attempt": 4,
        "designs": 32,
        "repairs": repairs,
        "original_candidate_validity": {
            "candidate_count": validity["candidate_count"],
            "valid_count": validity["valid_count"],
            "compile_or_test_failed_count": validity["compile_or_test_failed_count"],
        },
        "model_calls": 0,
        "counterfactual_outputs_accepted_as_actual": False,
        "counterfactual_outputs": result["counterfactual_outputs_path"],
        "counterfactual_outputs_sha256": result["counterfactual_outputs_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
