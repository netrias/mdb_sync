# ADR 001: Start with a Configurable STS Client

## Status

Accepted

## Context

The synchronization plan begins by listing MDB models through
`GET /v2/models/`. The supplied OpenAPI document and Swagger PDF do not identify
a deployed base URL or authentication mechanism. The eventual execution
platform is also undecided between Lambda and ECS/Fargate.

## Decision

Implement a small reusable Python client and local CLI for model discovery.
Supply the STS base URL through `MDB_API_BASE_URL` or a command-line option.
Defer AWS infrastructure and database writes until connectivity and deployment
requirements are known.

## Consequences

The project can test the source API as soon as a URL is available. The client
can be reused by later synchronization workflows. This slice does not yet
perform a complete model snapshot sync or deploy to AWS.

