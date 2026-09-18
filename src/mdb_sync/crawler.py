"""Comprehensive traversal of discoverable STS v2 resources."""

from __future__ import annotations

from collections.abc import Iterator
import sys
from typing import Any
from urllib.parse import quote

from mdb_sync.capture import RecordingSTSClient


def _segment(value: Any) -> str:
    return quote(str(value), safe="")


def _identifier(item: Any, field: str) -> str | None:
    if not isinstance(item, dict):
        return None
    value = item.get(field)
    return str(value) if value is not None and str(value) else None


class STSCrawler:
    """Traverse all v2 endpoints whose parameters can be discovered from STS."""

    def __init__(
        self,
        client: RecordingSTSClient,
        *,
        page_size: int = 100,
        max_pages: int = 100_000,
        capture_term_details: bool = False,
        capture_tags: bool = False,
        capture_ids: bool = False,
        capture_cde_pvs: bool = False,
        capture_model_pvs: bool = True,
    ) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        self._client = client
        self._page_size = page_size
        self._max_pages = max_pages
        self._capture_term_details = capture_term_details
        self._capture_tags_enabled = capture_tags
        self._capture_ids_enabled = capture_ids
        self._capture_cde_pvs_enabled = capture_cde_pvs
        self._capture_model_pvs_enabled = capture_model_pvs
        self._seen_nanoids: set[str] = set()
        self._cde_candidates: set[tuple[str, str]] = set()
        self.inventory: dict[str, Any] = {
            "models": [],
            "tags": [],
            "discovered_nanoids": [],
            "cde_candidates": [],
            "notes": [
                "Bounded first-pass capture is the default.",
                "404 responses for properties without acceptable values are expected.",
            ],
            "options": {
                "capture_cde_pvs": self._capture_cde_pvs_enabled,
                "capture_ids": self._capture_ids_enabled,
                "capture_model_pvs": self._capture_model_pvs_enabled,
                "capture_tags": self._capture_tags_enabled,
                "capture_term_details": self._capture_term_details,
                "max_pages": self._max_pages,
                "page_size": self._page_size,
            },
        }

    def run(self) -> dict[str, Any]:
        self._record_disabled_features()
        self._capture_models()
        if self._capture_tags_enabled:
            self._capture_tags()
        if self._capture_cde_pvs_enabled:
            self._capture_cde_permissible_values()
        if self._capture_ids_enabled:
            self._capture_ids()
        return self.current_inventory()

    def current_inventory(self, *, incomplete_reason: str | None = None) -> dict[str, Any]:
        """Return the best currently known inventory, including partial runs."""

        self.inventory["discovered_nanoids"] = sorted(self._seen_nanoids)
        self.inventory["cde_candidates"] = [
            {"id": cde_id, "version": version} for cde_id, version in sorted(self._cde_candidates)
        ]
        if incomplete_reason is not None:
            self.inventory["incomplete"] = True
            self.inventory["reason"] = incomplete_reason
        return self.inventory

    def _record_disabled_features(self) -> None:
        if not self._capture_term_details:
            self._client.record_skip(
                endpoint="term_detail",
                reason=(
                    "Skipped by bounded capture mode. Enable with --include-term-details "
                    "or --profile comprehensive."
                ),
            )
        if not self._capture_tags_enabled:
            self._client.record_skip(
                endpoint="tags",
                reason="Skipped by bounded capture mode. Enable with --include-tags.",
            )
        if not self._capture_cde_pvs_enabled:
            self._client.record_skip(
                endpoint="cde_permissible_values",
                reason=(
                    "Skipped by bounded capture mode. Enable with --include-cde-pvs "
                    "or --profile comprehensive."
                ),
            )
        if not self._capture_ids_enabled:
            self._client.record_skip(
                endpoint="entity_by_id",
                reason=(
                    "Skipped by bounded capture mode. Enable with --include-ids "
                    "or --profile comprehensive."
                ),
            )

    def _capture_models(self) -> None:
        self._get("models_count", "/v2/models/count")
        models = list(self._paginate("models", "/v2/models/"))

        # Deduplicate upfront — one entry per handle, first occurrence wins
        unique: dict[str, dict[str, Any]] = {}
        for model in models:
            handle = _identifier(model, "handle")
            self._remember_nanoid(model)
            if handle is not None and handle not in unique:
                unique[handle] = model

        for handle, model in unique.items():
            print(f"DEBUG: first encounter of handle={handle!r}", file=sys.stderr)
            model_inventory: dict[str, Any] = {
                "handle": handle,
                "name": _identifier(model, "name"),
                "versions": [],
            }
            self.inventory["models"].append(model_inventory)
            encoded_model = _segment(handle)
            latest_model = self._get(
                "model_latest_version",
                f"/v2/model/{encoded_model}/latest-version",
            )
            self._remember_nanoid(latest_model)
            versions = list(
                self._paginate(
                    "model_versions",
                    f"/v2/model/{encoded_model}/versions",
                )
            )
            for version_value in versions:
                version = str(version_value) if version_value is not None else ""
                if not version:
                    self._client.record_skip(
                        endpoint="model_version_traversal",
                        reason=f"Model {handle!r} returned an empty version.",
                    )
                    continue
                version_inventory = self._capture_version(handle, version)
                model_inventory["versions"].append(version_inventory)

    def _capture_version(self, model: str, version: str) -> dict[str, Any]:
        prefix = f"/v2/model/{_segment(model)}/version/{_segment(version)}"
        self._get("nodes_count", f"{prefix}/nodes/count")
        nodes = list(self._paginate("nodes", f"{prefix}/nodes"))
        version_inventory: dict[str, Any] = {"version": version, "nodes": []}

        for node in nodes:
            node_handle = _identifier(node, "handle")
            self._remember_nanoid(node)
            node_inventory: dict[str, Any] = {"handle": node_handle, "properties": []}
            version_inventory["nodes"].append(node_inventory)
            if node_handle is None:
                self._client.record_skip(
                    endpoint="node_traversal",
                    reason=f"Model {model!r} version {version!r} returned a node without a handle.",
                )
                continue

            node_prefix = f"{prefix}/node/{_segment(node_handle)}"
            self._remember_nanoid(self._get("node_detail", node_prefix))
            self._get("properties_count", f"{node_prefix}/properties/count")
            properties = list(self._paginate("properties", f"{node_prefix}/properties"))
            for prop in properties:
                prop_handle = _identifier(prop, "handle")
                self._remember_nanoid(prop)
                node_inventory["properties"].append(prop_handle)
                if prop_handle is None:
                    self._client.record_skip(
                        endpoint="property_traversal",
                        reason=(
                            f"Node {node_handle!r} in {model!r} {version!r} "
                            "returned a property without a handle."
                        ),
                    )
                    continue
                self._capture_property(
                    model=model,
                    version=version,
                    node_prefix=node_prefix,
                    property_handle=prop_handle,
                )
        return version_inventory

    def _capture_property(
        self,
        *,
        model: str,
        version: str,
        node_prefix: str,
        property_handle: str,
    ) -> None:
        property_prefix = f"{node_prefix}/property/{_segment(property_handle)}"
        self._remember_nanoid(self._get("property_detail", property_prefix))
        self._get("terms_count", f"{property_prefix}/terms/count")
        terms = list(self._paginate("terms", f"{property_prefix}/terms"))

        for term in terms:
            self._remember_nanoid(term)
            term_value = _identifier(term, "value")
            if self._capture_term_details and term_value is not None:
                self._get(
                    "term_detail",
                    f"{property_prefix}/term/{_segment(term_value)}",
                )
            origin_id = _identifier(term, "origin_id")
            origin_version = _identifier(term, "origin_version")
            if origin_id is not None and origin_version is not None:
                self._cde_candidates.add((origin_id, origin_version))

        if self._capture_model_pvs_enabled:
            self._get_all_pages(
                "model_permissible_values",
                f"/v2/terms/model-pvs/{_segment(model)}/{_segment(property_handle)}",
                base_params={"version": version},
            )

    def _capture_tags(self) -> None:
        self._get("tags_count", "/v2/tags/count")
        tags = list(self._paginate("tags", "/v2/tags/"))
        unique_keys: set[str] = set()
        for tag in tags:
            self._remember_nanoid(tag)
            key = _identifier(tag, "key")
            value = tag.get("value") if isinstance(tag, dict) else None
            self.inventory["tags"].append({"key": key, "value": value})
            if key is not None:
                unique_keys.add(key)

        for key in sorted(unique_keys):
            values = list(
                self._paginate(
                    "tag_values",
                    f"/v2/tag/{_segment(key)}/values",
                )
            )
            for value in values:
                encoded_value = _segment(str(value).lower() if isinstance(value, bool) else value)
                prefix = f"/v2/tag/{_segment(key)}/{encoded_value}/entities"
                self._get("tag_entities_count", f"{prefix}/count")
                entities = list(self._paginate("tag_entities", prefix))
                for entity in entities:
                    self._remember_nanoid(entity)
        if not unique_keys:
            self._client.record_skip(
                endpoint="tag_dependent_endpoints",
                reason=(
                    "No tag keys were returned, so tag values and entity endpoints "
                    "were not callable."
                ),
            )

    def _capture_cde_permissible_values(self) -> None:
        if not self._cde_candidates:
            self._client.record_skip(
                endpoint="cde_permissible_values",
                reason="No terms supplied both origin_id and origin_version.",
            )
        for cde_id, version in sorted(self._cde_candidates):
            self._get_all_pages(
                "cde_permissible_values",
                f"/v2/terms/cde-pvs/{_segment(cde_id)}/{_segment(version)}/pvs",
                base_params={"use_null_cde": False},
            )

    def _capture_ids(self) -> None:
        if not self._seen_nanoids:
            self._client.record_skip(
                endpoint="entity_by_id",
                reason="No nanoids were discoverable from other endpoint responses.",
            )
        for nanoid in sorted(self._seen_nanoids):
            self._get("entity_by_id", f"/v2/id/{_segment(nanoid)}")

    def _remember_nanoid(self, item: Any) -> None:
        nanoid = _identifier(item, "nanoid")
        if nanoid is not None:
            self._seen_nanoids.add(nanoid)

    def _paginate(
        self,
        endpoint: str,
        path: str,
        *,
        base_params: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        params = dict(base_params or {})
        skip = 0
        for _ in range(self._max_pages):
            page_params = {**params, "skip": skip, "limit": self._page_size}
            data = self._get(endpoint, path, params=page_params)
            if not isinstance(data, list):
                return
            yield from data
            if len(data) < self._page_size:
                return
            skip += len(data)
        self._client.record_skip(
            endpoint=endpoint,
            reason=f"Stopped {path} after max_pages={self._max_pages}.",
        )

    def _get_all_pages(
        self,
        endpoint: str,
        path: str,
        *,
        base_params: dict[str, Any] | None = None,
    ) -> None:
        for _ in self._paginate(endpoint, path, base_params=base_params):
            pass

    def _get(
        self,
        endpoint: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        data = self._client.get_json(endpoint, path, params=params)
        self._client.pause()
        return data
