"""Response models derived from the STS OpenAPI document."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """An MDB model returned by ``GET /v2/models/``."""

    model_config = ConfigDict(extra="allow")

    type: Literal["Model"] = "Model"
    handle: str | None = None
    version: str | None = None
    nanoid: str | None = None
    name: str | None = None
    repository: str | None = None
    is_latest_version: bool
