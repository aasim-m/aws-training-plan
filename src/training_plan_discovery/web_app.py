from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from .discovery import SearchRequest, TrainingPlanDiscovery, ValidationError, supported_training_plan_instance_types


STATIC_DIR = Path(__file__).with_name("static")
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(aws_secret_access_key|aws_access_key_id|token|password|secret)\s*=\s*[^,\s;]+"),
]


class SearchPayload(BaseModel):
    instance_type: str
    duration_days: int | None = None
    duration_hours: int | None = None
    instance_count: int | None = None
    segments: int | None = None
    maximum_segments: int | None = None
    max_lookahead_weeks: int | None = None
    regions: list[str] | str | None = None
    start_time_after: str | None = None
    approved_lookahead_weeks: int | None = None
    skip_instance_type_validation: bool = False


class AwsValidationPayload(BaseModel):
    instance_type: str
    duration_hours: int = 24
    instance_count: int = 1
    region: str = "us-east-1"


def create_app() -> FastAPI:
    app = FastAPI(title="AWS Training Plan Discovery")
    app.state.discovery_factory = TrainingPlanDiscovery

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _static_text("index.html")

    @app.get("/static/{asset_name}")
    def static_asset(asset_name: str) -> Response:
        if asset_name not in {"styles.css", "app.js"}:
            return Response(status_code=404)
        media_type = "text/css" if asset_name.endswith(".css") else "application/javascript"
        return Response(_static_text(asset_name), media_type=media_type)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/supported-instance-types")
    def supported_instance_types() -> dict[str, list[str]]:
        return {"supported_instance_types": supported_training_plan_instance_types()}

    @app.post("/api/search")
    def search(payload: SearchPayload) -> JSONResponse:
        try:
            request = SearchRequest.from_input(
                instance_type=payload.instance_type,
                duration_days=payload.duration_days,
                duration_hours=payload.duration_hours,
                instance_count=payload.instance_count,
                segments=payload.maximum_segments
                if payload.maximum_segments is not None
                else payload.segments,
                max_lookahead_weeks=payload.max_lookahead_weeks,
                regions=payload.regions,
                start_time_after=payload.start_time_after,
                validate_instance_type=not payload.skip_instance_type_validation,
            )
            discovery = app.state.discovery_factory()
            result = discovery.discover_latest(
                request,
                approve_expansion=_approval_callback(payload.approved_lookahead_weeks),
                continue_until_approved_window=True,
            )
            return JSONResponse(_public_result(result))
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/validate-instance-type")
    def validate_instance_type(payload: AwsValidationPayload) -> dict[str, Any]:
        discovery = app.state.discovery_factory()
        result = discovery.validate_instance_type_with_aws(
            instance_type=payload.instance_type,
            duration_hours=payload.duration_hours,
            instance_count=payload.instance_count,
            region=payload.region,
        )
        if "message" in result:
            result["message"] = _redact_sensitive_text(str(result["message"]))
        return result

    return app


def _approval_callback(approved_lookahead_weeks: int | None):
    approved = 1 if approved_lookahead_weeks is None else approved_lookahead_weeks

    def approve(previous_lookahead_weeks: int, next_lookahead_weeks: int) -> bool:
        del previous_lookahead_weeks
        return next_lookahead_weeks <= approved

    return approve


def _static_text(asset_name: str) -> str:
    return (STATIC_DIR / asset_name).read_text(encoding="utf-8")


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    public = dict(result)
    if public.get("best_offering") is not None:
        public["best_offering"] = _public_offering(public["best_offering"])
    public["offerings"] = [_public_offering(offering) for offering in public.get("offerings", [])]
    public["errors"] = [
        {
            "region": error.get("region", "unknown"),
            "message": _redact_sensitive_text(str(error.get("message", ""))),
        }
        for error in public.get("errors", [])
    ]
    return public


def _public_offering(offering: dict[str, Any]) -> dict[str, Any]:
    public = dict(offering)
    public.pop("raw", None)
    return public


def _redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def main() -> None:
    uvicorn.run("training_plan_discovery.web_app:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)


app = create_app()


if __name__ == "__main__":
    main()
