#!/usr/bin/env python3
"""Validate cohort reports against the shared completeness receipt contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from completeness_receipt import validate_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        receipt = validate_report(report)
        first = receipt["first_unresolved"]
        unresolved = first["id"] if first else "none"
        print(
            f"{path}: {receipt['profile_id']} "
            f"{receipt['decision']} first_unresolved={unresolved}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
