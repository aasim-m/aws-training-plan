from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from textwrap import shorten
from typing import Sequence

from .discovery import (
    SearchRequest,
    TrainingPlanDiscovery,
    ValidationError,
    supported_training_plan_instance_types,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find the latest available SageMaker HyperPod training plan offering in commercial US regions."
    )
    parser.add_argument("--instance-type", help="SageMaker instance type, for example ml.p5.48xlarge")
    parser.add_argument(
        "--list-supported-instance-types",
        action="store_true",
        help="Print the installed SDK's supported training plan instance types and exit",
    )
    parser.add_argument(
        "--skip-instance-type-validation",
        action="store_true",
        help="Skip local SDK enum validation and let the AWS API validate the instance type",
    )
    parser.add_argument(
        "--validate-instance-type-with-aws",
        action="store_true",
        help="Call AWS once to validate --instance-type against the live SearchTrainingPlanOfferings API and exit",
    )
    parser.add_argument(
        "--validation-region",
        default="us-east-1",
        help="AWS region for --validate-instance-type-with-aws. Defaults to us-east-1",
    )

    duration_group = parser.add_mutually_exclusive_group()
    duration_group.add_argument("--duration-days", type=int, help="Requested duration in days")
    duration_group.add_argument("--duration-hours", type=int, help="Requested duration in hours")

    parser.add_argument("--instance-count", type=int, default=1, help="Instance quantity to reserve. Defaults to 1")
    parser.add_argument(
        "--maximum-segments",
        "--segments",
        dest="maximum_segments",
        type=int,
        default=1,
        help="Maximum number of reserved-capacity segments per offering. Defaults to 1",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        help="Commercial US regions to search, for example --regions us-east-1 us-east-2",
    )
    parser.add_argument(
        "--start-time-after",
        help="Search for offerings starting after this ISO-8601 timestamp, for example 2026-07-01T00:00:00Z",
    )
    parser.add_argument(
        "--max-lookahead-weeks",
        type=int,
        default=1,
        help="Maximum number of weeks to search ahead. Defaults to 1",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve all lookahead window expansions without prompting",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON output for automation")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output when used with --json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.list_supported_instance_types:
            print(json.dumps({"supported_instance_types": supported_training_plan_instance_types()}, indent=2))
            return 0

        if args.instance_type is None:
            parser.error("--instance-type is required unless --list-supported-instance-types is used")

        if args.validate_instance_type_with_aws:
            result = TrainingPlanDiscovery().validate_instance_type_with_aws(
                instance_type=args.instance_type,
                duration_hours=args.duration_hours or (args.duration_days or 1) * 24,
                instance_count=args.instance_count,
                region=args.validation_region,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["valid"] is not False else 2

        if args.duration_days is None and args.duration_hours is None:
            parser.error("one of --duration-days or --duration-hours is required")

        request = SearchRequest.from_input(
            instance_type=args.instance_type,
            duration_days=args.duration_days,
            duration_hours=args.duration_hours,
            instance_count=args.instance_count,
            segments=args.maximum_segments,
            max_lookahead_weeks=args.max_lookahead_weeks,
            regions=args.regions,
            start_time_after=args.start_time_after,
            validate_instance_type=not args.skip_instance_type_validation,
        )
        result = TrainingPlanDiscovery().discover_latest(
            request,
            approve_expansion=_approve_all if args.yes else _prompt_for_expansion,
        )
    except ValidationError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    if args.json:
        indent = 2 if args.pretty else None
        print(json.dumps(result, indent=indent, sort_keys=bool(indent)))
    else:
        print(_format_search_result(result))
    return 0


def _approve_all(previous_lookahead_weeks: int, next_lookahead_weeks: int) -> bool:
    del previous_lookahead_weeks, next_lookahead_weeks
    return True


def _prompt_for_expansion(previous_lookahead_weeks: int, next_lookahead_weeks: int) -> bool:
    answer = input(
        f"No offerings found within {previous_lookahead_weeks} week(s). "
        f"Search within {next_lookahead_weeks} week(s)? [y/N]: "
    )
    return answer.strip().lower() in {"y", "yes"}


def _format_search_result(result: dict) -> str:
    lines: list[str] = []
    found = result.get("found") is True
    lookahead = result.get("lookahead_used_weeks")
    searched_regions = result.get("searched_regions", [])

    if found:
        offering_count = len(result.get("offerings") or [])
        suffix = "" if offering_count == 1 else "s"
        lines.append(f"Found {offering_count} training plan offering{suffix} within {lookahead} week(s).")
        lines.append("")
        lines.extend(_format_offerings_table(result.get("offerings") or [result["best_offering"]]))
    else:
        lines.append(f"No training plan offering found within {lookahead} week(s).")
        next_window = result.get("next_lookahead_weeks")
        if result.get("approval_required") and next_window is not None:
            lines.append(f"Next approval needed: search within {next_window} week(s).")

    lines.append("")
    lines.append(f"Searched regions: {', '.join(searched_regions) if searched_regions else 'none'}")

    errors = result.get("errors", [])
    if errors:
        lines.append("")
        lines.append("Region warnings:")
        lines.extend(_format_error_summary(errors))

    return "\n".join(lines)


def _format_offerings_table(offerings: list[dict]) -> list[str]:
    rows = []
    for offering in offerings:
        capacity = offering.get("reserved_capacity_offerings") or [{}]
        for item in capacity:
            rows.append(
                {
                    "Region": offering.get("region"),
                    "AZ": item.get("AvailabilityZone", ""),
                    "Instance": item.get("InstanceType", ""),
                    "Count": item.get("InstanceCount", ""),
                    "Start": item.get("StartTime") or offering.get("start_time") or "",
                    "End": item.get("EndTime") or offering.get("end_time") or "",
                    "Hours": item.get("DurationHours") or offering.get("duration_hours") or "",
                    "Fee": f"{offering.get('currency_code') or ''} {offering.get('upfront_fee') or ''}".strip(),
                    "OfferingId": offering.get("training_plan_offering_id") or "",
                }
            )

    return _render_table(
        rows,
        ["Region", "AZ", "Instance", "Count", "Start", "End", "Hours", "Fee", "OfferingId"],
        max_widths={"OfferingId": 28},
    )


def _format_error_summary(errors: list[dict]) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for error in errors:
        grouped[_sanitize_error_message(str(error.get("message", "")))].append(str(error.get("region", "unknown")))

    lines = []
    for message, regions in sorted(grouped.items(), key=lambda item: item[0]):
        unique_regions = sorted(set(regions))
        lines.append(f"- {', '.join(unique_regions)}: {message}")
    return lines


def _sanitize_error_message(message: str) -> str:
    if not message:
        return "Unknown error"

    validation_match = re.search(
        r"ValidationException\) when calling the SearchTrainingPlanOfferings operation: (.*)",
        message,
    )
    if validation_match:
        return validation_match.group(1).strip()

    return message.strip()


def _render_table(rows: list[dict], columns: list[str], max_widths: dict[str, int] | None = None) -> list[str]:
    max_widths = max_widths or {}
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                column: _truncate_cell(str(row.get(column, "")), max_widths.get(column))
                for column in columns
            }
        )

    widths = {
        column: max([len(column), *[len(row[column]) for row in display_rows]])
        for column in columns
    }
    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    rendered = [header, separator]
    rendered.extend(
        " | ".join(row[column].ljust(widths[column]) for column in columns)
        for row in display_rows
    )
    return rendered


def _truncate_cell(value: str, max_width: int | None) -> str:
    if max_width is None or len(value) <= max_width:
        return value
    return shorten(value, width=max_width, placeholder="...")


if __name__ == "__main__":
    raise SystemExit(main())
