from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import boto3
import botocore.session
from botocore.exceptions import ClientError


DEFAULT_LOOKAHEAD_WEEKS = 1
DEFAULT_MAX_LOOKAHEAD_WEEKS = 52
LOOKAHEAD_WINDOWS = [1, 2, 3, 4, 8, 16, 32, 52]
TARGET_RESOURCES = ["hyperpod-cluster"]


class ValidationError(ValueError):
    """Raised when caller input cannot be converted to a valid search request."""


@dataclass(frozen=True)
class SearchRequest:
    instance_type: str
    duration_hours: int
    instance_count: int = 1
    segments: int = 1
    max_lookahead_weeks: int = DEFAULT_MAX_LOOKAHEAD_WEEKS
    regions: tuple[str, ...] | None = None
    start_time_after: datetime | None = None

    @classmethod
    def from_input(
        cls,
        *,
        instance_type: str | None,
        duration_days: int | str | None = None,
        duration_hours: int | str | None = None,
        instance_count: int | str | None = None,
        segments: int | str | None = None,
        max_lookahead_weeks: int | str | None = None,
        regions: list[str] | tuple[str, ...] | str | None = None,
        start_time_after: datetime | str | None = None,
        validate_instance_type: bool = True,
    ) -> "SearchRequest":
        if not instance_type or not str(instance_type).strip():
            raise ValidationError("instance_type is required")

        parsed_instance_type = str(instance_type).strip()
        if validate_instance_type:
            validate_training_plan_instance_type(parsed_instance_type)

        if duration_days is not None and duration_hours is not None:
            raise ValidationError("provide either duration_days or duration_hours, not both")

        if duration_days is None and duration_hours is None:
            raise ValidationError("duration_days or duration_hours is required")

        if duration_days is not None:
            parsed_duration_days = _parse_positive_int(duration_days, "duration_days")
            parsed_duration_hours = parsed_duration_days * 24
        else:
            parsed_duration_hours = _parse_positive_int(duration_hours, "duration_hours")

        parsed_instance_count = _parse_positive_int(
            1 if instance_count is None else instance_count,
            "instance_count",
        )
        parsed_segments = _parse_positive_int(
            1 if segments is None else segments,
            "segments",
        )
        parsed_max_lookahead_weeks = _parse_positive_int(
            DEFAULT_MAX_LOOKAHEAD_WEEKS
            if max_lookahead_weeks is None
            else max_lookahead_weeks,
            "max_lookahead_weeks",
        )

        if parsed_max_lookahead_weeks < DEFAULT_LOOKAHEAD_WEEKS:
            raise ValidationError(
                f"max_lookahead_weeks must be at least {DEFAULT_LOOKAHEAD_WEEKS}"
            )
        if parsed_max_lookahead_weeks > DEFAULT_MAX_LOOKAHEAD_WEEKS:
            raise ValidationError(
                f"max_lookahead_weeks must be no more than {DEFAULT_MAX_LOOKAHEAD_WEEKS}"
            )
        if parsed_max_lookahead_weeks not in LOOKAHEAD_WINDOWS:
            allowed_windows = ", ".join(str(window) for window in LOOKAHEAD_WINDOWS)
            raise ValidationError(f"max_lookahead_weeks must be one of: {allowed_windows}")

        return cls(
            instance_type=parsed_instance_type,
            duration_hours=parsed_duration_hours,
            instance_count=parsed_instance_count,
            segments=parsed_segments,
            max_lookahead_weeks=parsed_max_lookahead_weeks,
            regions=_parse_regions(regions),
            start_time_after=_parse_timestamp(start_time_after, "start_time_after"),
        )


class TrainingPlanDiscovery:
    def __init__(
        self,
        *,
        session: boto3.session.Session | None = None,
        regions: list[str] | None = None,
        client_factory: Callable[[str], Any] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session or boto3.session.Session()
        self._regions = regions
        self._client_factory = client_factory
        self._now_provider = now_provider or _utc_now

    def discover_latest(
        self,
        request: SearchRequest,
        approve_expansion: Callable[[int, int], bool] | None = None,
        continue_until_approved_window: bool = False,
    ) -> dict[str, Any]:
        regions = list(request.regions) if request.regions else self._regions or self.list_commercial_us_regions()
        all_errors: list[dict[str, str]] = []
        seen_errors: set[tuple[str, str]] = set()
        skipped_regions: set[str] = set()
        best: dict[str, Any] | None = None
        offerings: list[dict[str, Any]] = []
        lookahead_used_weeks = DEFAULT_LOOKAHEAD_WEEKS
        approval_required = False
        next_lookahead_weeks: int | None = None

        for index, lookahead_weeks in enumerate(_lookahead_windows(request.max_lookahead_weeks)):
            active_regions = [region for region in regions if region not in skipped_regions]
            if not active_regions:
                break

            if index > 0 and approve_expansion is not None:
                previous_lookahead_weeks = lookahead_used_weeks
                if not approve_expansion(previous_lookahead_weeks, lookahead_weeks):
                    approval_required = True
                    next_lookahead_weeks = lookahead_weeks
                    break

            lookahead_used_weeks = lookahead_weeks
            window_result = self._search_window(request, active_regions, lookahead_weeks)
            for error in window_result["errors"]:
                error_key = (error["region"], error["message"])
                if error_key not in seen_errors:
                    seen_errors.add(error_key)
                    all_errors.append(error)
                if _is_non_retryable_region_error(error["message"]):
                    skipped_regions.add(error["region"])

            matching_offerings = [
                offering
                for offering in window_result["offerings"]
                if _segment_count(offering) <= request.segments
            ]
            window_offerings = sorted(
                matching_offerings,
                key=_offering_sort_key,
                reverse=True,
            )

            for offering in window_offerings:
                if best is None or _offering_sort_key(offering) > _offering_sort_key(best):
                    best = offering

            if best is not None and not continue_until_approved_window:
                offerings = window_offerings
                break
            if window_offerings:
                offerings = window_offerings

        return {
            "found": best is not None,
            "best_offering": best,
            "offerings": offerings,
            "searched_regions": regions,
            "lookahead_used_weeks": lookahead_used_weeks,
            "max_lookahead_weeks": request.max_lookahead_weeks,
            "approval_required": approval_required,
            "next_lookahead_weeks": next_lookahead_weeks,
            "errors": all_errors,
        }

    def list_commercial_us_regions(self) -> list[str]:
        regions = self._session.get_available_regions("sagemaker")
        return sorted(
            region
            for region in regions
            if region.startswith("us-") and not region.startswith("us-gov-")
        )

    def validate_instance_type_with_aws(
        self,
        *,
        instance_type: str,
        duration_hours: int = 24,
        instance_count: int = 1,
        region: str = "us-east-1",
    ) -> dict[str, Any]:
        start_time = self._now_provider()
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        end_time = start_time + timedelta(weeks=DEFAULT_LOOKAHEAD_WEEKS)

        try:
            client = self._create_sagemaker_client(region)
            client.search_training_plan_offerings(
                InstanceType=instance_type,
                InstanceCount=instance_count,
                StartTimeAfter=start_time,
                EndTimeBefore=end_time,
                DurationHours=duration_hours,
                TargetResources=TARGET_RESOURCES,
            )
            return {
                "instance_type": instance_type,
                "region": region,
                "valid": True,
                "source": "aws",
                "message": "AWS accepted the instance type for SearchTrainingPlanOfferings.",
            }
        except ClientError as exc:
            error = exc.response.get("Error", {})
            code = error.get("Code", "")
            message = error.get("Message", str(exc))
            if code == "ValidationException" and "instanceType" in message:
                return {
                    "instance_type": instance_type,
                    "region": region,
                    "valid": False,
                    "source": "aws",
                    "message": message,
                }
            return {
                "instance_type": instance_type,
                "region": region,
                "valid": None,
                "source": "aws",
                "message": f"AWS validation was inconclusive: {message}",
            }
        except Exception as exc:
            return {
                "instance_type": instance_type,
                "region": region,
                "valid": None,
                "source": "aws",
                "message": f"AWS validation was inconclusive: {exc}",
            }

    def _search_window(
        self,
        request: SearchRequest,
        regions: list[str],
        lookahead_weeks: int,
    ) -> dict[str, list[dict[str, Any]]]:
        start_time = request.start_time_after or self._now_provider()
        start_time = _ensure_utc(start_time)
        end_time = start_time + timedelta(weeks=lookahead_weeks)

        offerings: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for region in regions:
            try:
                client = self._create_sagemaker_client(region)
                response = client.search_training_plan_offerings(
                    InstanceType=request.instance_type,
                    InstanceCount=request.instance_count,
                    StartTimeAfter=start_time,
                    EndTimeBefore=end_time,
                    DurationHours=request.duration_hours,
                    TargetResources=TARGET_RESOURCES,
                )
                for offering in response.get("TrainingPlanOfferings", []):
                    offerings.append(_normalize_offering(offering, region))
            except Exception as exc:  # boto3 exceptions vary by region/credential state.
                errors.append({"region": region, "message": str(exc)})

        return {"offerings": offerings, "errors": errors}

    def _create_sagemaker_client(self, region: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(region)
        return self._session.client("sagemaker", region_name=region)


def _parse_positive_int(value: int | str | None, field_name: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a positive integer") from exc

    if parsed <= 0:
        raise ValidationError(f"{field_name} must be a positive integer")

    return parsed


def _parse_regions(regions: list[str] | tuple[str, ...] | str | None) -> tuple[str, ...] | None:
    if regions is None:
        return None

    if isinstance(regions, str):
        candidates = regions.split(",")
    else:
        candidates = list(regions)

    parsed = tuple(region.strip() for region in candidates if region and region.strip())
    if not parsed:
        return None

    for region in parsed:
        if not region.startswith("us-") or region.startswith("us-gov-"):
            raise ValidationError("regions must be commercial US regions such as us-east-1")

    return parsed


def _parse_timestamp(value: datetime | str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be an ISO-8601 timestamp")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 timestamp") from exc

    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def supported_training_plan_instance_types() -> list[str]:
    session = botocore.session.get_session()
    model = session.get_service_model("sagemaker")
    shape = model.shape_for("ReservedCapacityInstanceType")
    return sorted(shape.enum)


def validate_training_plan_instance_type(instance_type: str) -> None:
    supported = supported_training_plan_instance_types()
    if instance_type in supported:
        return

    supported_values = ", ".join(supported)
    raise ValidationError(
        f"instance_type '{instance_type}' is not supported by "
        f"SearchTrainingPlanOfferings. Supported values from the installed "
        f"botocore SageMaker model: {supported_values}"
    )


def _lookahead_windows(max_lookahead_weeks: int) -> list[int]:
    return [weeks for weeks in LOOKAHEAD_WINDOWS if weeks <= max_lookahead_weeks]


def _segment_count(offering: dict[str, Any]) -> int:
    return len(offering.get("reserved_capacity_offerings") or [])


def _is_non_retryable_region_error(message: str) -> bool:
    normalized = message.lower()
    return "validationexception" in normalized and (
        "invalid instance type" in normalized
        or "target resource hyperpod-cluster" in normalized
        or "failed to satisfy constraint" in normalized
    )


def _normalize_offering(offering: dict[str, Any], region: str) -> dict[str, Any]:
    normalized = _json_safe(offering)
    return {
        "region": region,
        "training_plan_offering_id": normalized.get("TrainingPlanOfferingId"),
        "start_time": normalized.get("RequestedStartTimeAfter"),
        "end_time": normalized.get("RequestedEndTimeBefore"),
        "duration_hours": normalized.get("DurationHours"),
        "duration_minutes": normalized.get("DurationMinutes"),
        "upfront_fee": normalized.get("UpfrontFee"),
        "currency_code": normalized.get("CurrencyCode"),
        "target_resources": normalized.get("TargetResources", []),
        "reserved_capacity_offerings": normalized.get("ReservedCapacityOfferings", []),
        "raw": normalized,
    }


def _offering_sort_key(offering: dict[str, Any]) -> str:
    start_time = offering.get("start_time")
    return "" if start_time is None else str(start_time)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
