from __future__ import annotations

import json

from training_plan_discovery import cli


class FakeDiscovery:
    def discover_latest(self, request: object, approve_expansion=None) -> dict[str, object]:
        if approve_expansion is not None:
            approve_expansion(1, 2)
        return {
            "found": True,
            "best_offering": {
                "region": "us-east-1",
                "training_plan_offering_id": "offering-1",
                "start_time": "2026-01-01T00:00:00Z",
                "end_time": None,
                "duration_hours": 24,
                "upfront_fee": "100.00",
                "currency_code": "USD",
                "raw": {"debug": "not needed in CLI response"},
                "reserved_capacity_offerings": [
                    {
                        "AvailabilityZone": "us-east-1a",
                        "InstanceType": "ml.p5.48xlarge",
                        "InstanceCount": 1,
                        "StartTime": "2026-01-01T01:00:00Z",
                        "EndTime": "2026-01-02T01:00:00Z",
                        "DurationHours": 24,
                    }
                ],
            },
            "offerings": [
                {
                    "region": "us-east-2",
                    "training_plan_offering_id": "offering-2",
                    "start_time": "2026-01-03T00:00:00Z",
                    "end_time": None,
                    "duration_hours": 24,
                    "upfront_fee": "120.00",
                    "currency_code": "USD",
                    "raw": {"debug": "not needed in CLI response"},
                    "reserved_capacity_offerings": [
                        {
                            "AvailabilityZone": "us-east-2a",
                            "InstanceType": "ml.p5.48xlarge",
                            "InstanceCount": 1,
                            "StartTime": "2026-01-03T01:00:00Z",
                            "EndTime": "2026-01-04T01:00:00Z",
                            "DurationHours": 24,
                        }
                    ],
                },
                {
                    "region": "us-east-1",
                    "training_plan_offering_id": "offering-1",
                    "start_time": "2026-01-01T00:00:00Z",
                    "end_time": None,
                    "duration_hours": 24,
                    "upfront_fee": "100.00",
                    "currency_code": "USD",
                    "raw": {"debug": "not needed in CLI response"},
                    "reserved_capacity_offerings": [
                        {
                            "AvailabilityZone": "us-east-1a",
                            "InstanceType": "ml.p5.48xlarge",
                            "InstanceCount": 1,
                            "StartTime": "2026-01-01T01:00:00Z",
                            "EndTime": "2026-01-02T01:00:00Z",
                            "DurationHours": 24,
                        }
                    ],
                },
            ],
            "searched_regions": ["us-east-1", "us-west-1"],
            "lookahead_used_weeks": 1,
            "max_lookahead_weeks": 52,
            "approval_required": False,
            "next_lookahead_weeks": None,
            "errors": [
                {
                    "region": "us-west-1",
                    "message": "An error occurred (ValidationException) when calling the SearchTrainingPlanOfferings operation: Invalid instance type ml.p5.48xlarge for target resource hyperpod-cluster.",
                }
            ],
        }

    def validate_instance_type_with_aws(
        self,
        *,
        instance_type: str,
        duration_hours: int = 24,
        instance_count: int = 1,
        region: str = "us-east-1",
    ) -> dict[str, object]:
        return {
            "instance_type": instance_type,
            "duration_hours": duration_hours,
            "instance_count": instance_count,
            "region": region,
            "valid": instance_type != "ml.bad",
            "source": "aws",
            "message": "ok",
        }


def test_cli_outputs_human_table_by_default(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())

    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(["--instance-type", "ml.p5.48xlarge", "--duration-days", "1"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Found 2 training plan offerings with start dates within 1 week(s)." in output
    assert "Region" in output
    assert "AZ" in output
    assert "offering-1" in output
    assert "offering-2" in output
    assert "Region warnings:" in output
    assert "us-west-1: Invalid instance type ml.p5.48xlarge" in output


def test_cli_outputs_json_when_requested(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(["--instance-type", "ml.p5.48xlarge", "--duration-days", "1", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["found"] is True
    assert len(output["offerings"]) == 2
    assert output["best_offering"]["training_plan_offering_id"] == "offering-1"


def test_format_search_result_shows_next_approval_for_no_result() -> None:
    output = cli._format_search_result(
        {
            "found": False,
            "best_offering": None,
            "searched_regions": ["us-east-1"],
            "lookahead_used_weeks": 1,
            "max_lookahead_weeks": 52,
            "approval_required": True,
            "next_lookahead_weeks": 2,
            "errors": [],
        }
    )

    assert "No training plan offering found with start dates within 1 week(s)." in output
    assert "Next approval needed: search start dates within 2 week(s)." in output


def test_cli_lists_supported_instance_types(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "supported_training_plan_instance_types", lambda: ["ml.p5.48xlarge", "ml.trn2.48xlarge"])

    exit_code = cli.main(["--list-supported-instance-types"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"supported_instance_types": ["ml.p5.48xlarge", "ml.trn2.48xlarge"]}


def test_cli_validates_instance_type_with_aws(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())

    exit_code = cli.main(
        [
            "--instance-type",
            "ml.p5.48xlarge",
            "--validate-instance-type-with-aws",
            "--validation-region",
            "us-west-2",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["region"] == "us-west-2"


def test_cli_validate_instance_type_with_aws_returns_two_when_invalid(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())

    exit_code = cli.main(["--instance-type", "ml.bad", "--validate-instance-type-with-aws"])

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is False


def test_cli_skip_instance_type_validation(monkeypatch, capsys) -> None:
    import training_plan_discovery.discovery as discovery_module

    monkeypatch.setattr(discovery_module, "supported_training_plan_instance_types", lambda: ["ml.p5.48xlarge"])
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(
        [
            "--instance-type",
            "ml.p3.2xlarge",
            "--duration-days",
            "1",
            "--skip-instance-type-validation",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Found 2 training plan offerings" in output


def test_cli_accepts_region_filter(monkeypatch, capsys) -> None:
    captured = {}

    def fake_from_input(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli.SearchRequest, "from_input", fake_from_input)
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(
        [
            "--instance-type",
            "ml.p5.48xlarge",
            "--duration-days",
            "1",
            "--regions",
            "us-east-1",
            "us-east-2",
        ]
    )

    assert exit_code == 0
    assert captured["regions"] == ["us-east-1", "us-east-2"]
    assert "Found 2 training plan offerings" in capsys.readouterr().out


def test_cli_accepts_maximum_segments(monkeypatch, capsys) -> None:
    captured = {}

    def fake_from_input(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli.SearchRequest, "from_input", fake_from_input)
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(
        [
            "--instance-type",
            "ml.p5.48xlarge",
            "--duration-days",
            "1",
            "--maximum-segments",
            "2",
        ]
    )

    assert exit_code == 0
    assert captured["segments"] == 2
    assert "Found 2 training plan offerings" in capsys.readouterr().out


def test_cli_accepts_start_time_after(monkeypatch, capsys) -> None:
    captured = {}

    def fake_from_input(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cli.SearchRequest, "from_input", fake_from_input)
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    exit_code = cli.main(
        [
            "--instance-type",
            "ml.p5.48xlarge",
            "--duration-days",
            "1",
            "--start-time-after",
            "2026-07-01T00:00:00Z",
        ]
    )

    assert exit_code == 0
    assert captured["start_time_after"] == "2026-07-01T00:00:00Z"
    assert "Found 2 training plan offerings" in capsys.readouterr().out


def test_cli_yes_approves_expansion(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "TrainingPlanDiscovery", lambda: FakeDiscovery())
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(AssertionError("unexpected prompt")))

    exit_code = cli.main(["--instance-type", "ml.p5.48xlarge", "--duration-days", "1", "--yes"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Found 2 training plan offerings" in output


def test_cli_validation_error(capsys) -> None:
    exit_code = cli.main(["--instance-type", "ml.p5.48xlarge", "--duration-days", "0"])

    assert exit_code == 2
    error = json.loads(capsys.readouterr().err)
    assert "duration_days must be a positive integer" in error["error"]
