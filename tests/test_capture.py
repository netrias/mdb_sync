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
