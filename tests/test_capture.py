import json
from pathlib import Path

import httpx

from mdb_sync.capture import CaptureWriter, RecordingSTSClient
from mdb_sync.client import STSClient
from mdb_sync.crawler import STSCrawler


def test_crawler_captures_full_discoverable_traversal(tmp_path: Path) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested_paths.append(path)
        assert path.startswith("/v2/")

        responses: dict[str, object] = {
            "/v2/models/count": 1,
            "/v2/models/": [
                {
                    "type": "Model",
                    "handle": "gc",
                    "version": "1.0",
                    "nanoid": "model-id",
                    "name": "GC",
                    "is_latest_version": True,
                }
            ],
            "/v2/model/gc/latest-version": {
                "type": "Model",
                "handle": "gc",
                "version": "1.0",
                "nanoid": "model-id",
                "name": "GC",
                "is_latest_version": True,
            },
            "/v2/model/gc/versions": ["1.0"],
            "/v2/model/gc/version/1.0/nodes/count": 1,
            "/v2/model/gc/version/1.0/nodes": [
                {
                    "type": "Node",
                    "handle": "participant",
                    "version": "1.0",
                    "nanoid": "node-id",
                    "model": "gc",
                }
            ],
            "/v2/model/gc/version/1.0/node/participant": {
                "type": "Node",
                "handle": "participant",
                "version": "1.0",
                "nanoid": "node-id",
                "model": "gc",
            },
            "/v2/model/gc/version/1.0/node/participant/properties/count": 1,
            "/v2/model/gc/version/1.0/node/participant/properties": [
                {
                    "type": "Property",
                    "handle": "sex",
                    "version": "1.0",
                    "nanoid": "property-id",
                    "model": "gc",
                    "value_domain": "value_set",
                }
            ],
            "/v2/model/gc/version/1.0/node/participant/property/sex": {
                "type": "Property",
                "handle": "sex",
                "version": "1.0",
                "nanoid": "property-id",
                "model": "gc",
                "value_domain": "value_set",
            },
            "/v2/model/gc/version/1.0/node/participant/property/sex/terms/count": 1,
            "/v2/model/gc/version/1.0/node/participant/property/sex/terms": [
                {
                    "type": "Term",
                    "value": "Female",
                    "origin_name": "caDSR",
                    "origin_id": "123",
                    "origin_version": "2",
                    "nanoid": "term-id",
                }
            ],
            "/v2/model/gc/version/1.0/node/participant/property/sex/term/Female": [
                {
                    "type": "Term",
                    "value": "Female",
                    "origin_name": "caDSR",
                    "nanoid": "term-id",
                }
            ],
            "/v2/terms/model-pvs/gc/sex": [
                {
                    "model": "gc",
                    "property": "sex",
                    "version": "1.0",
                    "permissibleValues": [{"value": "Female"}],
                }
            ],
            "/v2/tags/count": 1,
            "/v2/tags/": [{"type": "Tag", "key": "status", "value": "active", "nanoid": "tag-id"}],
            "/v2/tag/status/values": ["active"],
            "/v2/tag/status/active/entities/count": 1,
            "/v2/tag/status/active/entities": [
                {
                    "type": "Node",
                    "handle": "participant",
                    "version": "1.0",
                    "nanoid": "node-id",
                    "model": "gc",
                }
            ],
            "/v2/terms/cde-pvs/123/2/pvs": [
                {
                    "CDECode": "123",
                    "CDEFullName": "Sex",
                    "CDEVersion": "2",
                    "permissibleValues": [{"value": "Female"}],
                }
            ],
        }
        if path.startswith("/v2/id/"):
            return httpx.Response(200, json={"type": "Entity", "nanoid": path.rsplit("/", 1)[-1]})
        return httpx.Response(200, json=responses[path])

    writer = CaptureWriter(
        tmp_path,
        base_url="https://sts.cancer.gov",
        page_size=100,
    )
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),
    ) as client:
        crawler = STSCrawler(
            RecordingSTSClient(client, writer, retries=0),
            page_size=100,
            capture_term_details=True,
            capture_tags=True,
            capture_ids=True,
            capture_cde_pvs=True,
        )
        inventory = crawler.run()

    writer.write_inventory(inventory)
    capture_dir, archive = writer.finalize()

    expected_paths = {
        "/v2/models/count",
        "/v2/models/",
        "/v2/model/gc/latest-version",
        "/v2/model/gc/versions",
        "/v2/model/gc/version/1.0/nodes/count",
        "/v2/model/gc/version/1.0/nodes",
        "/v2/model/gc/version/1.0/node/participant",
        "/v2/model/gc/version/1.0/node/participant/properties/count",
        "/v2/model/gc/version/1.0/node/participant/properties",
        "/v2/model/gc/version/1.0/node/participant/property/sex",
        "/v2/model/gc/version/1.0/node/participant/property/sex/terms/count",
        "/v2/model/gc/version/1.0/node/participant/property/sex/terms",
        "/v2/model/gc/version/1.0/node/participant/property/sex/term/Female",
        "/v2/terms/model-pvs/gc/sex",
        "/v2/terms/cde-pvs/123/2/pvs",
        "/v2/tags/count",
        "/v2/tags/",
        "/v2/tag/status/values",
        "/v2/tag/status/active/entities/count",
        "/v2/tag/status/active/entities",
        "/v2/id/model-id",
        "/v2/id/node-id",
        "/v2/id/property-id",
        "/v2/id/tag-id",
        "/v2/id/term-id",
    }
    assert set(requested_paths) == expected_paths
    assert archive.is_file()
    assert (capture_dir / "inventory.json").is_file()
    assert list((capture_dir / "responses").iterdir())

    manifest = json.loads((capture_dir / "manifest.json").read_text())
    assert manifest["api_scope"] == "/v2 only"
    assert manifest["request_count"] == len(expected_paths)
    assert manifest["statuses"] == {"200": len(expected_paths)}


def test_crawler_deduplicates_model_rows_by_handle(tmp_path: Path) -> None:
    request_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        request_counts[path] = request_counts.get(path, 0) + 1
        assert path.startswith("/v2/")

        responses: dict[str, object] = {
            "/v2/models/count": 1,
            # /v2/models/ returns one row per model *version*, so the same
            # handle repeats across rows.
            "/v2/models/": [
                {"type": "Model", "handle": "c3dc", "version": "1.4.0", "nanoid": "m1"},
                {"type": "Model", "handle": "c3dc", "version": "2.0.0", "nanoid": "m2"},
                {"type": "Model", "handle": "c3dc", "version": "2.0.1", "nanoid": "m3"},
                {"type": "Model", "handle": "c3dc", "version": "2.1.0", "nanoid": "m4"},
            ],
            "/v2/model/c3dc/latest-version": {
                "type": "Model",
                "handle": "c3dc",
                "version": "2.1.0",
                "nanoid": "m4",
            },
            "/v2/model/c3dc/versions": ["1.4.0", "2.0.0", "2.0.1", "2.1.0"],
        }
        for version in ("1.4.0", "2.0.0", "2.0.1", "2.1.0"):
            prefix = f"/v2/model/c3dc/version/{version}"
            responses[f"{prefix}/nodes/count"] = 0
            responses[f"{prefix}/nodes"] = []
        return httpx.Response(200, json=responses[path])

    writer = CaptureWriter(
        tmp_path,
        base_url="https://sts.cancer.gov",
        page_size=100,
    )
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),
    ) as client:
        crawler = STSCrawler(
            RecordingSTSClient(client, writer, retries=0),
            page_size=100,
        )
        inventory = crawler.run()

    # The handle-discovery endpoints must be hit once, not once per duplicate row.
    assert request_counts["/v2/model/c3dc/latest-version"] == 1
    assert request_counts["/v2/model/c3dc/versions"] == 1

    # Each version's node traversal still happens exactly once.
    for version in ("1.4.0", "2.0.0", "2.0.1", "2.1.0"):
        assert request_counts[f"/v2/model/c3dc/version/{version}/nodes"] == 1

    # All four versions must still be captured, just without repeating the
    # /versions traversal for each duplicate handle row.
    assert len(inventory["models"]) == 1
    model_inventory = inventory["models"][0]
    assert model_inventory["handle"] == "c3dc"
    captured_versions = {version["version"] for version in model_inventory["versions"]}
    assert captured_versions == {"1.4.0", "2.0.0", "2.0.1", "2.1.0"}

    # Skipping duplicate rows must not drop the nanoids they carry, since each
    # row is a distinct entity that the --include-ids phase would look up.
    assert inventory["discovered_nanoids"] == ["m1", "m2", "m3", "m4"]


def test_crawler_first_pass_skips_high_volume_dependent_traversal(tmp_path: Path) -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested_paths.append(path)
        assert path.startswith("/v2/")

        responses: dict[str, object] = {
            "/v2/models/count": 1,
            "/v2/models/": [
                {
                    "type": "Model",
                    "handle": "gc",
                    "version": "1.0",
                    "nanoid": "model-id",
                    "name": "GC",
                    "is_latest_version": True,
                }
            ],
            "/v2/model/gc/latest-version": {
                "type": "Model",
                "handle": "gc",
                "version": "1.0",
                "nanoid": "model-id",
                "name": "GC",
                "is_latest_version": True,
            },
            "/v2/model/gc/versions": ["1.0"],
            "/v2/model/gc/version/1.0/nodes/count": 1,
            "/v2/model/gc/version/1.0/nodes": [
                {
                    "type": "Node",
                    "handle": "participant",
                    "version": "1.0",
                    "nanoid": "node-id",
                    "model": "gc",
                }
            ],
            "/v2/model/gc/version/1.0/node/participant": {
                "type": "Node",
                "handle": "participant",
                "version": "1.0",
                "nanoid": "node-id",
                "model": "gc",
            },
            "/v2/model/gc/version/1.0/node/participant/properties/count": 1,
            "/v2/model/gc/version/1.0/node/participant/properties": [
                {
                    "type": "Property",
                    "handle": "sex",
                    "version": "1.0",
                    "nanoid": "property-id",
                    "model": "gc",
                    "value_domain": "value_set",
                }
            ],
            "/v2/model/gc/version/1.0/node/participant/property/sex": {
                "type": "Property",
                "handle": "sex",
                "version": "1.0",
                "nanoid": "property-id",
                "model": "gc",
                "value_domain": "value_set",
            },
            "/v2/model/gc/version/1.0/node/participant/property/sex/terms/count": 1,
            "/v2/model/gc/version/1.0/node/participant/property/sex/terms": [
                {
                    "type": "Term",
                    "value": "Female",
                    "origin_name": "caDSR",
                    "origin_id": "123",
                    "origin_version": "2",
                    "nanoid": "term-id",
                }
            ],
            "/v2/terms/model-pvs/gc/sex": [
                {
                    "model": "gc",
                    "property": "sex",
                    "version": "1.0",
                    "permissibleValues": [{"value": "Female"}],
                }
            ],
        }
        return httpx.Response(200, json=responses[path])

    writer = CaptureWriter(
        tmp_path,
        base_url="https://sts.cancer.gov",
        page_size=100,
    )
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),
    ) as client:
        crawler = STSCrawler(
            RecordingSTSClient(client, writer, retries=0),
            page_size=100,
        )
        inventory = crawler.run()

    writer.write_inventory(inventory)
    capture_dir, _archive = writer.finalize()

    unexpected_paths = {
        "/v2/model/gc/version/1.0/node/participant/property/sex/term/Female",
        "/v2/tags/count",
        "/v2/tags/",
        "/v2/terms/cde-pvs/123/2/pvs",
        "/v2/id/model-id",
    }
    assert unexpected_paths.isdisjoint(requested_paths)
    assert "/v2/terms/model-pvs/gc/sex" in requested_paths
    assert inventory["options"]["capture_term_details"] is False
    assert inventory["discovered_nanoids"] == ["model-id", "node-id", "property-id", "term-id"]

    manifest = json.loads((capture_dir / "manifest.json").read_text())
    skipped_endpoints = {item["endpoint"] for item in manifest["skipped"]}
    assert {"cde_permissible_values", "entity_by_id", "tags", "term_detail"}.issubset(
        skipped_endpoints
    )
