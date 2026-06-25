"""HTTP client for the MDB Simple Terminology Server."""

from collections.abc import Iterator
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import TypeAdapter, ValidationError

from mdb_sync.models import Model

_MODELS_ADAPTER = TypeAdapter(list[Model])


class STSClientError(RuntimeError):
    """Raised when STS cannot be reached or returns an invalid response."""


class STSClient:
    """Typed and raw access to the STS v2 API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url must not be empty")

        self._client = httpx.Client(
            base_url=normalized_base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "mdb-sync/0.1.0"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    def get_v2(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send a GET request, refusing any path outside the v2 API."""
        if not path.startswith("/v2/"):
            raise ValueError(f"STS requests must use a /v2/ path: {path}")
        return self._client.get(path, params=params)

    def list_models(self, *, skip: int = 0, limit: int | None = None) -> list[Model]:
        """Return available MDB models."""
        if skip < 0 or (limit is not None and limit < 0):
            raise ValueError("skip and limit must be non-negative")
        params: dict[str, int] = {}
        if skip:
            params["skip"] = skip
        if limit is not None:
            params["limit"] = limit

        try:
            response = self.get_v2(
                "/v2/models/",
                params=params or None,
            )
            response.raise_for_status()
            return _MODELS_ADAPTER.validate_json(response.content)
        except httpx.HTTPStatusError as error:
            detail = error.response.text.strip()
            message = f"STS returned HTTP {error.response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise STSClientError(message) from error
        except httpx.RequestError as error:
            raise STSClientError(f"Could not reach STS: {error}") from error
        except ValidationError as error:
            raise STSClientError("STS returned an unexpected models response") from error

    def iter_models(self, *, page_size: int = 100) -> Iterator[Model]:
        """Yield all models using the API's skip/limit pagination."""
        if page_size <= 0:
            raise ValueError("page_size must be positive")

        skip = 0
        while True:
            page = self.list_models(skip=skip, limit=page_size)
            yield from page
            if len(page) < page_size:
                return
            skip += len(page)
