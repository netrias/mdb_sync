# MDB Sync

Initial Python client for testing access to the MDB Simple Terminology Server
(STS). This first slice calls `GET /v2/models/`, validates the response, and
prints the available models as JSON.

The STS base URL is not present in `openapi.json` or the supplied Swagger PDF,
so it is configuration rather than source code.

## Prerequisites

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/) (optional convenience runner)

## Quick start

```bash
uv sync --all-extras
cp .env.example .env
```

Replace the example URL in `.env`, then run:

```bash
uv run mdb-sync models
```

Without an `.env` file:

```bash
uv run mdb-sync --base-url https://actual-sts-host.example models
```

Pagination parameters can be passed directly:

```bash
uv run mdb-sync models --skip 0 --limit 10
```

If `just` is installed, the equivalent command is:

```bash
just fetch-models --limit 10
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `MDB_API_BASE_URL` | Yes, unless `--base-url` is used | STS scheme and host, without an endpoint path |

The supplied OpenAPI specification defines no authentication scheme. If the
deployed service requires authentication, add it to `STSClient` after the MDB
team provides the contract.

## Development

```bash
uv sync --all-extras
just check
```

Individual checks:

```bash
uv run ruff check src tests
uv run basedpyright src tests
uv run pytest tests -v
```

## Project layout

```text
src/mdb_sync/client.py   Typed STS HTTP client
src/mdb_sync/models.py   Response models derived from openapi.json
src/mdb_sync/cli.py      Local API probe
tests/                   Unit tests using an in-memory HTTP transport
adr/                     Architecture decisions
```

AWS deployment and database ingestion are intentionally deferred. The plan
does not yet establish the execution platform, database interface, credentials,
or source API authentication, and none are required to verify STS connectivity.

