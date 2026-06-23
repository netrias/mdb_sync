# ADR 002: Capture Raw STS v2 Traversal

## Status

Accepted

## Context

The development team cannot directly access the firewall-protected STS server.
Database mapping and deployment design require representative successful and
error responses across the model graph and auxiliary PV/tag endpoints.

## Decision

Provide a data-driven crawler that uses only `/v2` endpoints and records exact
response bodies, sanitized metadata, timings, hashes, discovery inventory, and
endpoint coverage in a ZIP archive.

Run requests sequentially with bounded retries. Traverse dependent endpoints
only when their path parameters can be derived from earlier responses.

## Consequences

The returned archive can become the source for offline fixtures, response-model
development, transformation design, and request-count estimates. The sweep may
be large because individual entity and term endpoints are included. It does not
prove behavior for endpoint parameters that the API never exposes.

