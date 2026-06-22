# Architecture

## Current scope

This repository currently verifies that the MDB STS API is reachable and that
its model-discovery response matches the supplied OpenAPI contract.

```text
CLI
  -> STSClient
      -> GET /v2/models/
          -> validated list[Model]
              -> formatted JSON output
```

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `mdb_sync.cli` | Read configuration and expose the initial manual test command |
| `mdb_sync.client` | Own HTTP behavior, pagination, timeouts, and error translation |
| `mdb_sync.models` | Validate external STS response data |

## Key decisions

- The base URL is runtime configuration because it is absent from the supplied
  API artifacts.
- The client starts with model discovery, which is step 1 of `plan.md`.
- HTTP and validation details stay outside the CLI so later Lambda, Fargate, or
  scheduled-job entry points can reuse the same client.
- Unknown response fields are retained by the Pydantic model, allowing additive
  server changes without immediately breaking the probe.

## Next planned extension

After connectivity is confirmed, add methods for model versions, nodes,
properties, and terms. Transformation and database ingestion should follow only
after property-key uniqueness and the authoritative permissible-value endpoint
are confirmed.

## Infrastructure

No AWS infrastructure is included in this first slice. The plan explicitly
leaves Lambda versus ECS/Fargate open, and an API connectivity probe does not
need deployed infrastructure.

