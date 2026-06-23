import httpx
import pytest

from mdb_sync.client import STSClient, STSClientError


def test_list_models_parses_response_and_sends_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/models/"
        assert dict(request.url.params) == {"skip": "10", "limit": "5"}
        return httpx.Response(
            200,
            json=[
                {
                    "type": "Model",
                    "handle": "gc",
                    "version": "11.0.4",
                    "nanoid": "abc123",
                    "name": "GC Schema",
                    "repository": "https://example.org/gc",
                    "is_latest_version": True,
                }
            ],
        )

    with STSClient("https://sts.example.org/", transport=httpx.MockTransport(handler)) as client:
        models = client.list_models(skip=10, limit=5)

    assert len(models) == 1
    assert models[0].handle == "gc"
    assert models[0].is_latest_version is True


def test_list_models_reports_http_errors() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"detail": "temporarily unavailable"})
    )

    with (
        STSClient("https://sts.example.org", transport=transport) as client,
        pytest.raises(STSClientError, match="HTTP 503"),
    ):
        client.list_models()


def test_list_models_rejects_unexpected_response() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []}))

    with (
        STSClient("https://sts.example.org", transport=transport) as client,
        pytest.raises(STSClientError, match="unexpected models response"),
    ):
        client.list_models()


def test_list_models_rejects_negative_pagination() -> None:
    with (
        STSClient(
            "https://sts.example.org",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
        ) as client,
        pytest.raises(ValueError, match="non-negative"),
    ):
        client.list_models(skip=-1)


def test_raw_client_refuses_non_v2_paths() -> None:
    with (
        STSClient(
            "https://sts.cancer.gov",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        ) as client,
        pytest.raises(ValueError, match="/v2/"),
    ):
        client.get_v2("/")
