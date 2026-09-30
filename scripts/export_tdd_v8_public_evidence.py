#!/usr/bin/env python3
"""Create a path-free public derivative from a fully verified TDD v8 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import adapt_tdd_v8_extra_domain_capture as adapter


CAPTURES = adapter.PROBE_DIR / "captures"
SAFE_ROOT_FILES = ("adapter-report.json", "source-manifest.json")
SAFE_CAPTURE_FILES = ("report.json", "summary.json", "phase-plans.json", "proxy/events.json")
SAFE_INVOCATION_FILES = ("fixture.gooo", "plan.search.json", "stdout.raw", "stderr.raw")
SECRET_PATTERN = re.compile(
    rb"(?:hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|"
    rb"Bearer\s+[A-Za-z0-9._~+/-]{20,})",
    re.IGNORECASE,
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def is_safe_public_bytes(raw: bytes) -> bool:
    private_path = any(token in raw for token in (b"/Users/", b"/private/tmp/", b"/home/"))
    return not private_path and SECRET_PATTERN.search(raw) is None


def included_paths(source: Path) -> list[Path]:
    paths = [source / name for name in SAFE_ROOT_FILES]
    paths.extend(source / "capture" / name for name in SAFE_CAPTURE_FILES)
    inv_root = source / "capture" / "invocations"
    for directory in sorted(path for path in inv_root.iterdir() if path.is_dir()):
        paths.extend(directory / name for name in SAFE_INVOCATION_FILES)
    for directory in ("proxy/requests", "proxy/responses"):
        paths.extend(sorted((source / "capture" / directory).glob("*.raw")))
    for directory in ("receipts", "sources"):
        paths.extend(sorted(path for path in (source / directory).rglob("*") if path.is_file()))
    result = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise ValueError(f"verified source bundle is missing a required regular file: {path.name}")
        raw = path.read_bytes()
        if not is_safe_public_bytes(raw):
            raise ValueError(f"refusing to export a private path or credential pattern from {path.name}")
        result.append(path)
    return result


def export_bundle(source: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    if not output.is_relative_to(CAPTURES.resolve()):
        raise ValueError("output must be a new directory beneath the frozen captures/ directory")
    if output.exists():
        raise ValueError("public evidence export is append-only; destination already exists")
    verified = adapter.verify_bundle(source)
    if verified.get("decision") != "VERIFIED":
        raise ValueError("only a fully verified TDD adapter bundle can be exported")
    files = included_paths(source)
    output.mkdir(parents=True, exist_ok=False)
    index = {}
    try:
        for path in files:
            relative = path.relative_to(source)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = path.read_bytes()
            target.write_bytes(raw)
            index[relative.as_posix()] = {"sha256": sha256(raw), "bytes": len(raw)}
        source_report = json.loads((source / "adapter-report.json").read_text(encoding="utf-8"))
        manifest_raw = (source / "source-manifest.json").read_bytes()
        derivation = {
            "schema": "gooo/tdd-v8-public-evidence-derivative/v1",
            "source_run_id": source_report["tdd_run_id"],
            "source_adapter_report_sha256": sha256((source / "adapter-report.json").read_bytes()),
            "source_manifest_sha256": sha256(manifest_raw),
            "source_bundle_decision": verified["decision"],
            "included_file_count": len(index),
            "omitted_categories": [
                "raw invocation records containing machine-local paths",
                "local preexecution and study-design documents containing machine-local paths",
                "copied study-code archive files; their frozen path/hash entries remain in adapter-report.json",
            ],
            "derivation_note": (
                "The original complete bundle passed adapter verification before export. This public "
                "derivative keeps the frozen plans, raw provider exchanges, native CLI JSON, emitted Go, "
                "source-unit receipts, report, and exact digests needed for offline rebinding; private "
                "filesystem paths and copied study-code files are omitted."
            ),
            "files": index,
        }
        (output / "public-derivation.json").write_bytes(canonical_json(derivation))
        verified_public = adapter.verify_public_bundle(output)
        return {**verified_public, "public_bundle": output.as_posix(),
                "derivation_sha256": sha256((output / "public-derivation.json").read_bytes())}
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_bundle(args.source_bundle, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
