#!/usr/bin/env python3
"""Compile and run the four captured Go bodies against the copied finite oracle; never calls Gooo or Laya."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parents[1]
RUN_REL = Path("runs/primary_run")
CONDITIONS = ("sequential", "simultaneous")
INTENTS = ("clamp", "absolute")
EXPECTED_BINARY_SHA = "f9f33b86c2114c1adeba01319fddb7d48f666e739aef768bbb5a580adfb7cda9"
EXPECTED_SOURCE_REVISION = "29d44bc778d85aee03b9af500bd83dc98f368189"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def load_primary_validator():
    path = ROOT / "scripts" / "validate_ir_search_cohort.py"
    spec = importlib.util.spec_from_file_location("primary_ir_search_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reusable independent Go oracle helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_capture(run_dir: Path, env: dict):
    script = HERE / "scripts" / "validate_run.py"
    proc = subprocess.run([sys.executable, str(script), "--run-dir", str(run_dir)],
                          cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=60)
    require(proc.returncode == 0,
            f"saved raw capture validation failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=HERE / RUN_REL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-go-version", help="require this exact Go version token, e.g. go1.27.0")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output_dir = (args.output or run_dir / "emitted-go-validation").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    go_env = os.environ.copy()
    go_env.update({
        "GO111MODULE": "off",
        "GOTOOLCHAIN": "local",
        "GOWORK": "off",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOOO_LAYA_URL": "",
        "GOOO_LAYA_API_KEY": "",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    go = load_primary_validator()
    version = go.run(["go", "version"], cwd=ROOT, env=go_env).stdout.strip()
    require(args.require_go_version is None or args.require_go_version in version,
            f"Go compiler version must contain {args.require_go_version!r}, got {version!r}")

    capture_check = validate_capture(run_dir, go_env)
    run_meta = read_json(run_dir / "run-metadata.json")
    manifest = read_json(run_dir / "input-manifest.json")
    require(run_meta["source_revision"] == EXPECTED_SOURCE_REVISION == manifest["binary"]["source_revision"],
            "captured compiler source revision does not match the pinned binary")
    require(run_meta["binary_sha256"] == EXPECTED_BINARY_SHA == manifest["binary"]["sha256"],
            "captured compiler binary hash does not match the pin")

    rows = []
    total_cases = 0
    for condition in CONDITIONS:
        for intent_id in INTENTS:
            invocation_dir = run_dir / "conditions" / condition / "invocations" / intent_id
            raw = (invocation_dir / "stdout.raw").read_bytes()
            output = json.loads(raw)
            report = output["report"]
            source = output["source"]
            source_bytes = source.encode("utf-8")
            source_hash = sha256(source_bytes)
            require(report.get("generated_digest") == f"sha256:{source_hash}",
                    f"{condition}/{intent_id}: saved Go source differs from emitted digest")
            expected_inputs = manifest["source_material"]["inputs"][intent_id]
            plan = read_json(HERE / expected_inputs["search_plan"]["path"])
            oracle = read_json(HERE / expected_inputs["finite_oracle"]["path"])
            body_search = report["body_search"]
            selected = body_search["selected_candidate_id"]
            candidate = next((candidate for candidate in plan["candidates"] if candidate["id"] == selected), None)
            require(candidate is not None and body_search["selected_expression"] == candidate["expression"],
                    f"{condition}/{intent_id}: selected expression does not match the declared plan")
            require(oracle.get("intent_id") == intent_id and oracle.get("schema") == "gooo/ir-search-finite-oracle/v1",
                    f"{condition}/{intent_id}: finite oracle identity/schema mismatch")

            activity = report["activity"]
            compiled = go.independent_go_oracle(source, activity, oracle, go_env)
            training_count = len(oracle["training"]["inputs"])
            actual_training = compiled["training_actuals"]
            actual_holdout = compiled["holdout_actuals"]
            expected_training = oracle["training"]["expected"]
            expected_holdout = oracle["holdout"]["expected"]
            selected_training = oracle["candidate_outputs"][selected]["training"]
            selected_holdout = oracle["candidate_outputs"][selected]["holdout"]
            require(actual_training == expected_training == selected_training,
                    f"{condition}/{intent_id}: compiled generated body differs from training oracle")
            require(actual_holdout == expected_holdout == selected_holdout,
                    f"{condition}/{intent_id}: compiled generated body differs from holdout oracle")
            case_count = len(expected_training) + len(expected_holdout)
            total_cases += case_count
            source_copy = output_dir / "sources" / f"{condition}-{intent_id}.go"
            source_copy.parent.mkdir(parents=True, exist_ok=True)
            source_copy.write_bytes(source_bytes)
            rows.append({
                "condition": condition,
                "intent_id": intent_id,
                "activity": activity,
                "selected_candidate_id": selected,
                "selected_expression": candidate["expression"],
                "emitted_source_sha256": source_hash,
                "generated_digest_matches": True,
                "training": {"inputs": oracle["training"]["inputs"], "expected": expected_training,
                             "compiled_actual": actual_training, "all_match": True},
                "holdout": {"inputs": oracle["holdout"]["inputs"], "expected": expected_holdout,
                            "compiled_actual": actual_holdout, "all_match": True},
                "compiled_case_count": case_count,
                "go_source_copy": str(source_copy.relative_to(output_dir)),
                "compiled_and_executed": True,
            })

    require(len(rows) == 4 and total_cases == 28, f"unexpected Go oracle run counts: {len(rows)} sources, {total_cases} cases")
    result = {
        "schema": "gooo/ir-search-parallel-emitted-go-validation/v1",
        "run_id": run_meta["run_id"],
        "validated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "go_version": version,
        "go_toolchain_required_by_ci": "go1.27.0",
        "go_execution_mode": "standard-library-only go test; GO111MODULE=off, GOPROXY=off, GOSUMDB=off, GOTOOLCHAIN=local",
        "laya_calls": 0,
        "gooo_cli_calls": 0,
        "capture_integrity_check": capture_check,
        "source_revision": run_meta["source_revision"],
        "binary_sha256": run_meta["binary_sha256"],
        "invocation_source_count": len(rows),
        "finite_case_execution_count": total_cases,
        "training_cases_executed": sum(len(row["training"]["inputs"]) for row in rows),
        "holdout_cases_executed_after_final_selection": sum(len(row["holdout"]["inputs"]) for row in rows),
        "all_cases_match_independent_oracle": all(row["training"]["all_match"] and row["holdout"]["all_match"] for row in rows),
        "rows": rows,
        "limitations": [
            "This is finite-suite execution, not a full int64-domain proof.",
            "The cohort has one replicate per condition, fixed sequential-then-simultaneous order, and no separate warmup.",
            "The sequential CLI pair's 523.5 ms inter-invocation gap is capture-proxy shutdown overhead; timing is not a speed claim.",
            "No Gooo CLI, Laya server, provider endpoint, or model was invoked by this validator.",
        ],
    }
    (output_dir / "validation-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Captured emitted Go source validation",
        "",
        f"- Saved invocations compiled and run: {len(rows)}",
        f"- Independent finite-oracle cases executed: {total_cases} (training {result['training_cases_executed']}; post-selection holdout {result['holdout_cases_executed_after_final_selection']})",
        f"- Go toolchain: `{version}` (CI pins `go1.27.0`; local validation records the installed version)",
        "- Raw capture hash/count validation: PASS",
        "- All compiled outputs match the independent training and holdout oracle vectors: PASS",
        "- Gooo CLI calls: 0; Laya/model calls: 0",
        "",
        "## Scope",
        "",
        *[f"- {item}" for item in result["limitations"]],
        "",
        "Per-invocation sources and vectors are recorded in `validation-report.json`; exact source copies are under `sources/`.",
        "",
    ]
    (output_dir / "validation-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(output_dir / "validation-report.json")


if __name__ == "__main__":
    main()
