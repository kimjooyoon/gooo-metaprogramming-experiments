#!/usr/bin/env python3
"""Compile candidate oracle attempt 2 in an execution-only derived module."""

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
GO_VERSION = "go1.27.0"


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
            function_lines[-1:-1] = [f"\t_ = {name}" for name in unused]
            repairs.extend({"function": function_lines[0].split("(", 1)[0][4:], "local": name} for name in unused)
        output.extend(function_lines)
    return "\n".join(output) + "\n", repairs


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
    destination = execution / "candidate-oracle-attempt-2"
    if destination.exists():
        raise SystemExit("attempt 2 already exists; preserve it and use a new attempt directory")

    version = subprocess.run([str(args.go_bin), "version"], capture_output=True, text=True, check=False)
    if version.returncode != 0 or GO_VERSION not in version.stdout:
        raise SystemExit(f"attempt 2 requires physical Go {GO_VERSION}; got {version.stdout.strip()!r}")
    module = destination / "module"
    for relative in ("go.mod", "oracle.go", "oracle_test.go", "testdata/vectors.json", "cmd/oracle-report/main.go"):
        source = COHORT / "oracle" / relative
        target = module / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    original_candidates = (COHORT / "oracle/candidates.go").read_text(encoding="utf-8")
    derived_candidates, repairs = add_unused_local_uses(original_candidates)
    if not repairs:
        raise SystemExit("attempt 2 expected to repair unused locals without changing candidate semantics")
    (module / "candidates.go").write_text(derived_candidates, encoding="utf-8")

    env = go_environment(args.go_bin)
    test = subprocess.run(
        [str(args.go_bin), "test", "-count=1", "./..."], cwd=module, env=env,
        capture_output=True, text=True, timeout=180, check=False,
    )
    result = {
        "schema": "gooo/ir-composition-candidate-oracle-attempt/v1",
        "attempt": 2,
        "status": "go_test_failed" if test.returncode else "go_test_passed",
        "source_design_freeze_sha256": sha((COHORT / "design-freeze.json").read_bytes()),
        "go_version": version.stdout.strip(),
        "original_candidates_sha256": sha(original_candidates.encode("utf-8")),
        "derived_candidates_sha256": sha(derived_candidates.encode("utf-8")),
        "repair": "append blank identifier uses for declared locals that are unused by a finite candidate branch; candidate expressions and specs unchanged",
        "repairs": repairs,
        "go_test_exit_code": test.returncode,
        "go_test_stdout": test.stdout[-4000:],
        "go_test_stderr": test.stderr[-4000:],
        "model_calls": 0,
    }
    write_result(destination / "result.json", result)
    if test.returncode:
        raise SystemExit("attempt 2 compiled-oracle Go tests failed; see execution/candidate-oracle-attempt-2/result.json")

    report = subprocess.run(
        [str(args.go_bin), "run", "./cmd/oracle-report"], cwd=module, env=env,
        capture_output=True, text=True, timeout=180, check=False,
    )
    result.update({
        "status": "report_failed" if report.returncode else "candidate_outputs_validated",
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
        result["compiled_go_oracle_crosscheck_passed"] = valid
        if valid:
            output = COHORT / "oracle/candidate-execution.json"
            if output.exists():
                raise SystemExit("candidate-execution.json already exists; preserve it and use a new attempt")
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result["candidate_execution_sha256"] = sha(output.read_bytes())
            result["candidate_execution_path"] = output.relative_to(ROOT).as_posix()
        else:
            result["status"] = "candidate_report_validation_failed"
    else:
        result["compiled_go_oracle_crosscheck_passed"] = False
    write_result(destination / "result.json", result)
    if not result.get("compiled_go_oracle_crosscheck_passed"):
        raise SystemExit("attempt 2 candidate report failed; see execution/candidate-oracle-attempt-2/result.json")
    print(json.dumps({
        "attempt": 2,
        "designs": 32,
        "repairs": repairs,
        "model_calls": 0,
        "candidate_execution": result["candidate_execution_path"],
        "candidate_execution_sha256": result["candidate_execution_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
