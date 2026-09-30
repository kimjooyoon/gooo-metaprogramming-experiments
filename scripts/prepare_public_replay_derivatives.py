#!/usr/bin/env python3
"""Create append-only path-redacted receipts for recorded probe replays."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil


EXECUTION = Path(__file__).resolve().parents[1] / "cohorts/ir-composition-curriculum-2026-09-30/extra-domain-probes-128/execution"
PRIVATE = (b"/Users/", b"/private/tmp/", b"/home/", b"/tmp/")
SECRET = re.compile(rb"(?:hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._~+/-]{20,})", re.I)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def ensure_public_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            if any(token in raw for token in PRIVATE) or SECRET.search(raw):
                raise ValueError(f"path or credential pattern remains in derivative file: {path.name}")


def rebuild_index(root: Path) -> None:
    files = {path.relative_to(root).as_posix(): digest(path.read_bytes())
             for path in sorted(root.rglob("*")) if path.is_file() and path.name != "artifact-index.json"}
    (root / "artifact-index.json").write_bytes(canonical({"files": files}))


def replay_derivative(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if not destination.is_relative_to(EXECUTION.resolve()):
        raise ValueError("replay derivative must be beneath the frozen execution directory")
    if destination.exists():
        raise ValueError("execution history is append-only; destination already exists")
    report_path = source / "replay-report.json"
    index_path = source / "artifact-index.json"
    report_raw, index_raw = report_path.read_bytes(), index_path.read_bytes()
    report = json.loads(report_raw.decode("utf-8"))
    toolchain = report.get("go_toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("path"), str):
        raise ValueError("source replay report has no Go path field to redact")
    redacted = copy.deepcopy(report)
    redacted_toolchain = redacted["go_toolchain"]
    del redacted_toolchain["path"]
    redacted_toolchain["binary"] = "go"
    redacted_toolchain["path_disclosure"] = "omitted from public receipt"
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for path in source.rglob("*"):
            if not path.is_file() or path.name in ("artifact-index.json", "replay-report.json"):
                continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        (destination / "replay-report.json").write_bytes(canonical(redacted))
        derivation = {
            "schema": "gooo/extra-domain-replay-public-path-redaction/v1",
            "source_attempt": source.name,
            "source_replay_report_sha256": digest(report_raw),
            "source_artifact_index_sha256": digest(index_raw),
            "public_replay_report_sha256": digest((destination / "replay-report.json").read_bytes()),
            "removed_fields": ["go_toolchain.path"],
            "replaced_fields": {"go_toolchain.binary": "go",
                                "go_toolchain.path_disclosure": "omitted from public receipt"},
            "result_decision": report.get("decision"),
            "model_calls": report.get("model_calls"),
            "candidate_selection_calls": report.get("candidate_selection_calls"),
            "note": "All replay observations are copied byte-for-byte; only the local executable path is removed from the public report.",
        }
        (destination / "public-report-derivation.json").write_bytes(canonical(derivation))
        rebuild_index(destination)
        ensure_public_tree(destination)
        return derivation
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def failure_derivative(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if not destination.is_relative_to(EXECUTION.resolve()):
        raise ValueError("failed-attempt derivative must be beneath the frozen execution directory")
    if destination.exists():
        raise ValueError("execution history is append-only; destination already exists")
    original = json.loads((source / "preflight-failure.json").read_text(encoding="utf-8"))
    redacted = copy.deepcopy(original)
    redacted.pop("go_path", None)
    redacted["path_disclosure"] = "omitted from public receipt"
    destination.mkdir(parents=True, exist_ok=False)
    try:
        copy_names = ("run-start.json", "source-manifest.json")
        index = {}
        for name in copy_names:
            raw = (source / name).read_bytes()
            (destination / name).write_bytes(raw)
            index[name] = digest(raw)
        failure_raw = canonical(redacted)
        (destination / "preflight-failure.json").write_bytes(failure_raw)
        derivation = {
            "schema": "gooo/extra-domain-preflight-failure-public-path-redaction/v1",
            "source_attempt": source.name,
            "source_preflight_failure_sha256": digest((source / "preflight-failure.json").read_bytes()),
            "source_run_start_sha256": digest((source / "run-start.json").read_bytes()),
            "public_preflight_failure_sha256": digest(failure_raw),
            "removed_fields": ["go_path"],
            "result_decision": redacted.get("decision"),
            "executed_probe_rows": redacted.get("executed_probe_rows"),
            "observed_binary_sha256": redacted.get("observed_go_binary_sha256"),
            "note": "The recorded toolchain hash mismatch and zero-row failure are preserved; the machine-local executable path is omitted.",
            "files": index,
        }
        (destination / "public-failure-derivation.json").write_bytes(canonical(derivation))
        rebuild_index(destination)
        ensure_public_tree(destination)
        return derivation
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("--source", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    failure = sub.add_parser("failure")
    failure.add_argument("--source", type=Path, required=True)
    failure.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.kind == "replay":
        result = replay_derivative(args.source, args.output)
    else:
        result = failure_derivative(args.source, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
