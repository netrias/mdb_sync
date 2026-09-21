"""Durable recording of STS requests and responses."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from mdb_sync.client import STSClient

_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ProgressCallback(Protocol):
    def __call__(self, result: CaptureResult) -> None: ...


@dataclass(frozen=True)
class CaptureResult:
    """The recorded result of one attempted request."""

    sequence: int
    endpoint: str
    path: str
    params: dict[str, Any]
    url: str
    status_code: int | None
    elapsed_ms: int
    response_offset: int | None
    response_headers: dict[str, str]
    response_sha256: str | None
    response_bytes: int
    error: str | None
    attempts: int


class CaptureWriter:
    """Write a self-describing capture directory and ZIP archive."""

    def __init__(
        self,
        output_parent: Path,
        *,
        base_url: str,
        page_size: int,
        source_openapi: Path | None = None,
    ) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.started_at = datetime.now(UTC)
        self.root = output_parent / f"sts-capture-{timestamp}"
        self.root.mkdir(parents=True, exist_ok=False)
        self._records_path = self.root / "requests.jsonl"
        self._records_path.touch()
        self._responses_path = self.root / "responses.jsonl"
        self._responses_path.touch()
        self._responses_bytes = 0
        self._request_count = 0
        self._response_bytes = 0
        self._statuses: Counter[str] = Counter()
        self._endpoints: dict[str, dict[str, int]] = {}
        self._skipped: list[dict[str, str]] = []
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._openapi_sha256: str | None = None

        if source_openapi is not None and source_openapi.is_file():
            destination = self.root / "openapi.json"
            shutil.copyfile(source_openapi, destination)
            self._openapi_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()

    def record_response(
        self,
        *,
        endpoint: str,
        path: str,
        params: dict[str, Any],
        response: httpx.Response,
        elapsed_ms: int,
        attempts: int,
    ) -> CaptureResult:
        sequence = self._request_count + 1
        body = response.content
        offset = self._append_response_body(sequence, response, body)

        result = CaptureResult(
            sequence=sequence,
            endpoint=endpoint,
            path=path,
            params=params,
            url=str(response.request.url),
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            response_offset=offset,
            response_headers=self._sanitize_headers(response.headers),
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            error=None,
            attempts=attempts,
        )
        self._append(result)
        return result

    def record_error(
        self,
        *,
        endpoint: str,
        path: str,
        params: dict[str, Any],
        url: str,
        elapsed_ms: int,
        error: Exception,
        attempts: int,
    ) -> CaptureResult:
        result = CaptureResult(
            sequence=self._request_count + 1,
            endpoint=endpoint,
            path=path,
            params=params,
            url=url,
            status_code=None,
            elapsed_ms=elapsed_ms,
            response_offset=None,
            response_headers={},
            response_sha256=None,
            response_bytes=0,
            error=f"{type(error).__name__}: {error}",
            attempts=attempts,
        )
        self._append(result)
        return result

    def record_skip(self, *, endpoint: str, reason: str) -> None:
        self._skipped.append({"endpoint": endpoint, "reason": reason})

    def _append_response_body(
        self,
        sequence: int,
        response: httpx.Response,
        body: bytes,
    ) -> int:
        """Append one body to responses.jsonl and return its byte offset."""
        record: dict[str, Any] = {
            "sequence": sequence,
            "content_type": response.headers.get("content-type", ""),
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
        try:
            record["body"] = body.decode("utf-8")
        except UnicodeDecodeError:
            # Bytes that are not UTF-8 still round-trip exactly through base64.
            record["base64"] = base64.b64encode(body).decode("ascii")
        line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
        offset = self._responses_bytes
        with self._responses_path.open("ab") as stream:
            stream.write(line)
        self._responses_bytes += len(line)
        return offset

    def write_inventory(self, inventory: dict[str, Any]) -> None:
        self._write_json(self.root / "inventory.json", inventory)

    def finalize(self) -> tuple[Path, Path]:
        finished_at = datetime.now(UTC)
        manifest = {
            "capture_format_version": 1,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - self.started_at).total_seconds(), 3),
            "base_url": self._base_url,
            "api_scope": "/v2 only",
            "page_size": self._page_size,
            "runtime": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "openapi_sha256": self._openapi_sha256,
            "request_count": self._request_count,
            "response_bytes": self._response_bytes,
            "statuses": dict(sorted(self._statuses.items())),
            "endpoints": dict(sorted(self._endpoints.items())),
            "skipped": self._skipped,
            "files": {
                "request_log": "requests.jsonl",
                "inventory": "inventory.json",
                "responses": "responses.jsonl",
                "openapi": "openapi.json" if self._openapi_sha256 else None,
            },
        }
        self._write_json(self.root / "manifest.json", manifest)
        archive_base = self.root.parent / self.root.name
        archive = Path(
            shutil.make_archive(str(archive_base), "zip", self.root.parent, self.root.name)
        )
        return self.root, archive

    def _append(self, result: CaptureResult) -> None:
        with self._records_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(result), sort_keys=True, default=str))
            stream.write("\n")
        self._request_count += 1
        self._response_bytes += result.response_bytes
        status = str(result.status_code) if result.status_code is not None else "request_error"
        self._statuses[status] += 1
        endpoint_summary = self._endpoints.setdefault(
            result.endpoint,
            {"requests": 0, "successes": 0, "http_errors": 0, "request_errors": 0},
        )
        endpoint_summary["requests"] += 1
        if result.status_code is None:
            endpoint_summary["request_errors"] += 1
        elif 200 <= result.status_code < 300:
            endpoint_summary["successes"] += 1
        else:
            endpoint_summary["http_errors"] += 1

    @staticmethod
    def _sanitize_headers(headers: httpx.Headers) -> dict[str, str]:
        return {
            key: value for key, value in headers.items() if key.lower() not in _SENSITIVE_HEADERS
        }

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


class RecordingSTSClient:
    """STS client wrapper that records every response and retries transient failures."""

    def __init__(
        self,
        client: STSClient,
        writer: CaptureWriter,
        *,
        retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        delay_seconds: float = 0.0,
        progress: ProgressCallback | None = None,
    ) -> None:
        self._client = client
        self._writer = writer
        self._retries = retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._delay_seconds = delay_seconds
        self._progress = progress

    def get_json(
        self,
        endpoint: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        request_params = params or {}
        started = time.monotonic()
        last_error: httpx.RequestError | None = None

        for attempt in range(1, self._retries + 2):
            try:
                response = self._client.get_v2(path, params=request_params)
                if response.status_code in _RETRYABLE_STATUSES and attempt <= self._retries:
                    self._sleep_before_retry(response, attempt)
                    continue

                elapsed_ms = round((time.monotonic() - started) * 1000)
                result = self._writer.record_response(
                    endpoint=endpoint,
                    path=path,
                    params=request_params,
                    response=response,
                    elapsed_ms=elapsed_ms,
                    attempts=attempt,
                )
                self._report_progress(result)
                if not 200 <= response.status_code < 300:
                    return None
                try:
                    return response.json()
                except ValueError:
                    return None
            except httpx.RequestError as error:
                last_error = error
                if attempt <= self._retries:
                    time.sleep(self._retry_backoff_seconds * (2 ** (attempt - 1)))
                    continue

        assert last_error is not None
        elapsed_ms = round((time.monotonic() - started) * 1000)
        url = f"{self._client_base_url()}{path}"
        result = self._writer.record_error(
            endpoint=endpoint,
            path=path,
            params=request_params,
            url=url,
            elapsed_ms=elapsed_ms,
            error=last_error,
            attempts=self._retries + 1,
        )
        self._report_progress(result)
        return None

    def pause(self) -> None:
        if self._delay_seconds > 0:
            time.sleep(self._delay_seconds)

    def record_skip(self, *, endpoint: str, reason: str) -> None:
        self._writer.record_skip(endpoint=endpoint, reason=reason)

    def _sleep_before_retry(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                time.sleep(float(retry_after))
                return
            except ValueError:
                pass
        time.sleep(self._retry_backoff_seconds * (2 ** (attempt - 1)))

    def _client_base_url(self) -> str:
        # This is used only to make a useful error record after no HTTP response exists.
        return self._client.base_url

    def _report_progress(self, result: CaptureResult) -> None:
        if self._progress is not None:
            self._progress(result)
