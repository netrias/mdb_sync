"""HTTP client for the MDB Simple Terminology Server."""

from collections.abc import Iterator
from types import TracebackType
from typing import Self

import httpx
from pydantic import TypeAdapter, ValidationError

from mdb_sync.models import Model

_MODELS_ADAPTER = TypeAdapter(list[Model])


class STSClientError(RuntimeError):
    """Raised when STS cannot be reached or returns an invalid response."""


class STSClient:
    """Small typed wrapper around the STS endpoints needed by the first sync step."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
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

    def list_models(self, *, skip: int = 0, limit: int = 0) -> list[Model]:
        """Return available MDB models."""
        if skip < 0 or limit < 0:
            raise ValueError("skip and limit must be non-negative")

        try:
            response = self._client.get(
                "/v2/models/",
                params={"skip": skip, "limit": limit},
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
