#!/usr/bin/env python3
"""Validate cohort reports against the shared completeness receipt contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from completeness_receipt import validate_receipt, validate_report


def validate_compiler_receipts(report: dict) -> int:
    cases = report.get("cases", [])
    if "compiler_receipt_valid_case_count" not in report:
        return 0
    expected_source = report.get("gooo_source_sha")
    valid_count = 0
    core_pass_count = 0
    status_counts = {"PASS": 0, "PROGRESS": 0, "UNKNOWN": 0, "FAIL_CLOSED": 0}
    for case in cases:
        receipt = case.get("compiler_completeness_receipt")
        validate_receipt(receipt)
        scope = receipt["scope"]
        if case.get("compiler_receipt_valid") is not True:
            raise ValueError(f"{case.get('case_id')}: compiler receipt was not marked valid")
        if case.get("compiler_source_sha") != expected_source or scope["compiler_source_sha"] != expected_source:
            raise ValueError(f"{case.get('case_id')}: compiler receipt source revision is not pinned")
        if case.get("compiler_plan_sha256") != scope["plan_sha256"]:
            raise ValueError(f"{case.get('case_id')}: compiler receipt plan identity is not report-bound")
        canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        actual_digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if case.get("compiler_completeness_receipt_sha256") != actual_digest:
            raise ValueError(f"{case.get('case_id')}: compiler receipt digest mismatch")
        dimensions = {item["id"]: item for item in receipt["dimensions"]}
        core_passed = all(dimensions[dimension_id]["status"] == "PASS" for dimension_id in receipt["core_dimensions"])
        if case.get("compiler_core_dimensions_passed") is not core_passed:
            raise ValueError(f"{case.get('case_id')}: compiler core pass indicator conflicts with dimensions")
        core_pass_count += int(core_passed)
        valid_count += 1
        for item in receipt["dimensions"]:
            status_counts[item["status"]] += 1

    if report.get("compiler_receipt_valid_case_count") != valid_count:
        raise ValueError("compiler receipt coverage count does not match case records")
    if report.get("compiler_core_receipt_passes") != core_pass_count:
        raise ValueError("compiler core receipt pass count does not match case records")
    if report.get("compiler_receipt_status_counts") != status_counts:
        raise ValueError("compiler receipt status counts do not match embedded receipts")
    return valid_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        receipt = validate_report(report)
        compiler_receipts = validate_compiler_receipts(report)
        first = receipt["first_unresolved"]
        unresolved = first["id"] if first else "none"
        print(
            f"{path}: {receipt['profile_id']} "
            f"{receipt['decision']} first_unresolved={unresolved} "
            f"compiler_receipts={compiler_receipts}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
