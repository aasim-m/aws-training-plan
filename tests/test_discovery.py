from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError
import pytest

from training_plan_discovery.discovery import SearchRequest, TrainingPlanDiscovery, ValidationError


FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, region: str, responses: dict[tuple[str, int], object], calls: list[dict[str, object]]) -> None:
        self._region = region
        self._responses = responses
        self._calls = calls

    def search_training_plan_offerings(self, **kwargs: object) -> dict[str, object]:
        self._calls.append({"region": self._region, **kwargs})
        request_span = kwargs["EndTimeBefore"] - kwargs["StartTimeAfter"]  # type: ignore[operator]
        duration_hours = int(kwargs.get("DurationHours", 0))
        lookahead_days = int((request_span.total_seconds() - duration_hours * 3600) // 86400)
        key = (self._region, lookahead_days)
        response = self._responses.get(key, {"TrainingPlanOfferings": []})
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


def fake_discovery(
    responses: dict[tuple[str, int], object],
    *,
    regions: list[str] | None = None,
    calls: list[dict[str, object]] | None = None,
) -> TrainingPlanDiscovery:
    captured_calls = [] if calls is None else calls

    def client_factory(region: str) -> FakeClient:
        return FakeClient(region, responses, captured_calls)

    return TrainingPlanDiscovery(
        regions=regions or ["us-east-1", "us-west-2"],
        client_factory=client_factory,
        now_provider=lambda: FIXED_NOW,
    )


def offering(offering_id: str, start_time: datetime, segments: int = 1) -> dict[str, object]:
    capacity = [
        {
            "InstanceType": "ml.p5.48xlarge",
            "StartTime": start_time,
            "EndTime": start_time,
            "DurationHours": 24,
        }
        for _ in range(segments)
    ]
    return {
        "TrainingPlanOfferingId": offering_id,
        "RequestedStartTimeAfter": start_time,
        "RequestedEndTimeBefore": start_time,
        "DurationHours": 24,
        "UpfrontFee": "100.00",
        "CurrencyCode": "USD",
        "TargetResources": ["hyperpod-cluster"],
        "ReservedCapacityOfferings": capacity,
    }


def test_request_defaults_to_days_and_instance_count_one() -> None:
    request = SearchRequest.from_input(instance_type=" ml.p5.48xlarge ", duration_days=2)

    assert request.instance_type == "ml.p5.48xlarge"
    assert request.duration_hours == 48
    assert request.instance_count == 1
    assert request.segments == 1
    assert request.max_lookahead_weeks == 52


def test_request_accepts_hours_quantity_and_max_lookahead() -> None:
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_hours="12",
        instance_count="4",
        segments="2",
        max_lookahead_weeks="16",
    )

    assert request.duration_hours == 12
    assert request.instance_count == 4
    assert request.segments == 2
    assert request.max_lookahead_weeks == 16


def test_request_accepts_region_filter() -> None:
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_days=1,
        regions=["us-east-1", "us-east-2"],
    )

    assert request.regions == ("us-east-1", "us-east-2")


def test_request_accepts_comma_separated_region_filter() -> None:
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_days=1,
        regions="us-east-1, us-west-2",
    )

    assert request.regions == ("us-east-1", "us-west-2")


def test_request_accepts_start_time_after() -> None:
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_days=1,
        start_time_after="2026-07-01T00:00:00Z",
    )

    assert request.start_time_after == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_request_normalizes_start_time_after_to_utc() -> None:
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_days=1,
        start_time_after="2026-07-01T04:00:00+04:00",
    )

    assert request.start_time_after == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_request_rejects_instance_type_not_supported_by_training_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "training_plan_discovery.discovery.supported_training_plan_instance_types",
        lambda: ["ml.p5.48xlarge"],
    )

    with pytest.raises(ValidationError, match="ml.p3.2xlarge"):
        SearchRequest.from_input(instance_type="ml.p3.2xlarge", duration_days=1)


def test_request_can_skip_instance_type_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "training_plan_discovery.discovery.supported_training_plan_instance_types",
        lambda: ["ml.p5.48xlarge"],
    )

    request = SearchRequest.from_input(
        instance_type="ml.p3.2xlarge",
        duration_days=1,
        validate_instance_type=False,
    )

    assert request.instance_type == "ml.p3.2xlarge"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"instance_type": "", "duration_days": 1}, "instance_type is required"),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "duration_hours": 24},
            "provide either duration_days or duration_hours",
        ),
        ({"instance_type": "ml.p5.48xlarge"}, "duration_days or duration_hours is required"),
        ({"instance_type": "ml.p5.48xlarge", "duration_days": 0}, "duration_days must be a positive integer"),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "instance_count": 0},
            "instance_count must be a positive integer",
        ),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "segments": 0},
            "segments must be a positive integer",
        ),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "max_lookahead_weeks": 7},
            "max_lookahead_weeks must be one of",
        ),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "max_lookahead_weeks": 53},
            "max_lookahead_weeks must be no more than 52",
        ),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "regions": ["eu-west-1"]},
            "regions must be commercial US regions",
        ),
        (
            {"instance_type": "ml.p5.48xlarge", "duration_days": 1, "start_time_after": "not-a-date"},
            "start_time_after must be an ISO-8601 timestamp",
        ),
    ],
)
def test_request_validation_errors(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        SearchRequest.from_input(**kwargs)


def test_finds_latest_start_date_across_regions_in_first_window() -> None:
    responses = {
        ("us-east-1", 7): {
            "TrainingPlanOfferings": [offering("east-old", datetime(2026, 1, 5, tzinfo=timezone.utc))]
        },
        ("us-west-2", 7): {
            "TrainingPlanOfferings": [offering("west-new", datetime(2026, 1, 20, tzinfo=timezone.utc))]
        },
    }

    result = fake_discovery(responses).discover_latest(
        SearchRequest.from_input(instance_type="ml.p5.48xlarge", duration_days=1)
    )

    assert result["found"] is True
    assert result["best_offering"]["training_plan_offering_id"] == "west-new"
    assert [offering["training_plan_offering_id"] for offering in result["offerings"]] == ["west-new", "east-old"]
    assert result["best_offering"]["start_time"] == "2026-01-20T00:00:00Z"
    assert result["lookahead_used_weeks"] == 1


def test_search_uses_request_region_filter() -> None:
    calls: list[dict[str, object]] = []

    result = fake_discovery({}, regions=["us-east-1", "us-west-2"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=1,
            regions=["us-east-2"],
        )
    )

    assert result["searched_regions"] == ["us-east-2"]
    assert [call["region"] for call in calls] == ["us-east-2"]


def test_search_filters_offerings_by_maximum_segment_count() -> None:
    responses = {
        ("us-east-1", 7): {
            "TrainingPlanOfferings": [
                offering("one-segment", datetime(2026, 1, 5, tzinfo=timezone.utc), segments=1),
                offering("two-segment", datetime(2026, 1, 6, tzinfo=timezone.utc), segments=2),
            ]
        }
    }

    result = fake_discovery(responses, regions=["us-east-1"]).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            segments=2,
        )
    )

    assert result["found"] is True
    assert [item["training_plan_offering_id"] for item in result["offerings"]] == [
        "two-segment",
        "one-segment",
    ]


def test_search_default_maximum_segments_excludes_discontinuous_offerings() -> None:
    responses = {
        ("us-east-1", 7): {
            "TrainingPlanOfferings": [
                offering("one-segment", datetime(2026, 1, 5, tzinfo=timezone.utc), segments=1),
                offering("two-segment", datetime(2026, 1, 6, tzinfo=timezone.utc), segments=2),
            ]
        }
    }

    result = fake_discovery(responses, regions=["us-east-1"]).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
        )
    )

    assert result["found"] is True
    assert [item["training_plan_offering_id"] for item in result["offerings"]] == ["one-segment"]


def test_search_uses_request_start_time_after() -> None:
    calls: list[dict[str, object]] = []

    fake_discovery({}, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=1,
            start_time_after="2026-07-01T00:00:00Z",
        )
    )

    assert calls[0]["StartTimeAfter"] == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert calls[0]["EndTimeBefore"] == datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_start_date_window_adds_duration_to_end_time_before() -> None:
    calls: list[dict[str, object]] = []

    fake_discovery({}, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=14,
            max_lookahead_weeks=1,
            start_time_after="2026-07-03T09:55:00Z",
        )
    )

    assert calls[0]["StartTimeAfter"] == datetime(2026, 7, 3, 9, 55, tzinfo=timezone.utc)
    assert calls[0]["EndTimeBefore"] == datetime(2026, 7, 24, 9, 55, tzinfo=timezone.utc)


def test_start_date_window_adds_segment_gap_buffer_to_end_time_before() -> None:
    calls: list[dict[str, object]] = []

    fake_discovery({}, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_hours=120,
            segments=2,
            max_lookahead_weeks=1,
            start_time_after="2026-07-03T09:55:00Z",
        )
    )

    assert calls[0]["EndTimeBefore"] == datetime(2026, 7, 15, 10, 55, tzinfo=timezone.utc)


def test_expands_beyond_first_window_only_when_needed() -> None:
    calls: list[dict[str, object]] = []
    responses = {
        ("us-east-1", 112): {
            "TrainingPlanOfferings": [offering("later", datetime(2026, 3, 1, tzinfo=timezone.utc))]
        }
    }

    result = fake_discovery(responses, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=16,
        )
    )

    assert result["found"] is True
    assert result["lookahead_used_weeks"] == 16
    assert [call["region"] for call in calls] == [
        "us-east-1",
        "us-east-1",
        "us-east-1",
        "us-east-1",
        "us-east-1",
        "us-east-1",
    ]


def test_stops_at_configured_max_lookahead_when_no_offerings() -> None:
    calls: list[dict[str, object]] = []

    result = fake_discovery({}, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=16,
        )
    )

    assert result["found"] is False
    assert result["best_offering"] is None
    assert result["lookahead_used_weeks"] == 16
    assert len(calls) == 6


def test_denied_expansion_stops_before_next_window() -> None:
    calls: list[dict[str, object]] = []

    result = fake_discovery({}, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=16,
        ),
        approve_expansion=lambda previous, next_window: False,
    )

    assert result["found"] is False
    assert result["approval_required"] is True
    assert result["lookahead_used_weeks"] == 1
    assert result["next_lookahead_weeks"] == 2
    assert len(calls) == 1


def test_approved_expansion_searches_next_window() -> None:
    calls: list[dict[str, object]] = []
    responses = {
        ("us-east-1", 14): {
            "TrainingPlanOfferings": [offering("approved", datetime(2026, 1, 10, tzinfo=timezone.utc))]
        }
    }

    result = fake_discovery(responses, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=16,
        ),
        approve_expansion=lambda previous, next_window: next_window <= 2,
    )

    assert result["found"] is True
    assert result["approval_required"] is False
    assert result["lookahead_used_weeks"] == 2
    assert len(calls) == 2


def test_can_continue_to_approved_window_after_finding_offerings() -> None:
    calls: list[dict[str, object]] = []
    responses = {
        ("us-east-1", 7): {
            "TrainingPlanOfferings": [offering("first-window", datetime(2026, 1, 5, tzinfo=timezone.utc))]
        },
        ("us-east-1", 14): {
            "TrainingPlanOfferings": [offering("second-window", datetime(2026, 1, 10, tzinfo=timezone.utc))]
        },
    }

    result = fake_discovery(responses, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=2,
        ),
        approve_expansion=lambda previous, next_window: next_window <= 2,
        continue_until_approved_window=True,
    )

    assert result["found"] is True
    assert result["lookahead_used_weeks"] == 2
    assert result["best_offering"]["training_plan_offering_id"] == "second-window"
    assert [item["training_plan_offering_id"] for item in result["offerings"]] == ["second-window"]
    assert len(calls) == 2


def test_reports_next_window_after_finding_offerings_when_continuation_not_approved() -> None:
    calls: list[dict[str, object]] = []
    responses = {
        ("us-east-1", 7): {
            "TrainingPlanOfferings": [offering("first-window", datetime(2026, 1, 5, tzinfo=timezone.utc))]
        }
    }

    result = fake_discovery(responses, regions=["us-east-1"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=2,
        ),
        approve_expansion=lambda previous, next_window: False,
        continue_until_approved_window=True,
    )

    assert result["found"] is True
    assert result["approval_required"] is True
    assert result["next_lookahead_weeks"] == 2
    assert result["lookahead_used_weeks"] == 1
    assert len(calls) == 1


def test_preserves_non_fatal_region_errors() -> None:
    responses = {
        ("us-east-1", 7): RuntimeError("region failed"),
        ("us-west-2", 7): {
            "TrainingPlanOfferings": [offering("ok", datetime(2026, 1, 20, tzinfo=timezone.utc))]
        },
    }

    result = fake_discovery(responses).discover_latest(
        SearchRequest.from_input(instance_type="ml.p5.48xlarge", duration_days=1)
    )

    assert result["found"] is True
    assert result["errors"] == [{"region": "us-east-1", "message": "region failed"}]


def test_skips_non_retryable_region_errors_only_within_search_session() -> None:
    calls: list[dict[str, object]] = []
    error = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "Invalid instance type ml.p4d.24xlarge for target resource hyperpod-cluster.",
            }
        },
        "SearchTrainingPlanOfferings",
    )
    responses = {
        ("us-west-1", 7): error,
        ("us-west-1", 14): error,
        ("us-east-2", 7): {"TrainingPlanOfferings": []},
        ("us-east-2", 14): {"TrainingPlanOfferings": []},
    }
    discovery = fake_discovery(responses, regions=["us-west-1", "us-east-2"], calls=calls)
    request = SearchRequest.from_input(
        instance_type="ml.p5.48xlarge",
        duration_days=1,
        max_lookahead_weeks=2,
    )

    first_result = discovery.discover_latest(request)
    second_result = discovery.discover_latest(request)

    assert first_result["found"] is False
    assert first_result["errors"] == [{"region": "us-west-1", "message": str(error)}]
    assert [call["region"] for call in calls[:3]] == ["us-west-1", "us-east-2", "us-east-2"]
    assert second_result["errors"] == [{"region": "us-west-1", "message": str(error)}]
    assert [call["region"] for call in calls[3:]] == ["us-west-1", "us-east-2", "us-east-2"]


def test_retries_transient_region_errors_on_expanded_windows() -> None:
    calls: list[dict[str, object]] = []
    responses = {
        ("us-west-2", 7): RuntimeError("temporary failure"),
        ("us-west-2", 14): RuntimeError("temporary failure"),
    }

    result = fake_discovery(responses, regions=["us-west-2"], calls=calls).discover_latest(
        SearchRequest.from_input(
            instance_type="ml.p5.48xlarge",
            duration_days=1,
            max_lookahead_weeks=2,
        )
    )

    assert result["found"] is False
    assert len(calls) == 2
    assert result["errors"] == [{"region": "us-west-2", "message": "temporary failure"}]


def test_region_filter_excludes_govcloud(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def get_available_regions(self, service_name: str) -> list[str]:
            assert service_name == "sagemaker"
            return ["us-east-1", "us-gov-west-1", "eu-west-1", "us-west-2"]

    discovery = TrainingPlanDiscovery(session=FakeSession())  # type: ignore[arg-type]

    assert discovery.list_commercial_us_regions() == ["us-east-1", "us-west-2"]


def test_validate_instance_type_with_aws_accepts_success() -> None:
    calls: list[dict[str, object]] = []
    discovery = fake_discovery({"us-east-1": {}}, regions=["us-east-1"], calls=calls)

    result = discovery.validate_instance_type_with_aws(instance_type="ml.p5.48xlarge")

    assert result["valid"] is True
    assert result["region"] == "us-east-1"


def test_validate_instance_type_with_aws_rejects_validation_exception() -> None:
    error = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": "Value 'ml.p3.2xlarge' at 'instanceType' failed to satisfy constraint",
            }
        },
        "SearchTrainingPlanOfferings",
    )
    discovery = fake_discovery({("us-east-1", 7): error}, regions=["us-east-1"])

    result = discovery.validate_instance_type_with_aws(instance_type="ml.p3.2xlarge")

    assert result["valid"] is False
    assert "ml.p3.2xlarge" in result["message"]


def test_validate_instance_type_with_aws_reports_inconclusive_for_other_errors() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "SearchTrainingPlanOfferings",
    )
    discovery = fake_discovery({("us-east-1", 7): error}, regions=["us-east-1"])

    result = discovery.validate_instance_type_with_aws(instance_type="ml.p5.48xlarge")

    assert result["valid"] is None
    assert "inconclusive" in result["message"]
