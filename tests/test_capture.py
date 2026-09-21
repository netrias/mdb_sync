import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from mdb_sync.capture import CaptureWriter, RecordingSTSClient
from mdb_sync.cli import _parser
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
    body_lines = (capture_dir / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(body_lines) == len(expected_paths)
    assert not (capture_dir / "responses").exists()

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
            capture_all_versions=True,
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


def _latest_version_handler(
    requested: list[str],
    *,
    latest_body: object,
    listing_flags_latest: bool = True,
) -> "object":
    """One model, four versions, empty node lists. latest_body drives selection."""
    versions = ["1.4.0", "2.0.0", "2.0.1", "2.1.0"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        if path == "/v2/models/count":
            return httpx.Response(200, json=len(versions))
        if path == "/v2/models/":
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "Model",
                        "handle": "c3dc",
                        "version": v,
                        "nanoid": f"m{i}",
                        "is_latest_version": listing_flags_latest and v == "2.1.0",
                    }
                    for i, v in enumerate(versions)
                ],
            )
        if path == "/v2/model/c3dc/latest-version":
            if latest_body is None:
                return httpx.Response(404, json={"detail": "not found"})
            return httpx.Response(200, json=latest_body)
        if path == "/v2/model/c3dc/versions":
            return httpx.Response(200, json=versions)
        if path.endswith("/nodes/count"):
            return httpx.Response(200, json=0)
        if path.endswith("/nodes"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path: {path}")

    return handler


def _walked_versions(requested: list[str]) -> set[str]:
    return {p.split("/version/")[1].split("/")[0] for p in requested if "/version/" in p}


def _run_with(tmp_path: Path, handler: object, **crawler_options: object) -> None:
    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    ) as client:
        STSCrawler(
            RecordingSTSClient(client, writer, retries=0),
            page_size=100,
            **crawler_options,  # type: ignore[arg-type]
        ).run()


def test_only_the_latest_version_is_traversed_by_default(tmp_path: Path) -> None:
    requested: list[str] = []
    handler = _latest_version_handler(
        requested,
        latest_body={"type": "Model", "handle": "c3dc", "version": "2.1.0", "nanoid": "m3"},
    )
    _run_with(tmp_path, handler)
    assert _walked_versions(requested) == {"2.1.0"}


def test_all_versions_are_traversed_when_requested(tmp_path: Path) -> None:
    requested: list[str] = []
    handler = _latest_version_handler(
        requested,
        latest_body={"type": "Model", "handle": "c3dc", "version": "2.1.0", "nanoid": "m3"},
    )
    _run_with(tmp_path, handler, capture_all_versions=True)
    assert _walked_versions(requested) == {"1.4.0", "2.0.0", "2.0.1", "2.1.0"}


def test_latest_version_falls_back_to_the_models_listing_flag(tmp_path: Path) -> None:
    """A 404 on /latest-version must not stop the model being traversed."""
    requested: list[str] = []
    handler = _latest_version_handler(requested, latest_body=None)
    _run_with(tmp_path, handler)
    assert _walked_versions(requested) == {"2.1.0"}


def test_model_is_skipped_when_no_latest_version_can_be_determined(tmp_path: Path) -> None:
    requested: list[str] = []
    handler = _latest_version_handler(
        requested,
        latest_body={"handle": "c3dc"},
        listing_flags_latest=False,
    )
    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    ) as client:
        STSCrawler(RecordingSTSClient(client, writer, retries=0), page_size=100).run()
    writer.write_inventory({})
    capture_dir, _ = writer.finalize()

    # No listing row is flagged latest here, so nothing below the model is walked.
    assert _walked_versions(requested) == set()
    manifest = json.loads((capture_dir / "manifest.json").read_text())
    reasons = " ".join(item["reason"] for item in manifest["skipped"])
    assert "exposed no latest version" in reasons


def test_response_bodies_round_trip_through_the_single_file(tmp_path: Path) -> None:
    requested: list[str] = []
    handler = _latest_version_handler(
        requested,
        latest_body={"type": "Model", "handle": "c3dc", "version": "2.1.0", "nanoid": "m3"},
    )
    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    ) as client:
        STSCrawler(RecordingSTSClient(client, writer, retries=0), page_size=100).run()
    writer.write_inventory({})
    capture_dir, _ = writer.finalize()

    records = [
        json.loads(line)
        for line in (capture_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    bodies_path = capture_dir / "responses.jsonl"
    raw = bodies_path.read_bytes()

    # response_offset must seek straight to that request's own body.
    for record in records:
        offset = record["response_offset"]
        assert offset is not None
        line = raw[offset:].split(b"\n", 1)[0]
        body = json.loads(line)
        assert body["sequence"] == record["sequence"]
        assert body["sha256"] == record["response_sha256"]
        assert len(body["body"].encode("utf-8")) == record["response_bytes"]

    manifest = json.loads((capture_dir / "manifest.json").read_text())
    assert manifest["files"]["responses"] == "responses.jsonl"


def _read_body_at(capture_dir: Path, offset: int) -> dict[str, Any]:
    raw = (capture_dir / "responses.jsonl").read_bytes()
    body: dict[str, Any] = json.loads(raw[offset:].split(b"\n", 1)[0])
    return body


def test_non_utf8_bodies_round_trip_as_base64(tmp_path: Path) -> None:
    payload = b"\xff\xfe\x00binary-not-utf8\x80\x81"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/octet-stream"},
        )

    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov", transport=httpx.MockTransport(handler)
    ) as client:
        recording = RecordingSTSClient(client, writer, retries=0)
        recording.get_json("models_count", "/v2/models/count")
    writer.write_inventory({})
    capture_dir, _ = writer.finalize()

    record = json.loads((capture_dir / "requests.jsonl").read_text().splitlines()[0])
    body = _read_body_at(capture_dir, record["response_offset"])
    assert "body" not in body
    assert base64.b64decode(body["base64"]) == payload
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["bytes"] == len(payload)


def test_offsets_stay_correct_when_bodies_need_json_escaping(tmp_path: Path) -> None:
    """Quotes, newlines and multi-byte characters all expand when encoded."""
    payloads = [
        '{"quote": "he said \\"hi\\""}',
        '{"newline": "a\\nb\\nc"}',
        '{"unicode": "café — 日本語 🧬"}',
        '{"plain": 1}',
    ]
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = payloads[len(sent)].encode("utf-8")
        sent.append(body)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov", transport=httpx.MockTransport(handler)
    ) as client:
        recording = RecordingSTSClient(client, writer, retries=0)
        for index in range(len(payloads)):
            recording.get_json("models_count", f"/v2/models/{index}/count")
    writer.write_inventory({})
    capture_dir, _ = writer.finalize()

    records = [
        json.loads(line)
        for line in (capture_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == len(payloads)
    for record, expected in zip(records, sent, strict=True):
        body = _read_body_at(capture_dir, record["response_offset"])
        assert body["body"].encode("utf-8") == expected
        assert body["sha256"] == hashlib.sha256(expected).hexdigest()


def test_connection_errors_record_no_response_body(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    writer = CaptureWriter(tmp_path, base_url="https://sts.cancer.gov", page_size=100)
    with STSClient(
        "https://sts.cancer.gov", transport=httpx.MockTransport(handler)
    ) as client:
        recording = RecordingSTSClient(client, writer, retries=0)
        assert recording.get_json("models_count", "/v2/models/count") is None
    writer.write_inventory({})
    capture_dir, _ = writer.finalize()

    record = json.loads((capture_dir / "requests.jsonl").read_text().splitlines()[0])
    assert record["response_offset"] is None
    assert record["status_code"] is None
    assert "ConnectError" in record["error"]
    assert (capture_dir / "responses.jsonl").read_text(encoding="utf-8") == ""


def test_all_versions_flag_is_wired_through_the_cli() -> None:
    default = _parser().parse_args(["capture"])
    assert default.all_versions is False
    enabled = _parser().parse_args(["capture", "--all-versions"])
    assert enabled.all_versions is True


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
