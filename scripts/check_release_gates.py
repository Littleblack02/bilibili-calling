"""Fail deployment when any required V2 verification report is missing or failed."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "ontology": "ontology-quality.json",
    "entity_linking": "entity-linking.json",
    "rag": "rag.json",
    "recommendation": "recommendation.json",
    "migration": "migration.json",
    "backfill": "backfill.json",
    "local_performance": "local-performance.json",
}


def check(report_dir: Path) -> dict[str, object]:
    gates = {}
    for name, filename in REQUIRED.items():
        path = report_dir / filename
        if not path.is_file():
            gates[name] = {"passed": False, "reason": "missing_report", "file": filename}
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            passed = bool(payload.get("passed", payload.get("passes", False)))
            gates[name] = {
                "passed": passed,
                "reason": "verified" if passed else "report_failed",
                "file": filename,
            }
        except (OSError, json.JSONDecodeError) as exc:
            gates[name] = {"passed": False, "reason": f"invalid_report:{type(exc).__name__}", "file": filename}
    passed = all(row["passed"] for row in gates.values())
    return {
        "schema_version": "1.0", "generated_at": datetime.now().astimezone().isoformat(),
        "gates": gates, "passed": passed,
        "required_action": (
            "May advance rollout only while every gate remains green."
            if passed else
            "Keep all V2 flags disabled (or immediately set rollout to 0) until reports pass."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "evaluation")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "release-gates.json")
    args = parser.parse_args()
    report = check(args.report_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
