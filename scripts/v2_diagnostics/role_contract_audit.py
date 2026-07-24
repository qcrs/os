from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.runtime.role_contract import audit_role_contract_report, role_contracts_payload
from v2.utils import stable_json_dumps


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# StateBus v2 Role Contract Audit",
        "",
        f"- pass: `{payload['pass']}`",
        f"- role_graph: `{payload['role_graph']}`",
        f"- expected_role_graph: `{payload['expected_role_graph']}`",
        f"- failed_checks: `{','.join(payload['failed_checks']) or 'none'}`",
        "",
        "| Role | Passed | Missing Metrics |",
        "| --- | --- | --- |",
    ]
    for role in payload["roles"]:
        lines.append(
            f"| `{role['role']}` | `{role['passed']}` | `{','.join(role['missing_metric_keys']) or '-'}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_role_contract_audit_bundle(
    *,
    report_path: Path,
    output_root: Path,
    suite_id: str = "statebus-v2-role-contract-audit",
) -> Path:
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    bundle_dir = output_root / suite_id
    audit_payload = audit_role_contract_report(report_payload)
    audit_payload["source_report_path"] = str(report_path)
    _write_json(bundle_dir / "role_contracts.json", role_contracts_payload())
    _write_json(bundle_dir / "summary.json", audit_payload)
    _write_markdown(bundle_dir / "summary.md", audit_payload)
    return bundle_dir


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit StateBus v2 role contract metrics in a benchmark report.")
    parser.add_argument("--report", type=Path, required=True, help="benchmark family report JSON")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/tmp") / "statebus-v2-role-contract-audit",
        help="output root for audit bundle",
    )
    parser.add_argument("--suite-id", default="statebus-v2-role-contract-audit", help="audit bundle directory name")
    return parser


def main(argv: list[str] | None = None) -> Path:
    args = _build_parser().parse_args(argv)
    bundle_dir = build_role_contract_audit_bundle(
        report_path=args.report,
        output_root=args.output_root,
        suite_id=args.suite_id,
    )
    print(
        stable_json_dumps(
            {
                "bundle_dir": str(bundle_dir),
                "summary_json": str(bundle_dir / "summary.json"),
                "summary_markdown": str(bundle_dir / "summary.md"),
                "role_contracts_json": str(bundle_dir / "role_contracts.json"),
            }
        )
    )
    return bundle_dir


if __name__ == "__main__":
    main()
