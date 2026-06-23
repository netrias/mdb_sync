# Architecture

## Current scope

This repository captures the protected STS v2 API into an offline development
dataset. It does not yet transform or write data to the Data Model Store.

```text
CLI
  -> STSCrawler
      -> RecordingSTSClient
          -> STSClient (/v2 only)
          -> CaptureWriter
              -> requests.jsonl
              -> exact response bodies
              -> inventory.json
              -> manifest.json
              -> ZIP archive
```

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `mdb_sync.cli` | Configuration, progress output, and colleague-facing commands |
| `mdb_sync.client` | HTTP session and strict `/v2/` path boundary |
| `mdb_sync.capture` | Retries, durable response recording, sanitization, manifest, and archive |
| `mdb_sync.crawler` | Discover parameters and traverse dependent STS resources |
| `mdb_sync.models` | Validate the small interactive model-list command |

## Traversal flow

```text
models
  -> versions
      -> nodes
          -> properties
              -> terms
              -> model PVs
                  -> CDE IDs/versions
                      -> CDE PVs

tags
  -> values
      -> tagged entities

all discovered nanoids
  -> entity-by-id
```

Counts and individual detail endpoints are called alongside list endpoints.
Endpoint parameters that cannot be inferred from returned data are recorded as
skipped rather than fabricated.

## Capture design

Responses are stored as exact bytes rather than only transformed JSON. This
preserves undocumented fields, null behavior, errors, content types, and other
details needed to build realistic fixtures later.

The JSON Lines request log maps each body to request metadata and supports
streaming analysis even when a capture is large. The inventory provides a
smaller navigation index without replacing raw responses.

Sensitive headers are removed. Response hashes allow archive integrity and
duplicate-response analysis.

## Operational decisions

- Requests are sequential by default because this is an exploratory sweep of a
  protected upstream service.
- Every path is checked in the client and must start with `/v2/`.
- Pagination defaults to 100 records per request.
- Retryable failures use bounded exponential backoff.
- Non-success HTTP responses are captured and traversal continues where
  possible.
- Python 3.12 is pinned to align with the intended AWS runtime and repository
  standards.

## Deferred work

The offline captures will inform:

- authoritative permissible-value endpoint selection;
- property-key uniqueness rules;
- response models for all entity types;
- snapshot transformation and validation;
- database ingestion and idempotency;
- Lambda versus ECS/Fargate deployment;
- checkpointing and incremental synchronization.

