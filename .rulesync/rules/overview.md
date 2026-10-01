---
root: true
targets: ["*"]
description: "Project overview and working rules for AI agents"
globs: ["**/*"]
---

# aws-training-plan

## Purpose
- Local CLI and FastAPI web UI that finds SageMaker HyperPod training plan offerings across commercial US regions (`us-*`, no GovCloud).
- Calls only `sagemaker:SearchTrainingPlanOfferings` with the user's local AWS credentials. It never creates or buys a plan, deploys nothing, and is local-only (`127.0.0.1`).

## Structure
- `src/training_plan_discovery/discovery.py`: shared search logic. This covers input validation, region selection, start-date window expansion (1, 2, 3, 4, 8, 16, 32 and 52 weeks), segment filtering and per-region error capture.
- `src/training_plan_discovery/cli.py`: the `training-plan-discovery` CLI (human-readable and `--json` output).
- `src/training_plan_discovery/web_app.py`: the FastAPI backend (`training-plan-discovery-web`), which also serves `static/`.
- `src/training_plan_discovery/static/`: the browser UI (`index.html`, `app.js`, `styles.css`), bundled as package data.
- `tests/`: pytest suites for discovery, entry points and the web app. They use fake clients and never call AWS.
- `docs/architecture.md`: Mermaid diagrams of the request flow and the security boundary.

## Commands (PowerShell)
- Setup: `python -m pip install -e .[dev]` (Python >= 3.10)
- Test: `python -m pytest`
- Web UI: `python -m training_plan_discovery.web_app`, then open http://127.0.0.1:8000
- CLI: `training-plan-discovery --instance-type ml.p5.48xlarge --duration-days 7`
- AWS credentials: the standard provider chain with the `default` profile (see AWS safety)

## AWS safety
- **Read-only.** The only AWS call is SageMaker `SearchTrainingPlanOfferings` (CLI, web UI and live instance-type validation). Under the global AWS safety policy, running searches with the `default` profile is allowed.
- **Repo-specific rule:** keep it read-only. Never add calls that create, purchase, modify or delete anything (for example `create_training_plan`). Never add deployment code (SAM, CloudFormation, CDK) to this repo; the Lambda/SAM variant lives in `aws-training-plan-discovery`.

## Conventions and constraints
- Keep credentials out of the browser. Web responses stay sanitized: no raw offering payload, and key, token, password and secret patterns are redacted. Render values with escaping or `textContent`. Static serving is limited to the bundled files.
- Tests must not call AWS. Use fake clients like the existing ones, and add tests for new behavior.
- Per-region API failures are non-fatal. Report them as warnings and keep searching the other regions.
- Instance types are validated against the installed botocore `ReservedCapacityInstanceType` enum, not against scraped lists.
- Update `README.md` when CLI flags, inputs or behavior change.

## Agent config
- Agent instructions are generated. Edit `.rulesync/` (not `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/` or `.agents/`), run `rulesync generate`, and commit both.
