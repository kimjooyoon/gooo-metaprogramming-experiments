"""Shared v2 contract for evidence-bounded metaprogramming completeness receipts."""

from __future__ import annotations

from typing import Any


RECEIPT_SCHEMA = "gooo/metaprogramming-completeness-receipt/v2"
STATUSES = ("PASS", "PROGRESS", "UNKNOWN", "FAIL_CLOSED")
UNRESOLVED_STATUSES = ("PROGRESS", "UNKNOWN", "FAIL_CLOSED")
REQUIRED_SCOPE_FIELDS = (
    "domain_scope",
    "allowed_investment",
    "excluded_scope",
    "plan_sha256",
    "compiler_source_sha",
    "toolchain",
    "execution_environment",
)
REQUIRED_DIMENSION_FIELDS = ("id", "status", "numerator", "denominator", "unit", "reason", "evidence")
REQUIRED_RECEIPT_FIELDS = (
    "schema",
    "profile_id",
    "decision",
    "decision_basis",
    "scope",
    "core_dimensions",
    "dimensions",
    "status_counts",
    "aggregate_completeness_score",
    "first_unresolved",
    "unresolved_claims",
    "not_claimed",
    "fail_closed_reason",
)


def dimension(
    dimension_id: str,
    numerator: int,
    denominator: int,
    unit: str,
    reason: str,
    evidence: list[str],
    *,
    fail_closed: bool = False,
) -> dict[str, Any]:
    if fail_closed:
        status = "FAIL_CLOSED"
    elif denominator <= 0 or numerator <= 0:
        status = "UNKNOWN"
    elif numerator == denominator:
        status = "PASS"
    else:
        status = "PROGRESS"
    return {
        "id": dimension_id,
        "status": status,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "reason": reason,
        "evidence": evidence,
    }


def finalize_receipt(
    *,
    profile_id: str,
    decision_basis: str,
    scope: dict[str, Any],
    dimensions: list[dict[str, Any]],
    core_dimensions: set[str],
    next_operations: dict[str, str],
    not_claimed: list[str],
    force_fail_closed_reason: str = "",
) -> dict[str, Any]:
    ids = [item.get("id") for item in dimensions]
    if len(ids) != len(set(ids)):
        raise ValueError("completeness receipt dimension IDs must be unique")
    if not core_dimensions or not core_dimensions.issubset(set(ids)):
        raise ValueError("completeness receipt core dimensions must all be declared")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("completeness receipt profile_id is required")
    if not isinstance(decision_basis, str) or not decision_basis.strip():
        raise ValueError("completeness receipt decision_basis is required")
    validate_scope(scope)
    for item in dimensions:
        validate_dimension(item)

    by_id = {str(item["id"]): item for item in dimensions}
    core = [by_id[item] for item in sorted(core_dimensions)]
    core_failure = next((item for item in core if item["status"] == "FAIL_CLOSED"), None)
    failure_dimension = next((item for item in dimensions if item["status"] == "FAIL_CLOSED"), None)
    if force_fail_closed_reason or failure_dimension is not None or core_failure is not None:
        decision = "FAIL_CLOSED"
    elif all(item["status"] == "PASS" for item in core):
        decision = "PASS_WITHIN_DECLARED_FIXTURE_SCOPE"
    else:
        decision = "PROGRESS_WITHIN_DECLARED_FIXTURE_SCOPE"

    status_counts = {status: sum(item["status"] == status for item in dimensions) for status in STATUSES}
    unresolved: list[dict[str, str]] = []
    for item in dimensions:
        if item["status"] not in UNRESOLVED_STATUSES:
            continue
        operation = next_operations.get(str(item["id"]))
        if not operation:
            raise ValueError(f"unresolved completeness dimension {item['id']!r} has no next operation")
        unresolved.append(
            {
                "id": str(item["id"]),
                "status": str(item["status"]),
                "reason": str(item["reason"]),
                "next_operation": operation,
            }
        )

    failure_reason = force_fail_closed_reason or (str(failure_dimension["reason"]) if failure_dimension else "")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "profile_id": profile_id,
        "decision": decision,
        "decision_basis": decision_basis,
        "scope": scope,
        "core_dimensions": sorted(core_dimensions),
        "dimensions": dimensions,
        "status_counts": status_counts,
        "aggregate_completeness_score": None,
        "first_unresolved": unresolved[0] if unresolved else None,
        "unresolved_claims": unresolved,
        "not_claimed": not_claimed,
        "fail_closed_reason": failure_reason or None,
    }
    validate_receipt(receipt)
    return receipt


def validate_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ValueError("completeness receipt scope must be an object")
    missing = [field for field in REQUIRED_SCOPE_FIELDS if field not in scope]
    if missing:
        raise ValueError(f"completeness receipt scope omits required fields: {missing}")
    for field in ("domain_scope", "allowed_investment", "plan_sha256", "compiler_source_sha", "toolchain", "execution_environment"):
        if not isinstance(scope[field], str) or not scope[field].strip():
            raise ValueError(f"completeness receipt scope field {field!r} must be a non-empty string")
    if not scope["plan_sha256"].startswith("sha256:"):
        raise ValueError("completeness receipt plan identity must be a SHA-256 digest")
    if not isinstance(scope["excluded_scope"], list) or not scope["excluded_scope"] or any(
        not isinstance(item, str) or not item.strip() for item in scope["excluded_scope"]
    ):
        raise ValueError("completeness receipt excluded_scope must list explicit exclusions")


def validate_dimension(item: Any) -> None:
    if not isinstance(item, dict):
        raise ValueError("completeness receipt dimensions must be objects")
    missing = [field for field in REQUIRED_DIMENSION_FIELDS if field not in item]
    if missing:
        raise ValueError(f"completeness dimension omits required fields: {missing}")
    if not isinstance(item["id"], str) or not item["id"].strip():
        raise ValueError("completeness dimension id is required")
    if item["status"] not in STATUSES:
        raise ValueError(f"completeness dimension {item['id']!r} has an invalid status")
    if type(item["numerator"]) not in (int, float) or type(item["denominator"]) not in (int, float):
        raise ValueError(f"completeness dimension {item['id']!r} must use numeric evidence counts")
    if item["numerator"] < 0 or item["denominator"] < 0:
        raise ValueError(f"completeness dimension {item['id']!r} cannot use negative counts")
    if item["numerator"] > item["denominator"]:
        raise ValueError(f"completeness dimension {item['id']!r} numerator exceeds its denominator")
    if item["denominator"] == 0 and item["status"] != "UNKNOWN":
        raise ValueError(f"zero-denominator dimension {item['id']!r} must remain UNKNOWN")
    if not isinstance(item["unit"], str) or not item["unit"].strip():
        raise ValueError(f"completeness dimension {item['id']!r} needs a unit")
    if not isinstance(item["reason"], str) or not item["reason"].strip():
        raise ValueError(f"completeness dimension {item['id']!r} needs a reason")
    if not isinstance(item["evidence"], list) or not item["evidence"] or any(
        not isinstance(value, str) or not value.strip() for value in item["evidence"]
    ):
        raise ValueError(f"completeness dimension {item['id']!r} needs explicit evidence references")


def validate_receipt(receipt: Any) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("completeness receipt must be an object")
    missing = [field for field in REQUIRED_RECEIPT_FIELDS if field not in receipt]
    if missing:
        raise ValueError(f"completeness receipt omits required fields: {missing}")
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise ValueError(f"unsupported completeness receipt schema {receipt['schema']!r}")
    for field in ("profile_id", "decision_basis"):
        if not isinstance(receipt[field], str) or not receipt[field].strip():
            raise ValueError(f"completeness receipt {field!r} must be a non-empty string")
    if receipt["decision"] not in ("PASS_WITHIN_DECLARED_FIXTURE_SCOPE", "PROGRESS_WITHIN_DECLARED_FIXTURE_SCOPE", "FAIL_CLOSED"):
        raise ValueError("completeness receipt decision is invalid")
    if receipt["aggregate_completeness_score"] is not None:
        raise ValueError("aggregate completeness score must remain null")
    if not isinstance(receipt["dimensions"], list):
        raise ValueError("completeness receipt dimensions must be an array")
    if not isinstance(receipt["not_claimed"], list) or not receipt["not_claimed"] or any(
        not isinstance(value, str) or not value.strip() for value in receipt["not_claimed"]
    ):
        raise ValueError("completeness receipt must explicitly list unclaimed conclusions")
    for item in receipt["dimensions"]:
        validate_dimension(item)
    ids = [item["id"] for item in receipt["dimensions"]]
    if len(ids) != len(set(ids)):
        raise ValueError("completeness receipt dimension IDs must be unique")
    core_ids = receipt["core_dimensions"]
    if not isinstance(core_ids, list) or not core_ids or len(core_ids) != len(set(core_ids)) or not set(core_ids).issubset(ids):
        raise ValueError("completeness receipt core dimensions must name declared dimensions")
    expected_counts = {status: sum(item["status"] == status for item in receipt["dimensions"]) for status in STATUSES}
    if receipt["status_counts"] != expected_counts:
        raise ValueError("completeness receipt status_counts do not match its dimensions")

    unresolved = []
    for item in receipt["dimensions"]:
        if item["status"] in UNRESOLVED_STATUSES:
            unresolved.append(item["id"])
    claims = receipt["unresolved_claims"]
    if not isinstance(claims, list) or [item.get("id") for item in claims] != unresolved:
        raise ValueError("unresolved_claims must retain every non-PASS dimension in receipt order")
    for claim in claims:
        if any(not isinstance(claim.get(field), str) or not claim[field].strip() for field in ("status", "reason", "next_operation")):
            raise ValueError(f"unresolved claim {claim.get('id')!r} needs status, reason, and next_operation")
        source = next(item for item in receipt["dimensions"] if item["id"] == claim["id"])
        if claim["status"] != source["status"] or claim["reason"] != source["reason"]:
            raise ValueError(f"unresolved claim {claim['id']!r} conflicts with its dimension evidence")
    expected_first = claims[0] if claims else None
    if receipt["first_unresolved"] != expected_first:
        raise ValueError("first_unresolved must equal the first retained unresolved claim")

    core = [item for item in receipt["dimensions"] if item["id"] in core_ids]
    failure_reason = receipt["fail_closed_reason"]
    if receipt["decision"] == "FAIL_CLOSED":
        if not failure_reason:
            raise ValueError("FAIL_CLOSED receipts must preserve the failing reason")
    elif any(item["status"] == "FAIL_CLOSED" for item in receipt["dimensions"]):
        raise ValueError("FAIL_CLOSED dimensions require a FAIL_CLOSED receipt decision")
    elif failure_reason is not None:
        raise ValueError("non-failing receipts cannot carry a forced failure reason")
    elif receipt["decision"] == "PASS_WITHIN_DECLARED_FIXTURE_SCOPE" and not all(item["status"] == "PASS" for item in core):
        raise ValueError("PASS decision requires every core dimension to pass")
    elif receipt["decision"] == "PROGRESS_WITHIN_DECLARED_FIXTURE_SCOPE" and all(item["status"] == "PASS" for item in core):
        raise ValueError("PROGRESS decision cannot have all core dimensions pass")


def validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("cohort report must be an object")
    receipt = report.get("completeness_receipt")
    validate_receipt(receipt)
    scope = receipt["scope"]
    if scope["plan_sha256"] != report.get("plan_sha256"):
        raise ValueError("receipt plan digest is not bound to the cohort report")
    report_source = report.get("gooo_source_sha") or report.get("compiler_source_sha") or "UNBOUND_LOCAL_SOURCE"
    if scope["compiler_source_sha"] != report_source:
        raise ValueError("receipt compiler identity is not bound to the cohort report")
    if report.get("decision") == "PASS" and receipt["decision"] == "FAIL_CLOSED":
        raise ValueError("passing cohort report cannot carry a FAIL_CLOSED completeness receipt")
    if report.get("decision") == "FAIL_CLOSED" and receipt["decision"] != "FAIL_CLOSED":
        raise ValueError("failed cohort report must preserve FAIL_CLOSED in its completeness receipt")
    return receipt
