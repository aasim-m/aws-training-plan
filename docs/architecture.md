# Architecture

This project is a local-only admin tool. It provides a local FastAPI web UI and a CLI that both use the same shared discovery logic.

No AWS infrastructure is deployed by this repository. There is no public endpoint, hosted website, or cloud-hosted backend.

## Local Web App

```mermaid
flowchart LR
    Browser[Admin Browser] -->|HTTP on 127.0.0.1| FastAPI[Local FastAPI Web App]
    FastAPI --> Static[Static UI Assets<br/>HTML CSS JS]
    FastAPI --> Discovery[Shared Discovery Logic]
    Discovery --> Botocore[Local botocore<br/>SageMaker Service Model]
    Discovery -->|boto3 API calls| SageMaker[SageMaker<br/>SearchTrainingPlanOfferings]
    FastAPI --> Sanitizer[Response Sanitization<br/>strip raw payloads<br/>redact token-like messages]
    Sanitizer --> Browser

    subgraph LocalMachine[Admin Machine]
        Browser
        FastAPI
        Static
        Discovery
        Botocore
        Sanitizer
        Credentials[AWS Credential Chain]
    end

    Credentials --> Discovery
```

## CLI Flow

```mermaid
flowchart LR
    Terminal[Admin Terminal] --> CLI[CLI Entrypoint]
    CLI --> Discovery[Shared Discovery Logic]
    Discovery --> Credentials[AWS Credential Chain]
    Discovery --> Botocore[Local botocore<br/>SageMaker Service Model]
    Discovery -->|boto3 API calls| SageMaker[SageMaker<br/>SearchTrainingPlanOfferings]
    Discovery --> Formatter[Human Table or JSON Formatter]
    Formatter --> Terminal
```

## Request Flow

```mermaid
sequenceDiagram
    participant User as Admin
    participant Web as Local FastAPI / CLI
    participant Core as Shared Discovery Logic
    participant SDK as boto3 / botocore
    participant SM as SageMaker

    User->>Web: Submit search inputs
    Web->>Core: Build SearchRequest
    Core->>SDK: Validate instance type against SDK enum
    Core->>SM: SearchTrainingPlanOfferings by region and start date window
    SM-->>Core: Offerings or region errors
    Core-->>Web: Result with offerings, warnings, and next start date window
    Web-->>User: Table, JSON, or web response
```

## Start Date Window Flow

```mermaid
stateDiagram-v2
    [*] --> OneWeek: first start date window
    OneWeek --> Found: offerings returned
    OneWeek --> ApprovalNeeded: no offerings and next start date window is available
    ApprovalNeeded --> ExpandedSearch: admin approves larger start date window
    ExpandedSearch --> Found: offerings returned
    ExpandedSearch --> ApprovalNeededAgain: admin can keep expanding
    ApprovalNeededAgain --> ExpandedSearch
    ExpandedSearch --> Exhausted: no offerings through max start date window
    Found --> [*]
    Exhausted --> [*]
```

## Security Boundary

```mermaid
flowchart TB
    Browser[Local Browser] -->|search inputs only| Backend[Local Backend]
    Backend -->|local AWS credential chain| SageMaker[AWS SageMaker]
    Backend -->|sanitized results| Browser

    Credentials[AWS credentials<br/>profile, env vars, credential files] --> Backend
    Credentials -. not sent .-> Browser
    Raw[Duplicated raw AWS response payload] -. stripped before web response .-> Browser
    Secrets[Token-like warning text] -. redacted before web response .-> Browser

    PublicInternet[Public internet] -. no listener .-> Backend
    HostedEndpoint[Hosted AWS endpoint] -. not created .-> Backend
```

## Operational Notes

- The local web app listens on `127.0.0.1`.
- Each admin uses their own local AWS identity and IAM permissions.
- The required AWS permission is `sagemaker:SearchTrainingPlanOfferings`.
- The frontend treats `offerings` as the primary table data and `best_offering` as the latest-start recommendation.
- `maximum_segments` defaults to `1`; higher values allow discontinuous multi-segment offerings.
