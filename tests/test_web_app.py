from __future__ import annotations

from fastapi.testclient import TestClient

from training_plan_discovery.web_app import create_app


class FakeDiscovery:
    def discover_latest(self, request, approve_expansion=None, continue_until_approved_window=False):
        if approve_expansion is not None:
            approve_expansion(1, 2)
        assert continue_until_approved_window is True
        return {
            "found": True,
            "best_offering": {"training_plan_offering_id": "offering-1"},
            "offerings": [
                {
                    "region": "us-east-1",
                    "training_plan_offering_id": "offering-1",
                    "raw": {"debug": "not needed by UI"},
                    "duration_hours": 24,
                    "upfront_fee": "100.00",
                    "currency_code": "USD",
                    "reserved_capacity_offerings": [
                        {
                            "AvailabilityZone": "us-east-1a",
                            "InstanceType": "ml.p5.48xlarge",
                            "InstanceCount": 1,
                            "StartTime": "2026-07-01T00:00:00Z",
                            "EndTime": "2026-07-02T00:00:00Z",
                            "DurationHours": 24,
                        }
                    ],
                }
            ],
            "searched_regions": ["us-east-1"],
            "lookahead_used_weeks": 1,
            "max_lookahead_weeks": 52,
            "approval_required": False,
            "next_lookahead_weeks": None,
            "errors": [
                {
                    "region": "us-east-1",
                    "message": "token=dummy-redaction-value",
                }
            ],
        }

    def validate_instance_type_with_aws(self, **kwargs):
        return {
            "valid": True,
            "source": "aws",
            "message": "ok token=dummy-redaction-value",
            **kwargs,
        }


def client() -> TestClient:
    app = create_app()
    app.state.discovery_factory = lambda: FakeDiscovery()
    return TestClient(app)


def test_index_serves_ui() -> None:
    response = client().get("/")

    assert response.status_code == 200
    assert "Training Plan Discovery" in response.text


def test_static_asset_served() -> None:
    response = client().get("/static/app.js")

    assert response.status_code == 200
    assert "runSearch" in response.text
    assert "updateSegmentsWarning" in response.text
    assert "segment-badge" in response.text
    assert "sortOfferings" in response.text
    assert "filterOfferings" in response.text
    assert "clearResults" in response.text
    assert "localDateTimeToIso" in response.text
    assert "updateSegmentFilterOptions" in response.text
    assert "MAX_LOOKAHEAD_WEEKS" in response.text
    assert "alert(" not in response.text


def test_index_has_segments_input() -> None:
    response = client().get("/")

    assert response.status_code == 200
    assert "Maximum Segments" in response.text
    assert "Initial window" in response.text
    assert 'data-sort-key="segments"' in response.text
    assert 'id="maximumSegments"' in response.text
    assert 'id="segmentsWarning"' in response.text
    assert 'id="timeZone"' in response.text
    assert 'id="tableSearch"' in response.text
    assert 'id="regionFilter"' in response.text
    assert 'id="azFilter"' in response.text
    assert 'id="segmentFilter"' in response.text
    assert 'id="clearResultsButton"' in response.text
    assert "GST - Gulf Standard Time" in response.text
    assert "Let AWS validate instance type during search" in response.text
    assert "Discontinuous segments" in response.text


def test_search_endpoint_returns_offerings() -> None:
    response = client().post(
        "/api/search",
        json={
            "instance_type": "ml.p5.48xlarge",
            "duration_days": 1,
            "segments": 1,
            "regions": ["us-east-1"],
            "skip_instance_type_validation": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["offerings"][0]["training_plan_offering_id"] == "offering-1"
    assert "raw" not in body["offerings"][0]
    assert "[REDACTED]" in body["errors"][0]["message"]


def test_search_endpoint_accepts_maximum_segments(monkeypatch) -> None:
    captured = {}
    app = create_app()

    def fake_from_input(**kwargs):
        captured.update(kwargs)
        return object()

    import training_plan_discovery.web_app as web_app

    monkeypatch.setattr(web_app.SearchRequest, "from_input", fake_from_input)
    app.state.discovery_factory = lambda: FakeDiscovery()
    response = TestClient(app).post(
        "/api/search",
        json={
            "instance_type": "ml.p5.48xlarge",
            "duration_days": 1,
            "maximum_segments": 2,
            "skip_instance_type_validation": True,
        },
    )

    assert response.status_code == 200
    assert captured["segments"] == 2


def test_search_endpoint_returns_validation_error() -> None:
    response = client().post(
        "/api/search",
        json={
            "instance_type": "ml.p5.48xlarge",
            "duration_days": 1,
            "regions": ["eu-west-1"],
            "skip_instance_type_validation": True,
        },
    )

    assert response.status_code == 400
    assert "regions must be commercial US regions" in response.json()["error"]


def test_validate_instance_type_endpoint() -> None:
    response = client().post(
        "/api/validate-instance-type",
        json={"instance_type": "ml.p5.48xlarge", "region": "us-west-2"},
    )

    assert response.status_code == 200
    assert response.json()["region"] == "us-west-2"
    assert "[REDACTED]" in response.json()["message"]
