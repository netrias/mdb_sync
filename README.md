# MDB STS Capture

Python tooling for capturing the MDB Simple Terminology Server (STS) API for
offline synchronization development. The capture command performs a
data-driven traversal of the STS and writes every attempted request and exact
response body into a portable ZIP archive.

The configured server is:

```text
https://sts.cancer.gov
```

The client enforces `/v2/` paths and never calls the unversioned root endpoint.

## Someone with firewall access has to run the following

Prerequisites:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Network access to `https://sts.cancer.gov`

From the repository root:

```bash
uv sync --all-extras --no-editable
uv run --no-editable mdb-sync capture
```

The `--no-editable` option is required on both commands. It avoids a Homebrew
Python issue where hidden editable-install `.pth` files are skipped.

The command prints progress for every completed request. When it finishes, it
prints a path similar to:

```text
Return this archive: captures/sts-capture-20260623T140000Z.zip
```

Please return that ZIP file.

For a gentler request rate:

```bash
uv run --no-editable mdb-sync capture --delay 0.1
```

For a different output location:

```bash
uv run --no-editable mdb-sync capture --output /path/to/output
```

The known base URL is the default. It can still be overridden:

```bash
uv run --no-editable mdb-sync --base-url https://another-host.example capture
```

## What the comprehensive capture traverses

The crawler starts from model and tag discovery, then supplies discovered
parameters to dependent endpoints:

- model list and count;
- model versions and latest-version metadata;
- nodes, node counts, and node details;
- properties, property counts, and property details;
- terms, term counts, and individual term-value lookups;
- model/property PV and synonym responses;
- tags, tag values, tagged entities, and counts;
- direct `/v2/id/{id}` lookups for every discovered nanoid;
- CDE PV responses when terms expose both `origin_id` and `origin_version`.

List endpoints are paginated with `skip` and `limit`. Traversal is sequential
to avoid placing unnecessary concurrent load on the protected server.
Transient HTTP statuses (`429`, `500`, `502`, `503`, and `504`) and connection
failures are retried with exponential backoff.

Some `404` responses are expected, particularly for properties that do not use
an acceptable value set. They are retained because error behavior is part of
the API contract we need to understand.

## Capture contents

Each timestamped capture contains:

```text
manifest.json       Run metadata, status totals, endpoint coverage, and skips
requests.jsonl      One metadata record per attempted logical request
inventory.json      Discovered model/version/node/property and tag inventory
responses/          Exact response bodies, numbered to match requests.jsonl
openapi.json        The OpenAPI document used during development
```

`requests.jsonl` includes:

- request URL, path, query parameters, and logical endpoint name;
- HTTP status or connection error;
- elapsed time and retry-attempt count;
- sanitized response headers;
- response byte count and SHA-256 hash;
- path to the corresponding exact response body.

Authorization, cookie, proxy-authorization, and set-cookie headers are excluded
from captures.

## Useful options

```bash
uv run --no-editable mdb-sync capture \
  --page-size 100 \
  --timeout 120 \
  --retries 3 \
  --retry-backoff 1 \
  --delay 0
```

Use `--quiet` to suppress per-request progress. Avoid raising `--page-size`
without confirmation from the STS owners.

## Small connectivity test

To test only model discovery:

```bash
uv run --no-editable mdb-sync models --limit 10
```

If that returns a server error, collect diagnostics:

```bash
uv run --no-editable mdb-sync diagnose > sts-diagnostics.jsonl
```

Send back `sts-diagnostics.jsonl`. It compares the same model endpoint with
and without optional query parameters and includes status/body snippets for
related low-risk endpoints.

## Development

```bash
uv sync --all-extras --no-editable
just check
```

Individual checks:

```bash
uv run --no-editable ruff check src tests
uv run --no-editable basedpyright src tests
uv run --no-editable pytest tests -v
```

## Project layout

```text
src/mdb_sync/client.py    HTTP client with strict /v2 path enforcement
src/mdb_sync/capture.py   Response recorder, retries, manifest, and ZIP output
src/mdb_sync/crawler.py   Data-driven comprehensive STS traversal
src/mdb_sync/models.py    Typed model-discovery response
src/mdb_sync/cli.py       models and capture commands
tests/                    Mock-server traversal and client tests
adr/                      Architecture decisions
```
