# AWS Training Plan Discovery

Local CLI and FastAPI web UI for finding SageMaker HyperPod training plan offerings across commercial US regions.

The tool calls the SageMaker `SearchTrainingPlanOfferings` API using your local AWS credentials. It does not deploy AWS infrastructure, expose a public endpoint, or send AWS credentials to the browser.

## What It Does

- Searches SageMaker HyperPod training plan offerings with `TargetResources=["hyperpod-cluster"]`
- Supports instance type, duration, instance count, maximum segments, region filtering, and start-time filtering
- Searches commercial `us-*` AWS regions by default, excluding GovCloud
- Expands start date windows through `1`, `2`, `3`, `4`, `8`, `16`, `32`, and `52` weeks
- Shows all matching offerings from the selected start date window
- Provides a local web UI with sorting, filtering, grouped multi-segment offerings, and JSON export
- Provides a CLI for terminal usage and automation

## Requirements

- Python 3.10 or newer
- AWS credentials configured locally
- IAM permission for `sagemaker:SearchTrainingPlanOfferings`

Install the project:

```powershell
python -m pip install -e .[dev]
```

For runtime-only installation:

```powershell
python -m pip install -e .
```

## AWS Credentials

Use the standard AWS credential provider chain. For example:

```powershell
aws configure
```

Or use a named AWS profile:

```powershell
$env:AWS_PROFILE = "your-admin-profile"
```

Minimum IAM policy shape:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sagemaker:SearchTrainingPlanOfferings",
      "Resource": "*"
    }
  ]
}
```

## Local Web UI

Start the local web app:

```powershell
python -m training_plan_discovery.web_app
```

Open:

```text
http://127.0.0.1:8000
```

Admin quickstart from a fresh clone:

```powershell
git clone https://github.com/aasim-m/aws-training-plan.git
cd aws-training-plan
python -m pip install -e .[dev]
aws configure
python -m training_plan_discovery.web_app
```

The web UI supports:

- Required-field markers
- Instance type suggestions from the installed SDK model
- Duration in days or hours
- Instance count
- Maximum Segments filtering with a warning for discontinuous multi-segment offerings
- Region filtering
- Optional start time
- Start date window selection
- Timezone display, defaulting to GST
- Elapsed-time search status while AWS calls are running
- Sortable and filterable offerings table
- Collapsible grouped multi-segment offerings
- Copy actions for offering IDs, offering JSON, and the equivalent CLI command
- Clear results, reset form, and JSON export actions
- Region warning summary
- Live AWS instance type validation

## Web UI Data Safety

The browser talks only to the local FastAPI backend on `127.0.0.1`.

- AWS credentials stay in the local backend process and are never sent to the browser.
- The browser never receives local credential files, environment variables, or SDK sessions.
- The duplicated raw AWS offering payload is removed from web search responses.
- Region warning and validation messages are redacted for common key, token, password, and secret patterns.
- UI-rendered response values are escaped or assigned with `textContent`.
- Static asset serving is limited to the bundled HTML, CSS, and JavaScript files.

## CLI Usage

Run with duration in days:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7
```

Run with duration in hours:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-hours 168
```

Specify instance count:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7 --instance-count 4
```

Allow up to two reserved-capacity segments:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7 --maximum-segments 2
```

Filter regions:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7 --regions us-east-1 us-east-2
```

Search from a specific start time:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7 --start-time-after 2026-07-01T00:00:00Z
```

Approve all start date window expansions up to a maximum:

```powershell
training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7 --max-lookahead-weeks 16 --yes
```

Output JSON:

```powershell
python -m training_plan_discovery.cli --instance-type ml.p5.48xlarge --duration-days 7 --json --pretty
```

List training-plan-supported instance types from the installed SDK model:

```powershell
training-plan-discovery --list-supported-instance-types
```

Validate one instance type against the live AWS API:

```powershell
python -m training_plan_discovery.cli --instance-type ml.p5.48xlarge --validate-instance-type-with-aws --validation-region us-west-2
```

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `instance_type` | Yes | None | SageMaker reserved-capacity instance type, for example `ml.p5.48xlarge`. |
| `duration_days` | Yes, unless `duration_hours` is provided | None | Requested duration in days. |
| `duration_hours` | Yes, unless `duration_days` is provided | None | Requested duration in hours. |
| `instance_count` | No | `1` | Number of instances to reserve. |
| `maximum_segments` | No | `1` | Maximum number of reserved-capacity segments per offering. Values above `1` allow discontinuous segments. |
| `regions` | No | Commercial US SageMaker regions | Optional region filter. |
| `start_time_after` | No | Current UTC time | ISO-8601 timestamp to start searching from. |
| `max_lookahead_weeks` | No | `52` in the shared backend, `1` in the CLI and web UI | Maximum start date lookahead cap. Must be one of `1`, `2`, `3`, `4`, `8`, `16`, `32`, or `52`. |

Provide either `duration_days` or `duration_hours`, not both.

## Instance Type Validation

The tool validates `instance_type` locally by default. It reads the `ReservedCapacityInstanceType` enum from the installed `botocore` SageMaker service model.

This is different from scraping a general SageMaker instance type page. A value can be valid for notebook instances or training jobs and still be invalid for training plan offerings.

To update the local supported list, update `boto3` and `botocore`:

```powershell
python -m pip install --upgrade boto3 botocore
```

If the installed SDK model is stale, use one of these options:

- Upgrade `boto3` and `botocore`.
- Use `--skip-instance-type-validation` to let AWS validate during the real search.
- Use `--validate-instance-type-with-aws` to make one live AWS validation call for a single instance type.

Being listed by the SDK enum means the API accepts the value. It does not guarantee current availability in any region, quantity, duration, or start date window.

## Start Date Window Behavior

The start date window controls how far after `start_time_after` the offering is allowed to start. It does not require the full training plan to end inside that window.

For example:

```text
start_time_after = 2026-07-03T09:55:00Z
duration_days = 14
start date window = 1 week
```

The tool searches for 14-day offerings whose start date is within the first week after `start_time_after`. It still allows those offerings to end after that first week.

## Region Behavior

The tool searches commercial AWS regions whose names start with `us-`, excluding GovCloud regions such as `us-gov-west-1`.

Region-specific API failures are non-fatal. They are captured in the warnings/errors output while the search continues in other regions.

During one search session, clear non-retryable region validation errors are not retried on expanded start date windows. For example, if `us-west-1` reports that the requested instance type is invalid for `hyperpod-cluster`, later windows in the same search skip `us-west-1`. The next independent search starts fresh and checks the region again.

## Architecture

See [docs/architecture.md](docs/architecture.md) for local-only Mermaid diagrams covering the web app, CLI, request flow, and security boundary.

## Testing

Run all tests:

```powershell
python -m pytest
```

The tests use fake clients and do not call AWS.

Covered scenarios include:

- Input validation
- Unsupported training plan instance type handling
- Supported instance type listing
- Local instance type validation bypass
- Live AWS instance type validation command
- Region filtering
- Maximum Segments filtering
- Optional `start_time_after`
- Latest start date selection across regions
- Returning all offerings from the successful start date window
- Start date window expansion
- No-offering responses
- Non-fatal per-region errors
- CLI human-readable and JSON output
- Local web API endpoints and static UI serving
- Web response sanitization

## Current Limits

- The tool targets HyperPod training plans only.
- It does not create or purchase a training plan.
- The web UI is local-only and is intended to run on `127.0.0.1`.
